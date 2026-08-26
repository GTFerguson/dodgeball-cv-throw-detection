---
title: Labelling Tool — Design System
created: 2026-08-25
updated: 2026-08-25
tags: [design, tooling, reference]
---

# Labelling Tool — Design System

The visual language of `tools/labeler/`. This document exists so a page built next month
looks like it belongs without a round of corrections first. It records the reasoning, not
just the values — the values are in `tools/labeler/src/index.css`, which is the source of
truth for every token named here.

## Identity

The labeller is an **instrument for establishing what happened in a frame**. A human asserts
the truth about ~60 throws in about an hour, hands on the keyboard the whole time; later the
same surface shows the model's version of the clip beside that truth.

Two audiences, and they want the same thing from the design:

- **The annotator** needs speed and legibility for an hour without fatigue. Every pixel of
  chrome competes with the frame they are actually judging.
- **A reviewer** assessing the work needs to see that the truth set was built carefully. The
  interface is evidence of rigour, so precision has to be visible, not claimed.

### What it feels like

A well-made measuring instrument on a bright bench. Calm, exact, unhurried. Closer to a
drafting table or a lab notebook than to a media application.

### What it is explicitly not

- **Not a video editor.** Premiere, DaVinci, CVAT and Label Studio all default to near-black
  chrome. That is the templated answer for this category and it is the wrong one here.
- **Not a product dashboard.** No hero numbers, no cards with accent rails, no gradient
  anything. Nothing on screen is selling a result.
- **Not a demo.** It is used, not shown. Density serves the person working, not the screenshot.

## Load-bearing decisions

Each of these looks like a preference and is not. Changing one breaks something real.

### Light, never dark

The tool is used for long stretches in a bright room, and the frame under inspection is a
brightly lit sports hall. Dark chrome around a bright picture forces the eye to re-adapt on
every glance between the frame and the event list. The ground is warm paper; the frame sits
on it like a print on a bench.

### Colour is exclusively semantic

**Every coloured pixel in the interface encodes something about the data.** Outcome class,
live state, or match status. Nothing is coloured for emphasis, hierarchy, branding or
decoration.

The consequence, and the reason it is worth the discipline: when something is coloured, it
means something, and the annotator learns the mapping once. Selection is therefore shown with
**ink** — a solid rule, a filled block, a heavier border — never with a colour.

### Warmth only in the lightest values

Warm greys at mid lightness read as dirt, not as warmth. The cream lives in `--ground`,
`--surface` and the near-whites; from `--rule` downward everything is near-neutral, and `--ink`
is a neutral charcoal. Warm paper with neutral ink is what reads as refined; warm paper with
warm-grey ink reads as grubby.

### Absence of knowledge is shown as absence of ink

An `unresolved` outcome gets no fill — a dashed outline only. A `fake` gets an outline and a
slash rather than a colour of its own. The truth set is honest about what it does not know,
and the design says so before the annotator reads a word.

### Comprehension beats cleverness

The timeline was first drawn as a single axis with truth above and predictions below. It was
elegant and nobody could read it. It is now two named tracks, `YOU` and `MODEL`, compared by
looking straight down, with an explicit legend. **If a device needs explaining, it is wrong,
however well it encodes the data.**

### The frame on screen is the frame the labels reference

The overlay is drawn inside the video's own frame callback, from the media time it reports.
Nothing in the design may imply a frame that is not the one being displayed — which is why a
box label reads `THROWER · f1418` even when the playhead sits at 1443. The box was placed on
1418 and says so.

## Colour

Tokens are defined in `tools/labeler/src/index.css` on `:root` and surfaced to Tailwind
through `theme.extend` in `tailwind.config.js`. Names below are the contract; hex values live
in the CSS.

### Chrome — achromatic, warm at the top end only

| Token | Role |
|---|---|
| `--ground` | The bench. The page behind everything. |
| `--surface` | Panels, timeline, cards. The paper. |
| `--surface-2` | Recessed fills — track backgrounds, hovered rows, the stats strip. |
| `--surface-3` | The frame's letterbox ground, pressed states. |
| `--ink` | Primary text, selection marks, the frame readout. |
| `--ink-mute` | Secondary text. The floor for anything a person must read. |
| `--ink-faint` | Tertiary labels only — ruler ticks, section eyebrows. Never body copy. |
| `--rule` | Hairlines between sections. |
| `--rule-strong` | Borders on controls, ruler ticks, dashed outlines. |

