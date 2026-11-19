#!/usr/bin/env bash
# Собирает результаты прогона в runs/<время>_<метка>/, чтобы передать их через git.
#   bash scripts/collect_logs.sh [метка] [путь к eval_result/.../<время>]
# Без пути берётся самый свежий прогон в external/UniVTAC/eval_result/N0VTLA/.
# Видео НЕ копируются (тяжёлые) — только список. Логи сервера политики, если есть,
# кладите в runs/server.log перед запуском (см. docs/RUN.md, `tee`).
# После: git add runs && git commit -m "run: <метка>" && git push
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNI="$REPO/external/UniVTAC"
LABEL="${1:-run}"
SRC="${2:-}"
if [ -z "$SRC" ]; then
  SRC="$(ls -dt "$UNI"/eval_result/N0VTLA/*/*/*/ 2>/dev/null | head -1 || true)"
fi
OUT="$REPO/runs/$(date +%Y%m%d_%H%M%S)_$LABEL"
mkdir -p "$OUT"

{
  echo "date: $(date -Is)"
  echo "label: $LABEL"
  echo "source: ${SRC:-<не найден>}"
  echo "tactile-vla: $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '?') $(git -C "$REPO" status --porcelain | grep -q . && echo '(есть незакоммиченные изменения)')"
  for r in UniVTAC N0-VTLA; do
    [ -d "$REPO/external/$r/.git" ] && echo "$r: $(git -C "$REPO/external/$r" rev-parse --short HEAD)"
  done
  command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=index,name,memory.used,memory.total,driver_version --format=csv,noheader
} > "$OUT/env.txt" 2>&1

if [ -n "$SRC" ] && [ -d "$SRC" ]; then
  find "$SRC" -maxdepth 1 -type f ! -name '*.mp4' -size -5M -exec cp {} "$OUT/" \;
  [ -d "$SRC/video" ] && ls -la "$SRC/video" > "$OUT/videos.txt"
  [ -f "$SRC/log.log" ] && grep -a '\[N0VTLA\]' "$SRC/log.log" > "$OUT/adapter.log" || true
else
  echo "  ! папка прогона не найдена, сохранил только env.txt"
fi
FIRST="$UNI/eval_result/N0VTLA/first_obs"
[ -d "$FIRST" ] && cp -r "$FIRST" "$OUT/first_obs"
[ -f "$REPO/runs/server.log" ] && mv "$REPO/runs/server.log" "$OUT/server.log"
[ -f "$REPO/runs/sim.log" ] && mv "$REPO/runs/sim.log" "$OUT/sim.log"

echo "==> $OUT"
ls -la "$OUT"
echo "Дальше: git add runs && git commit -m \"run: $LABEL\" && git push"
