---
title: Reading Jersey Numbers from Video
created: 2026-08-26
updated: 2026-08-26
status: active
tags: [ocr, jersey, identity, reference]
---

# Reading Jersey Numbers from Video

Evidence for how jersey numbers are read from sports video, what the published
pipelines do, and what the literature says about the two decisions this project
had to make by hand: which frames to read, and how to turn several readings into
one name. Written after a measured failure on this clip (§5) that the literature
predicts.

## 1. The number is legible on a small minority of frames

| Source | Data | Legible frames |
|---|---|---|
| Tier 3: Koshkina & Elder (2024), *CVPRW*, 132,983 hockey images | Human-labelled | **5.0%** train, 8.7% test |
| Tier 3: Balaji et al. (2023), *MMSports*, 2,052,306 soccer images | Machine-filtered | **12.35%** retained |

Koshkina & Elder note the imbalance "reflects the true distribution", where
legible means "the annotator could be certain of the jersey number". Vats et al.
(2023) go further: **50.4% of their 3,510 hockey tracklets are `null`** — the
number is never legible anywhere in the track (Tier 3: *Expert Systems with
Applications* 213:119250).

This matches what the identity pass sees here, and it is why reading is organised
around a shortlist of the best crops rather than every frame.

## 2. The split that matters: detectors fail, recognisers transfer

Off-the-shelf scene-text **detection** on sports video is a precision disaster,
measured three times on three sports:

| Measurement | Off the shelf | Adapted | Source |
|---|---|---|---|
| **CRAFT detection H-mean**, basketball | **0.50** (P 0.54 / R 0.46) | **0.97** | Tier 3: Nady & Hemayed (2021), *VISAPP*, Table 3 |
| Text-spotter detection precision, racing numbers | **0.19–0.23** | 0.81–0.85 | Tier 3: Tyo et al. (2023), arXiv:2311.09256, Table 1 |
| Mask TextSpotter V3 / SwinTextSpotter, jersey AP50 | **2.43 / 6.85** | 26.87–50.69 (number-specific detector) | Tier 3: Liu & Bhanu (2022), *IEEE TCSVT* 32(11), Table III |

That first row is this project's exact detector: **CRAFT off the shelf scores an
H-mean of 0.50 on jersey numbers**, and fine-tuning takes it to 0.97. Tyo et
al.'s 0.19 precision means roughly four in five boxes a general spotter emits are
not the number.

Scene-text **recognition** is the opposite. Given an already-localised torso
crop, a general recogniser beats purpose-built classifiers (Tier 3: Koshkina &
Elder, 2024, *CVPRW*, Table 5, hockey):

| Model | Accuracy |
|---|---|
| Holistic classifier (ResNet34, numbers as classes) | 48.1% |
| Multi-task classifier (Vats et al., 2021) | 65.2% |
| **PARSeq scene-text recogniser, off the shelf** | **85.4%** |
| PARSeq fine-tuned on hockey | 91.4% |

The reconciliation: every result where a general system loses is a **detection**
result on uncropped input; the result where it wins is a **recognition** result
on a pose-cropped torso. Nady & Hemayed's own baseline — pretrained CRAFT plus a
strong recogniser — scores 65.64% against a plain CNN classifier's 84.73% on the
same set, because the detector is doing the losing.

**This is the frame for §5.** The recogniser used here is not the problem; given
a clean box it returns `55` at confidence 1.00. The detector stage is.

## 3. Localise before reading, and pose is the cheap way

| Approach | Geometry | Result |
|---|---|---|
| No localisation, fixed prior | Upper half of a 64×128 player box | 0.83 (Tier 3: Gerke et al., 2015, *ICCVW*) |
| Learned spatial transformer | Affine sample of the last conv map | +0.8 pt, +0.6 more with corner supervision (Tier 3: Li et al., 2018, *CVPRW*) |
| **Pose-guided digit regression** | 4 keypoints (shoulders, hips) | **92.14%** vs 89.02% for Faster R-CNN (Tier 3: Liu & Bhanu, 2019, Table 2) |
| Pose torso crop, off-the-shelf keypoints | Shoulder-and-hip rectangle, 5 px pad | Koshkina & Elder (2024) — chosen for annotation economy, **not ablated** |
| Fixed torso fraction | Remove top 1/6 and bottom 1/3 of the box | Tier 4: Grad (2025), *CVPRW* |

Liu & Bhanu isolate the source of their gain: a 3-class region proposal network
is worth "−0.09, 0.12 and −0.14" on mAP/AP50/AP75 — nothing — while pose
supervision gives "4.14 gain over Faster R-CNN". The keypoints carry it.

