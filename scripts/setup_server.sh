#!/usr/bin/env bash
# Подготовка машины для расчётов (Linux + GPU). Запускать из клона этого репозитория:
#   git clone <url> tactile-vla && cd tactile-vla && bash scripts/setup_server.sh
# Что делает:
#   - клонирует UniVTAC и N0-VTLA в external/ (папка в .gitignore);
#   - делает симлинк external/UniVTAC/policy/N0VTLA -> adapters/N0VTLA,
#     так что после `git pull` адаптер обновляется без копирования;
#   - печатает сведения о GPU/ОС/conda/диске.
# Тяжёлые установки (Isaac Sim, зависимости модели) НЕ запускает: см. docs/RUN.md.
# Повторный запуск безопасен.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXT="$REPO/external"
mkdir -p "$EXT"
cd "$EXT"
echo "==> Репозиторий: $REPO"

command -v git >/dev/null || { echo "Нужен git (sudo apt install git)"; exit 1; }
[ -d UniVTAC/.git ] || git clone https://github.com/univtac/UniVTAC.git
[ -d N0-VTLA/.git ] || git clone https://github.com/neoteai/N0-VTLA.git

LINK="$EXT/UniVTAC/policy/N0VTLA"
if [ -L "$LINK" ]; then
  echo "  симлинк адаптера уже есть: $(readlink "$LINK")"
elif [ -e "$LINK" ]; then
  echo "  ! $LINK существует и это не симлинк — уберите его вручную"; exit 1
else
  ln -s ../../../adapters/N0VTLA "$LINK"
  echo "  симлинк: $LINK -> adapters/N0VTLA"
fi
[ -f "$LINK/deploy_policy.py" ] || { echo "  ! симлинк битый"; exit 1; }
[ -f "$EXT/UniVTAC/policy/_base_policy.py" ] || echo "  ! нет UniVTAC/policy/_base_policy.py — адаптер импортирует BasePolicy оттуда, сообщите"

echo "==> Версии внешних репозиториев"
for r in UniVTAC N0-VTLA; do
  echo "  $r: $(git -C "$EXT/$r" rev-parse --short HEAD) ($(git -C "$EXT/$r" log -1 --format=%cs))"
done

echo "==> Окружение"
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader | sed 's/^/  GPU /'
else
  echo "  ! nvidia-smi не найден — нужен драйвер NVIDIA"
fi
. /etc/os-release 2>/dev/null && echo "  ОС: $PRETTY_NAME (нужна Ubuntu 22.04)"
command -v conda >/dev/null && echo "  conda: $(conda --version)" || echo "  ! conda не найдена — поставьте Miniconda"
df -h "$EXT" | awk 'NR==2{print "  свободно на диске: "$4" (нужно ~100 ГБ)"}'

cat <<EOF

Готово. Дальше — установка по docs/RUN.md (шаги 1–2).
Вывод этого скрипта можно сразу прислать в чат.
EOF
