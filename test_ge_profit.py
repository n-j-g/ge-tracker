import json
import unittest

from ge_profit import (DEFAULT_RECIPES, parse_prices, actions_per_limit, Price, PricingError, Recipe, evaluate,
                       evaluate_all, ge_tax, load_recipes)

IDS = {"yew logs": 1, "yew longbow (u)": 2, "bow string": 3, "yew longbow": 4,
       "bucket of sand": 5, "soda ash": 6, "molten glass": 7, "bucket": 8,
       "ranarr weed": 9, "vial of water": 10, "ranarr potion (unf)": 11,
       "green dragonhide": 12, "green dragon leather": 13}
PRICES = {
    1: Price(high=300, low=290),
    2: Price(high=400, low=380),
    3: Price(high=150, low=140),
    4: Price(high=600, low=580),
    5: Price(high=40, low=35),
    6: Price(high=60, low=55),
    7: Price(high=200, low=190),
    8: Price(high=10, low=5),
    9: Price(high=7000, low=6900),
    10: Price(high=5, low=4),
    11: Price(high=7200, low=7100),
    12: Price(high=1500, low=1450),
    13: Price(high=1700, low=1650),
}

STRING_YEW = Recipe("String yew longbow", "Fletching", 75,
                    {"Yew longbow (u)": 1, "Bow string": 1}, {"Yew longbow": 1})


class TestTax(unittest.TestCase):
    def test_two_percent_rounded_down(self):
        self.assertEqual(ge_tax(580), 11)  # 11.6 -> 11

    def test_under_50_untaxed(self):
        self.assertEqual(ge_tax(49), 0)
        self.assertEqual(ge_tax(50), 1)

    def test_cap(self):
        self.assertEqual(ge_tax(1_000_000_000), 5_000_000)


class TestEvaluate(unittest.TestCase):
    def test_conservative(self):
        r = evaluate(STRING_YEW, IDS, PRICES, "conservative")
        self.assertEqual(r.cost, 400 + 150)        # buy at high
        self.assertEqual(r.revenue, 580 - 11)      # sell at low, minus tax
        self.assertEqual(r.profit, 19)
        self.assertAlmostEqual(r.gp_per_xp, 19 / 75)

    def test_optimistic_and_mid(self):
        self.assertEqual(evaluate(STRING_YEW, IDS, PRICES, "optimistic").cost, 380 + 140)
        self.assertEqual(evaluate(STRING_YEW, IDS, PRICES, "mid").cost, 390 + 145)

    def test_no_tax(self):
        self.assertEqual(evaluate(STRING_YEW, IDS, PRICES, tax=False).revenue, 580)

    def test_multiple_outputs(self):
        glass = Recipe("Glass", "Crafting", 20, {"Bucket of sand": 1, "Soda ash": 1},
                       {"Molten glass": 1, "Bucket": 1})
        r = evaluate(glass, IDS, PRICES)
        self.assertEqual(r.cost, 100)
        self.assertEqual(r.revenue, (190 - 3) + 5)

    def test_zero_xp(self):
        unf = Recipe("Unf", "Herblore", 0, {"Ranarr weed": 1, "Vial of water": 1},
                     {"Ranarr potion (unf)": 1})
        self.assertIsNone(evaluate(unf, IDS, PRICES).gp_per_xp)

    def test_coins_input(self):
        tan = Recipe("Tan", "Crafting", 0, {"Green dragonhide": 1, "Coins": 20},
                     {"Green dragon leather": 1})
        self.assertEqual(evaluate(tan, IDS, PRICES).cost, 1520)

    def test_fractional_quantity(self):
        r = Recipe("Half", "X", 10, {"Bow string": 0.2}, {"Bucket": 1})
        self.assertAlmostEqual(evaluate(r, IDS, PRICES).cost, 30)

    def test_crossed_prices(self):
        prices = dict(PRICES)
        prices[3] = Price(high=140, low=150)  # bow string: low above high
        cons = evaluate(STRING_YEW, IDS, prices, "conservative")
        opt = evaluate(STRING_YEW, IDS, prices, "optimistic")
        self.assertEqual(cons.cost, 400 + 150)
        self.assertEqual(opt.cost, 380 + 140)

    def test_unknown_item(self):
        bad = Recipe("Bad", "X", 1, {"Not an item": 1}, {"Yew logs": 1})
        with self.assertRaises(PricingError):
            evaluate(bad, IDS, PRICES)

    def test_missing_price_side(self):
        prices = dict(PRICES)
        prices[4] = Price(high=600, low=None)
        with self.assertRaises(PricingError):
            evaluate(STRING_YEW, IDS, prices, "conservative")

    def test_evaluate_all_sorts_and_collects_errors(self):
        bad = Recipe("Bad", "X", 1, {"Nope": 1}, {"Yew logs": 1})
        cut = Recipe("Cut", "Fletching", 75, {"Yew logs": 1}, {"Yew longbow (u)": 1})
        results, errors = evaluate_all([cut, bad, STRING_YEW], IDS, PRICES)
        self.assertEqual([r.recipe.name for r in results], ["Cut", "String yew longbow"])
        self.assertEqual(errors[0][0], "Bad")