`src/jersey.py:torso_crop` takes the top 60% of the **detection box**, with a
comment noting the deliberate choice of box over keypoints ("a shoulder keypoint
drops out exactly when a player turns"). That is defensible on availability, but
it is the loosest crop in the table above, and it is what leaves the chest print
inside the region handed to the detector.

### A usable spatial prior

Liu & Bhanu (2019), Table 1, over 6,293 digit instances: the digit-mask centre
sits at **(0.50, 0.29) ± (0.12, 0.09)** of the player crop — horizontally
centred, 29% of the way down — with digit boxes 34.7 ± 15.2 px tall. Liu & Bhanu
(2022) add that the **digit-to-player box area ratio is about 2%**. A detection
occupying far more than that, or centred far from (0.50, 0.29), is not a number.

## 4. Which frames you read dominates how you count them

| Change | Effect | Source |
|---|---|---|
| Add a keyframe filter in front of the sequence model | **+37.8 to +40.5 points** | Tier 3: Balaji et al. (2023), Table 3 |
| Remove the tracklet visibility gate | **−33.1 points** (83.17% → 50.10%) | Tier 3: Vats et al. (2023), Table VI |
| Filter out frames where another player occludes the subject | +2.89 points | Tier 3: Koshkina & Elder (2024), Table 8 |
| Confidence-weighted vote instead of hard majority | +2.58 points | Vats et al. (2023), Table VI |
| Down-weight one-digit votes | +0.66 points | Koshkina & Elder (2024), Table 8 |

The admission policy is worth an order of magnitude more than the voting rule.
The pass here has the analogues of the first three — `held_in_play`,
`unobstructed()`, and the crop shortlist — and a comparatively elaborate voting
rule in `confirm()`.

## 5. Measured on this clip: a detector threshold, not a reader failure

**Finding (2026-08-26, this repo).** `OCR_PARAMS` in `src/jersey.py` lowers all
three CRAFT detection thresholds far below EasyOCR's defaults
(`text_threshold` 0.2 vs 0.7, `low_text` 0.1 vs 0.4, `link_threshold` 0.1 vs 0.4)
to make digits detectable on cloth at all. `low_text` is the region-score floor
that decides how far each character's activation blob grows before boxes are cut,
and CRAFT forms one text instance per 4-connected component of
`text_score OR link_score` (EasyOCR 1.7.2, `craft_utils.getDetBoxes_core`) — a
step with no notion of lines.

> [!IMPORTANT]
> **This fusion mode is an original observation here, not a literature finding.**
> No surveyed paper reports a text detector merging two separate text regions
> into one wrongly-grouped box; where grouping appears it is a deliberate feature
> (CRAFT's affinity score links characters into an instance) or an intentional
> stage (Balaji et al. merge nearby digit detections by hue). The published error
> runs the other way — under-reading a 2-digit number as 1 digit. The nearest
> published relative is Nady & Hemayed (2021) §3.1, who note "other text
> instances than jersey number printed on player's shirt such as player name and
> its club" and filter them geometrically, on the rule that a number's box has
> aspect ratio below 1.5. They report no error rate for it.

At `low_text=0.1` on this footage, the blobs of the `USA` chest print and the
number below it merge into a single component, and the recogniser is handed one
image containing both. With `allowlist="0123456789"` the print cannot come back
as letters, so it comes back as digits.

Raw readings over ~12–14 spread, unobstructed crops per track:

| Track | Shirt | At `low_text=0.1` | At `low_text=0.4` |
|---|---|---|---|
| 17 | USA 27 | `77`, `3`, `87`, `37`, `137` | **`27`×5** |
| 73 | USA 55 | `55`×2, `4`, `155`, `65`, `055` | **`55`×6** |
| 167 | USA 01 | `7` | **`01`×5** |
| 21 | USA 24 | `201`, `24`, `2` | **`24`×2** |
| 255 | 10 | `6`×2, `1` | **`10`×3** |
| 82 | 10 (unnamed) | `1`×2, `6`×2, `60`, `16`, `10` | **`10`×5** |
| 268 | `4C` (unnamed) | `7`, `4`, `1` | `40`×9; with letters allowed, **`4C`×10** |
| 285 | 7 | `7`×6, **`77`×3** | `7`×12, no `77` |

Three consequences:

1. **Both sides were affected**, not only the far side — every named near-side
   track reads its own number more often at the default threshold.
2. **Two failures recorded in [[../architecture/player-identity]] as reader
   behaviour are artefacts of this threshold**: the `6` that stands in for a `10`
   "whenever the 0 is on a fold" (track 255 reads `10` cleanly at the default),
   and the `77` that outvoted eight `7`s (absent at the default).
3. **The two-digit weighting in `confirm()` is calibrated against the wrong
   failure.** Koshkina & Elder weight *against* one-digit reads because occlusion
   makes a 2-digit number look like 1 digit 48% of the time versus the reverse
   at 7% (Table 3). That is an occlusion asymmetry. A detector that fuses a print
   into the number manufactures the 7% case instead, and doubling its weight
   amplifies the noise.

Raising `low_text` is not free: track 165, correctly named today, yields no
reading at all at the default because its crops are smaller. The setting trades
recall at distance against precision under a two-line print.

> [!NOTE]
> These are raw reads on hand-picked crops, not the pass's own shortlist, and not
> a scored evaluation. The claim is about the mechanism; the effect on named
> tracks needs the whole pass re-run both ways and checked against the by-eye
> verdict in [[../architecture/player-identity]].

## 6. Abstention: the published metrics do not measure what this project needs

Every paper surveyed scores plain accuracy, counting a correct abstention exactly
like a correct name and a wrong name exactly like a wrong abstention. SoccerNet
makes it explicit: accuracy is "the number of correctly predicted jersey numbers
(including −1 for non-visible numbers) over the total number of tracklets"
(Tier 4: Cioppa et al., 2023, arXiv:2309.06006, §8.2). **There is no published
risk-coverage or precision-at-coverage curve for jersey identity.**

The one explicit statement of the asymmetry is Chan et al. (2021), §3.2.2
(Tier 3: *Expert Systems with Applications* 165:113891):

> "Oftentimes, a player's jersey number is not always visible to viewers, so
> assigning a label to confirm a player is unknown is more appropriate than
> classifying the player with an incorrect label."

This project takes the same position for a sharper reason — a wrong number merges
two players and poisons every event attributed to either — and so operates
outside what the literature measures. **Published thresholds and accuracies are
calibrated for a symmetric game and cannot be transplanted.** `MIN_MAJORITY` and
`MIN_CONFIRMATIONS` have to be set against a measurement made here.

One structural safeguard is worth copying: Vats et al. keep `null` inside every
roster prior mask, so a known team sheet can never force a name onto an
unreadable track.

## 7. Readings across a track are not independent evidence

Vats et al. (2023) report **85% of misclassified two-digit numbers share a digit
with the ground truth** (55→65, 26→28), from "occlusions and folds in player
jerseys". Chan et al. (2021) independently find misreads land on numbers sharing
a tens digit — "the main source of error for our system".

A systematic misread repeats on every frame that shares its cause, so N agreeing
readings are not N independent confirmations. Diversity of viewing condition —
distance, pose, court end — carries more weight than a raw count. This is the
evidence behind reading a shortlist spread over a track's life rather than its
tallest crops alone.

## References

- Baek Y, Lee B, Han D, Yun S, Lee H (2019). Character Region Awareness for Text Detection. *CVPR 2019*. arXiv:1904.01941.
- Balaji B, Bright J, Prakash H, Chen Y, Clausi DA, Zelek J (2023). Jersey Number Recognition using Keyframe Identification from Low-Resolution Broadcast Videos. *MMSports '23*, pp. 123–130. doi:10.1145/3606038.3616162. arXiv:2309.06285.
- Chan A, Levine MD, Javan M (2021). Player identification in hockey broadcast videos. *Expert Systems with Applications* 165:113891. arXiv:2009.02429.
- Cioppa A, Giancola S, Somers V, et al. (2023). SoccerNet 2023 Challenges Results. arXiv:2309.06006.
- Gerke S, Muller K, Schafer R (2015). Soccer Jersey Number Recognition Using Convolutional Neural Networks. *ICCV Workshops*, pp. 17-24. doi:10.1109/ICCVW.2015.100.
- Grad P (2025). Jersey number recognition with digit-aware classification heads. *CVPR Workshops*.
- Koshkina M, Elder JH (2024). A General Framework for Jersey Number Recognition in Sports Video. *CVPRW 2024* (CVsports), pp. 3235–3244. doi:10.1109/CVPRW63382.2024.00329. arXiv:2405.13896.
- Li G, Xu S, Liu X, Li L, Wang C (2018). Jersey Number Recognition with Semi-Supervised Spatial Transformer Network. *CVPR Workshops*, pp. 1783-1790.
- Liu H, Bhanu B (2019). Pose-Guided R-CNN for Jersey Number Recognition in Sports. *CVPR Workshops*, pp. 2457-2466.
- Liu H, Bhanu B (2022). JEDE: Universal Jersey Number Detector for Sports. *IEEE TCSVT* 32(11):7894-7909.
- Nady A, Hemayed EE (2021). Player Identification in Different Sports. *VISAPP*, pp. 653-660. doi:10.5220/0010341706530660.
- Tyo J, et al. (2023). RnD: Racer Number Dataset. arXiv:2311.09256.
- Vats K, Fani M, Clausi DA, Zelek J (2021). Multi-task learning for jersey number recognition in ice hockey. *MMSports '21*, pp. 11–15. arXiv:2108.07848.
- Vats K, Walters P, Fani M, Clausi DA, Zelek JS (2023). Player tracking and identification in ice hockey. *Expert Systems with Applications* 213(A):119250. arXiv:2110.03090.
