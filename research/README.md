# Research: GE price history

Studies of hourly Grand Exchange prices since March 2021, using the recipe
structure (inputs → outputs) to look at processing margins and the market
price of XP. Results: [docs/price-history-findings.md](../docs/price-history-findings.md).

Unlike the main tool, this folder uses pandas, numpy and statsmodels
(`pip install -r research/requirements.txt`).

## Pipeline

1. `backfill_history.py`: download every hour of history for every item into
   `data/history/prices_1h.sqlite` (~3.75 GB; standard library only, runs anywhere).
2. `extract_subset.py`: copy the rows for the study's items into
   `data/history/study_subset.sqlite` (~94 MB; standard library only).
3. `margin_study.py`, `xp_price.py`: the analyses; results in `data/history/results/`.
4. `export_findings.py`: small CSVs for the findings page (`results/findings/`).
5. `findings_page.html`: the findings page (a dashboard artifact on claude.ai that
   reads those CSVs).

```
python3 research/backfill_history.py
python3 research/extract_subset.py
python3 -m research.margin_study
python3 -m research.xp_price
python3 -m research.export_findings
```

## Files

- `chains.py`: the chains and training methods studied (quantities and XP
  checked against the Wiki recipe data; Prayer/Firemaking/Construction values noted).
- `history.py`: loading, pricing conventions (mid vs executable), GE tax by date.
- `margin_study.py`: profitability, stability (ADF), wide-margin event study and
  half-life, daily rhythm, before/after tax changes, which price moves first.
- `xp_price.py`: gp per XP by method and skill, timing patterns, patient-order savings.

## Conventions and caveats

- Prices are hourly averages; a side with no trades is filled forward up to 3 hours.
- GE tax: none before 2021-12-09, 1% until 2025-05-29, 2% after (per item, floored, 5m cap).
- Event study and "now vs history" use only past data at each point (no look-ahead).
- Burn rates, travel and price impact of large orders are not modelled.
