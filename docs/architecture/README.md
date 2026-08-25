# Architecture

How the shipped system works and why.

| Doc | Contents |
|---|---|
| [court-geometry.md](court-geometry.md) | The geometry layer: what makes this footage hard, and how the court fit gets around each of it |
| [pose-precompute.md](pose-precompute.md) | One shared detector run per clip: the on-disk contract, and why the tool and the pipeline must share it |
| [set-start.md](set-start.md) | Where a set begins: balls laid out on the centre line, gated whistle, sprint confirmation |
| [player-identity.md](player-identity.md) | Who is who: ByteTrack over the pose run, and the jersey number that survives a player crossing the court |
| [design-system.md](design-system.md) | Visual language of the labelling tool — philosophy, tokens, components, voice, anti-patterns |

The pipeline's own architecture docs land here when the prototype ships.
