# Architecture

How the shipped system works and why.

| Doc | Contents |
|---|---|
| [pipeline.md](pipeline.md) | Footage in, timeline out: the stage order and the front door, the clip-hash contract, time in seconds, the venue as a config file |
| [court-geometry.md](court-geometry.md) | The geometry layer: what makes this footage hard, and how the court fit gets around each of it |
| [pose-precompute.md](pose-precompute.md) | One shared detector run per clip: the on-disk contract, and why the tool and the pipeline must share it |
| [set-start.md](set-start.md) | Where a set begins: balls laid out on the centre line, gated whistle, sprint confirmation |
| [set-end.md](set-end.md) | Where a set ends: the hit on the last player standing, or the floor showing it — one side down to one, then the court fills |
| [player-identity.md](player-identity.md) | Who is who: ByteTrack over the pose run, and the jersey number that survives a player crossing the court |
| [roster.md](roster.md) | Who is a player, who is an official, and which side: the one structure every stage reads for role and team |
| [throw-candidates.md](throw-candidates.md) | Proposed throwing motions from the pose run, for the annotator to accept, reject or adjust — the bootstrap for the truth set |
| [release-gate.md](release-gate.md) | From proposals to events and from events to releases, on the ball as colour: ball in hand before the peak, then a chain of blobs seen leaving it |
| [destination.md](destination.md) | Pass or throw from the ball's first direction in the image, and why the floor homography cannot place a ball in the air |
| [outcome.md](outcome.md) | Hit, catch or miss from persistent steps in a side's in-play count, attributed to the last throw at that side — and why the ball, the whistle and single tracks could not say |
| [evaluation.md](evaluation.md) | Scoring a timeline against the truth set one level at a time; same-frame, same-player matching; set end from the last hit |
| [design-system.md](design-system.md) | Visual language of the labelling tool — philosophy, tokens, components, voice, anti-patterns |