class TestParsing(unittest.TestCase):
    def test_average_format(self):
        raw = {"data": {"1515": {"avgHighPrice": 90, "highPriceVolume": 500,
                                 "avgLowPrice": 86, "lowPriceVolume": 700}}}
        p = parse_prices(raw)[1515]
        self.assertEqual((p.high, p.low, p.high_volume, p.low_volume), (90, 86, 500, 700))

    def test_latest_format(self):
        raw = {"data": {"1515": {"high": 88, "highTime": 1, "low": 85, "lowTime": 2}}}
        p = parse_prices(raw)[1515]
        self.assertEqual((p.high, p.low, p.high_volume), (88, 85, None))

    def test_one_sided_average_is_skipped(self):
        raw = {"data": {"4": {"avgHighPrice": 600, "highPriceVolume": 3,
                              "avgLowPrice": None, "lowPriceVolume": 0}}}
        prices = dict(PRICES); prices.update(parse_prices(raw))
        with self.assertRaises(PricingError):
            evaluate(STRING_YEW, IDS, prices)


class TestLimits(unittest.TestCase):
    LIMITS = {2: 10000, 3: 13000, 5: 13000, 6: 13000, 12: 13000}

    def test_tightest_input_wins(self):
        self.assertEqual(actions_per_limit(STRING_YEW, IDS, self.LIMITS), 10000)

    def test_quantity_and_coins(self):
        r = Recipe("X", "X", 1, {"Bow string": 2, "Coins": 20}, {"Bucket": 1})
        self.assertEqual(actions_per_limit(r, IDS, self.LIMITS), 6500)

    def test_unknown_limit(self):
        self.assertIsNone(actions_per_limit(STRING_YEW, IDS, {3: 13000}))

    def test_gp_per_limit_without_volume_data(self):
        r = evaluate(STRING_YEW, IDS, PRICES, limits=self.LIMITS)
        self.assertEqual(r.gp_per_limit, 19 * 10000)  # only buy limits apply

    def test_volume_caps_actions(self):
        prices = dict(PRICES)
        prices[2] = Price(400, 380, 50_000, 50_000)
        prices[3] = Price(150, 140, 50_000, 50_000)
        prices[4] = Price(600, 580, 300, 200)   # Yew longbow: 500/hr -> 2,000 per 4h
        r = evaluate(STRING_YEW, IDS, prices, limits=self.LIMITS)
        self.assertEqual(r.volume_actions, 2000)
        self.assertEqual(r.capped_actions(0.10), 200)       # 10% of volume binds
        self.assertEqual(r.capped_actions(1.0), 2000)
        self.assertEqual(r.gp_per_limit, 19 * 200)
        rich = evaluate(STRING_YEW, IDS, {**prices, 4: Price(600, 580, 10**6, 10**6)}, limits=self.LIMITS)
        self.assertEqual(rich.capped_actions(0.10), 10000)  # buy limit binds

    def test_volume_window_scaling(self):
        prices = {**PRICES, 2: Price(400, 380, 600, 0), 3: Price(150, 140, 600, 0),
                  4: Price(600, 580, 600, 0)}
        r = evaluate(STRING_YEW, IDS, prices, volume_hours=5 / 60)  # 5-minute volumes
        self.assertAlmostEqual(r.volume_actions, 600 * 48)