**Contrast floor: 4.5:1 against the surface behind it, for every piece of text without
exception.** Faded grey labels were the single worst usability defect in the first pass. If a
label is not worth 4.5:1, it is not worth showing.

### Semantic — the only colour in the product

Each class has a **soft** fill and a **deep** tone. Fills are for pill backgrounds and bands;
the deep tone is for text on that fill, and for marks and strokes on paper.

| Token pair | Means | Notes |
|---|---|---|
| `--sig-hit` / `-soft` | Outcome: hit | Also the colour for "the model missed this" |
| `--sig-catch` / `-soft` | Outcome: catch | Also the saved-state dot |
| `--sig-block` / `-soft` | Outcome: block | |
| `--sig-miss` / `-soft` | Outcome: miss | Deliberately the quietest — nothing happened |
| `--sig-open` / `-soft` | A throw in flight, and `fake` | The only "live" colour in the tool |
| `--sig-model` / `-soft` | Anything the model produced | Never used for a human label |

Rules:

- **`--sig-model` never marks a human label, and no outcome colour ever marks a prediction.**
  An accepted detection therefore leaves `--sig-model` behind: once a person has made a claim
  theirs, it is drawn in ink like everything else they are answerable for. Unreviewed keeps the
  model's blue, and rejected falls to `--ink-faint` — still the model's, no longer worth ink.
  Whose claim it is must be readable from colour alone.
- `unresolved` has **no token**. It is `--ink-faint` on a dashed outline, by design.
- `pass` has **no token** either, for a different reason: only outcomes are coloured, and a
  pass has none — the ball never crossed for anything to happen to it. It is `--ink-faint` on a
  solid outline, which separates it from `fake`'s live-coloured ring and `unresolved`'s dashed
  one without spending a hue on a class that is excluded from the metric.
- Soft fills are matched for lightness so no chip jumps out of a list of chips.

### The frame

The drawn hall uses its own tokens — `--hall`, `--hall-2`, `--wall`, `--wall-2`, `--seat`,
`--court`, `--court-line`, `--court-edge`, `--court-centre`. These describe *footage*, not
chrome, and are the one place the palette is allowed a cool note (`--seat` is a soft slate,
which stops the picture becoming a wash of warm mud).

Overlay ink: `--wire-near` and `--wire-far` for on-court skeletons, `--wire-casing-dark` /
`--wire-casing-light` behind them, `--wire-off` for detections the court test puts out of play.

### Team is the one thing the frame is allowed to colour

The key badge stays achromatic — the key row already tells the teams apart — but the skeleton
itself is coloured by team. This is not a relaxation of the semantic rule: which half a
player's feet are in *is* the team claim, so a coloured wire encodes data exactly as an outcome
chip does. It earns its place because the wire is drawn on footage, where there is no key row
to read against it, and because it makes the claim checkable — a red player in a violet wire is
the fit or the foot point being wrong, visible at a glance across the whole frame.

Three constraints fixed the pair, and the order matters:

- **The casing is the tonal opposite of the wire, not of the kit.** A skeleton crosses a
  jersey, black shorts and pale floor within one limb, so no wire colour is legible over all of
  it unaided. Once the casing carries legibility, the hue is free to mean team and nothing
  else — and taking the casing from the wire keeps that true when the teams swap ends, or when
  a clip has two dark kits and there is no light one to oppose.
- **The pair separates on lightness, not only hue.** They sit 107° apart, but hue is not what
  distinguishes them: under deuteranopia both collapse towards blue. What survives is the
  3.8:1 luminance ratio, which also means they read apart in greyscale.
- **Neither crowds the signal palette.** Both are drawn on the frame alongside outcome marks.
  The bar is derived rather than picked: no wire may sit closer to a `--sig-` colour than the
  closest two `--sig-` colours already sit to each other. A round number instead put the bar
  above what the colour space can supply — nothing with a usable lightness gap clears dE 60
  from all six.

The far wire is worth a note, because the obvious answer is wrong. The near team's kit is a
strongly chromatic red, so its complement is meaningful. The far team's "white" kit measures
S 0.13 at that distance — the complement of an almost-grey is another almost-grey, and it
disappears against everything. The far wire is therefore chosen as the near wire's harmonic
partner rather than as an opposition to the jersey it sits on.

