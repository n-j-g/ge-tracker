# PRD: Account Advisor ("Mortimer for mains")

Status: draft · Owner: n-j-g · Last updated: 2026-11-06

## 1. Summary

Turn ge-tracker from a GE production calculator into a personal advisor for
main accounts: tell me the 5–10 best things to do **right now**, for **my
account**, at **the intensity I want to play at**, weighing both GP and XP.
Later, use the same numbers to recommend how to train each skill, given what
my time is worth in gold.

## 2. Problem

Mains deciding what to do with a play session juggle information spread
across many places:

- The Wiki money making guides rank methods, but aren't personal and mostly
  treat GP and XP separately.
- Skill calculators and training guides give XP rates but ignore what the
  method costs or earns at today's prices.
- Hiscores and trackers know your levels but not which methods those unlock.
- Price sites know prices but not which skilling methods they make profitable.

Nothing combines **your account + your preferred intensity + live prices +
GP and XP together** into a short list.

## 3. Users and thesis

- **Primary: the casual-to-engaged main.** Plays in sessions, has preferences
  ("I want to bankstand tonight", "something AFK while I watch TV"), cares
  about both gold and progress, and isn't optimizing every tick.
- **Not the target:** max-efficiency players chasing EHP. Their needs (tick
  manipulation, exact efficiency tables) are served elsewhere; the model
  should not assume sweaty play.
- **Thesis:** a ranked, personal shortlist at a chosen intensity is more useful
  than a complete, generic table. "Mortimer for mains."

## 4. Goals and non-goals

Goals:

1. Shortlist: 5–10 recommendations at a chosen intensity, ranked by a clear
   combination of GP and XP, filtered to what the account can actually do.
2. Every number explainable: show where the rate, price and requirements came
   from (Wiki, GE, hand-set), and what limits it (speed, buy limit, volume).
3. Live: market numbers refresh hourly with no action from the user.
4. Training advisor: for any skill, rank training methods by effective XP/hr
   once the gold they cost or earn is converted to time.

Non-goals (for now):

- Modelling combat kill rates, gear or DPS (use stated rates from Wiki guides).
- Ironman play (no GE); multi-account management; social features.
- Automation of any in-game action. Information only.
- Price prediction (separate research track, "Idea 1"; may feed in later).

## 5. What exists today (baseline)

Already built and live at https://n-j-g.github.io/ge-tracker/:

- ~5,800 production recipes from the Wiki recipe data, priced hourly from GE
  1-hour averages (thin sides filled from latest trades), with GE tax.
- Feasible GP/hr and XP/hr for the next hour: actions limited by production
  speed (Wiki ticks + banking model, hand-set overrides), one full buy limit,
  or a share of trading volume. GP/4h for longer sessions.
- XP pace: this hour's XP versus the user's normal training method per skill.
- Quality filters: minimum trading volume, chance by-products excluded,
  burnt-food rows dropped.
- Sortable, themed web page; rebuilt hourly by GitHub Actions.

## 6. Scope by phase

### Phase 1: Personalize what we have

User stories:

- As a player, I enter my RSN and only see methods I have the levels for.
- As a player, I pick an intensity and see the top 5–10 methods for it.
- As a player, my choices (RSN, intensity, filters) are remembered.

Requirements:

- **Levels:** look up the account's skill levels (public hiscores, likely via
  Wise Old Man's public API so the page can do it in the browser). Hide or
  grey out methods whose level requirements aren't met. The Wiki recipe data
  already includes a level per skill per recipe; it is currently ignored and
  needs to be carried through the converter.
- **Intensity tag per method.** Proposed levels (to confirm with the owner):
  - *AFK*: long stretches without input
  - *Bankstanding*: repetitive, low attention, at a bank
  - *Moderate*: regular attention, some movement
  - *High*: constant attention or tick-precise
  Production recipes default to Bankstanding; exceptions are hand-tagged
  (e.g. Blast Furnace = Moderate).
- **Shortlist view:** a "Top picks" panel above the full table: 5–10 rows for
  the chosen intensity, ranked by the scoring rule in §7.
- **Membership:** filter F2P/members using the Wiki's members flag.