class TestWeb(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("node"), "needs Node.js to syntax-check the page script")
    def test_page_script_is_valid_javascript(self):
        import re, subprocess, tempfile
        from web import render_html
        page = render_html([evaluate(STRING_YEW, IDS, PRICES)], {"source": "1h", "mode": "conservative"})
        script = re.search(r"<script>(.*)</script>", page, re.S).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
        result = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_page_renders_and_escapes(self):
        from web import render_html
        bad = Recipe("</script><b>x", "Fletching", 75, {"Yew longbow (u)": 1, "Bow string": 1}, {"Yew longbow": 1})
        page = render_html([evaluate(bad, IDS, PRICES)], {"source": "1h", "mode": "conservative"})
        self.assertIn("GE production profits", page)
        self.assertNotIn("</script><b>", page)


class TestWiki(unittest.TestCase):
    ROW = {"page_name": "Bronze bar", "source_template": "recipe", "production_json": json.dumps({
        "ticks": "3", "members": False,
        "materials": [{"quantity": "1", "name": "Copper ore"}, {"quantity": "1", "name": "Tin ore"},
                      {"quantity": "1", "name": "Nature rune"}, {"quantity": "4", "name": "Fire rune"}],
        "skills": [{"experience": "6.2", "name": "Smithing"}, {"experience": "53", "name": "Magic"}],
        "output": {"quantity": "1", "name": "Bronze bar", "subtxt": "Superheat"}})}

    def test_convert_multi_skill(self):
        from wiki_recipes import convert_row
        r = convert_row(self.ROW)
        self.assertEqual(r.name, "Bronze bar (Superheat)")
        self.assertEqual(r.skill, "Smithing + Magic")
        self.assertAlmostEqual(r.xp, 59.2)
        self.assertEqual(r.inputs["Fire rune"], 4)
        self.assertEqual(r.outputs, {"Bronze bar": 1})
        self.assertEqual((r.ticks, r.members, r.source), (3, False, "wiki"))

    def test_non_numeric_xp_skipped(self):
        from wiki_recipes import convert_row
        row = dict(self.ROW)
        p = json.loads(row["production_json"]); p["skills"][0]["experience"] = "1×Construction level"
        row["production_json"] = json.dumps(p)
        self.assertIsNone(convert_row(row))

    def test_duplicate_materials_summed(self):
        from wiki_recipes import convert_row
        row = dict(self.ROW)
        p = json.loads(row["production_json"])
        p["materials"] = [{"quantity": "1", "name": "Coal"}, {"quantity": "2", "name": "Coal"}]
        row["production_json"] = json.dumps(p)
        self.assertEqual(convert_row(row).inputs, {"Coal": 3})

    def test_manual_overrides_wiki(self):
        from ge_profit import merge_recipes
        manual = Recipe("Mine", "Fletching", 75, {"Yew logs": 1}, {"Yew longbow (u)": 1})
        wiki = Recipe("Wiki", "Fletching", 70, {"yew logs": 1}, {"Yew longbow (u)": 1}, source="wiki")
        other = Recipe("Other", "Fletching", 1, {"Maple logs": 1}, {"Bucket": 1}, source="wiki")
        self.assertEqual([r.name for r in merge_recipes([manual], [wiki, other])], ["Mine", "Other"])


class TestFallback(unittest.TestCase):
    def test_fill_missing_side(self):
        from ge_profit import fill_missing
        primary = {1: Price(90, None, 5, 0), 2: Price(10, 9, 1, 1)}
        fallback = {1: Price(88, 85), 3: Price(7, 6)}
        m = fill_missing(primary, fallback)
        self.assertEqual((m[1].high, m[1].low, m[1].high_volume), (90, 85, 5))
        self.assertEqual((m[2].high, m[2].low), (10, 9))
        self.assertEqual((m[3].high, m[3].low, m[3].high_volume), (7, 6, 0))


