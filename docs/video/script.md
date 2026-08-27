---
title: Walkthrough script
created: 2026-08-27
tags: [video, submission]
---

# Walkthrough script

Target 7½ minutes. The deck is `deck.html`, built from `deck.src.html` and `assets/` by
`build.py`. Full-screen the browser, arrow keys to advance. `m` mutes the sound
effects, `r` re-arms them for another take. The first keypress plays the title thud.
Two cut-ins away from the deck: the terminal and the labeller.

Numbers are the README's as of 27 Aug, 20:00, with the rebound stage in (outcome 82%) and the
stress rows rerun on it. If they move again, slides 5 and 6 and the lines marked ★ move with them.

## 1 · Title (0:00–0:30)

Thud on entry.

- Dodgeball. The 2014 world final, USA against Canada, one fixed camera at the end of the court.
- Six identical balls, twelve players, a throw every few seconds. The ball is twenty pixels across.
- The job: turn three and a half minutes of that into a list of every throw attempt. Who threw, did the ball leave their hand, where did it go, did it get anyone. Plus one number a coach would use.
- One movie line, then move on.

## 2 · The event (0:30–1:25)

- A throw attempt starts as a motion, a player winding up. What it becomes is up to the ball.
- Ball never leaves the hand: a fake. Leaves but stays on their side: a pass. Crosses the line: a throw, and a throw has an outcome. Hit, catch, block or miss.
- That's the rulebook's view and it's why this is hard. A fake is the same arm as a throw. You can't tell them apart from the body. You have to find the ball.
- The metric is throw efficiency: eliminations divided by throws, per team. Dodgeball's shooting percentage. Fakes and passes are outside the denominator, so every one misread as a throw drags it down.
- Ground truth: one complete set labelled by hand, sixty events, with a tool I built for it. Every ambiguous one is flagged and has a note.

## 3 · Pipeline (1:25–2:35)

- Top to bottom, the figure from the design doc. Pose on every frame finds the players and their arms. The court fit turns pixels into metres. The whistle on the audio finds the start of the set.
- The roster stitches broken tracks back into people by jersey number and side. It also decides who's a player, because the referee's stripes read like a jersey.
- Then the cascade, in red. Each box is a separate decision with its own score.
  - Wind-up: wrist speed against the torso, arm past the shoulder. Finds the motion.
  - Release gate: is there ball-coloured stuff at the wrist, and do we then see it leave? This is the fake-or-throw decision, and it's the ball's, not the body's.
  - Destination: follow the ball until it reaches someone, or check which way it's going. Pass or throw.
  - Rebound: follow the ball through the player it reached. A ball that comes back off him hit him; a ball that carries on didn't.
  - Outcome: you can't see the hit at this resolution, but you can see someone leaving the court. So we count bodies, and when the count drops a throw gets the credit. Which throw: the one whose ball bounced. A ball that bounced and put nobody out was blocked.

## Demo cut-in (2:35–4:05)

Slide 4 is a marker. Switch to the screen.

- Terminal: `scripts/run.py data/footage/wdbf2014_final_h2_set2.mp4 --from set_end`. About a minute; speed it up in the edit. Point at the output as it goes: set end found, candidates, events, the evaluation table at the end.
- Labeller: open the clip, scrub to 0:42. Rings on the throwers, ball path drawn. Show one accept/reject keypress so it's clear how the labels were made.
- Roster panel in the labeller: who played, and the roster cards. Each player's worth in players out: a hit is one opponent gone, a catch is the thrower gone plus a teammate back, so two. Weights read off the rulebook, not fitted; 29 throws can't fit anything. This is where the slide-8 fix matters: the card is only right if the credit is.
- One event's evidence in the timeline JSON: how much ball was at the wrist before the peak, how far it travelled, the chain of ball sightings, who it reached, which count step resolved the outcome.
- Say it here: there's no confidence score in the timeline, on purpose. Every threshold is a named constant and the evidence behind every claim is in the file, so a sweep reads the file instead of re-running the footage. If someone wants a confidence number, it's a margin-to-threshold away.

## 5 · Results (4:05–4:55) ★

- Five questions, scored one at a time, at a quarter-second tolerance, against the sixty labelled events.
- Is there a throw attempt here at all, a wind-up, fakes included? Found 56 of the 60, 88% F1. Of those 56: did the ball leave the hand? 88%. Fake, pass or throw? 86%. And does a real throw come out the far end labelled throw, with all three steps compounded? 75%: seven real ones lost on the way, eight called throw where nothing was labelled.
- Who did it get? 82%, eighteen of twenty-two. Fifty-nine before the ball was followed through the player; that's slide 8.
- Efficiency: Canada 29% against a true 27%. USA 8% against 14%. And the Canada number is right for the wrong reasons. Five spurious throws and two invented hits cancel.

