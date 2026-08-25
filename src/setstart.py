"""Set-start detection: when a set of dodgeball actually begins.

A set opens the same way every time. Six balls are laid on the centre line, both
teams wait behind their baselines, a referee whistles, and twelve players sprint
for the balls. Each of those three signals is ambiguous alone and the
combination is not:

* Balls on the line is a *layout*, not a count. Balls lie all over the floor
  during play, but only between sets do several of them sit within a few
  centimetres of the centre line and spread across its width.
* Referees whistle for eliminations, line violations and timeouts throughout a
  set, so a whistle means nothing on its own. Heard only while the balls are
  laid out, it can mean almost nothing else.
* The sprint confirms the whistle started play rather than warning someone, and
  it is what a false start or a re-lay of the balls fails.

The whistle is the start time. The sprint is the players' reaction to it and
lags by a few hundred milliseconds, so it is used to confirm rather than to
time; the first ball leaving the line is the fallback when the audio is missing
or too muddy to gate.

Sizes and positions are in court metres throughout, because the camera is
end-on: a ball on the far half of the centre line is barely half the width of
one on the near half, and no pixel threshold is right for both.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from court import CENTRE_LINE_M, COURT_WIDTH_M, Court, foot_point

REPO_ROOT = Path(__file__).resolve().parent.parent
SETS_ROOT = REPO_ROOT / "data" / "sets"

SCHEMA_VERSION = 1

# Balls at rest on the line, in the colour space of this footage. The floor is
# grey and the jerseys red; orange survives both, which is why an HSV blob is
# enough here and a learned detector is not needed for this stage.
ORANGE_HSV_LO = (5, 120, 90)
ORANGE_HSV_HI = (22, 255, 255)

# The strip of floor searched, as a court-metre band about the centre line. Wide
# enough that a ball nudged out of line still falls inside it.
BALL_BAND_M = 1.0
BALL_BAND_MARGIN_M = 0.5

# How far a blob's floor contact may sit from the centre line and still count as
# laid out on it. Balls at rest measure within 0.25 m; a ball in a player's
# hands near the line does not.
BALL_LINE_TOLERANCE_M = 0.35

# Ball diameter as a fraction of the perspective scale at its floor contact
# (see Court.normalise). Laid-out balls measure ~0.027 at both ends of the line;
# the band admits compression wobble and rejects orange shoes and kit flashes,
# which measure under 0.012.
BALL_DIAMETER_NORM = (0.020, 0.036)

# A blob much taller than it is wide is a limb or a shadow, not a ball.
BALL_ASPECT = (0.6, 1.8)

# What counts as laid out: enough balls, spread across the line rather than
# clustered at one end. Six is nominal, but a ball is routinely hidden behind a
# player waiting at the baseline, so the count is not the discriminating part -
# the spread is.
ARMED_MIN_BALLS = 4
ARMED_MIN_SPREAD_M = 5.0
ARMED_MIN_DURATION_S = 1.0

# Sampling stride for the armed-state sweep. The state persists for seconds, so
# every frame need not be looked at; the whistle is timed from audio, not from
# this sweep, so the stride costs no precision.
ARMED_SAMPLE_STRIDE = 5

# A referee whistle is a narrow tone well above the crowd, which is broadband and
# concentrated lower. Prominence is the peak in the whistle band over the mean of
# the reference band, so it measures the tone against whatever noise the room is
# making at that moment rather than against an absolute level.
WHISTLE_BAND_HZ = (2500, 4500)
WHISTLE_REFERENCE_BAND_HZ = (200, 2000)
WHISTLE_SAMPLE_RATE = 16000
WHISTLE_WINDOW = 1024
WHISTLE_HOP = 160

# The gate does the disambiguating, so this only has to clear the room: inside an
# armed window there is nothing else that whistles. Ungated it would fire on
# every elimination call.
WHISTLE_MIN_PROMINENCE_DB = 20.0
WHISTLE_MIN_DURATION_S = 0.05

# Mid-court: the floor neither team stands on while waiting. Entering it is the
# sprint, and its emptiness is what tells waiting players from playing ones.
MID_COURT_M = (2.0, 16.0)
SPRINT_WINDOW_S = 1.5
SPRINT_MIN_PLAYERS = 3
PLAYER_MIN_CONF = 0.5


@dataclass
class ArmedWindow:
    """A stretch where the balls are laid out on the centre line."""

    start_frame: int
    end_frame: int
    max_balls: int
    max_spread_m: float


@dataclass
class SetStart:
    """One detected set start, or an armed window that never produced one."""

    armed: ArmedWindow
    start_frame: int | None = None
    whistle_prominence_db: float | None = None
    sprint_frame: int | None = None
    first_ball_moves_frame: int | None = None
    status: str = "no_whistle"
    notes: list[str] = field(default_factory=list)

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


def centre_line_mask(court: Court, frame_size: tuple[int, int]) -> np.ndarray:
    """Pixels that could hold a ball lying on the centre line.

    Built from the court fit rather than drawn by hand, so it follows the line's
    perspective instead of being a rectangle that is too tall at one end. The
    band is projected from the floor and then extended upwards, because a ball is
    a solid object standing on the floor and its pixels are above its contact
    point.
    """
    w, h = frame_size
    half = BALL_BAND_M / 2
    corners = [
        (-BALL_BAND_MARGIN_M, CENTRE_LINE_M - half),
        (COURT_WIDTH_M + BALL_BAND_MARGIN_M, CENTRE_LINE_M - half),
        (COURT_WIDTH_M + BALL_BAND_MARGIN_M, CENTRE_LINE_M + half),
        (-BALL_BAND_MARGIN_M, CENTRE_LINE_M + half),
    ]
    quad = np.array([court.to_image(cx, cy) for cx, cy in corners], np.float32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [quad.astype(np.int32)], 255)
    # A ball at the near end of the line is taller in pixels than one at the far
    # end; the tallest is what the extension has to clear. The anchor sits at the
    # top of the kernel so the band grows towards the top of the image, which is
    # where a ball standing on the band's floor actually appears.
    lift = int(round(BALL_DIAMETER_NORM[1] * court.scale_at(quad[:, 1].max())))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, lift + 1))
    return cv2.dilate(mask, kernel, anchor=(0, 0))


def balls_on_line(frame: np.ndarray, court: Court, mask: np.ndarray) -> list[float]:
    """Across-court positions of the balls lying on the centre line, in metres."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    orange = cv2.bitwise_and(cv2.inRange(hsv, ORANGE_HSV_LO, ORANGE_HSV_HI), mask)
    orange = cv2.morphologyEx(orange, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(orange)
    found = []
    for i in range(1, count):
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if w == 0 or h == 0:
            continue
        if not BALL_ASPECT[0] <= w / h <= BALL_ASPECT[1]:
            continue
        contact_y = float(stats[i, cv2.CC_STAT_TOP] + h)
        diameter = float(court.normalise(max(w, h), contact_y))
        if not BALL_DIAMETER_NORM[0] <= diameter <= BALL_DIAMETER_NORM[1]:
            continue
        cx, cy = court.to_court(float(centroids[i][0]), contact_y)
        if abs(float(cy) - CENTRE_LINE_M) > BALL_LINE_TOLERANCE_M:
            continue
        found.append(float(cx))
    return sorted(found)


def is_armed(ball_positions: list[float]) -> bool:
    """Whether a frame's balls are laid out for a set rather than in play."""
    if len(ball_positions) < ARMED_MIN_BALLS:
        return False
    return ball_positions[-1] - ball_positions[0] >= ARMED_MIN_SPREAD_M


def armed_windows(video: str | Path, court: Court,
                  stride: int = ARMED_SAMPLE_STRIDE) -> list[ArmedWindow]:
    """Every stretch of the clip where the balls sit laid out on the line."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or court.fps
    mask = centre_line_mask(court, court.frame_size)
    samples: list[tuple[int, int, float]] = []
    index = 0
    while True:
        if index % stride:
            if not cap.grab():
                break
        else:
            ok, frame = cap.read()
            if not ok:
                break
            found = balls_on_line(frame, court, mask)
            if is_armed(found):
                samples.append((index, len(found), found[-1] - found[0]))
        index += 1
    cap.release()

    windows: list[ArmedWindow] = []
    # A ball briefly hidden by someone walking past must not split a window.
    gap = stride * 3
    for frame_index, balls, spread in samples:
        if windows and frame_index - windows[-1].end_frame <= gap:
            last = windows[-1]
            last.end_frame = frame_index
            last.max_balls = max(last.max_balls, balls)
            last.max_spread_m = max(last.max_spread_m, spread)
        else:
            windows.append(ArmedWindow(frame_index, frame_index, balls, spread))
    return [w for w in windows
            if (w.end_frame - w.start_frame) / fps >= ARMED_MIN_DURATION_S]


def whistle_prominence(video: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Whistle-band prominence over time, in dB above the crowd.

    Returns sample times in seconds and the prominence at each. Decoded straight
    from the clip so the times share the clip's own timeline and need no offset
    to line up with frame indices.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not on PATH; the whistle gate needs it to decode audio")
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1",
         "-ar", str(WHISTLE_SAMPLE_RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio = np.frombuffer(decoded.stdout, np.int16).astype(np.float32) / 32768.0
    # A clip cut without an audio track is a silent failure otherwise: every set
    # would come back unconfirmed with nothing saying why.
    if len(audio) < WHISTLE_WINDOW:
        raise RuntimeError(
            f"no usable audio in {Path(video).name} - the whistle gate cannot run. "
            f"ffmpeg said: {decoded.stderr.decode(errors='replace').strip() or 'nothing'}")
    frames = (len(audio) - WHISTLE_WINDOW) // WHISTLE_HOP
    window = np.hanning(WHISTLE_WINDOW)
    strided = np.lib.stride_tricks.as_strided(
        audio, shape=(frames, WHISTLE_WINDOW),
        strides=(audio.strides[0] * WHISTLE_HOP, audio.strides[0]))
    spectrum = np.abs(np.fft.rfft(strided * window, axis=1))
    freqs = np.fft.rfftfreq(WHISTLE_WINDOW, 1.0 / WHISTLE_SAMPLE_RATE)
    band = (freqs >= WHISTLE_BAND_HZ[0]) & (freqs <= WHISTLE_BAND_HZ[1])
    reference = (freqs >= WHISTLE_REFERENCE_BAND_HZ[0]) & (freqs < WHISTLE_REFERENCE_BAND_HZ[1])
    peak = spectrum[:, band].max(axis=1)
    floor = spectrum[:, reference].mean(axis=1)
    prominence = 20 * np.log10((peak + 1e-9) / (floor + 1e-9))
    times = np.arange(frames) * WHISTLE_HOP / WHISTLE_SAMPLE_RATE
    return times, prominence


def loudest_whistle(times: np.ndarray, prominence: np.ndarray,
                    window_s: tuple[float, float]) -> tuple[float, float] | None:
    """Onset and strength of the strongest whistle inside a time window.

    The onset is reported rather than the peak: a whistle takes a moment to reach
    full volume, and play starts when the referee blows it, not when the tone
    tops out.
    """
    inside = (times >= window_s[0]) & (times <= window_s[1])
    if not inside.any():
        return None
    loud = inside & (prominence >= WHISTLE_MIN_PROMINENCE_DB)
    if not loud.any():
        return None
    indices = np.flatnonzero(loud)
    runs = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    step = float(times[1] - times[0]) if len(times) > 1 else 0.0
    runs = [r for r in runs if len(r) * step >= WHISTLE_MIN_DURATION_S]
    if not runs:
        return None
    best = max(runs, key=lambda r: prominence[r].max())
    return float(times[best[0]]), float(prominence[best].max())


def mid_court_players(detections: list[dict], court: Court) -> int:
    """How many players stand on the floor neither team occupies while waiting."""
    total = 0
    for detection in detections:
        if detection.get("conf", 0.0) < PLAYER_MIN_CONF:
            continue
        x, y, _ = foot_point(detection)
        cx, cy = court.to_court(x, y)
        if not court.on_court(cx, cy):
            continue
        if MID_COURT_M[0] <= float(cy) <= MID_COURT_M[1]:
            total += 1
    return total


def sprint_frame(pose, court: Court, from_frame: int, fps: float) -> int | None:
    """First frame after ``from_frame`` where the teams have broken for the balls."""
    last = min(int(from_frame + SPRINT_WINDOW_S * fps), pose.frame_count - 1)
    for index in range(from_frame, last + 1):
        if mid_court_players(pose.frame(index), court) >= SPRINT_MIN_PLAYERS:
            return index
    return None


def first_ball_moves(video: str | Path, court: Court, window: ArmedWindow) -> int | None:
    """First frame at the end of an armed window where the layout breaks.

    The fallback start time when there is no usable audio. It is later than the
    whistle by the players' reaction and their run to the line, so it is a bound
    rather than an equivalent.
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {video}")
    mask = centre_line_mask(court, court.frame_size)
    cap.set(cv2.CAP_PROP_POS_FRAMES, window.start_frame)
    index = window.start_frame
    result = None
    limit = window.end_frame + ARMED_SAMPLE_STRIDE * 3
    while index <= limit:
        ok, frame = cap.read()
        if not ok:
            break
        if not is_armed(balls_on_line(frame, court, mask)):
            result = index
            break
        index += 1
    cap.release()
    return result


def detect_set_starts(video: str | Path, court: Court, pose) -> list[SetStart]:
    """Find every set start in a clip.

    Armed windows are found first because they are what makes the other two
    signals safe to trust; a whistle or a surge into mid-court is looked for only
    inside one.
    """
    fps = court.fps
    windows = armed_windows(video, court)
    times, prominence = whistle_prominence(video)
    results = []
    for window in windows:
        result = SetStart(armed=window)
        span = (window.start_frame / fps, (window.end_frame + fps) / fps)
        whistle = loudest_whistle(times, prominence, span) if len(times) else None
        if whistle is None:
            result.status = "no_whistle"
            result.notes.append(
                "balls laid out but no whistle before the layout broke or the clip ended")
            result.first_ball_moves_frame = first_ball_moves(video, court, window)
            results.append(result)
            continue
        onset_s, strength = whistle
        result.start_frame = int(round(onset_s * fps))
        result.whistle_prominence_db = strength
        result.sprint_frame = sprint_frame(pose, court, result.start_frame, fps)
        result.first_ball_moves_frame = first_ball_moves(video, court, window)
        if result.sprint_frame is None:
            result.status = "unconfirmed"
            result.notes.append(
                "whistle inside the layout but no break for the balls after it")
        else:
            result.status = "confirmed"
        results.append(result)
    return results


@dataclass(frozen=True)
class LivePlayInterval:
    """A stretch of a clip where a set is being played.

    ``end_is_bound`` says the end is an upper bound rather than the moment play
    actually stopped. A set ends on its last elimination, which needs the throw
    outcome resolver; until that exists the end is taken as the moment the balls
    are laid out again, which is later by the huddle between sets.
    """

    start_frame: int
    end_frame: int
    end_is_bound: bool

    def contains(self, frame: int) -> bool:
        return self.start_frame <= frame <= self.end_frame


@dataclass(frozen=True)
class SetTimeline:
    """The set starts found in one clip, as written to ``data/sets/``.

    The reader half of ``scripts/detect_set_start.py``. Downstream stages take
    their live-play intervals from here rather than re-deriving them, so a throw
    is judged in or out of play by the same intervals the metric is computed
    over.
    """

    video: str
    clip_sha256: str
    fps: float
    frame_count: int
    clip_offset_s: float
    thresholds: dict
    sets: list[dict]

    @classmethod
    def load(cls, path: str | Path) -> "SetTimeline":
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"{path} is schema {data.get('schema_version')}, expected {SCHEMA_VERSION}")
        return cls(
            video=data["video"],
            clip_sha256=data["clip_sha256"],
            fps=float(data["fps"]),
            frame_count=int(data["frame_count"]),
            clip_offset_s=float(data.get("clip_offset_s", 0.0)),
            thresholds=data.get("thresholds", {}),
            sets=data["sets"],
        )

    @classmethod
    def for_video(cls, video: str | Path) -> "SetTimeline":
        path = SETS_ROOT / f"{Path(video).stem}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"no set timeline at {path}; run scripts/detect_set_start.py")
        return cls.load(path)

    def check_clip(self, clip_sha256: str) -> None:
        """Refuse to mix a timeline with a different cut of the footage.

        Frame indices are all that tie calibration, detections, labels and this
        timeline together, and a re-encode shifts them without changing a
        filename.
        """
        if self.clip_sha256 != clip_sha256:
            raise ValueError(
                f"set timeline for {self.video} was computed on a different clip")

    @property
    def starts(self) -> list[int]:
        """Frames where a set was confirmed to start, in order."""
        return sorted(s["start_frame"] for s in self.sets
                      if s["status"] == "confirmed" and s["start_frame"] is not None)

    def live_play_intervals(self) -> list[LivePlayInterval]:
        """When a set is in progress, one interval per confirmed start.

        A set ends somewhere before the balls are laid out for the next one, so
        the next layout bounds it. Where no further layout is seen the clip's own
        end bounds it instead - still a bound, and still marked as one.
        """
        layouts = sorted(s["armed"]["start_frame"] for s in self.sets)
        intervals = []
        for start in self.starts:
            later = [f for f in layouts if f > start]
            end = later[0] if later else self.frame_count - 1
            intervals.append(LivePlayInterval(start, end, end_is_bound=True))
        return intervals

    def interval_for(self, frame: int) -> LivePlayInterval | None:
        """The set a frame belongs to, or None if it falls in dead time."""
        for interval in self.live_play_intervals():
            if interval.contains(frame):
                return interval
        return None