class TestQualityFilters(unittest.TestCase):
    def test_min_volume_is_least_traded_item(self):
        from ge_profit import min_volume
        prices = dict(PRICES)
        prices[2] = Price(400, 380, 50, 20)    # Yew longbow (u): 70/hr
        prices[3] = Price(150, 140, 900, 100)  # Bow string: 1000/hr
        prices[4] = Price(600, 580, 5, 0)      # Yew longbow: 5/hr
        self.assertEqual(min_volume(STRING_YEW, IDS, prices), 5)
        self.assertIsNone(min_volume(STRING_YEW, IDS, PRICES))  # no volume data

    def test_passes_volume(self):
        from ge_profit import Result, passes_volume
        self.assertTrue(passes_volume(Result(STRING_YEW, 0, 0, None, None), 100))
        self.assertFalse(passes_volume(Result(STRING_YEW, 0, 0, None, 99), 100))
        self.assertTrue(passes_volume(Result(STRING_YEW, 0, 0, None, 100), 100))

    def test_excludes(self):
        from ge_profit import apply_excludes, load_excludes
        self.assertIn("squid beak", load_excludes(DEFAULT_RECIPES))
        beak = Recipe("Beak", "Cooking", 2, {"Raw jumbo squid": 1}, {"Squid beak": 1})
        self.assertEqual(apply_excludes([beak, STRING_YEW], {"squid beak"}), [STRING_YEW])

    def test_burnt_outcome_dropped(self):
        from wiki_recipes import convert_row
        row = {"production_json": json.dumps({"materials": [{"quantity": "1", "name": "Raw shark"}],
               "skills": [{"experience": "0", "name": "Cooking"}],
               "output": {"quantity": "1", "name": "Burnt shark"}})}
        self.assertIsNone(convert_row(row))


class TestSpeed(unittest.TestCase):
    def test_banking_model(self):
        from ge_profit import speed
        # 14 per inventory, 2 ticks each + 10-tick bank trip = 38 ticks per 14 actions
        r = Recipe("S", "Fletching", 75, {"Yew longbow (u)": 1, "Bow string": 1}, {"Yew longbow": 1}, ticks=2)
        self.assertAlmostEqual(speed(r), 14 * 3600 / (38 * 0.6))

    def test_stackables_and_tools(self):
        from ge_profit import is_stackable, speed
        self.assertTrue(is_stackable("Fire rune")); self.assertTrue(is_stackable("Ruby bolt tips"))
        self.assertFalse(is_stackable("Pure essence")); self.assertFalse(is_stackable("Steel bar"))
        # 1 diamond (non-stackable) per action, chisel takes a slot -> 27 per trip
        r = Recipe("D", "Fletching", 7, {"Diamond": 1}, {"Diamond bolt tips": 12}, ticks=5, tools=("Chisel",))
        self.assertAlmostEqual(speed(r), 27 * 3600 / ((27 * 5 + 10) * 0.6))
        # all-stackable inputs: no banking
        r2 = Recipe("F", "Fletching", 1, {"Feather": 1, "Rune dart tip": 1}, {"Rune dart": 1}, ticks=1)
        self.assertAlmostEqual(speed(r2), 6000)

    def test_unmodelled_and_override(self):
        from ge_profit import speed
        rc = Recipe("Blood rune", "Runecraft", 10.5, {"Pure essence": 1}, {"Blood rune": 1}, ticks=1)
        self.assertIsNone(speed(rc))
        self.assertIsNone(speed(Recipe("Z", "Cooking", 1, {"Raw shark": 1}, {"Shark": 1}, ticks=0)))
        self.assertEqual(speed(Recipe("Blood rune", "Runecraft", 10.5, {"Pure essence": 1},
                                      {"Blood rune": 1}, ticks=1, actions_per_hour=4000)), 4000)

    def test_cooking_floor_and_travel_facilities(self):
        from ge_profit import speed
        manta = Recipe("M", "Cooking", 216, {"Raw manta ray": 1}, {"Manta ray": 1}, ticks=1,
                       facility="Cooking range")
        self.assertAlmostEqual(speed(manta), 28 * 3600 / ((28 * 4 + 10) * 0.6))
        orb = Recipe("O", "Magic", 66, {"Unpowered orb": 1, "Cosmic rune": 3, "Air rune": 30},
                     {"Air orb": 1}, ticks=3, facility="Obelisk of Air")
        self.assertIsNone(speed(orb))

    def test_hour_plan_binding(self):
        from ge_profit import Result
        base = dict(recipe=STRING_YEW, cost=0, revenue=19)
        self.assertEqual(Result(**base, actions_per_limit=10000, volume_actions=10**7, speed=1300)
                         .hour_plan(0.1), (1300, "speed"))
        self.assertEqual(Result(**base, actions_per_limit=500, volume_actions=10**7, speed=1300)
                         .hour_plan(0.1), (500, "limit"))
        self.assertEqual(Result(**base, actions_per_limit=10000, volume_actions=4000, speed=1300)
                         .hour_plan(0.1), (100, "volume"))
        self.assertEqual(Result(**base, actions_per_limit=10000, volume_actions=4000, speed=1300)
                         .gp_per_hour(0.1), 1900)

    def test_manual_inherits_wiki_speed(self):
        from ge_profit import merge_recipes
        manual = Recipe("Mine", "Fletching", 75, {"Yew logs": 1}, {"Yew longbow (u)": 1})
        wiki = Recipe("Wiki", "Fletching", 75, {"Yew logs": 1}, {"Yew longbow (u)": 1},
                      ticks=3, tools=("Knife",), source="wiki")
        m = merge_recipes([manual], [wiki])[0]
        self.assertEqual((m.name, m.ticks, m.tools), ("Mine", 3, ("Knife",)))

    def test_tools_parsing(self):
        from wiki_recipes import _tools
        self.assertEqual(_tools("Saw, Hammer"), ("Saw", "Hammer"))
        self.assertEqual(_tools("[[Pickaxe]]"), ("Pickaxe",))
        self.assertEqual(_tools("Air tiara, Binding necklace, Magic Imbue"), ())


