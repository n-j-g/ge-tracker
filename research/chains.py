"""Production chains and training methods used in the price-history research.

Quantities and XP are per action and were checked against the OSRS Wiki recipe
data (Bucket:Recipe), except Prayer, Firemaking and Construction methods, which
aren't in that data and use standard values (noted below).

`margin`: include in the margin study (processing chains with GE inputs and outputs).
`xp`: include in the XP-price study (standard ways to train the skill).
"""
from __future__ import annotations

from dataclasses import dataclass, field

BF_COFFER_PER_HOUR = 72_000  # Blast Furnace coffer, coins per hour


@dataclass(frozen=True)
class Chain:
    name: str
    skill: str
    xp: float
    inputs: dict
    outputs: dict = field(default_factory=dict)  # empty = nothing to sell (bones, logs burnt, furniture)
    fee: float = 0.0          # coins per action (NPC fees, coffer spread over the action rate)
    margin: bool = False
    xp_method: bool = False
    note: str = ""


def bf(per_hour: int) -> float:
    return BF_COFFER_PER_HOUR / per_hour


CHAINS = [
    # ---------------- Smelting / Smithing
    Chain("Runite bar (Blast Furnace)", "Smithing", 50, {"Runite ore": 1, "Coal": 4}, {"Runite bar": 1},
          fee=bf(2160), margin=True),
    Chain("Adamantite bar (Blast Furnace)", "Smithing", 37.5, {"Adamantite ore": 1, "Coal": 3},
          {"Adamantite bar": 1}, fee=bf(2700), margin=True),
    Chain("Steel bar (Blast Furnace)", "Smithing", 17.5, {"Iron ore": 1, "Coal": 1}, {"Steel bar": 1},
          fee=bf(5400), margin=True),
    Chain("Cannonballs", "Smithing", 25.6, {"Steel bar": 1}, {"Steel cannonball": 4}, margin=True),
    Chain("Rune platebody", "Smithing", 375, {"Runite bar": 5}, {"Rune platebody": 1}, margin=True, xp_method=True),
    Chain("Adamant platebody", "Smithing", 312.5, {"Adamantite bar": 5}, {"Adamant platebody": 1}, xp_method=True),

    # ---------------- Fletching
    Chain("Cut magic longbow (u)", "Fletching", 91.5, {"Magic logs": 1}, {"Magic longbow (u)": 1}, margin=True),
    Chain("String magic longbow", "Fletching", 91.5, {"Magic longbow (u)": 1, "Bow string": 1},
          {"Magic longbow": 1}, margin=True),
    Chain("String yew longbow", "Fletching", 75, {"Yew longbow (u)": 1, "Bow string": 1}, {"Yew longbow": 1},
          margin=True),
    Chain("Magic longbow (logs to bow)", "Fletching", 183, {"Magic logs": 1, "Bow string": 1},
          {"Magic longbow": 1}, xp_method=True),
    Chain("Diamond bolt tips", "Fletching", 7, {"Diamond": 1}, {"Diamond bolt tips": 12}, margin=True),
    Chain("Ruby bolt tips", "Fletching", 6.3, {"Ruby": 1}, {"Ruby bolt tips": 12}, margin=True),
    Chain("Dragon darts", "Fletching", 25, {"Dragon dart tip": 1, "Feather": 1}, {"Dragon dart": 1},
          margin=True, xp_method=True),
    Chain("Amethyst darts", "Fletching", 21, {"Amethyst dart tip": 1, "Feather": 1}, {"Amethyst dart": 1},
          xp_method=True),

    # ---------------- Herblore (margin study: from unfinished potions; XP study: from clean herbs)
    Chain("Ranarr potion (unf)", "Herblore", 0, {"Ranarr weed": 1, "Vial of water": 1}, {"Ranarr potion (unf)": 1},
          margin=True),
    Chain("Prayer potion (from unf)", "Herblore", 87.5, {"Ranarr potion (unf)": 1, "Snape grass": 1},
          {"Prayer potion(3)": 1}, margin=True),
    Chain("Super restore (from unf)", "Herblore", 142.5, {"Snapdragon potion (unf)": 1, "Red spiders' eggs": 1},
          {"Super restore(3)": 1}, margin=True),
    Chain("Saradomin brew (from unf)", "Herblore", 180, {"Toadflax potion (unf)": 1, "Crushed nest": 1},
          {"Saradomin brew(3)": 1}, margin=True),
    Chain("Prayer potion", "Herblore", 87.5, {"Ranarr weed": 1, "Vial of water": 1, "Snape grass": 1},
          {"Prayer potion(3)": 1}, xp_method=True),
    Chain("Super restore", "Herblore", 142.5, {"Snapdragon": 1, "Vial of water": 1, "Red spiders' eggs": 1},
          {"Super restore(3)": 1}, xp_method=True),
    Chain("Saradomin brew", "Herblore", 180, {"Toadflax": 1, "Vial of water": 1, "Crushed nest": 1},
          {"Saradomin brew(3)": 1}, xp_method=True),

    # ---------------- Cooking (burns ignored)
    Chain("Cook shark", "Cooking", 210, {"Raw shark": 1}, {"Shark": 1}, margin=True, xp_method=True),
    Chain("Cook manta ray", "Cooking", 216.3, {"Raw manta ray": 1}, {"Manta ray": 1}, margin=True),
    Chain("Cook karambwan", "Cooking", 190, {"Raw karambwan": 1}, {"Cooked karambwan": 1}, margin=True,
          xp_method=True),
    Chain("Cook anglerfish", "Cooking", 230, {"Raw anglerfish": 1}, {"Anglerfish": 1}, margin=True),

    # ---------------- Crafting
    Chain("Tan green dragonhide (tanner)", "Crafting", 0, {"Green dragonhide": 1}, {"Green dragon leather": 1},
          fee=20, margin=True),
    Chain("Green d'hide body", "Crafting", 186, {"Green dragon leather": 3, "Thread": 0.2}, {"Green d'hide body": 1},
          xp_method=True),
    Chain("Blue d'hide body", "Crafting", 210, {"Blue dragon leather": 3, "Thread": 0.2}, {"Blue d'hide body": 1},
          xp_method=True),
    Chain("Black d'hide body", "Crafting", 258, {"Black dragon leather": 3, "Thread": 0.2}, {"Black d'hide body": 1},
          margin=True, xp_method=True),
    Chain("Air battlestaff", "Crafting", 137.5, {"Air orb": 1, "Battlestaff": 1}, {"Air battlestaff": 1},
          xp_method=True),

    # ---------------- Magic
    Chain("Ring of recoil", "Magic", 17.5, {"Sapphire ring": 1, "Cosmic rune": 1, "Water rune": 1},
          {"Ring of recoil": 1}, margin=True),

    # ---------------- Pure XP purchases (nothing to sell). Standard XP values:
    # bones at a gilded altar give 350% of base (dragon 72, superior dragon 150).
    Chain("Dragon bones (gilded altar)", "Prayer", 252, {"Dragon bones": 1}, xp_method=True),
    Chain("Superior dragon bones (gilded altar)", "Prayer", 525, {"Superior dragon bones": 1}, xp_method=True),
    Chain("Burn yew logs", "Firemaking", 202.5, {"Yew logs": 1}, xp_method=True),
    Chain("Burn magic logs", "Firemaking", 303.8, {"Magic logs": 1}, xp_method=True),
    Chain("Burn redwood logs", "Firemaking", 350, {"Redwood logs": 1}, xp_method=True),
    Chain("Oak larder", "Construction", 480, {"Oak plank": 8}, xp_method=True),
    Chain("Mahogany table", "Construction", 840, {"Mahogany plank": 6}, xp_method=True),
]


def all_items() -> list[str]:
    names = set()
    for c in CHAINS:
        names |= set(c.inputs) | set(c.outputs)
    return sorted(names)