## 6 · Break it (4:55–5:35) ★

- Same clip, same labels, same scoring. Top table: degrade the footage and rerun everything. Bottom: switch the stages on one at a time.
- Each condition breaks a different stage. 480p takes the ball, eight pixels of colour, and the bounce goes with it: who-it-got drops from 82 to 47. Heavy compression takes pose; the blocks look like arms and it proposes twice as many throws. Half the frame rate takes the wind-up; a whip lasts under a hundred milliseconds.
- Bottom: pose alone calls every wind-up a throw, 43. Only count it if the ball left the hand: 69. Only if it crossed the line: 75. The ball gate buys 33 points of precision and costs 18 of recall. Then follow the ball through the player, and the last question goes from 59 to 82 without touching the others.

## 7 · Uncertainty (5:35–6:05)

- When the number's wrong, it's one of three things, and I've kept them apart.
- The system got it wrong: about thirty points either way on one set, nearly all of it that last step, crediting the walk-off to the last thrower.
- The label was wrong: about four points. I labelled it myself, and flagged three calls I wasn't sure of.
- Or nobody can tell. At 25 frames a second and twenty pixels there's no frame where the ball touches anyone. Here's one: ball arrives, ball's past him, did it graze him? I couldn't say when I labelled it. Nobody left the court, so it's a miss. The game decided, not the picture.
- And fifteen throws a side means one set can't say much about a team either way. The metric wants a match.

## 8 · The last stage (6:05–6:45)

Whistle on entry.

- Forty-three seconds in. Player 10 throws and hits. Half a second later player 7 throws and misses. Two seconds after that, the target walks off. Who gets the credit? Until this afternoon, whoever threw last: 7.
- So we follow the ball through the player. This strip is 10's ball, frame by frame: into the player on the third frame, back off him at 77 degrees. 7's ball goes straight through the man beside him.
- New rule: someone walks off, the credit goes to whoever's ball came back off him. That fixed five of the nine wrong outcomes: this pair, two blocks the count could never see, and a hit on a player already walking off.
- How: a segmenter, SAM 2, is shown the ball on one frame and finds it again after it vanishes behind the body. The colour tracker couldn't, because it predicts where the ball is going, and a hit breaks that by definition.
- The table on the right, the last question five ways. Whoever threw last: 59. Reading the colour tracker past the player, three ways: no separation at all. SAM 2 as a tie-break only where the tracker had already reached him: 68. SAM 2 on one big crop, calling contact the first box the ball enters: 55, worse than the count, because in 2D the ball crosses bystanders. SAM 2 on a moving crop, calling contact the box the ball turns in: 82. The segmenter isn't the win on its own; the definition of contact is.

## 9 · One failure (6:45–7:20)

- 1:47. Far player 2 throws, 44 catches it. A second later 18 throws and hits 2, who's already out and walking off, so that moves nobody. A second after that far 13 throws, 18 catches it. Catch, hit, catch on one player in two seconds. A catch puts the thrower out and brings one of your own back on.
- Two USA players walk off. Two Canada players should walk on. The roster registered one. A walk-off with nobody coming back is a hit by the count's rules, so the first catch is scored a miss and the hit lands on a later throw.
- The ball can't help: a caught ball just stops in the hands, its flight barely bends, same as a ball that sails past. This one is identity's. Tracks fragment when players cross the sideline, and the second returning player was never stitched back to a number.

## 10 · Next move (7:20–7:45)

Thud on entry.

- Label a second set and score the bounce blind. The rebound stage was built and its one threshold set on the set it's scored on, from six visible hits. About an hour and a half with the tool doubles the throws, halves the error band, and says whether the threshold holds. The set's last hit is a 34-degree graze that reads as a miss; the second set says whether grazes are the exception.
- Two patches waiting on what it shows: reseed a track that dies behind a body from the colour mask at the feet, and bridge the frames where the tracker loses a fast far-side ball before it arrives.
- Code, labels, labelling guide, design doc and this deck are in the repo.

## Recording notes

- Record at 1600×1000 or 1920×1200 with the browser full-screen. The nav dots are fine on camera.
- Take the demo cut-in separately and drop it in at slide 4.
- The poster on slide 1 is the film's and the hit sound is from YouTube (youtube.com/watch?v=ac_aVzP8cSI). Both fine in the video; both come out of the deck before it is committed to a public repo. The whistle is the clip's own audio and stays.