class TestXpPace(unittest.TestCase):
    def test_reference_and_pace(self):
        from ge_profit import Result, reference_rates, xp_pace
        normal = Result(Recipe("String magic longbow", "Fletching", 91.5, {"A": 1}, {"B": 1}), 0, 0, speed=2000)
        darts = Result(Recipe("Dragon dart", "Fletching", 25, {"C": 1}, {"D": 1}), 0, 0, speed=20000)
        thin = Result(Recipe("Thin", "Fletching", 100, {"G": 1}, {"H": 1}), 0, 0,
                      volume_actions=4000, speed=2000)  # 10% of 1,000/hr -> 100 actions
        unknown = Result(Recipe("X", "Fletching", 10, {"E": 1}, {"F": 1}), 0, 0, speed=None)
        refs = reference_rates([normal, darts, unknown], {"Fletching": "string magic longbow"})
        self.assertEqual(refs["Fletching"]["xp_per_hour"], 183000)
        self.assertAlmostEqual(xp_pace(darts, refs), 500000 / 183000)
        self.assertAlmostEqual(xp_pace(normal, refs), 1.0)
        self.assertIsNone(xp_pace(unknown, refs))
        self.assertAlmostEqual(xp_pace(thin, refs, 0.1), 100 * 100 / 183000)  # market-limited
        self.assertIsNone(xp_pace(Result(Recipe("Y", "Cooking", 10, {"E": 1}, {"F": 1}), 0, 0, speed=100), refs))

    def test_shipped_normal_training_loads(self):
        from ge_profit import load_normal_training
        self.assertEqual(load_normal_training(DEFAULT_RECIPES)["Fletching"], "String magic longbow")


class TestHourlyFees(unittest.TestCase):
    def test_fee_spread_over_actions(self):
        r = Recipe("String yew longbow", "Fletching", 75, {"Yew longbow (u)": 1, "Bow string": 1},
                   {"Yew longbow": 1}, actions_per_hour=2000, coins_per_hour=72000)
        res = evaluate(r, IDS, PRICES)
        self.assertAlmostEqual(res.cost, 400 + 150 + 36)

    def test_shipped_blast_furnace_overrides(self):
        from ge_profit import apply_speed_overrides, load_hourly_fees, load_speed_overrides
        bf = Recipe("Runite bar (Blast Furnace)", "Smithing", 50, {"Runite ore": 1, "Coal": 4},
                    {"Runite bar": 1}, ticks=11, source="wiki")
        out = apply_speed_overrides([bf], load_speed_overrides(DEFAULT_RECIPES),
                                    load_hourly_fees(DEFAULT_RECIPES))[0]
        self.assertEqual((out.actions_per_hour, out.coins_per_hour), (2160, 72000))


class TestRecipeFile(unittest.TestCase):
    def test_shipped_recipes_load(self):
        recipes = load_recipes(DEFAULT_RECIPES)
        self.assertGreater(len(recipes), 30)
        self.assertEqual(len({r.name for r in recipes}), len(recipes))
        for r in recipes:
            self.assertTrue(r.inputs and r.outputs, r.name)


if __name__ == "__main__":
    unittest.main()
