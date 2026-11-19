# Запуск N0-VTLA в UniVTAC (Insert Hole) на машине для расчётов

Все пути ниже — от корня клона `tactile-vla` на сервере.

## 0. Требования к машине

- Ubuntu 22.04, свежий драйвер NVIDIA, conda.
- GPU **с RT-ядрами** (RTX 4090 / A6000 / L4 / L40S). Isaac Sim рендерит камеры через RTX, на A100/H100 камеры, по нашим данным, не работают.
- Память: Isaac Sim + модель на одной карте — ориентир от 24 ГБ, комфортно 48 ГБ. Можно развести на две карты.
- Диск: ~100 ГБ (Isaac Sim, кэши, чекпойнт 8.25 ГБ).

```bash
git clone <url этого репозитория> tactile-vla && cd tactile-vla
bash scripts/setup_server.sh        # клоны в external/, симлинк адаптера, проверка окружения
```

## 0.5. Проверка рендера камер (обязательно на A100/H100)

Без sudo и conda: ставит uv (если нет), venv `external/venvs/univtac` с torch и isaacsim теми же версиями, что и `install.sh`, и рендерит один кадр:

```bash
bash scripts/rtx_smoke.sh 2>&1 | tee runs/rtx_smoke.log
git add runs && git commit -m "run: rtx smoke" && git push
```

Смотреть строку `[RTXCHECK] VERDICT`. `FAIL` — симулятор на этой GPU не поедет, дальше шаг 1 не делать.

## 1. Симулятор UniVTAC (conda env `UniVTAC`, Python 3.10)

```bash
cd external/UniVTAC
conda create -n UniVTAC python=3.10 -y && conda activate UniVTAC
bash scripts/install.sh          # Isaac Sim 4.5, Isaac Lab 2.1.1, TacEx, cuRobo; спросит sudo для apt
pip install pyzmq msgpack opencv-python
python third_party/TacEx/scripts/demos/tactile_sim_approaches/check_taxim_sim.py --headless
```

## 2. Модель N0-VTLA (conda env `vtla`, Python 3.11)

```bash
cd external/N0-VTLA
conda create -n vtla python=3.11 -y && conda activate vtla
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
cp -r n0vtla/models_pytorch/transformers_replace/* \
  "$CONDA_PREFIX/lib/python3.11/site-packages/transformers/"

export N0VTLA_DATA_HOME="$PWD/models"
export HF_HOME="$N0VTLA_DATA_HOME/huggingface"
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python -c \
  "from transformers import AutoModel; AutoModel.from_pretrained('facebook/dinov2-base')"

hf download NeoteAI/n0_VTLA_insert_hole --local-dir checkpoints/n0_VTLA_insert_hole
python scripts/gate_c_check.py   # регрессионный тест сборки модели
```

## 3. Прогон — два окна tmux

Окно 1, сервер политики (лог пишется в `runs/server.log`):

```bash
conda activate vtla && cd external/N0-VTLA
export HF_HOME="$PWD/models/huggingface"
VTLA_ASSET_ID=n0_insert_hole_norm python scripts/serve_zmq.py \
  --config sim_single_arm_tactile \
  --ckpt checkpoints/n0_VTLA_insert_hole \
  --addr "tcp://*:5557" --default-prompt "insert hole" 2>&1 | tee ../../runs/server.log
```

Дождаться в логе списка tactile views (должно быть 2) и action horizon 50.

Окно 2, симулятор (сначала 5 эпизодов):

```bash
conda activate UniVTAC && cd external/UniVTAC
CUDA_VISIBLE_DEVICES=0 python scripts/eval_policy.py insert_hole demo N0VTLA/deploy --total_num 5 \
  2>&1 | tee ../../runs/sim.log
```

## 4. Передать результат

```bash
bash scripts/collect_logs.sh insert_hole_5ep
git add runs && git commit -m "run: insert_hole_5ep" && git push
```

Скрипт кладёт в `runs/<время>_<метка>/`: `env.txt` (версии, GPU), `log.log` из UniVTAC, `adapter.log` (строки `[N0VTLA]`), `server.log`, `sim.log`, `first_obs/*.png` (что видит модель на первом шаге), список видео. Сами видео лежат в `external/UniVTAC/eval_result/N0VTLA/insert_hole/deploy/<время>/video/` — если нужно, пришлите одно отдельно.

Если упало раньше, чем дошло до прогона, — достаточно прислать в чат хвост ошибки (последние ~50 строк).

## Если что-то не так

| Симптом | Что проверить |
|---|---|
| `did not answer in 60000 ms` | Сервер не поднят / другой порт; первый запрос может быть долгим — увеличить `request_timeout_ms` |
| Рука доезжает, но захват не сжимается | Должен исполняться весь чанк (50 шагов): `exec_steps: null` |
| Успех сильно ниже статьи | Попробовать `tactile_type: rgb` в `adapters/N0VTLA/deploy.yml` |
| OOM на GPU | Развести: сервер на `CUDA_VISIBLE_DEVICES=1`, симулятор на `0` |
| Isaac Sim падает на старте | Драйвер/GPU без RT-ядер; сначала добиться работы `check_taxim_sim.py` |
