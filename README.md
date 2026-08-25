# Dodgeball Throw-Attempt Detection

Turning broadcast dodgeball footage into an attributed timeline of throw attempts
(wind-up → release → outcome) and a derived team throw-efficiency metric.

Status: in progress. Plan in [docs/plans/throw-attempt-detection.md](docs/plans/throw-attempt-detection.md);
shipped components in [docs/architecture/](docs/architecture/README.md).

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_weights.py     # pose weights (~113 MB)
scripts/download_footage.sh && scripts/make_clip.sh
```

Needs Python 3.12, `ffmpeg`/`ffprobe` and `yt-dlp` on PATH. The labelling tool has its
own Node setup — see [tools/labeler/README.md](tools/labeler/README.md).

## Layout

```
docs/        design, plans, architecture, reference, labelling guide
data/        labels, court calibration and set timelines (committed); footage and pose runs (generated, never committed)
scripts/     footage download, court fit, pose precompute, renderers, tests
src/         pipeline modules
tools/       labelling tool
output/      generated timelines, metrics and evaluation reports
```

## Reproducing what exists

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Python 3.12
./scripts/download_footage.sh && ./scripts/make_clip.sh

.venv/bin/python scripts/fit_court.py    data/footage/wdbf2014_final_h2_set2.mp4
.venv/bin/python scripts/precompute_pose.py data/footage/wdbf2014_final_h2_set2.mp4
.venv/bin/python scripts/render_court_overlay.py data/footage/wdbf2014_final_h2_set2.mp4 \
    --frame 625 --open
.venv/bin/python scripts/detect_set_start.py data/footage/wdbf2014_final_h2_set2.mp4 \
    --offset 360

for t in scripts/test_*.py; do .venv/bin/python "$t" -q || exit 1; done
```

The court fit aborts rather than writing a calibration if the floor's held-out
markings do not land where a regulation court's would - see
[docs/architecture/court-geometry.md](docs/architecture/court-geometry.md).

Set-start detection finds the clip's set beginning at frame 433 (17.32 s, 6:17.3 of
the half) and reports the next set's ball layout as having no whistle before the clip
ends - see [docs/architecture/set-start.md](docs/architecture/set-start.md).
