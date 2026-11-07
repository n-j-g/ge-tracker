"""Turn the study results into the small CSV files the findings page reads.

    python3 -m research.export_findings     # after margin_study and xp_price

Writes to data/history/results/findings/.
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

from research.chains import CHAINS
from research.history import SUBSET
from research.margin_study import EVENT_HORIZONS, OUT

FIND = OUT / "findings"
DAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()


def who_leads(pt: dict) -> str:
    """Which side's price moves first (daily Granger tests + 7-day catch-up)."""
    a, b = pt["input_leads_output"], pt["output_leads_input"]
    qa = a["granger_p"] < 0.01 and a["cum_7d"] >= 0.2
    qb = b["granger_p"] < 0.01 and b["cum_7d"] >= 0.2
    if qa and qb and abs(a["cum_7d"] - b["cum_7d"]) < 0.2:
        return "Both ways"
    if qb and b["cum_7d"] > a["cum_7d"]:
        return "Product first"
    if qa and a["cum_7d"] > b["cum_7d"]:
        return "Materials first"
    return "Loosely linked"


def run() -> None:
    FIND.mkdir(parents=True, exist_ok=True)
    m = json.loads((OUT / "margin_study.json").read_text())
    x = json.loads((OUT / "xp_price.json").read_text())

    # --- study scope
    con = sqlite3.connect(f"file:{SUBSET}?mode=ro", uri=True)
    n_hours, lo, hi = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM fetched WHERE n_items > 0").fetchone()
    n_items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    pd.DataFrame([{
        "hours": n_hours, "items": n_items,
        "chains": sum(c.margin for c in CHAINS), "methods": sum(c.xp_method for c in CHAINS),
        "first_hour": pd.Timestamp(lo, unit="s").strftime("%Y-%m-%d"),
        "last_hour": pd.Timestamp(hi, unit="s").strftime("%Y-%m-%d"),
    }]).to_csv(FIND / "study.csv", index=False)

    # --- one row per margin chain
    rows, decay = [], []
    for name, r in m.items():
        profitable = r["share_hours_profitable"] > 0.5
        losing = r["spells"].get("unprofitable", {})
        rows.append({
            "chain": name, "skill": r["skill"],
            "median_margin_gp": round(r["median_margin_gp"]),
            "hours_profitable": round(r["share_hours_profitable"], 4),
            "profitable": "yes" if profitable else "no",
            "typical_losing_spell_h": losing.get("median_h") if profitable else None,
            "longest_losing_spell_h": losing.get("longest_h") if profitable else None,
            "half_life_h": None if r["half_life_wide_h"] is None else round(r["half_life_wide_h"]),
            "left_after_24h": round(r["wide_events"]["left_after_24h"], 3),
            "left_after_72h": round(r["wide_events"]["left_after_72h"], 3),
            "returns_to_level": "yes" if r["stability"]["returns_to_level"] else "no",
            "margin_2024_gp": round(r["net_margin_2024_vs_2026"][0]),
            "margin_2026_gp": round(r["net_margin_2024_vs_2026"][1]),
            "moves_first": who_leads(r["pass_through"]),
            "monthly_corr": round(r["pass_through"]["monthly"]["corr"], 2),
        })
        decay.append({"chain": name, "hours": 0, "left": 1.0})
        for h in EVENT_HORIZONS:
            decay.append({"chain": name, "hours": h, "left": round(r["wide_events"][f"left_after_{h}h"], 3)})
    pd.DataFrame(rows).to_csv(FIND / "chains.csv", index=False)
    pd.DataFrame(decay).to_csv(FIND / "decay.csv", index=False)

    # --- XP price per skill
    skills = []
    for skill, s in x["skills"].items():
        usual = max(s["cheapest_method_share"], key=s["cheapest_method_share"].get)
        skills.append({
            "skill": skill, "usual_method": usual,
            "median_gp_per_xp": round(s["median"], 2), "p10": round(s["p10"], 2), "p90": round(s["p90"], 2),
            "now_gp_per_xp": round(s["last_7d"], 2), "now_percentile": round(s["last_7d_percentile"], 3),
            "cheapest_month": s["cheapest_month"][0], "dearest_month": s["dearest_month"][0],
            "cost_10m_cheapest": round(s["goal_cost_10M"]["cheapest_month"], -5),
            "cost_10m_median": round(s["goal_cost_10M"]["median_month"], -5),
            "cost_10m_dearest": round(s["goal_cost_10M"]["dearest_month"], -5),
        })
    pd.DataFrame(skills).to_csv(FIND / "xp_skills.csv", index=False)

    daily = pd.read_csv(OUT / "xp_price_daily.csv", index_col=0, parse_dates=True)
    weekly = daily[[c for c in daily.columns if c.startswith("[")]].resample("W-MON", label="left").mean()
    weekly.columns = [c.strip("[]") for c in weekly.columns]
    long = weekly.reset_index(names="week").melt(id_vars="week", var_name="skill", value_name="gp_per_xp").dropna()
    long["week"] = long.week.dt.strftime("%Y-%m-%d")
    long["gp_per_xp"] = long.gp_per_xp.round(2)
    long.to_csv(FIND / "xp_weekly.csv", index=False)

    # --- XP methods: timing and patience
    meth = []
    for name, s in x["methods"].items():
        rh = s["input_rhythm"]
        meth.append({
            "method": name, "skill": s["skill"],
            "median_gp_per_xp": round(s["median"], 2), "now_gp_per_xp": round(s["last_7d"], 2),
            "weekday_swing": round(rh["weekday_swing_pct"], 4),
            "cheapest_day": DAYS[rh["cheapest_weekday"]], "dearest_day": DAYS[rh["dearest_weekday"]],
            "hour_swing": round(rh["hour_swing_pct"], 4),
            "patient_saving": round(s["patient_saving_share_of_spend"], 4),
        })
    pd.DataFrame(meth).to_csv(FIND / "methods.csv", index=False)
    for f in sorted(FIND.glob("*.csv")):
        print(f"{f.name:16} {sum(1 for _ in f.open()) - 1:>5} rows  {f.stat().st_size / 1e3:6.1f} KB")


if __name__ == "__main__":
    run()
