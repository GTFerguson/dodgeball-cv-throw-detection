#!/usr/bin/env python3
"""Put jersey numbers on the players in a clip, and write its roster.

Three stages. ByteTrack follows every player on court for as long as it can, which
on the evaluation clip is most of a set. Then each track's largest crops - the
frames where that player was closest to the camera - are read for a number, and a
number several crops agree on is confirmed for the whole track. Then every track
is given a role and a side, and tracks that confirm to the same number on the
same side, one after another, are joined into one player.

That order is what makes it work. Reading is hard at the far baseline and easy at
the near one, and a track that spans a set contains both, so the number never has
to be read where it is hard.

Writes ``data/roster/<stem>.json`` - the one file that says who is a player, on
which side, wearing what number, and which detection on which frame was them -
and, with --sheet, a contact sheet of the crops behind each confirmed number and
of every long player track the vote declined to name, in time order, so a reader
that keeps dropping a digit can be told by eye from a tracker that stitched two
players together.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
# setstart imports its siblings bare, the rest of src by package; serve both.
sys.path.insert(0, str(REPO_ROOT / "src"))

from setstart import SetTimeline  # noqa: E402
from src.court import Court  # noqa: E402
from src.jersey import (  # noqa: E402
    Crop,
    CropKeeper,
    JerseyReader,
    Reading,
    confirm,
    in_time_order,
    needs_review,
    shortlist,
    switch,
    torso_crop,
    unobstructed,
)
from src.players import (  # noqa: E402
    CLAIM_MIN_READINGS,
    clash,
    fold_by_occupancy,
    join,
    swaps_between,
    worn_at_once,
)
from src.pose import PoseRun  # noqa: E402
from src.roster import (  # noqa: E402
    PLAYER_MIN_CORE_FRAMES,
    Participant,
    Roster,
    TrackRecord,
    assign_role,
    assign_team,
    chest_region,
    core_of,
    intervals_of,
    kit_fractions,
    live_cores,
    participant_id,
    sides_from,
    vote_kit,
)
from src.tracking import (  # noqa: E402
    cut_frame,
    held_in_play,
    swap_frame,
    tracks_continue,
    tracks_together,
)
from src.tracking import track as track_players

# A track shorter than this is a detection artefact rather than a player, and
# naming one spends an identity on noise.
MIN_TRACK_FRAMES = 25

# Crops are collected every few frames. Consecutive frames show the same pose from
# the same distance, so they are near-duplicates as far as a reader is concerned,
# and keeping all of them just fills the shortlist with one moment.
SAMPLE_EVERY = 5

# Kit colour is sampled more sparsely still: a chest is the same colour on every
# frame, and it is sampled on every track, officials included.
KIT_SAMPLE_EVERY = 10


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="clip stem or path under data/footage/")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--sheet", type=Path, default=None)
    ap.add_argument("--cpu", action="store_true", help="run OCR on the CPU")
    args = ap.parse_args()

    stem = Path(args.video).stem
    court = Court.for_video(stem)
    run = PoseRun.for_video(stem)
    timeline = SetTimeline.for_video(stem)
    timeline.check_clip(run.manifest["clip_sha256"])
    cores = live_cores(timeline, run.fps)
    if not cores:
        print("no confirmed set start: roles can only come from kit", file=sys.stderr)

    end = args.end if args.end is not None else run.frame_count
    frames = {f: run.frame(f) for f in range(args.start, end)}
    tracks = track_players(court, frames, run.fps)
    tracks = [t for t in tracks if len(t.frames) >= MIN_TRACK_FRAMES]
    span = end - args.start
    held = sum(len(t.frames) for t in tracks)
    lengths = sorted(len(t.frames) for t in tracks)
    print(f"{len(tracks)} tracks over {span} frames "
          f"({held / span:.1f} concurrent, median {lengths[len(lengths) // 2]} frames)")

    video = REPO_ROOT / "data" / "footage" / f"{stem}.mp4"
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"cannot open {video}", file=sys.stderr)
        return 1

    # Only frames where the player is in play are worth a crop. Tracking admits
    # the margin band, which is where the officials stand and the eliminated wait,
    # and a referee's stripes read as a digit as readily as a jersey does. Nothing
    # off court needs a name: attribution only ever asks about players in play.
    # Kit colour is the opposite: it is wanted on every track, because it is what
    # tells an official from a player who was never in live play.
    playing = {t.id: held_in_play(court, t) for t in tracks}
    wanted: dict[int, list] = defaultdict(list)
    kit_wanted: dict[int, list] = defaultdict(list)
    for t in tracks:
        for i, (f, on) in enumerate(zip(t.frames, playing[t.id], strict=True)):
            if on and i % SAMPLE_EVERY == 0:
                wanted[f].append(t)
            if i % KIT_SAMPLE_EVERY == 0:
                kit_wanted[f].append(t)

    # Bounded per track: the shortlist's crops and no more. See CropKeeper.
    crops: dict[int, CropKeeper] = defaultdict(CropKeeper)
    kit_samples: dict[int, list[tuple[int, tuple[float, float, float]]]] = defaultdict(list)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)
    for f in range(args.start, end):
        ok, image = cap.read()
        if not ok:
            break
        for t in wanted.get(f, ()):
            det = t.at(f)
            if det is None or not unobstructed(det, frames[f]):
                continue
            crop = torso_crop(image, det)
            if crop is not None:
                crops[t.id].add(Crop(frame=f, image=crop))
        for t in kit_wanted.get(f, ()):
            det = t.at(f)
            if det is None or not unobstructed(det, frames[f]):
                continue
            region = chest_region(det)
            if region is None:
                continue
            x1, y1, x2, y2 = region
            chest = image[y1:y2, x1:x2]
            if chest.size:
                kit_samples[t.id].append((f, kit_fractions(chest)))
    cap.release()

    with_crops = sum(1 for t in tracks if crops.get(t.id))
    print(f"{with_crops}/{len(tracks)} tracks have a crop tall enough to read")

    reader = JerseyReader(gpu=not args.cpu)
    evidence: dict[int, list[Reading]] = {}
    shortlists: dict[int, list[Crop]] = {}
    for t in tracks:
        picked = shortlist(crops[t.id].crops()) if t.id in crops else []
        if not picked:
            continue
        shortlists[t.id] = picked
        readings: list[Reading] = []
        for crop in picked:
            readings.extend(reader.read(crop))
        evidence[t.id] = readings

    # What every player on a side wears is not a number. The team's name sits
    # above the number on the chest and the reader returns it as digits, so it
    # arrives looking like a number several players wear at once - which no
    # number is. Dropped here, before anything is cut or named, so that neither
    # the switch nor the vote ever sees it.
    counts = {tid: Counter(r.number for r in rs) for tid, rs in evidence.items()}
    spans = {t.id: (t.start, t.end) for t in tracks}
    not_numbers = worn_at_once(spans, counts)
    if not_numbers:
        wearers = {n: sorted(i for i in counts if counts[i][n] >= CLAIM_MIN_READINGS)
                   for n in sorted(not_numbers)}
        for number, ids in wearers.items():
            print(f"#{number} is worn by {len(ids)} players at once - not a number: "
                  f"tracks {', '.join(str(i) for i in ids)}")
        evidence = {tid: [r for r in rs if r.number not in not_numbers]
                    for tid, rs in evidence.items()}

    # A track whose readings name one player and then another changed player
    # while the tracker was not looking. It is cut where the change is, and each
    # half is named on its own readings. A half can switch again, so cut until
    # nothing does.
    splits: dict[int, tuple[int, int]] = {}
    switched: dict[int, int] = {}
    next_id = max(t.id for t in tracks) + 1

    def cut(t, at: int):
        """Split a track at a frame, dividing its readings, crops and kit samples."""
        nonlocal next_id
        head, tail = t.split(at, next_id)
        next_id += 1
        # The head keeps the id, so take both halves before either is stored.
        whole_readings, whole_crops = evidence.get(t.id, []), shortlists.get(t.id, [])
        whole_kit = kit_samples.get(t.id, [])
        evidence[head.id] = [r for r in whole_readings if r.frame < at]
        evidence[tail.id] = [r for r in whole_readings if r.frame >= at]
        shortlists[head.id] = [c for c in whole_crops if c.frame < at]
        shortlists[tail.id] = [c for c in whole_crops if c.frame >= at]
        kit_samples[head.id] = [k for k in whole_kit if k[0] < at]
        kit_samples[tail.id] = [k for k in whole_kit if k[0] >= at]
        splits[tail.id] = (t.id, at)
        return head, tail

    queue = list(tracks)
    tracks = []
    while queue:
        t = queue.pop(0)
        found = switch(evidence.get(t.id, []))
        if found is None:
            tracks.append(t)
            continue
        a, b, last_a, first_b = found
        at = cut_frame(t, last_a, first_b)
        head, tail = cut(t, at)
        print(f"track {t.id} reads #{a} then #{b}: cut at {at} -> {head.id}, {tail.id}")
        switched[head.id], switched[tail.id] = a, b
        queue[:0] = [head, tail]
    tracks = [t for t in tracks if t.frames]

    # Two tracks on court together that read one number one after the other
    # traded players where their boxes crossed: the number stayed on the man
    # and moved between the ids. Neither track reads two numbers, so the
    # switch above cannot see it; the pair can. Both are cut at the crossing,
    # the halves that read the number are named by it, and the other two halves
    # are the other player, left for the reader or the fold.
    def claim_windows():
        out: dict[int, dict[str, tuple[int, int]]] = {}
        for tid, rs in evidence.items():
            counts = Counter(r.number for r in rs)
            for number, n in counts.items():
                if n >= CLAIM_MIN_READINGS:
                    frames = [r.frame for r in rs if r.number == number]
                    out.setdefault(tid, {})[number] = (min(frames), max(frames))
        return out

    by_id = {t.id: t for t in tracks}
    for swap in swaps_between({t.id: (t.start, t.end) for t in tracks}, claim_windows()):
        a, b = by_id.get(swap.a), by_id.get(swap.b)
        if a is None or b is None:
            continue
        at = swap_frame(a, b, swap.last_a, swap.first_b)
        if at is None:
            print(f"tracks {a.id} and {b.id} read #{swap.number} one after the other but never crossed: "
                  f"left as they are")
            continue
        a_head, a_tail = cut(a, at)
        b_head, b_tail = cut(b, at)
        print(f"tracks {a.id} and {b.id} traded players at {at}: #{swap.number} is {a_head.id} then "
              f"{b_tail.id}; {b_head.id} and {a_tail.id} are the other")
        switched[a_head.id] = switched[b_tail.id] = swap.number
        for old, halves in ((a, (a_head, a_tail)), (b, (b_head, b_tail))):
            tracks.remove(old)
            tracks.extend(h for h in halves if h.frames)
        by_id = {t.id: t for t in tracks}
    tracks.sort(key=lambda t: (t.start, t.id))
    playing = {t.id: held_in_play(court, t) for t in tracks}

    # A half cut off a switched track is named by the switch that cut it: the
    # readings that confirmed a change of player are the readings it has, and
    # asking them to confirm again at the higher bar leaves the new man unnamed.
    numbers: dict[int, str] = {}
    for t in tracks:
        got = confirm(evidence.get(t.id, []))
        if got is None:
            got = switched.get(t.id)
        if got is not None:
            numbers[t.id] = got

    read_any = sum(1 for r in evidence.values() if r)
    print(f"{read_any} tracks returned a reading, {len(numbers)} confirmed")

    # Where each track was while in play, and which set's live core that was
    # inside - the evidence for calling it a player, and for which sets it played.
    half_counts: dict[int, Counter] = {}
    core_frames: dict[int, Counter] = {}
    for t in tracks:
        halves = Counter()
        core = Counter()
        for (_cx, cy), f, on in zip(t.points, t.frames, playing[t.id], strict=True):
            if on:
                halves[str(court.half(cy))] += 1
                inside = core_of(f, cores)
                if inside is not None:
                    core[inside] += 1
        half_counts[t.id], core_frames[t.id] = halves, core

    kits = {t.id: vote_kit([k for _, k in kit_samples.get(t.id, [])]) for t in tracks}
    sides = sides_from([(kits[t.id][0], half_counts[t.id].most_common(1)[0][0])
                        for t in tracks if core_frames[t.id] and half_counts[t.id]])
    print(f"sides: {sides or 'not established'}")
    roles = {t.id: assign_role(kits[t.id][0], sum(core_frames[t.id].values())) for t in tracks}
    teams = {t.id: assign_team(dict(half_counts[t.id]), kits[t.id][0], sides) for t in tracks}

    # Tracks that confirm to the same number on the same side, in sequence, are
    # one player whose track broke; the same number on two tracks at once is two
    # people the side could not tell apart.
    spans = {t.id: (t.start, t.end) for t in tracks}
    players = join(spans, numbers, {tid: teams[tid][0] for tid in numbers})
    print(f"{len(players)} numbered players from {len(numbers)} named tracks")
    for p in players:
        print(f"  {p.team or '?':<5} #{p.number:<3} {p.start:>5}-{p.end:<5} "
              f"tracks {', '.join(map(str, p.track_ids))}")
    for key in sorted({(p.team, p.number) for p in players}, key=lambda k: (k[0] or "", k[1])):
        worn_by = [tid for tid, n in numbers.items() if n == key[1] and teams[tid][0] == key[0]]
        pair = clash(spans, worn_by)
        if pair is not None:
            print(f"  {key[0]} #{key[1]} is on tracks {pair[0]} and {pair[1]} at once: not joined")

    # The pieces no number was read on: a piece in play on a side while exactly
    # one of its six has no track is that player; one in play when all six are
    # tracked is a seventh body, and no player.
    pieces = [t.id for t in tracks if t.id not in numbers and roles[t.id] == "player"
              and core_frames[t.id]]
    by_id = {t.id: t for t in tracks}
    claims = {tid: set(numbers_read) for tid, numbers_read in claim_windows().items()}
    fold = fold_by_occupancy(players, pieces, spans, {tid: teams[tid][0] for tid in spans},
                             {tid: dict(core_frames[tid]) for tid in spans}, PLAYER_MIN_CORE_FRAMES,
                             together=lambda a, b: tracks_together(by_id[a], by_id[b]),
                             continues=lambda a, b: tracks_continue(by_id[a], by_id[b]),
                             claims=claims)
    players = fold.players
    for tid, p in sorted(fold.folded.items(), key=lambda kv: spans[kv[0]]):
        print(f"  track {tid} {spans[tid][0]}-{spans[tid][1]} folded into {p.team} #{p.number}: "
              f"the one of the six with no track then")
    for tid in sorted(fold.excess, key=lambda t: spans[t]):
        print(f"  track {tid} {spans[tid][0]}-{spans[tid][1]} is a seventh body on the "
              f"{teams[tid][0]} side: excess, not a player who played")
    for tid in sorted(fold.unsure, key=lambda t: spans[t]):
        why = f"read #{'/'.join(sorted(claims[tid]))}" if claims.get(tid) else "two of the six missing, or fewer than six known"
        print(f"  track {tid} {spans[tid][0]}-{spans[tid][1]} on the {teams[tid][0]} side left unnamed: {why}")
    print(f"{len(fold.folded)} pieces folded, {len(fold.excess)} excess, {len(fold.unsure)} left unnamed")
    number_of = dict(numbers)
    number_of.update({tid: p.number for tid, p in fold.folded.items()})

    owner: dict[int, str] = {}
    participants: dict[str, Participant] = {}
    for p in players:
        ids = list(p.track_ids)
        role = "player" if any(roles[i] == "player" for i in ids) else roles[ids[0]]
        if role != "player":
            print(f"  #{p.number} on tracks {ids} was never seen in play; kept as {role}")
        pid = participant_id(role, p.team, p.number, ids[0])
        while pid in participants:
            pid += "'"
        participants[pid] = Participant(
            id=pid, role=role, team=p.team, number=p.number, track_ids=tuple(ids),
            start_frame=p.start, end_frame=p.end,
            core_in_play_by_set=dict(sum((core_frames[i] for i in ids), Counter())))
        for i in ids:
            owner[i] = pid
    for t in tracks:
        if t.id in owner:
            continue
        role, (team, _) = roles[t.id], teams[t.id]
        pid = participant_id(role, team, numbers.get(t.id), t.id)
        while pid in participants:
            pid += "'"
        participants[pid] = Participant(id=pid, role=role, team=team, number=numbers.get(t.id),
                                        track_ids=(t.id,), start_frame=t.start, end_frame=t.end,
                                        core_in_play_by_set=dict(core_frames[t.id]),
                                        excess=t.id in fold.excess)
        owner[t.id] = pid

    records: dict[int, TrackRecord] = {}
    for t in tracks:
        detections = []
        for f, det in zip(t.frames, t.detections, strict=True):
            index = next(i for i, d in enumerate(frames[f]) if d is det)
            detections.append((f, index))
        kit, share = kits[t.id]
        team, source = teams[t.id]
        records[t.id] = TrackRecord(
            id=t.id, participant_id=owner[t.id], role=roles[t.id], team=team,
            team_source=source, kit=kit, kit_share=share, number=number_of.get(t.id),
            number_source=("read" if t.id in numbers else "occupancy" if t.id in fold.folded else None),
            start_frame=t.start, end_frame=t.end, detections=tuple(detections),
            in_play=tuple(intervals_of(t.frames, playing[t.id])),
            core_in_play_by_set=dict(core_frames[t.id]), split_from=splits.get(t.id),
            readings=tuple((r.frame, r.number, r.confidence)
                           for r in sorted(evidence.get(t.id, []), key=lambda r: r.frame)))

    roster = Roster(
        video=f"{stem}.mp4", clip_sha256=run.manifest["clip_sha256"], pose_run=run.dir.name,
        fps=run.fps, frame_count=run.frame_count, sides=sides,
        live_cores=cores, tracks=records, participants=participants)
    out = roster.write(REPO_ROOT / "data" / "roster" / f"{stem}.json")
    back = Roster.load(out)
    by_role = Counter(t.role for t in back.tracks.values())
    print(f"\n{len(back.tracks)} tracks: " + ", ".join(f"{n} {r}" for r, n in by_role.items()))
    for team in ("near", "far"):
        ps = back.players(team)
        played = back.played(team)
        named = sorted(p.number for p in played if p.number is not None)
        print(f"  {team}: {len(ps)} players, {len(played)} played - "
              f"numbered {named}, {sum(p.number is None for p in played)} unnamed")
        for s in sorted(back.live_cores):
            in_set = back.played(team, s)
            print(f"    set {s + 1}: {len(in_set)} played - "
                  f"numbered {sorted(p.number for p in in_set if p.number is not None)}, "
                  f"{sum(p.number is None for p in in_set)} unnamed")
    print(f"  {len(back.officials())} officials, {len(back.unknown())} unknown, "
          f"{len(back.excess())} excess")
    print(f"wrote {out.relative_to(REPO_ROOT)}")

    review = [t for t in tracks if roles[t.id] == "player"
              and needs_review(numbers.get(t.id), sum(playing[t.id]), span)]
    print(f"{len(review)} long player tracks left unnamed: "
          + ", ".join(str(t.id) for t in review))

    if args.sheet:
        write_sheet(args.sheet, tracks, numbers, evidence, shortlists, review)
        print(f"wrote {args.sheet}")
    return 0


def write_sheet(path: Path, tracks, numbers, evidence, shortlists, review) -> None:
    """Each named track beside the crops that named it, then the unnamed long ones.

    Crops run left to right in frame order and each carries what the reader made
    of it, so a track whose readings switch part-way - one player then another -
    looks different from one the reader misreads throughout.
    """
    cell = 96
    caption = 16
    rows = []
    for t in tracks:
        if t.id not in numbers and t not in review:
            continue
        by_frame: dict[int, list[int]] = defaultdict(list)
        for r in evidence.get(t.id, []):
            by_frame[r.frame].append(r.number)
        rows.append((t, numbers.get(t.id), by_frame,
                     in_time_order(shortlists.get(t.id, []))))
    # Named tracks first, by number; the questions after, longest first.
    rows.sort(key=lambda r: (r[1] is None, r[1] or 0, -len(r[0].frames)))
    if not rows:
        return
    width = max(sum(int(c.image.shape[1] * cell / c.height) + 6 for c in r[3])
                for r in rows) + 210
    row_h = cell + caption + 14
    sheet = np.full((row_h * len(rows) + 10, max(width, 400), 3), 250, np.uint8)
    y = 6
    for t, number, by_frame, crops in rows:
        label = f"#{number}" if number is not None else "?"
        cv2.putText(sheet, label, (8, y + 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (20, 20, 20), 2)
        cv2.putText(sheet, f"track {t.id}  {t.start}-{t.end}", (8, y + 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (90, 90, 90), 1)
        counts = Counter(n for ns in by_frame.values() for n in ns)
        cv2.putText(sheet, dict(counts).__repr__()[:22], (8, y + 74),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (90, 90, 90), 1)
        x = 120
        for crop in crops:
            up = cv2.resize(crop.image, (int(crop.image.shape[1] * cell / crop.height), cell),
                            interpolation=cv2.INTER_AREA)
            if x + up.shape[1] >= sheet.shape[1]:
                break
            sheet[y:y + cell, x:x + up.shape[1]] = up
            seen = ",".join(str(n) for n in by_frame.get(crop.frame, [])) or "-"
            cv2.putText(sheet, f"f{crop.frame} {seen}", (x, y + cell + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (60, 60, 60), 1)
            x += up.shape[1] + 6
        y += row_h
    cv2.imwrite(str(path), sheet)


if __name__ == "__main__":
    raise SystemExit(main())
