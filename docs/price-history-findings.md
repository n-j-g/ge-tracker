# Price history findings (first pass)

Data: 49,548 hourly snapshots (2021-03-08 to 2026-11-07), 67 items, 22 processing
chains, 21 training methods. Code and method: [research/](../research/README.md).
Interactive version: the "GE price history findings" dashboard on claude.ai.

## Processing margins

- **They're a wage, not a trade.** 16 of 22 chains make money trading instantly;
  those were profitable in a median 99.2% of hours. Losing spells typically last
  1–2 hours.
- **Unusually wide margins fade within about a day.** After a margin enters its
  top 10% versus the past 30 days, half of the extra is gone in a median ~22 hours,
  most of it within a week. Slow exceptions (wide margins persist for days):
  Blast Furnace bars, cannonballs, sharks, karambwans, Saradomin brews, black d'hide.
- **Most margins return to a level** (ADF p < 0.05 for 16 of 22). Blast Furnace
  runite, adamantite and steel bars, ranarr unfinished potions, Saradomin brews and
  black d'hide wander.
- **Margins are wider now than in 2024** for 15 of 16 profitable chains, despite the
  tax going to 2% in May 2025. BF runite: 531 → 1,110 gp/bar, because runite ore fell
  ~8% (11,133 → 10,224) while bars held at ~12,270.
- **The product usually moves first.** For potions, cooked fish, bows and darts,
  raw-material prices follow the product's price within days (e.g. raw manta rays
  catch up ~93% of a cooked-manta move within a week). Gem → bolt tips is the
  reverse (the gem moves first). BF ore and bar prices move in opposite directions
  day to day (corr ≈ −0.25), likely processors buying ore and selling bars at once.
- Short-window before/after estimates of the tax changes were too noisy to read;
  the year-over-year comparison above is more robust but not causal.

## Price of XP (cheapest standard method; gp lost per XP)

