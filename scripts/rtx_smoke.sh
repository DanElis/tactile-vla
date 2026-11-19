#!/usr/bin/env bash
# Быстрая проверка до полной установки UniVTAC: рендерит ли Isaac Sim камеры на этой GPU.
#   bash scripts/rtx_smoke.sh 2>&1 | tee runs/rtx_smoke.log
# Что делает (без sudo):
#   1. ставит Miniconda в ~/miniconda3, если conda нет;
#   2. создаёт env UniVTAC (python 3.10) и ставит туда torch 2.5.1+cu124 и isaacsim 4.5.0 —
#      ровно те версии, что ставит UniVTAC/scripts/install.sh, так что работа не пропадёт;
#   3. запускает scripts/check_rtx_camera.py. Итог — строка "[RTXCHECK] VERDICT: ...".
# Нужно ~20 ГБ на диске и время на скачивание.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
mkdir -p runs

if ! command -v conda >/dev/null; then
  if [ ! -x "$HOME/miniconda3/bin/conda" ]; then
    echo "==> Ставлю Miniconda в ~/miniconda3"
    wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
    rm -f /tmp/miniconda.sh
    "$HOME/miniconda3/bin/conda" init bash >/dev/null
  fi
  export PATH="$HOME/miniconda3/bin:$PATH"
fi
eval "$(conda shell.bash hook)"
echo "==> conda: $(conda --version)"

# Новые версии conda требуют принять ToS каналов по умолчанию; без этого create падает.
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main >/dev/null 2>&1 || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r >/dev/null 2>&1 || true

conda env list | grep -qE '^UniVTAC\s' || conda create -n UniVTAC python=3.10 -y
conda activate UniVTAC
echo "==> python: $(python --version) ($(which python))"

python -m pip install -q --upgrade pip
if ! python -c "import torch; assert torch.__version__.startswith('2.5.1')" 2>/dev/null; then
  echo "==> Ставлю torch 2.5.1+cu124"
  python -m pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
fi
if ! python -m pip show isaacsim >/dev/null 2>&1; then
  echo "==> Ставлю isaacsim 4.5.0 (долго, ~15 ГБ)"
  python -m pip install -q "isaacsim[all,extscache]==4.5.0" --extra-index-url https://pypi.nvidia.com
fi
python -c "import torch; print('==> torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

echo "==> Тест рендера камеры"
export OMNI_KIT_ACCEPT_EULA=YES
python scripts/check_rtx_camera.py runs/rtx_check || echo "[RTXCHECK] python exited with code $?"
echo "==> Итог:"
grep -h "VERDICT" runs/rtx_smoke.log 2>/dev/null || true
