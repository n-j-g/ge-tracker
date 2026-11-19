"""The basket of everyday goods for the OSRS price index ("CPI").

Everyday consumables and skilling supplies that a typical main buys again and
again, grouped into categories. Rare and luxury items (gear, rares) are left
out on purpose: they behave like assets, not like the cost of playing.

How much each item counts (its weight) isn't set here: it comes from how much
gold was spent on it on the GE in the base year, like a real CPI's expenditure
weights. Names must match the Wiki item names exactly; an item missing from the
data is reported and left out.
"""
from __future__ import annotations

BASKET: dict[str, list[str]] = {
    "Food": [
        "Shark", "Manta ray", "Anglerfish", "Cooked karambwan", "Monkfish", "Lobster",
    ],
    "Potions": [
        "Prayer potion(4)", "Super restore(4)", "Saradomin brew(4)", "Stamina potion(4)",
        "Super combat potion(4)", "Ranging potion(4)", "Anti-venom+(4)",
    ],
    "Runes": [
        "Nature rune", "Law rune", "Death rune", "Blood rune", "Chaos rune", "Cosmic rune",
        "Astral rune", "Soul rune", "Fire rune", "Air rune",
    ],
    "Ammo": [
        "Rune arrow", "Amethyst arrow", "Rune dart", "Dragon dart", "Ruby bolts (e)",
        "Diamond bolts (e)", "Cannonball", "Zulrah's scales",
    ],
    "Teleports": [
        "Teleport to house", "Varrock teleport", "Ring of dueling(8)", "Games necklace(8)",
        "Amulet of glory(6)",
    ],
    "Ores & bars": [
        "Coal", "Iron ore", "Runite ore", "Steel bar", "Gold bar", "Adamantite bar", "Runite bar",
    ],
    "Logs & planks": [
        "Oak logs", "Maple logs", "Yew logs", "Magic logs", "Redwood logs",
        "Oak plank", "Teak plank", "Mahogany plank",
    ],
    "Herbs & seeds": [
        "Grimy ranarr weed", "Grimy snapdragon", "Grimy toadflax", "Ranarr seed", "Snapdragon seed",
    ],
    "Other supplies": [
        "Dragon bones", "Big bones", "Green dragonhide", "Black dragonhide", "Uncut diamond",
        "Uncut ruby", "Flax", "Bow string", "Battlestaff", "Pure essence", "Feather", "Vial of water",
    ],
}


def basket_items() -> dict[str, str]:
    """{item name: category}"""
    return {name: cat for cat, names in BASKET.items() for name in names}
