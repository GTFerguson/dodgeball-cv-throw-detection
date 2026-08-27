# Throw Labeler

Browser-based, frame-accurate labelling tool for throw attempts. Footage is read from
`data/footage/`, labels are written to `data/labels/<video>.json` as you work (autosave).

```bash
cd tools/labeler
npm install
npm run dev            # http://localhost:5173
npm run test           # domain logic
npm run typecheck
```

**Open the labelled clip.** The truth set is on
`wdbf2014_final_h2_set2.mp4` — the 3.5-minute clip, 60 events. That is the one
to open to see the labels behind the reported scores. The picker lists every
file in `data/footage/` with its event count beside it, and the full half reads
*no labels yet*: opening it starts an empty file, so a blank tool there is
untouched footage rather than labels that went missing. The header says so too
whenever the file on screen is one the tool has just started.

The same applies to `?annotator=name`, which is a *different file* by design
(that is how a blind second pass keeps clear of the first). A name with no file
behind it opens empty for the same reason.

Requires `ffprobe` on PATH — the frame rate is probed server-side because the browser
cannot read it, and every frame index in the labels depends on it.

## Before you label

1. **Pose run** — `.venv/bin/python scripts/precompute_pose.py data/footage/<clip>.mp4`
   writes `data/pose/<stem>/<run-id>/`, which the tool lists in the header. Without one
   there are no skeletons to snap to; boxes can still be drawn by hand.
2. **Set starts** (optional) — `.venv/bin/python scripts/detect_set_start.py data/footage/<clip>.mp4`
   writes `data/sets/<stem>.json`, drawn on the timeline's `MODEL` track as a pennant at each
   detected start. Read-only: the tool never writes it. Without one the track draws empty and
   says so.
3. **Court geometry** — `G` cycles court editing: polygon → centre line → off. Click the
   four corners of the court, then `G` again and click the two ends of the centre line.
   It saves to `data/court/<stem>.json` on every click. The polygon decides which
   skeletons get player keys; the centre line decides which team a thrower is on.

## Labelling a throw

Two moments, one or two keypresses each:

```
release      T  →  thrower key                    throw opens
resolution   H / C / B / M / U  →  target key     throw closes
fake         F  →  thrower key                    terminal
```

An outcome closes the **selected** open throw — the most recently opened by default,
`Tab` to cycle when a coordinated attack has two or three balls in the air. Open throws
are highlighted in the list and the header counts them.

While a box is pending the player rows own the keyboard: `1`–`6` for the near team,
`Q`–`Y` for the far team, ordered left to right on the current frame. So `T` means
"far-court player 5" during a placement and "open a throw" otherwise.

Press `?` in the app for the full key map.

## Second pass

`?annotator=<name>` writes to `data/labels/<video>.<name>.json` instead, so a blind
second pass never sees or touches the first. Agreement between the two files is the
label-uncertainty term in the error budget.

## Label schema

One file per video (and per annotator):

```json
{
  "schema_version": 2,
  "video": "match.mp4", "fps": 25, "width": 1920, "height": 1080,
  "annotator": "default", "created": "…", "updated": "…",
  "events": [
    {
      "id": "…",
      "status": "closed",
      "fake": false,
      "release_frame": 1214, "start_frame": 1201, "end_frame": 1230,
      "thrower": {
        "box": { "x1": 800, "y1": 400, "x2": 900, "y2": 700 },
        "frame": 1214,
        "source": "snapped", "adjusted": false,
        "pose_run": {
          "run_id": "yolo11x-pose-1920-013c4354",
          "model": "yolo11x-pose.pt",
          "weights_sha256": "013c4354…",
          "imgsz": 1920
        }
      },
      "team": "near", "team_source": "inferred",
      "outcome": "hit",
      "target": { "box": { "…": 0 }, "frame": 1230, "source": "drawn", "adjusted": true, "pose_run": null },
      "release_visible": true, "outcome_visible": true,
      "ref_signal": "seen",
      "uncertain": false,
      "note": ""
    }
  ],
  "live_play": [{ "id": "…", "start_frame": 450, "end_frame": 5100 }]
}
```

Frames are indices at the video's native rate.

`status` is explicit rather than inferred from a null outcome: a throw whose outcome
was never observed is `closed` with `unresolved`, and must not read the same as one the
annotator has yet to resolve. A fake is `closed` from the moment it is created.

Boxes are in source pixels and are stored **by value**. A player key copies the four
numbers out of the pose run; from then on the box references nothing, so re-running the
detector cannot change what a label means. `source` says whether it was accepted from a
detection or drawn by hand, `adjusted` whether it was moved afterwards, and `pose_run`
records which run was on screen — provenance only, nothing in evaluation reads it.

`team` is `near` or `far`: the fixed end-on camera makes the court half directly
observable, and sides do not change within a half. It is inferred from where the
thrower's feet are relative to the centre line, and `team_source` records whether the
annotator overrode that.

Nothing derived is stored — detector miss rate, attribution, eliminations and game state
all recompute from the labels when the model changes.

## Server

The API is Vite middleware (`server/api.ts`), not a separate process:

| Route | Purpose |
|---|---|
| `GET /api/footage` | clips in `data/footage/` with their probed frame rate and size |
| `GET`/`PUT` `/api/labels/<key>` | the label file |
| `GET`/`PUT` `/api/court/<stem>` | court polygon and centre line |
| `GET /api/pose/<stem>` | manifests of the available pose runs |
| `GET /api/pose/<stem>/<run-id>/<chunk>` | one frame-range chunk |

Every path is resolved and checked for containment under its root before it is opened,
and both a sandbox escape and a missing file answer 404 so a probe cannot tell them
apart. Label and court writes go to a temp file in the same directory and are renamed,
because autosave means a write is nearly always in flight.
