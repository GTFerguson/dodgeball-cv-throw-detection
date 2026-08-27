---
title: Player Impact Metrics
created: 2026-08-27
updated: 2026-08-27
tags: [reference, metrics, dodgeball, analytics]
---

# Player Impact Metrics

How a single number for "how well did this player play" is built in sports that
have solved it, what dodgeball specifically already does, and which of it this
project can support from 29 labelled throws. Written before the roster cards
were built so the weights on those cards can be checked against something.

The whole evidence base here is **Tier 5** — governing-body rulebooks,
practitioner blogs and industry statistics. There is no academic literature on
dodgeball player valuation. Nothing below should be read as an empirical claim
about what wins matches; it is a record of how the established metrics are
*constructed*, which is what the design needed.

## The established shape: weight each event, then sum

Every mature version of this metric is a linear sum of weighted events. The
design question is never the shape, it is always where the weights come from.

**Baseball — linear weights / wOBA.** Each event (single, double, walk, out) is
assigned a run value taken from run-expectancy tables: the average change in
runs scored following that event across a large sample. The weights are measured,
not chosen (Tier 5: Tango, Lichtman & Dolphin, *The Book*, 2006).

**Ice hockey and basketball — plus/minus.** The player is credited with the
change in score differential while they are on the ice or the floor. No weights
at all: the metric *is* the differential. Adjusted Plus Minus regresses out
teammate and opponent quality to recover an individual signal (Tier 5:
[Wikipedia, plus–minus](https://en.wikipedia.org/wiki/Plus%E2%80%93minus_(sports))).

**Counter-Strike — HLTV Rating 2.0.** The closest analogue to what a dodgeball
card wants, because it explicitly fuses a kill/death ledger with efficiency
terms. Reverse-engineered as:

```
0.0073·KAST + 0.3591·KPR − 0.5329·DPR + 0.2372·Impact + 0.0032·ADR + 0.1587
```

HLTV describe the balance as roughly 60–40 between *output* (kills, damage,
impact) and *the price paid for that output* (survival, KAST) — a useful framing
for splitting a rating into offence and defence. The coefficients were fitted by
linear regression of each component against round win (Tier 5:
[HLTV, Introducing Rating 2.0](https://www.hltv.org/news/20695/introducing-rating-20);
[flashed.gg, Reverse Engineering the HLTV 2.0 Rating](https://flashed.gg/posts/reverse-engineering-hltv-rating/)).

**The lesson that matters.** The metrics that survive scrutiny derive their
weights — wOBA from run expectancy, HLTV from regression against round win.
The hand-weighted composites (Hollinger's PER, Game Score) are the ones
persistently criticised, and for a structural reason rather than a taste one:
when coefficients are chosen, whoever chooses them chooses the ranking.

## What dodgeball already has

Thinner than the above, but it exists and it converges on the same two rates.

**Raw and compound stats.** *Hit %* = opponents eliminated ÷ throws. *Defence %*
= 1 − (times eliminated ÷ times thrown at). The headline compound stat is
*points per minute* — total points ÷ playing time — which is a rate rather than
a count, and so is robust to a player simply being on court longer (Tier 5:
[Sarovic, Dodgeball Statistics: Basic stats and measurements](https://www.darkosarovic.com/blog/dodgeball-statistics-raw-compound-stats)).

Both rates are directly computable from this project's label schema. Defence %
is the notable one: it credits *not being eliminated*, which is the term a
pure elimination ledger misses.

**Win Probability Added.** A dodgeball WPA modelled on sabermetrics, crediting
each hit, catch and revival with the change in the team's win probability it
caused (Tier 5:
[Hu, Predicting Dodgeball Wins and Player Impact](https://medium.com/@arthurwang0815/predicting-dodgeball-wins-and-player-impact-a-data-driven-dive-into-win-probability-e8f7f8c6e61f)).
This is the correct long-run target and it is **not** available here: a win
probability model has to be fitted to many sets, and this project has one.

## Why this project derives weights from the rulebook

Fitting weights by regression needs a sample. The labelled clip contains 29
throws and 9 eliminations across twelve-plus players. Nothing can be regressed
against anything at that size, and hand-picking coefficients would put the
ranking in the hands of whoever picked them.

The rulebook supplies the weights instead, because dodgeball's win condition is
itself a count of eliminations:

> **10.2.1** A set is won, when (1) a team has eliminated all players of the
> opposing team, or (2) a team has more live players than the opposing team
> after the designated set time runs out when using the Cloth Playing Format.

So the natural unit is **players eliminated, net** — the change an event makes
to the on-court player differential. Every labelled outcome has an exact effect
on that differential, and there is nothing left to tune:

| Outcome | Thrower | Target | Rule |
|---|---|---|---|
| hit | +1 | −1 | 19.1 — the ball touching a dead object puts the target out |
| catch | −2 | +2 | 23.1 — thrower out; plus the teammate the catch returns |
| block | 0 | 0 | 21.1/21.2 — ball stays live, nobody out |
| miss | 0 | 0 | nobody out |
| unresolved | 0 | 0 | not observed |
| pass, fake | 0 | 0 | no live ball crossed |

See [[wdbf-rules]] for the quoted text of each rule.

### The catch weight is +2, and its second point is observed rather than quoted

Rule 23.1 puts the thrower out, which is one point. The second point is the
teammate a catch returns to the court, which is standard in WDBF play and is
**observed directly in the labelled clip** — returns on a catch are visible
several times in the 2014 final's second half — but is not quoted in
[[wdbf-rules]], whose catch section covers only 23.1 and 23.6.

This is the single most load-bearing number in the metric: at +2 a catch is the
most valuable act in the sport and worth double a hit, at +1 it merely equals
one. It is pinned to a named constant in `tools/labeler/src/lib/tally.ts` rather
than written inline, so settling it against the rulebook text is a one-line
change. **@todo quote the return-to-play rule in [[wdbf-rules]] and cite it here.**

## Why efficiency is not folded into the impact number

The temptation is to finish with something like `0.7·net + 0.3·accuracy`. That
step is what turns a quantity into an index: net eliminations is measured in
players and means something in the world, and any weighted blend of it with a
unitless rate is measured in nothing.

Two constructions keep the meaning and are used instead:

- **Impact and efficiency shown side by side**, which is what every scoreboard
  in the prior art above actually does — HLTV shows K/D *and* ADR *and* KAST as
  separate columns, and only fuses them into Rating because it has the
  regression to justify the coefficients.
- **Impact per involvement** — net ÷ (throws + times thrown at). Still measured
  in players eliminated, now per opportunity, so a player who is +2 from three
  involvements is separated from one who is +2 from twelve. This is the same
  move as Sarovic's points per minute.

## Dodging, and why the ledger needs it

A player who is thrown at and evades it causes no elimination, so the impact
ledger scores them zero — yet not being eliminated is most of what a good
dodgeball player does, and a side wins by having players left. This is the
metric's largest blind spot and it is the same one CS:GO's KAST and Sarovic's
defence % were both introduced to close.

It is fixable here because a dodge is rule-defined rather than a judgement:

> **16.1** A throw must be a valid attempt to hit an opposing player out. A
> valid attempt is a throw that lands or passes within 1 meter of a player or a
> player's position at the moment the ball was released.

A `miss` carrying a target box is therefore exactly "a valid attempt that
reached nobody" — the target was thrown at, within a metre, and is still in.
The label schema already permits a target on a miss and 2 of the 15 misses in
the labelled set carry one, so the stat is readable today and completes as the
remaining misses get a target.

A dodge is worth **0** in the impact ledger, correctly: nobody went out. It
enters the metric through defence % instead, as the survival term —

```
defence % = (dodges + catches + blocks) ÷ (dodges + catches + blocks + hits taken)
```

— which is Sarovic's defence % with the survival modes named. Keeping it out of
the elimination sum and in the rate is what lets both numbers keep their unit.

## Sample size, and what may honestly be claimed

29 throws, 9 eliminations, twelve-plus players. Most players' entire record is
one or two events.

Consequences the presentation has to respect, and the reason the roster cards
show counts before rates:

- A ratio over n=1 is noise with a decimal point. Rates are suppressed below a
  minimum denominator rather than printed and caveated.
- "MVP" over 9 eliminations is a description of one set, not a judgement about a
  player. The wording on any surface that ranks players should say so.
- The metric is unvalidated. There is no held-out set, no second labeller, and
  no win-probability model to check it against. It is a defensible construction,
  not a measured one.

## References

- Sarovic D. *Dodgeball Statistics: Basic stats and measurements.*
  https://www.darkosarovic.com/blog/dodgeball-statistics-raw-compound-stats
- Hu A. *Predicting Dodgeball Wins and Player Impact: A Data-Driven Dive into
  Win Probability.*
  https://medium.com/@arthurwang0815/predicting-dodgeball-wins-and-player-impact-a-data-driven-dive-into-win-probability-e8f7f8c6e61f
- HLTV.org (2017). *Introducing Rating 2.0.* https://www.hltv.org/news/20695/introducing-rating-20
- flashed.gg. *Reverse Engineering the HLTV 2.0 Rating.*
  https://flashed.gg/posts/reverse-engineering-hltv-rating/
- Tango T, Lichtman M, Dolphin A (2006). *The Book: Playing the Percentages in
  Baseball.* Potomac Books. (Linear weights / wOBA.)
- World Dodgeball Federation (2024). *WDBF Dodgeball Rules 2024.* Quoted in
  [[wdbf-rules]].
