---
title: WDBF Rules That Define the Event
created: 2026-08-26
updated: 2026-08-26
tags: [reference, rules, dodgeball]
---

# WDBF Rules That Define the Event

What the World Dodgeball Federation's rules say about the moments this project
labels and detects, quoted so the event definition in the plan and the
decisions in the pipeline can be checked against the sport rather than against
each other. The 2014 final was played under the WDBF; the 2024 rulebook is the
current text and the relevant rules are unchanged in substance from 2022.

Source: World Dodgeball Federation (2024). *WDBF Dodgeball Rules 2024*.
https://worlddodgeballfederation.com/wdbf-content/uploads/2024/03/WDBF-Dodgeball-Rules-2024.pdf
(Tier 5: governing-body rulebook — the authority on what the terms mean, not
evidence about how often anything happens.)

## A throw begins at release

> **15.2** A throw must leave a player's hand. The thrown ball becomes a live ball once the player is no longer in contact with the ball.

> **Live Ball** — A live ball is a ball that has been thrown and can get a player out.
> **Dead Ball** — A dead ball is a ball that can no longer get a player out.

> **15.5** A live ball becomes a dead ball once it touches another live ball, a surface or a dead object.

Consequence for the definition: nothing before release is a rule event. The
wind-up, and a fake — a wind-up that stops short — are coaching terms; the
rulebook contains no "fake", "feint", "pump" or "decoy". What counts as a fake
is the project's to define ([[throw-attempt-detection]]), and the model's
release gate ([[release-gate]]) is asking the rule's own question: did the
ball leave the hand.

## A pass is a throw that did not cross

> **16.1** A throw must be a valid attempt to hit an opposing player out. A valid attempt is a throw that lands or passes within 1 meter of a player or a player's position at the moment the ball was released.

> **16.2** Passing throws and plays are not deemed invalid throws, if the ball does not cross into the opponent team's fair territory or past the center line when out of bounds.

> **16.3** If a player fails to make a valid throw (1) they are deemed out, when using the Cloth Playing Format; (2) they may receive a verbal warning or are deemed out at the discretion of the match official, when using the Foam Playing Format.

Consequence: the rules classify by where the ball went, not by what the
thrower meant, which is the plan's "classified by destination" rule. A pass
that crosses is a throw (and a live ball); a throw that lands on its own side
is a pass. Rule 16.1's one-metre test also gives the outcome resolver a
rule-backed notion of a throw *at* someone, if it is ever needed.

## Outcomes

> **19.1** A live player shall be deemed out, when a live ball that hits them on any part of their body, including hair or on any part of their clothing and uniform, touches a dead object.

> **21.1** A player can use one or more balls to block a live ball from hitting them.
> **21.2** A live ball remains a live ball after it has been blocked.

> **23.1** A live ball may be caught by an opposing live player, rendering the throwing player out immediately after the catch is complete.
> **23.6** A live ball becomes a dead ball once it is caught.

Consequence: a hit is not an out until the ball touches a dead object (the
floor, usually), so the `end` frame of a hit is that touch, not the contact
with the player — and a blocked ball stays live, which is why block is not
miss in the outcome set.

## A set ends on the last elimination

> **10.2.1** A set is won, when (1) a team has eliminated all players of the opposing team, or (2) a team has more live players than the opposing team after the designated set time runs out when using the Cloth Playing Format.

Consequence: set end is the outcome of the last hit or catch, which is what
the harness derives from the labels ([[evaluation]]). The pipeline reads the
same moment from the floor — one side down to a single player, then more
bodies on the court than (1) allows — and traces the hit back to it
([[set-end]]); (2), the timed cloth format, has no such shape and is out of
scope.

## Advantage and the throw clock

> **17.3.1** The team with advantage has 10 seconds to make an attempt. This time resets if a ball is thrown.
> **17.3.2** If a ball has not been thrown within 5 seconds of having advantage, the match officials will start an audible countdown.

Consequence: the "countdown attack" the plan names as a source of simultaneous
throws is a rule mechanism, not just a tactic — the audible countdown is a
signal in the audio track if it is ever wanted.
