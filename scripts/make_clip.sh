#!/usr/bin/env bash
# Cuts the evaluation segment from the full half. Re-encodes rather than stream-copies
# so the clip starts exactly at the requested second and every frame index in the
# label files maps to the same picture on every machine.
#
# Segment: one complete set — opening rush at ~6:04 through to the next opening rush
# at ~9:28 — chosen so all twelve players start on court and the throw rate is highest.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="data/footage/wdbf2014_final_h2.mp4"
OUT="data/footage/wdbf2014_final_h2_set2.mp4"
START=360      # 6:00
DURATION=210   # 3:30

[[ -f "$SRC" ]] || { echo "run scripts/download_footage.sh first"; exit 1; }
if [[ -f "$OUT" ]]; then echo "already present: $OUT"; exit 0; fi

ffmpeg -v error -ss "$START" -i "$SRC" -t "$DURATION" \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -r 25 -g 25 \
  -c:a aac -b:a 128k -movflags +faststart "$OUT"
echo "saved: $OUT"
