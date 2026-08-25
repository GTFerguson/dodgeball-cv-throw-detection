#!/usr/bin/env bash
# Fetches the evaluation footage into data/footage/. Footage is never committed.
#
# Source: World Dodgeball Federation, "Canada vs USA - Men's Final | Dodgeball World
# Championship 2014 | 2nd Half", https://www.youtube.com/watch?v=Spu6OlAZHUo
# 1080p, 25 fps, H.264. Used for evaluation only.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p data/footage

VIDEO_ID="Spu6OlAZHUo"
OUT="data/footage/wdbf2014_final_h2.mp4"

if [[ -f "$OUT" ]]; then
  echo "already present: $OUT"
  exit 0
fi

# Pin the H.264 1080p stream so every checkout decodes identical frames.
yt-dlp -f "137+140" --merge-output-format mp4 -o "$OUT" "https://www.youtube.com/watch?v=${VIDEO_ID}"
echo "saved: $OUT"
