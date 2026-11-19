"""The basket of everyday goods for the OSRS price index ("CPI").

Everyday consumables and skilling supplies that players buy again and again,
grouped two ways:

- category: what kind of good it is (food, potions, runes, ...);
- tier: who buys it.
    Basic    early game: low-level food, potions, runes, arrows, F2P skilling
    Economy  mid game: the standard supplies of a mid-level main
    Luxury   late game: high-level PvM supplies and top-end skilling inputs

Rare and luxury *items* (gear, rares) are left out on purpose: they behave like
assets, not like the cost of playing. "Luxury" here means late-game supplies.

How much each item counts (its weight) isn't set here: it comes from how much
gold was spent on it on the GE in the base year, like a real CPI's expenditure
weights (within each tier for the tier indices). Names must match the Wiki item
names exactly; an item missing from the data is reported and left out.
"""
from __future__ import annotations

TIERS = ["Basic", "Economy", "Luxury"]

# (item, category, tier)
BASKET_ROWS: list[tuple[str, str, str]] = [
    # ---------------- Basic: early game
    ("Trout", "Food", "Basic"),
    ("Salmon", "Food", "Basic"),
    ("Tuna", "Food", "Basic"),
    ("Lobster", "Food", "Basic"),
    ("Swordfish", "Food", "Basic"),
    ("Attack potion(4)", "Potions", "Basic"),
    ("Strength potion(4)", "Potions", "Basic"),
    ("Energy potion(4)", "Potions", "Basic"),
    ("Air rune", "Runes", "Basic"),
    ("Water rune", "Runes", "Basic"),
    ("Earth rune", "Runes", "Basic"),
    ("Fire rune", "Runes", "Basic"),
    ("Mind rune", "Runes", "Basic"),
    ("Chaos rune", "Runes", "Basic"),
    ("Iron arrow", "Ammo", "Basic"),
    ("Steel arrow", "Ammo", "Basic"),
    ("Mithril arrow", "Ammo", "Basic"),
    ("Adamant arrow", "Ammo", "Basic"),
    ("Varrock teleport (tablet)", "Teleports", "Basic"),
    ("Iron ore", "Ores & bars", "Basic"),
    ("Coal", "Ores & bars", "Basic"),
    ("Steel bar", "Ores & bars", "Basic"),
    ("Oak logs", "Logs & planks", "Basic"),
    ("Willow logs", "Logs & planks", "Basic"),
    ("Maple logs", "Logs & planks", "Basic"),
    ("Big bones", "Other supplies", "Basic"),
    ("Cowhide", "Other supplies", "Basic"),
    ("Feather", "Other supplies", "Basic"),
    ("Flax", "Other supplies", "Basic"),
    ("Bow string", "Other supplies", "Basic"),
    ("Vial of water", "Other supplies", "Basic"),
    ("Eye of newt", "Other supplies", "Basic"),
    # ---------------- Economy: mid game
    ("Monkfish", "Food", "Economy"),
    ("Shark", "Food", "Economy"),
    ("Cooked karambwan", "Food", "Economy"),
    ("Prayer potion(4)", "Potions", "Economy"),
    ("Super combat potion(4)", "Potions", "Economy"),
    ("Ranging potion(4)", "Potions", "Economy"),
    ("Super energy(4)", "Potions", "Economy"),
    ("Stamina potion(4)", "Potions", "Economy"),
    ("Antifire potion(4)", "Potions", "Economy"),
    ("Nature rune", "Runes", "Economy"),
    ("Law rune", "Runes", "Economy"),
    ("Death rune", "Runes", "Economy"),
    ("Cosmic rune", "Runes", "Economy"),
    ("Astral rune", "Runes", "Economy"),
    ("Rune arrow", "Ammo", "Economy"),
    ("Adamant dart", "Ammo", "Economy"),
    ("Rune dart", "Ammo", "Economy"),
    ("Ruby bolts (e)", "Ammo", "Economy"),
    ("Steel cannonball", "Ammo", "Economy"),
    ("Teleport to house (tablet)", "Teleports", "Economy"),
    ("Ring of dueling(8)", "Teleports", "Economy"),
    ("Games necklace(8)", "Teleports", "Economy"),
    ("Amulet of glory(6)", "Teleports", "Economy"),
    ("Gold bar", "Ores & bars", "Economy"),
    ("Adamantite bar", "Ores & bars", "Economy"),
    ("Yew logs", "Logs & planks", "Economy"),
    ("Oak plank", "Logs & planks", "Economy"),
    ("Teak plank", "Logs & planks", "Economy"),
    ("Grimy ranarr weed", "Herbs & seeds", "Economy"),
    ("Grimy toadflax", "Herbs & seeds", "Economy"),
    ("Ranarr seed", "Herbs & seeds", "Economy"),
    ("Dragon bones", "Other supplies", "Economy"),
    ("Green dragonhide", "Other supplies", "Economy"),
    ("Uncut ruby", "Other supplies", "Economy"),
    ("Uncut diamond", "Other supplies", "Economy"),
    ("Battlestaff", "Other supplies", "Economy"),
    ("Pure essence", "Other supplies", "Economy"),
    # ---------------- Luxury: late game
    ("Anglerfish", "Food", "Luxury"),
    ("Manta ray", "Food", "Luxury"),
    ("Dark crab", "Food", "Luxury"),
    ("Saradomin brew(4)", "Potions", "Luxury"),
    ("Super restore(4)", "Potions", "Luxury"),
    ("Divine super combat potion(4)", "Potions", "Luxury"),
    ("Divine ranging potion(4)", "Potions", "Luxury"),
    ("Anti-venom+(4)", "Potions", "Luxury"),
    ("Extended super antifire(4)", "Potions", "Luxury"),
    ("Blood rune", "Runes", "Luxury"),
    ("Soul rune", "Runes", "Luxury"),
    ("Wrath rune", "Runes", "Luxury"),
    ("Amethyst arrow", "Ammo", "Luxury"),
    ("Dragon arrow", "Ammo", "Luxury"),
    ("Dragon dart", "Ammo", "Luxury"),
    ("Diamond bolts (e)", "Ammo", "Luxury"),
    ("Ruby dragon bolts (e)", "Ammo", "Luxury"),
    ("Zulrah's scales", "Ammo", "Luxury"),
    ("Runite ore", "Ores & bars", "Luxury"),
    ("Runite bar", "Ores & bars", "Luxury"),
    ("Magic logs", "Logs & planks", "Luxury"),
    ("Redwood logs", "Logs & planks", "Luxury"),
    ("Mahogany plank", "Logs & planks", "Luxury"),
    ("Grimy snapdragon", "Herbs & seeds", "Luxury"),
    ("Grimy torstol", "Herbs & seeds", "Luxury"),
    ("Snapdragon seed", "Herbs & seeds", "Luxury"),
    ("Torstol seed", "Herbs & seeds", "Luxury"),
    ("Superior dragon bones", "Other supplies", "Luxury"),
    ("Black dragonhide", "Other supplies", "Luxury"),
    ("Uncut dragonstone", "Other supplies", "Luxury"),
]

BASKET: dict[str, list[str]] = {}
for _name, _cat, _tier in BASKET_ROWS:
    BASKET.setdefault(_cat, []).append(_name)


def basket_items() -> dict[str, str]:
    """{item name: category}"""
    return {name: cat for name, cat, _ in BASKET_ROWS}


def basket_tiers() -> dict[str, str]:
    """{item name: tier}"""
    return {name: tier for name, _, tier in BASKET_ROWS}