`src/overlay.py` is the pipeline's copy of these values, and
`scripts/test_overlay_contract.py` holds the two in step along with the court thresholds.

## Typography

Two faces, no more.

| Face | Role |
|---|---|
| **Archivo** | Interface voice — labels, buttons, list rows, headings, legend. |
| **IBM Plex Mono** | Every number that can be compared or counted. |

The mono is not decoration. **Frame indices, timecodes, pixel coordinates, deltas and counts
are all mono with `tabular-nums`**, because they are read in columns and compared against each
other. A frame index in a proportional face is a bug.

| Element | Size / weight | Notes |
|---|---|---|
| Frame readout | 34px / 500, mono | The instrument's primary display |
| Timecode | 13px / 400, mono | Sits with the readout |
| List row frame | 12px / 400, mono | |
| Body, list rows, legend | 11–12px / 400–500 | |
| Buttons, chips | 11.5–12px / 500 | |
| Section eyebrows | 10.5px / 600, uppercase, `.09em` | |
| Pills | 10px / 600, uppercase, `.05em` | |

Anti-patterns: no italics anywhere. No serif. No third face. No weight above 700. No
letter-spacing on anything that is not an uppercase label.

## Voice

Write from the annotator's side of the screen. They know the domain — do not explain dodgeball
to them — but they are moving fast, so say exactly what is true.

| Good | Bad | Why |
|---|---|---|
| `not labelled yet` | `No data available` | Describes the work, not the database |
| `fired with no throw here` | `False positive detected` | Says what the model did |
| `predicted, nothing to check it against` | `Out of evaluation range` | Explains the gap honestly |
| `2 throws in flight` | `Active events: 2` | The domain's own words |
| `Saved to data/labels/wdbf2014_final_h2.json` | `Changes saved successfully` | Names the file; the annotator may need it |
| `One dot per throw, at the release frame.` | `Timeline visualisation` | Tells you how to read it |

Rules:

- **Use the key map's exact words.** The outcome classes are `hit`, `catch`, `block`, `miss`,
  `unresolved`, `fake`. Never a synonym — not "caught", not "deflected", not "no result".
- **Say `frame 1418`, not "timestamp" or "position".** Frames are the unit of truth.
- **Never claim more than is known.** "nothing to check it against" beats "unmatched"; the
  scope of a statistic is stated next to it, not implied.
- **Sentence case everywhere** except the uppercase eyebrow labels and pills.
- No exclamation marks, no apologies, no "successfully", no emoji.

## Components

### The frame

A bordered well filling the height left over after the timeline and instrument bar. The
picture is drawn on a canvas and **letterboxed with `min(w/W, h/H)`, centred** — never
stretched, because a stretched frame means every box coordinate on screen is a lie. Letterbox
ground is `--surface-3`, which reads as the bench showing through rather than as a black bar.

### Layer chips

Small toggles floated on the top-right of the frame itself, on a translucent paper background.
They live on the picture because they control the picture; giving them their own row wastes a
band of vertical space in a layout that has none to spare.

### Two-track timeline

The signature. The same clip drawn twice: `YOU` (labels) above, `MODEL` (predictions) below,
sharing one time axis so comparison is vertical.

`MODEL` carries set starts and proposed throws — the pipeline's throw *prediction* has not been
built, and a proposal is a weaker claim than a prediction. An empty track is drawn **with a
caption naming the scripts that fill it**, never hidden: an absent track reads as "nothing to
compare", an empty one as "not built yet", and only the second is true.

- One dot per throw at its **release frame**, coloured by outcome.
- A **set start is a pennant, not a dot**. It is a moment rather than a throw, and putting it on
  the outcome scale would make it read as one. Filled pennant on a solid stem: a start the
  detector timed from a whistle. Hollow pennant on a dashed stem: balls laid out with no whistle
  found — a weaker claim drawn as a weaker mark, per *absence of ink*.
- A set start the annotator holds is **the same pennant in `--ink`, on the `YOU` track**. It is
  drawn twice on purpose: the model's claim stays where it was made, and the vertical gap between
  the two pennants is the correction the annotator applied to it. A pennant on `YOU` with nothing
  under it is a start the detector missed.
