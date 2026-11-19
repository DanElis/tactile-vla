#!/usr/bin/env bash
# Быстрая проверка до полной установки UniVTAC: рендерит ли Isaac Sim камеры на этой GPU.
#   bash scripts/rtx_smoke.sh 2>&1 | tee runs/rtx_smoke.log
# Что делает (без sudo и без conda):
#   1. ставит uv в ~/.local/bin, если его нет;
#   2. создаёт venv external/venvs/univtac (python 3.10, uv сам скачает интерпретатор) и ставит
#      torch 2.5.1+cu124 и isaacsim 4.5.0 — те же версии, что UniVTAC/scripts/install.sh;
#   3. запускает scripts/check_rtx_camera.py. Итог — строка "[RTXCHECK] VERDICT: ...".
# Нужно ~20 ГБ на диске (venv + кэш uv в ~/.cache/uv).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
mkdir -p runs
VENV="$REPO/external/venvs/univtac"

if ! command -v uv >/dev/null; then
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null || { echo "==> Ставлю uv"; curl -LsSf https://astral.sh/uv/install.sh | sh; }
fi
echo "==> $(uv --version)"

[ -x "$VENV/bin/python" ] || uv venv --python 3.10 "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "==> python: $(python --version) ($(which python))"

if ! python -c "import torch; assert torch.__version__.startswith('2.5.1')" 2>/dev/null; then
  echo "==> Ставлю torch 2.5.1+cu124"
  uv pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
fi
if ! uv pip show isaacsim >/dev/null 2>&1; then
  echo "==> Ставлю isaacsim 4.5.0 (долго, ~15 ГБ)"
  # unsafe-best-match: пакеты isaacsim-* лежат на pypi.nvidia.com, остальное — на PyPI
  uv pip install "isaacsim[all,extscache]==4.5.0" \
    --extra-index-url https://pypi.nvidia.com --index-strategy unsafe-best-match
fi
python -c "import torch; print('==> torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

echo "==> Тест рендера камеры"
export OMNI_KIT_ACCEPT_EULA=YES
python scripts/check_rtx_camera.py runs/rtx_check || echo "[RTXCHECK] python exited with code $?"
