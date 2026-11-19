"""All estimates for the thesis version of 'The Shadow Price of an Inventory Slot'.

Inputs (made from the full history on the machine that holds it):
  data/history/food_daily.csv.gz    classic food, daily average traded price + volume
  data/history/trawl_daily.csv.gz   Sailing fish
  data/history/daily_prices.csv.gz  basket items (potions, for cross-resource pricing)
Output: data/history/results/thesis.json, printed as it goes.

    python3 -m research.slot_thesis
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
H = ROOT / "data" / "history"
OUT = H / "results" / "thesis.json"
WINDOW_DAYS = 56
RNG = np.random.default_rng(2026)

# heal per slot and characteristics (OSRS Wiki)
FOOD = pd.DataFrame([
    # name, heal per slot, bites, combo, overheal, prayer points, run %, sailing, members
    ("Monkfish", 16, 1, 0, 0, 0, 0, 0, 1), ("Shark", 20, 1, 0, 0, 0, 0, 0, 1),
    ("Sea turtle", 21, 1, 0, 0, 0, 0, 0, 1), ("Manta ray", 22, 1, 0, 0, 0, 0, 0, 1),
    ("Dark crab", 22, 1, 0, 0, 0, 0, 0, 1), ("Tuna potato", 22, 1, 0, 0, 0, 0, 0, 1),
    ("Anglerfish", 22, 1, 0, 1, 0, 0, 0, 1), ("Cooked karambwan", 18, 1, 1, 0, 0, 0, 0, 1),
    ("Pineapple pizza", 22, 2, 0, 0, 0, 0, 0, 1), ("Anchovy pizza", 18, 2, 0, 0, 0, 0, 0, 1),
    ("Curry", 19, 1, 0, 0, 0, 0, 0, 1), ("Potato with cheese", 16, 1, 0, 0, 0, 0, 0, 1),
    ("Giant krill", 17, 1, 0, 0, 0, 0, 1, 1), ("Haddock", 18, 1, 0, 1, 0, 0, 1, 1),
    ("Yellowfin", 19, 1, 0, 0, 0, 20, 1, 1), ("Halibut", 20, 1, 1, 0, 0, 0, 1, 1),
    ("Bluefin", 22, 1, 0, 0, 5, 0, 1, 1), ("Marlin", 24, 1, 0, 0, 0, 0, 1, 1),
    ("Trout", 7, 1, 0, 0, 0, 0, 0, 0), ("Salmon", 9, 1, 0, 0, 0, 0, 0, 0),
    ("Tuna", 10, 1, 0, 0, 0, 0, 0, 0), ("Lobster", 12, 1, 0, 0, 0, 0, 0, 0),
    ("Swordfish", 14, 1, 0, 0, 0, 0, 0, 0), ("Bass", 13, 1, 0, 0, 0, 0, 0, 1),
], columns=["food", "heal", "bites", "combo", "overheal", "prayer", "run", "sailing", "members"]).set_index("food")
CORE = ["Monkfish", "Shark", "Sea turtle", "Manta ray", "Dark crab", "Tuna potato"]
F2P = ["Tuna", "Lobster", "Swordfish"]
R: dict = {}


def load() -> pd.DataFrame:
    d = pd.concat([pd.read_csv(H / f, parse_dates=["date"]) for f in
                   ["food_daily.csv.gz", "trawl_daily.csv.gz", "daily_prices.csv.gz"]])
    d = d.drop_duplicates(["date", "item"])  # some foods are in more than one file
    d["gp"] = d.price * d.volume
    return d


def window_prices(d, days=WINDOW_DAYS, how="value"):
    w = d[d.date > d.date.max() - pd.Timedelta(days=days)]
    if how == "median":
        return w.groupby("item").price.median()
    g = w.groupby("item")[["gp", "volume"]].sum()
    return g.gp / g.volume


def ols_line(px, items, weights=None):
    X = sm.add_constant(FOOD.loc[items, "heal"].astype(float))
    y = px[items].astype(float)
    m = (sm.WLS(y, X, weights=weights) if weights is not None else sm.OLS(y, X)).fit()
    c, a = m.params["heal"], m.params["const"]
    lam = -a
    # delta method for lam/c
    V = m.cov_params().loc[["const", "heal"], ["const", "heal"]].to_numpy()
    g = np.array([-1 / c, a / c ** 2])  # d(-a/c)/da, d(-a/c)/dc
    se_ratio = float(np.sqrt(g @ V @ g))
    return m, c, lam, lam / c, se_ratio


def main():
    d = load()
    px = window_prices(d)
    vol = d[d.date > d.date.max() - pd.Timedelta(days=WINDOW_DAYS)].groupby("item").volume.sum() / WINDOW_DAYS

    # ---- summary statistics
    R["summary"] = [{"food": f, "heal": int(FOOD.loc[f, "heal"]), "price": round(float(px[f])), "vol_day": round(float(vol[f]))}
                    for f in FOOD.index if f in px]

    # ---- baseline
    m, c, lam, ratio, se_ratio = ols_line(px, CORE)
    tcrit = stats.t.ppf(0.975, m.df_resid)
    R["baseline"] = {"c": c, "c_se": m.bse["heal"], "lam": lam, "lam_se": m.bse["const"], "ratio": ratio,
                     "ratio_se": se_ratio, "ratio_ci": [ratio - tcrit * se_ratio, ratio + tcrit * se_ratio],
                     "r2": m.rsquared, "n": int(m.nobs), "df": int(m.df_resid),
                     "c_ci": list(m.conf_int().loc["heal"]), "lam_ci": list(-m.conf_int().loc["const"][::-1])}
    # food bootstrap
    heals = FOOD.loc[CORE, "heal"]
    bs = []
    while len(bs) < 4000:
        s = list(RNG.choice(CORE, len(CORE)))
        if heals[s].nunique() < 3:
            continue
        b = np.polyfit(heals[s].astype(float), px[s].astype(float), 1)
        bs.append(-b[1] / b[0])
    R["baseline"]["ratio_boot_ci"] = list(np.percentile(bs, [2.5, 97.5]))
    print("baseline", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in R["baseline"].items()})

    # ---- multi-characteristic regressions (classical SEs: several dummies are carried by one food,
    #      where robust SEs are undefined; those coefficients are flagged as single-food)
    def hedonic(items, cols):
        X = sm.add_constant(FOOD.loc[items, ["heal"] + cols].astype(float))
        X["bites"] = X["bites"] - 1 if "bites" in X else 0
        y = px[items].astype(float)
        mm = sm.OLS(y, X).fit()
        return mm

    specs = {
        "(1) core": (CORE, []),
        "(2) + other members food": (CORE + ["Anglerfish", "Cooked karambwan", "Pineapple pizza", "Anchovy pizza", "Curry",
                                            "Potato with cheese"], ["bites", "combo", "overheal"]),
        "(3) + mid-level Sailing fish and bluefin": (CORE + ["Anglerfish", "Cooked karambwan", "Pineapple pizza",
                                                             "Anchovy pizza", "Curry", "Potato with cheese", "Giant krill",
                                                             "Haddock", "Yellowfin", "Bluefin"],
                                                     ["bites", "combo", "overheal", "prayer", "run", "sailing"]),
    }
    R["hedonic"] = {}
    for name, (items, cols) in specs.items():
        mm = hedonic(items, cols)
        cc = mm.params["heal"]
        R["hedonic"][name] = {
            "n": int(mm.nobs), "r2": mm.rsquared,
            "coef": {k: [float(mm.params[k]), float(mm.bse[k])] for k in mm.params.index},
            "ratio": float(-mm.params["const"] / cc),
            "in_hp": {k: float(mm.params[k] / cc) for k in mm.params.index if k not in ("const", "heal")},
            "carried_by": {k: [f for f in items if FOOD.loc[f, k] != (1 if k == "bites" else 0)] for k in cols},
        }
        print(name, "n", int(mm.nobs), "R2", round(mm.rsquared, 3), "slot HP", round(-mm.params["const"] / cc, 2))
        print(pd.DataFrame({"coef": mm.params, "se": mm.bse, "p": mm.pvalues}).round(3).to_string()); print("carried by", R["hedonic"][name]["carried_by"])
    # top end: residuals of halibut and marlin from spec (3)
    items3, cols3 = specs["(3) + mid-level Sailing fish and bluefin"]
    m3 = hedonic(items3, cols3)
    top = []
    for f in ["Halibut", "Marlin"]:
        x = FOOD.loc[[f], ["heal"] + cols3].astype(float).copy()
        x["bites"] -= 1
        x.insert(0, "const", 1.0)
        pred = float((m3.params * x.iloc[0]).sum())
        top.append({"food": f, "price": float(px[f]), "pred": pred, "gap": float(px[f] / pred - 1)})
    R["hedonic_top"] = top
    print("top-end residuals", top)

    # ---- robustness
    rob = []

    def add(label, p, items=CORE, weights=None):
        mm, c_, l_, r_, se_ = ols_line(p, items, weights)
        rob.append({"spec": label, "c": c_, "lam": l_, "ratio": r_, "se": se_, "r2": mm.rsquared})
    add("Baseline: 8 weeks, value-weighted price, core six", px)
    for wk in [4, 13, 26, 52]:
        add(f"Window: {wk} weeks", window_prices(d, wk * 7))
    add("Price measure: median of daily prices", window_prices(d, how="median"))
    add("Weighted by volume traded (WLS)", px, CORE, vol[CORE].to_numpy())
    add("Drop the two thinnest foods (sea turtle, tuna potato)", px, ["Monkfish", "Shark", "Manta ray", "Dark crab"])
    add("Add curry and potato with cheese", px, CORE + ["Curry", "Potato with cheese"])
    add("22 HP foods only plus monkfish and shark (no sea turtle)", px, ["Monkfish", "Shark", "Manta ray", "Dark crab", "Tuna potato"])
    R["robustness"] = rob
    print(pd.DataFrame(rob).round(3).to_string())

    # ---- monthly stability
    d["mo"] = d.date.dt.to_period("M")
    g = d.groupby(["mo", "item"])[["gp", "volume"]].sum()
    mp = (g.gp / g.volume).unstack()
    ts = []
    for mo, row in mp.iterrows():
        if row[CORE].isna().any():
            continue
        mm, c_, l_, r_, se_ = ols_line(row, CORE)
        ts.append({"month": str(mo), "c": c_, "lam": l_, "ratio": r_, "r2": mm.rsquared})
    ts = pd.DataFrame(ts)
    yrs = np.arange(len(ts)) / 12
    tr = sm.OLS(ts.ratio, sm.add_constant(yrs)).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
    R["stability"] = {"median": float(ts.ratio.median()), "iqr": list(ts.ratio.quantile([.25, .75])),
                      "corr_c_lam": float(np.corrcoef(ts.c, ts.lam)[0, 1]), "lam_range": [float(ts.lam.min()), float(ts.lam.max())],
                      "cv_lam": float(ts.lam.std() / ts.lam.mean()), "cv_ratio": float(ts.ratio.std() / ts.ratio.mean()),
                      "trend": float(tr.params.iloc[1]), "trend_se": float(tr.bse.iloc[1]), "median_r2": float(ts.r2.median())}
    print("stability", {k: v for k, v in R["stability"].items()})

    # ---- free-to-play
    mf, cf, lf, rf, sef = ols_line(px, F2P)
    R["f2p"] = {"c": cf, "c_se": mf.bse["heal"], "lam": lf, "lam_se": mf.bse["const"], "ratio": rf, "r2": mf.rsquared}
    # test: is the F2P slope equal to the members slope? pooled with interaction
    items = CORE + F2P
    X = pd.DataFrame({"const": 1.0, "heal": FOOD.loc[items, "heal"].astype(float),
                      "f2p": [1.0 if f in F2P else 0.0 for f in items]})
    X["heal_x_f2p"] = X.heal * X.f2p
    mp_ = sm.OLS(px[items].astype(float), X).fit()
    R["f2p"]["slope_diff"] = [float(mp_.params["heal_x_f2p"]), float(mp_.bse["heal_x_f2p"]), float(mp_.pvalues["heal_x_f2p"])]
    print("f2p", R["f2p"])

    # ---- out of sample: prediction intervals for Sailing fish
    Xc = sm.add_constant(FOOD.loc[CORE, "heal"].astype(float))
    oos = []
    for f in ["Giant krill", "Haddock", "Yellowfin", "Halibut", "Bluefin", "Marlin"]:
        pr = m.get_prediction(np.array([[1.0, float(FOOD.loc[f, "heal"])]])).summary_frame(alpha=0.05)
        oos.append({"food": f, "price": float(px[f]), "pred": float(pr["mean"].iloc[0]),
                    "pi": [float(pr["obs_ci_lower"].iloc[0]), float(pr["obs_ci_upper"].iloc[0])]})
    R["oos"] = oos
    print(pd.DataFrame(oos).round(0).to_string())

    # ---- cross-resource
    pray = 5 * px["Prayer potion(4)"] / 124
    R["cross"] = {"bluefin_prem": float(px["Bluefin"] - (c * 22 - lam)), "prayer5": float(pray),
                  "slot_share": float(5 / 124 * lam),
                  "yellowfin_prem": float(px["Yellowfin"] - (c * 19 - lam)),
                  "energy20": float(px["Energy potion(4)"] / 2), "super20": float(px["Super energy(4)"] / 4)}
    print("cross", R["cross"])

    # ---- difference-in-differences
    BASE = ["Monkfish", "Shark", "Sea turtle"]
    TOP = ["Manta ray", "Tuna potato", "Dark crab", "Anglerfish"]
    gap = []
    for mo, row in mp.iterrows():
        if row[BASE + TOP].isna().any():
            continue
        h = FOOD.loc[BASE, "heal"].astype(float)
        b = np.polyfit(h, row[BASE].astype(float), 1)
        gap.append({"mo": mo, **{t: row[t] / (b[0] * 22 + b[1]) - 1 for t in TOP}})
    gp_ = pd.DataFrame(gap).set_index("mo")

    def did(pre, post, rel=False):
        sub = pd.concat([gp_.loc[pre[0]:pre[1]].assign(post=0), gp_.loc[post[0]:post[1]].assign(post=1)])
        treated = sub[["Manta ray", "Tuna potato", "Dark crab"]].mean(axis=1)
        ctrl = sub["Anglerfish"]
        dd = (np.log1p(treated) - np.log1p(ctrl)) if rel else (treated - ctrl) * 100
        mm = sm.OLS(dd.to_numpy(), sm.add_constant(sub.post.to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
        return {"est": float(mm.params[1]), "se": float(mm.bse[1]),
                "ci": list(map(float, mm.conf_int()[1])), "p": float(mm.pvalues[1]), "n": int(mm.nobs)}
    R["did"] = {
        "main_pp": did(("2023-01", "2024-12"), ("2025-12", "2026-11")),
        "main_log": did(("2023-01", "2024-12"), ("2025-12", "2026-11"), rel=True),
        "placebo_pp": did(("2023-01", "2023-12"), ("2024-01", "2024-12")),
        "placebo_log": did(("2023-01", "2023-12"), ("2024-01", "2024-12"), rel=True),
    }
    # simple before/after per food for the table
    pre, post = gp_.loc["2023-01":"2024-12"].median(), gp_.loc["2025-12":"2026-11"].median()
    R["did_table"] = {t: [float(pre[t]), float(post[t])] for t in TOP}
    print("did", json.dumps(R["did"], indent=1))

    OUT.write_text(json.dumps(R, indent=1, default=float))


if __name__ == "__main__":
    main()