- A **judged detection keeps its mark.** Accepted: underscored on the model track — the start it
  became is the pennant above. Rejected: struck through and dropped to `--ink-faint`, because
  hiding it would make a run look cleaner after review than it was.
- `fake` is a ring, `pass` a grey ring, `unresolved` a dashed ring, in-flight a filled dot
  with a pulsing halo. A fill means the ball crossed.
- On the frame, **the proposal being looked at is loud**: a soft `--sig-model` fill, a white
  casing under a heavy stroke, and `proposed` on a chip — it has to be found on a frame full of
  skeletons before it can be judged. Other unjudged proposals in the same second draw thin and
  dashed with only their frame, so a coordinated attack's other throws are present without
  competing; judged ones stay off the frame unless their card is selected, when they draw loud
  like any other — a rejection the annotator clicked to reconsider has to be visible. A selected
  proposal is loud only within tolerance of its own frame; further away nothing is loud, because
  a player who throws several times in a row would otherwise wear the older throw's box on the
  newer throw's frame while the keys still classified the older card. The box
  **follows the player** from frame to frame through the roster's track, rather than sitting where
  they were at the proposed frame. **Every box on the frame follows the same rule**: on the
  frame it was placed, where it was placed, and editable; on any other frame, where the roster
  says that player is now, not editable — a label is a box at its frame, and it is edited only
  there. Every box's chip carries the frame it belongs to, `thrower @595`, the number its card
  leads with; a followed box adds a green dot to the chip rather than a word. Where the follow
  cannot be made the stored box is drawn with its frame and no dot.
- A **proposed throw is a ring in `--sig-model`** — no fill, because a proposal claims a motion
  and nothing about a ball. Accepted: filled and underscored, with the throw it became directly
  above on `YOU`; the horizontal gap is the correction. Rejected: struck and dropped to
  `--ink-faint`. On the frame, a proposal's box is drawn in `--sig-model` and labelled
  `proposed`, never editable — the event it becomes is the thing to edit.
- A model dot with nothing above it fired where there is no throw; a **✕ on the model track**
  is a throw the model missed. The two failure modes get two distinct marks — never one.
- The shaded band is live play. Past the playhead, the label track is **hatched and captioned
  `not labelled yet`**, because the truth set is genuinely built left to right and hiding that
  would overstate what exists.
- **Always shipped with a legend.** No exceptions.

### Event stream

One list. Labels and the model's claims are both events at frames, so they share it, switched on
and off as **two source toggles** (`Labels`, `Model`) rather than chosen as views. There is no
"compare" mode: both on *is* the comparison. An accepted proposal and the throw it became are the
same moment and collapse into one row; everything else is single-sided — a label with nothing
beside it is a miss, a model row with nothing beside it is unreviewed or rejected. Set starts sit
in the same stream as rows of their own kind.

The list **follows the playhead**: every row within a second of the frame on screen is lit in
proportion to how close it is, so a coordinated attack lights two or three rows together, and
the nearest is kept in view. **Selection is separate from emphasis.** The selected row is the one
the keys edit and moves only when the annotator moves it — stepping frames to find a release
must not change what `H` lands on. `>` / `<` walk the visible list, selecting as they go.

**The card is where an event gets its kind, outcome and target.** The selected card opens into
the editor — frames, thrower and target with who they are, team, kind, outcome, referee signal,
flags, note — and nothing about an event is edited anywhere else. Cards sit with air between
them on a recessed ground, so each is one thing. A verdict is a **glyph, not a word**: `✓`
accepted in ink, `✕` rejected faint, a hollow `--sig-model` ring for unreviewed — the same ring
the timeline draws for the claim — with the word in the tooltip only. Accept / Reject are real
buttons on every card that can take them.

**A proposal is classified from its card.** Selected, a proposal offers `it was fake / pass` and
`throw hit / catch / block / miss / unresolved`; choosing one accepts the proposal and labels it in
one move, because "accept, then say what it was" is a step nobody should have to take. The same
keys do it from the keyboard. A note field on the card lets a rejection carry its reason.

**Choices wear their colour.** A button that means an outcome or a kind takes that signal's
tone — soft until chosen, full once it is — so what you press and what you get read as one
thing. Accept and Reject wear the catch green and the hit red: colour is semantic, and here the
semantics are exactly good and bad.

