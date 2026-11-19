"""Smoke test: can Isaac Sim render a camera image on this GPU?

UniVTAC needs RTX-rendered cameras (head/wrist RGB) and TacEx tactile images.
NVIDIA does not support RTX rendering on GPUs without RT cores (A100, H100), so
on such a machine this script is expected to fail or produce an empty image.

Run inside the UniVTAC conda env after isaacsim==4.5.0 is installed:
    OMNI_KIT_ACCEPT_EULA=YES python scripts/check_rtx_camera.py [out_dir]
Prints lines starting with "[RTXCHECK]" and a final verdict; saves rgb.png.
"""
import os
import sys
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "runs/rtx_check"
os.makedirs(OUT, exist_ok=True)


def log(msg):
    print(f"[RTXCHECK] {msg}", flush=True)


t0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True, "width": 320, "height": 240})
log(f"SimulationApp started in {time.time() - t0:.0f}s")

verdict = "FAIL"
try:
    import numpy as np

    try:  # Isaac Sim 4.5 names, with fallback to pre-4.5 omni.isaac.*
        from isaacsim.core.api import World
        from isaacsim.core.api.objects import DynamicCuboid
        from isaacsim.core.utils.rotations import euler_angles_to_quat
        from isaacsim.sensors.camera import Camera
    except ImportError:
        from omni.isaac.core import World
        from omni.isaac.core.objects import DynamicCuboid
        from omni.isaac.core.utils.rotations import euler_angles_to_quat
        from omni.isaac.sensor import Camera

    import carb

    settings = carb.settings.get_settings()
    log(f"renderer: {settings.get('/renderer/active')}  "
        f"rtx mode: {settings.get('/rtx/rendermode')}")

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    world.scene.add(DynamicCuboid(prim_path="/World/cube", name="cube",
                                  position=np.array([0.0, 0.0, 0.3]),
                                  scale=np.array([0.3, 0.3, 0.3]),
                                  color=np.array([1.0, 0.0, 0.0])))
    # light, otherwise a correct render can still be black
    from pxr import Sdf, UsdLux
    light = UsdLux.DistantLight.Define(world.stage, Sdf.Path("/World/light"))
    light.CreateIntensityAttr(3000)

    cam = Camera(prim_path="/World/cam", position=np.array([2.0, 0.0, 1.0]),
                 resolution=(320, 240),
                 orientation=euler_angles_to_quat(np.array([0, 20, 180]), degrees=True))
    world.reset()
    cam.initialize()

    rgba = None
    for i in range(60):
        world.step(render=True)
        rgba = cam.get_rgba()
        if rgba is not None and getattr(rgba, "size", 0) and rgba[..., :3].std() > 1:
            log(f"got non-empty frame at step {i}")
            break

    if rgba is None or not getattr(rgba, "size", 0):
        log("camera returned no data")
    else:
        rgb = np.asarray(rgba)[..., :3].astype(np.uint8)
        log(f"frame shape={rgb.shape} min={rgb.min()} max={rgb.max()} std={rgb.std():.1f} "
            f"mean_rgb={rgb.reshape(-1, 3).mean(0).round(1).tolist()}")
        try:
            from PIL import Image
            Image.fromarray(rgb).save(os.path.join(OUT, "rgb.png"))
            log(f"saved {OUT}/rgb.png")
        except Exception as e:  # PIL missing is not a render failure
            np.save(os.path.join(OUT, "rgb.npy"), rgb)
            log(f"PIL failed ({e}); saved rgb.npy")
        if rgb.std() > 1:
            verdict = "OK"
except Exception as e:
    import traceback
    traceback.print_exc()
    log(f"exception: {type(e).__name__}: {e}")
finally:
    log(f"VERDICT: {verdict}  (OK = cameras render, UniVTAC can run on this GPU)")
    app.close()