Acceptance: entering a real RSN changes the list correctly for a low-level and
a high-level account; every pick shows why it's listed and what limits it.

### Phase 2: Beyond production

- Import the Wiki money making guides to cover gathering, collecting, bossing
  and other non-recipe methods, with their stated hourly inputs/outputs,
  intensity and requirements, re-priced hourly from the GE.
- First task: check whether these guides are stored as structured data (as
  recipes were). If not, scrape the guide template carefully or hand-curate
  a starter set of popular methods.
- Quests/diaries: start with user toggles for key unlocks; later consider the
  WikiSync RuneLite plugin data.

### Phase 3: Training advisor

For a chosen skill (and target level), rank training methods by effective
XP/hr after converting their gold cost into time (§7). Show the fastest,
cheapest and best-value options side by side.

## 7. Scoring model

Notation for a method m: `G_m` = GP/hr, `X_m` = XP/hr (in the relevant skill),
`g*` = the user's reference gold rate (their best money-maker's GP/hr at their
preferred intensity, computed live or set by hand).

**Shortlist ranking (Phase 1).** The user chooses what they value:

- *Money first:* rank by `G_m`, with XP shown.
- *XP first:* rank by XP pace, with GP shown.
- *Balanced:* rank by `G_m + λ · Σ_s w_s · X_{m,s}`, where `λ` is how many GP an
  XP is worth to the user and `w_s` lets them weight the skills they care about.
  Default `λ` from the training advisor's shadow price (below), editable.

**Training advisor (Phase 3).** A method that costs `C_m` GP per hour of
training also costs `C_m / g*` hours of money-making to fund. So:

    effective XP/hr = X_m / (1 + C_m / g*)

Profitable methods have negative `C_m` and score above their raw XP/hr. XP
gained in other skills (including combat) can be credited at the user's value
for that XP. The market's own price of XP per skill (from money-losing
training methods, see Idea 1) can be shown next to the user's.

## 8. Data sources

| Data | Source | Notes |
|---|---|---|
| Prices, volumes, buy limits | Wiki real-time price API | in use |
| Production recipes, ticks, levels | Wiki recipe bucket | in use (levels to add) |
| Money making methods | Wiki money making guides | Phase 2; structure TBD |
| Account levels | Hiscores via Wise Old Man API | Phase 1; confirm browser access |
| Quests/diaries | User toggles; WikiSync later | Phase 2 |
| Hand-set rates, fees, tags | `recipes.toml` | in use |

All Wiki access must use a descriptive User-Agent and polite request rates.

## 9. Architecture

- Keep the split that works today: **market calculations run hourly** on
  GitHub Actions and publish a static page with the data embedded.
- **Personalization runs in the browser:** fetch levels for the entered RSN,
  filter and score client-side, remember settings locally. No server needed
  while this holds.
- Move to a small backend only when needed (e.g. if hiscore lookups can't be
  done from the browser, or for saved profiles across devices).
- Keep calculation code pure and testable, separate from fetching and display.

## 10. Risks

- **Data quality.** Wiki rows include chance outcomes, wrong tick counts and
  thinly traded items (all hit already). Mitigation: filters, overrides,
  regular spot-checks against the money making guides.
- **Maintenance.** Game updates change methods and rates. Mitigation: prefer
  community-maintained Wiki data over hand-set numbers.
- **Trust.** One silly number undermines the list. Mitigation: always show the
  limiting factor and data source; conservative pricing by default.
- **Scope creep into combat.** Mitigation: stated rates only until Phase 2 is
  solid.

## 11. Success measures

- The owner uses the shortlist to choose what to do in most sessions.
- Spot-checks: top picks agree with Wiki money making guides within ~10% where
  both exist.
- No recommendation the owner can't actually do (level/requirement misses).

## 12. Open questions

1. Intensity levels: are AFK / Bankstanding / Moderate / High the right split?
2. Default ranking for the shortlist: money first, XP first or balanced?
3. Is Wise Old Man usable directly from the browser, or is a proxy needed?
4. Are the money making guides available as structured data?
5. How to value XP by default (`λ`): from `g*`, from market-implied XP prices,
   or simply user-set?