**Emphasis is lift, not colour.** A card near the playhead grows (up to 5%), its border darkens
towards ink, and it casts a shadow, all in proportion to closeness; the nearest is scrolled to
centre. `↑` `↓` (and `>` `<`) walk the cards, selecting as they go; the arrow keys nudge a box
only while one is being placed.

Sections, top to bottom: the source toggles and filters, then the stream, then the save state.
The list flexes to fill so the panel matches the frame's height.

### Event row

Frame index (mono) · side · **who threw → who it reached** · flag glyphs · outcome pill, and on
a model row the verdict tag. Who is `key #number Name`, as much of it as is known: the key is
whatever would snap the box on the frame on screen, the number is the roster's, the name is
hand-authored beside the roster. The left edge names the source — ink for a label, `--sig-model`
for an unjudged claim, faint for a rejected one. Selection is an inset ink ring plus the recessed
fill — never a colour.

Flag glyphs are terse and consistent: `!` uncertain, `◌` not visible, `§` referee signal seen.

### In-flight chip

An open throw, with the soft open fill, an ink-weight left border and the word `open`. Pinned
above the list because an unclosed throw is the one thing that can be silently forgotten.

### Pills

Soft fill, deep text, 2px radius. `fake` and `unresolved` are outline-only — see *absence of
ink*.

### Instrument bar

Frame readout, timecode, transport, then the key map. The key map is permanently visible
rather than hidden behind a help overlay, because the tool is keyboard-driven and a key you
have to look up is a key you do not use.

## Layout

- **Viewport height, no page scroll.** The app fills the window: header rail, then a stretch
  region, then nothing below the fold. A tool that scrolls has lost its instrument character.
- **Side gutters `clamp(20px, 3vw, 52px)`.** Visible framing at every width, which stops the
  content touching the screen edge, without the dead bands a fixed max-width column produces
  on a wide monitor. Both extremes are wrong: a 1500px centred column wastes a third of a wide
  screen; full bleed looks unfinished.
- **Grid `minmax(0,1fr) 356px`**, `align-items: stretch`. The panel is a fixed rail; the stage
  takes everything else.
- Radius is `2–3px` everywhere. Not zero (too severe against warm paper), never `8px+`.
- Shadow only on the panel, and barely — one soft ambient layer. Nothing else is lifted.
- Below 980px the grid stacks, the frame returns to a fixed 16:9, and the page is allowed to
  scroll. Mobile is a courtesy, not a target: this is a desktop instrument.

## Motion

Restrained to the point of near-absence. Two deliberate moments, both encoding state:

- **In-flight pulse** — a throw that is open breathes; a closed one does not. State, not decoration.
- **Model lane fade** — the second track fades in when the source switch moves to `Model` or
  `Compare`, so the reader sees where it came from.

Everything else is instant. Hover feedback is a fill change with no transition. All animation
is disabled under `prefers-reduced-motion`.

## Anti-patterns

Each of these was either tried and corrected, or is the generic default for this category.

- **No dark chrome.** Not as an option, not as a toggle.
- **No text below 4.5:1.** No faded grey for anything meaningful.
- **No decorative colour.** If it does not encode data, it is ink or paper.
- **No warm grey below the near-whites.** Brown at mid lightness reads as dirt.
- **No abstract chart device without a legend and named axes.**
- **No feature tabs in the panel.** One list, one source switch.
- **No centred max-width column**, and no zero-gutter full bleed. Gutters clamp.
- **No card-with-accent-rail, no `rounded-lg`, no gradients, no glassmorphism.**
- **No emoji in the interface.** Glyphs and typography only.
- **No third typeface, no italics, no serif.**
- **No proportional figures for comparable numbers.**
- **No hero numbers or vanity stats.** Statistics appear with their scope stated beside them.
- **No Tailwind opacity modifiers on these tokens.** `bg-surface/90` compiles to
  `rgb(var(--surface) / .9)`, and the tokens are hex strings rather than channel triplets, so
  the colour is invalid and the background silently disappears. Chrome that sits on the frame
  uses a solid fill and a shadow to separate itself — which reads better over video anyway.
  Canvas and SVG read these tokens directly, which is why they stay hex.
- **No new component pattern without adding it here.**
