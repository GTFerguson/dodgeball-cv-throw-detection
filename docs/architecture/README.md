# Architecture

How the shipped system works and why.

| Doc | Contents |
|---|---|
| [court-geometry.md](court-geometry.md) | The geometry layer: what makes this footage hard, and how the court fit gets around each of it |
| [pose-precompute.md](pose-precompute.md) | One shared detector run per clip: the on-disk contract, and why the tool and the pipeline must share it |
| [set-start.md](set-start.md) | Where a set begins: balls laid out on the centre line, gated whistle, sprint confirmation |
| [player-identity.md](player-identity.md) | Who is who: ByteTrack over the pose run, and the jersey number that survives a player crossing the court |
| [roster.md](roster.md) | Who is a player, who is an official, and which side: the one structure every stage reads for role and team |
| [throw-candidates.md](throw-candidates.md) | Proposed throwing motions from the pose run, for the annotator to accept, reject or adjust — the bootstrap for the truth set |
| [release-gate.md](release-gate.md) | From proposals to events and from events to releases, on the ball as colour: ball in hand before the peak, then a chain of blobs seen leaving it |
| [evaluation.md](evaluation.md) | Scoring a timeline against the truth set one level at a time; same-frame, same-player matching; set end from the last hit |
| [design-system.md](design-system.md) | Visual language of the labelling tool — philosophy, tokens, components, voice, anti-patterns |
