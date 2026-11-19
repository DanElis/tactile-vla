"""UniVTAC policy adapter that drives an N0-VTLA checkpoint served by
N0-VTLA's scripts/serve_zmq.py (ZMQ REQ/REP + msgpack).

scripts/setup_server.sh symlinks this folder to UniVTAC/policy/N0VTLA, then e.g.
    python scripts/eval_policy.py insert_hole demo N0VTLA/deploy --total_num 5

Requires in the UniVTAC env:  pip install pyzmq msgpack opencv-python

Every line this adapter prints starts with "[N0VTLA]" so it can be grepped out of
the Isaac Sim log (scripts/collect_logs.sh does exactly that).
"""
import time

import cv2
import msgpack
import numpy as np
import torch
import zmq

from .._base_policy import BasePolicy


def _log(msg: str):
    print(f"[N0VTLA] {msg}", flush=True)


def _describe(x, prefix="", out=None):
    """Flat list of 'key: type shape dtype [min..max]' lines for a nested observation."""
    out = [] if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            _describe(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(x, torch.Tensor):
        t = x.detach()
        rng = ""
        if t.numel() and (t.is_floating_point() or t.dtype == torch.uint8):
            tf = t.float()
            rng = f" [{tf.min().item():.3g}..{tf.max().item():.3g}]"
        out.append(f"{prefix}: Tensor{tuple(t.shape)} {t.dtype} {t.device}{rng}")
    elif isinstance(x, np.ndarray):
        rng = f" [{x.min():.3g}..{x.max():.3g}]" if x.size and x.dtype != object else ""
        out.append(f"{prefix}: ndarray{x.shape} {x.dtype}{rng}")
    else:
        out.append(f"{prefix}: {type(x).__name__} {str(x)[:80]}")
    return out


def _to_uint8_hwc(img) -> np.ndarray:
    if isinstance(img, torch.Tensor):
        img = img.detach().cpu().numpy()
    img = np.asarray(img)
    if img.ndim == 4 and img.shape[0] == 1:
        img = img[0]  # drop batch dim
    if img.ndim == 3 and img.shape[0] in (1, 3, 4) and img.shape[0] < img.shape[-1]:
        img = np.transpose(img, (1, 2, 0))  # CHW -> HWC
    if img.dtype != np.uint8:
        img = img * 255.0 if img.max() <= 1.0 else img
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 3 and img.shape[-1] == 4:
        img = img[..., :3]  # drop alpha
    return img


def _png(img) -> bytes:
    arr = _to_uint8_hwc(img)
    ok, buf = cv2.imencode(".png", arr[..., ::-1])  # RGB -> BGR for OpenCV
    if not ok:
        raise RuntimeError(f"PNG encoding failed for array {arr.shape} {arr.dtype}")
    return buf.tobytes()


class Policy(BasePolicy):
    def __init__(self, args):
        super().__init__(args)
        self.addr = args.get("server_addr", "tcp://127.0.0.1:5557")
        self.timeout_ms = int(args.get("request_timeout_ms", 60000))
        self.tactile_type = args.get("tactile_type", "rgb_marker")
        self.action_dim = int(args.get("action_dim", 8))
        self.prompt = args.get("prompt")
        self.exec_steps = args.get("exec_steps")
        self.debug = bool(args.get("debug", True))
        self.dump_dir = args.get("dump_first_obs_dir")  # save first-episode PNGs here
        self.queue = []
        self.infer_ms = []
        self.episode = 0
        self.step = 0
        self._described = False
        self._connect()
        _log(f"connected to {self.addr}, tactile={self.tactile_type}, action_dim={self.action_dim}, "
             f"exec_steps={self.exec_steps}, timeout={self.timeout_ms}ms")

    # ---------------------------------------------------------------- transport
    def _connect(self):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(self.addr)

    def _request(self, msg: dict) -> dict:
        t0 = time.time()
        try:
            self.sock.send(msgpack.packb(msg, use_bin_type=True))
            rep = msgpack.unpackb(self.sock.recv(), raw=False)
        except zmq.Again:
            # A REQ socket is unusable after a timeout: rebuild it, then fail loudly.
            self.sock.close()
            self._connect()
            raise RuntimeError(f"N0-VTLA server at {self.addr} did not answer in {self.timeout_ms} ms "
                               f"(cmd={msg.get('cmd')})")
        if rep.get("status") != "ok":
            raise RuntimeError(f"N0-VTLA server error (cmd={msg.get('cmd')}): {rep.get('message', rep)}")
        rep["_roundtrip_ms"] = (time.time() - t0) * 1000
        return rep

    # ---------------------------------------------------------------- policy API
    def encode_obs(self, observation):
        if self.debug and not self._described:
            _log("observation structure (first call):")
            for line in _describe(observation):
                _log("  " + line)
            self._described = True

        cams = observation["observation"]
        tac = observation["tactile"]
        images = {
            "observation/image": cams["head"]["rgb"],
            "observation/left_tactile": tac["left_tactile"][self.tactile_type],
            "observation/right_tactile": tac["right_tactile"][self.tactile_type],
        }
        if "wrist" in cams:
            images["observation/wrist_image"] = cams["wrist"]["rgb"]

        if self.dump_dir and self.episode == 0 and self.step == 0:
            import os
            os.makedirs(self.dump_dir, exist_ok=True)
            for k, v in images.items():
                path = os.path.join(self.dump_dir, k.replace("/", "_") + ".png")
                cv2.imwrite(path, _to_uint8_hwc(v)[..., ::-1])
            _log(f"dumped first observation images to {self.dump_dir}")

        state = observation["embodiment"]["joint"][: self.action_dim].detach().cpu().float()
        msg = {"cmd": "predict", "state": state.tolist()}
        msg.update({k: _png(v) for k, v in images.items()})
        if self.prompt:
            msg["prompt"] = self.prompt
        return msg

    def eval(self, task, observation):
        if not self.queue:
            msg = self.encode_obs(observation)
            rep = self._request(msg)
            raw = np.asarray(rep["actions"], dtype=np.float32)
            actions = raw[:, : self.action_dim]
            if self.exec_steps:
                actions = actions[: int(self.exec_steps)]
            self.queue = list(actions)
            self.infer_ms.append(rep.get("infer_time_ms", 0.0))
            if self.debug:
                _log(f"ep={self.episode} step={self.step} chunk {raw.shape} -> exec {len(actions)}; "
                     f"infer={rep.get('infer_time_ms', 0.0):.0f}ms roundtrip={rep['_roundtrip_ms']:.0f}ms; "
                     f"state={np.round(msg['state'], 3).tolist()}; "
                     f"a[0]={np.round(actions[0], 3).tolist()}; a[-1]={np.round(actions[-1], 3).tolist()}")
        action = torch.as_tensor(self.queue.pop(0), device=task.device, dtype=torch.float32)
        task.take_action(action, action_type="qpos")
        self.step += 1

    def reset(self):
        if self.infer_ms:
            _log(f"episode {self.episode} done: {self.step} steps, mean inference "
                 f"{np.mean(self.infer_ms):.0f} ms over {len(self.infer_ms)} chunks")
            self.episode += 1
        self.queue = []
        self.infer_ms = []
        self.step = 0
        self._request({"cmd": "reset"})  # clears the per-episode tactile baseline

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