| Skill | Typical | Now (Nov 2026) | Past days cheaper than now | 10M XP: cheapest / typical / dearest month |
|---|---|---|---|---|
| Prayer (dragon bones, gilded) | 10.2 | 14.1 | 86% | 56m / 102m / 166m |
| Construction (oak larders) | 7.5 | 8.0 | 68% | 62m / 75m / 101m |
| Herblore (prayer potions) | 2.3 | −0.1 | 8% | −6m / 23m / 66m |
| Crafting (green d'hide / battlestaves) | 2.2 | 3.6 | 78% | −2m / 23m / 70m |
| Firemaking (yew / redwood logs) | 1.0 | 0.4 | 0% | 4m / 10m / 15m |
| Smithing (adamant platebodies) | 0.5 | −1.2 | 9% | −20m / 5m / 26m |
| Fletching (magic longbows) | −0.8 | −1.2 | 17% | −15m / −8m / −4m |
| Cooking (sharks) | −1.0 | −1.2 | 14% | −14m / −10m / −6m |

- **Timing is worth a lot:** the same 10M XP cost up to 3× more in the dearest month
  than the cheapest (Prayer), and swings of 50–70m for Herblore and Crafting.
- **Right now** Firemaking, Herblore and Smithing XP are near historic lows; Prayer
  and Crafting are expensive.
- Dragon bones roughly tripled from May 2021 (~1,370) to Sept 2024 (~4,200).
- **Buying tricks are small:** cheapest vs dearest weekday ≤ 1.5% (supplies usually
  cheapest at the weekend, dearest Wednesday–Thursday), hour of day ≤ 1.6%, trading at
  the mid price instead of instantly ≤ 2% of spend.

## Ideas this supports

- Advisor: flag when a method ranks high only because its margin is unusually wide
  (expect half of the extra gone by tomorrow).
- Advisor: per skill, show today's XP price against its history ("cheap now / dear now").
- Next studies: Magic (alching), Runecraft; stockpiling across buy-limit windows;
  price impact of large orders; a long-run inflation adjustment.

## Acting on wide margins (research/early_detection.py)

Simulation: the hourly average for hour t shows a margin entering its top 10% vs
the past 30 days; the player buys inputs instantly in hour t+1, processes, and
sells instantly later. Compared with the normal (trailing 30-day median) margin:

- **Hourly data is early enough.** Selling 4 hours later still keeps a median ~76%
  of the gap that was seen (range ~36–95%), and the trade beats the normal margin
  in 72–99% of episodes. Faster (5-minute) detection could add only the small
  remainder.
- **A wide-margin session pays a median ~29% more** than a normal session of the
  same method (mostly 19–53%; more where the normal margin is tiny). Each chain has about 8 such episodes a month.
- **Where the gap comes from decides the move.** Blast Furnace bars and black
  d'hide: the gap is cheap inputs, locked in the moment you buy, so there's no rush
  to sell. Bolt tips, manta rays, ranarr unf, rings of recoil: the gap is a pricier
  product, which fades over a day, so sell fast.
- For money-losing training methods, the same episodes make training 12–31% cheaper
  than usual (black d'hide, Saradomin brews, super restores, prayer potions, dragon darts).

## Suspected gold transfers (research/transfer_scan.py, transfer_episodes.py, trap_backtest.py)

Following [poignanttech's "Virtual Markets" part two](https://poignanttech.com/2024/03/01/virtual-markets-part-two-market-fundamentals-and-the-high-low-spread/):
an hour where an item traded at ≥ 20× its median price that month, with ≥ 10m gp above
normal value, excluding each item's first 30 days on the GE (launch prices).

- **About 3,500 episodes on 757 items since 2021**, 120–290b gp a year (falling: ~290b in
  2022, ~130b a year since 2024). The median episode moves ~115m gp; 87% last a single hour.
- **They favour worthless, low-dose potions and junk**: Defence potion(1)/(2), divine
  potions, barbarian mixes, Guthix rest(1), Relicym's balm, swamp weed, Blamish shells.
  The same items recur for years (87 items have 10+ episodes); ~80% of episodes are
  on an item used before, and that share hasn't changed in 2026.
- **Volume is down, and spread thinner.** Episodes per quarter fell from ~150–280
  (2021–23) to ~50–150 (2024–26), and Aug–Sep 2026 were the quietest months on record
  (12–13 episodes). October rebounded (55 episodes, ~46b, mostly poisoned javelins and
  bolts). In late 2026 only 3–4% of episodes hit last year's 8 busiest items (13–21%
  before), so they're spread over many familiar items rather than moving to new ones.
  The data can't separate less real-world trading (bot bans, harsher penalties for
  gold buyers from Sept 2025) from transfers moving to channels this filter misses.
- Evenings and nights UTC (peak 19:00–23:00), busiest on Saturdays.
- **Trap backtest (a ceiling, not a forecast):** each month list the 8 items with the most
  episodes in the past year at half their usual transfer price. If GE price priority
  means a resting cheaper ask fills first, those offers would have met ~14% of episodes
  and caught a median ~320m a month (2022–2026), ~180m a month since 2025, and nothing in
  Aug–Oct 2026. If transferrers abandon an item after one interception, it drops to ~78m
  a month on average (zero in most months).
- **Timing isn't predictable from 'tests'** (research/transfer_leadup.py, 1,201
  episodes since Feb 2024). Small high-price prints appear in the 48h before 26% of
  transfers (13% expected by chance), but only 1% of such prints are followed by a
  transfer within 48h. Ordinary trading and stocking-up volume before a transfer look
  normal. These items trade in about a third of all hours, so they aren't dead items.
- **But transfers cluster** (research/transfer_clustering.py). After a transfer on an item,
  another on the same item follows within a week 30% of the time; a month later
  the same one-week window has 10%, and six months later 5%. 58% of transfers fall on
  days with 3+ transfer items. A repeat usually reuses the price (median ratio 0.98; 85%
  at least half the last price).
- **Reactive trap:** after each transfer, list that item for 7 days at half the price
  just seen (8 slots, newest wins): catches ~20% of transfers, median ~560m a month over
  2022–26 and ~135m a month in 2026, with a catch in every month. Same caveats as above;
  being intercepted may itself make them drop the item.
- Untested assumptions: that the GE really fills the cheapest resting offer first for
  these trades, and that the transferrer doesn't check for other offers first. Gold
  traced to real-world trading can be removed by Jagex, possibly with the receiving account
  flagged.
