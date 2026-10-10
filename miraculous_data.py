# -*- coding: utf-8 -*-
"""
Canon database of all 19 Miraculous in the Miracle Box: the seven "main"
ones (Ladybug, Black Cat, Fox, Bee, Turtle, Peacock, Butterfly) plus the 12
Chinese-zodiac ones (Mouse, Ox, Tiger, Rabbit, Dragon, Snake, Horse, Goat,
Monkey, Rooster, Dog, Pig).

The Miraculous is identified by its animal / Kwami, NOT by a fixed show hero
name: whoever holds it picks their own hero name when they transform.

Fields per Miraculous
---------------------
phrase / detransform   canon transformation / de-transformation phrases.
                       detransform = None means the show never revealed it
                       (the bot then falls back to "<Kwami>, Power Down!").
dark_phrase /          the phrase used when the Miraculous is used "for evil"
dark_detransform       (Dark Side mode). Only filled in where it is confirmed
                       by the show; otherwise None -> the normal phrase is used.
food                   the Kwami's favourite food (fan-compiled from the show,
                       toys and games; None = "a tasty snack").
leaves_damage          True when the signature power leaves damage behind
                       that "Miraculous Ladybug!" can repair.
use_category           how "Use Power" works: no_input | text_input |
                       target_member | target_member_text.
"""

MIRACULOUS = {
    "Ladybug": {
        "emoji": "🐞",
        "jewel": "Earrings",
        "kwami": "Tikki",
        "food": "cookies",
        "concept": "Creation",
        "phrase": "Tikki, Spots On!",
        "detransform": "Tikki, Spots Off!",
        "signature_move": "Lucky Charm",
        "tool": "Yo-yo",
        "description": (
            "Tikki grants the power of Creation. 'Lucky Charm' summons a random "
            "object that, used cleverly, can solve almost any problem. The "
            "Ladybug Miraculous holder is also the only one who can cure damage "
            "caused by an akuma or amok, by calling 'Miraculous Ladybug!'."
        ),
        "color": 0xFF0000,
        "use_category": "text_input",
        "use_prompt": "What object does Lucky Charm summon, and how do you use it?",
    },
    "Black Cat": {
        "emoji": "🐈‍⬛",
        "jewel": "Ring",
        "kwami": "Plagg",
        "food": "Camembert",
        "concept": "Destruction",
        "phrase": "Plagg, Claws Out!",
        "detransform": "Plagg, Claws In!",
        "dark_phrase": "Plagg, Daggers Out!",
        "dark_detransform": "Plagg, Daggers In!",
        "leaves_damage": True,
        "signature_move": "Cataclysm",
        "tool": "Baton",
        "description": (
            "Plagg grants the power of Destruction. 'Cataclysm' instantly "
            "destroys or corrodes anything the wielder touches, alongside "
            "enhanced cat-like agility, senses and reflexes."
        ),
        "color": 0x000000,
        "use_category": "text_input",
        "use_prompt": "What do you touch and destroy with Cataclysm?",
    },
    "Fox": {
        "emoji": "🦊",
        "jewel": "Necklace",
        "kwami": "Trixx",
        "food": "grapes",
        "concept": "Illusion",
        "phrase": "Trixx, Let's Pounce!",
        "detransform": "Trixx, Let's Rest!",
        "signature_move": "Mirage",
        "tool": "Flute",
        "description": (
            "Trixx grants the power of Illusion. 'Mirage' creates realistic "
            "illusions (often copies of the wielder) used to confuse and "
            "mislead enemies."
        ),
        "color": 0xFF8C00,
        "use_category": "text_input",
        "use_prompt": "Describe the illusion(s) Mirage creates.",
    },
    "Bee": {
        "emoji": "🐝",
        "jewel": "Comb",
        "kwami": "Pollen",
        "food": "honey",
        "concept": "Subjugation",
        "phrase": "Pollen, Buzz On!",
        "detransform": "Pollen, Buzz Off!",
        "signature_move": "Venom",
        "tool": "Spinning Top",
        "description": (
            "Pollen grants the power of Subjugation. 'Venom' temporarily "
            "paralyzes any target it touches — including, as a last resort, "
            "the wielder themselves."
        ),
        "color": 0xFFD700,
        "use_category": "target_member",
        "use_prompt": "Who do you paralyze with Venom?",
    },
    "Turtle": {
        "emoji": "🐢",
        "jewel": "Bracelet",
        "kwami": "Wayzz",
        "food": "leafy greens",
        "concept": "Protection",
        "phrase": "Wayzz, Shell On!",
        "detransform": "Wayzz, Shell Off!",
        "signature_move": "Shell-ter",
        "tool": "Shield",
        "description": (
            "Wayzz grants the power of Protection. 'Shell-ter' creates a "
            "powerful defensive shield that can protect the wielder and "
            "others from harm."
        ),
        "color": 0x228B22,
        "use_category": "target_member",
        "use_prompt": "Who do you protect with Shell-ter? (pick yourself if it's for you)",
    },
    "Peacock": {
        "emoji": "🦚",
        "jewel": "Brooch",
        "kwami": "Duusu",
        "food": "almonds",
        "concept": "Emotion",
        "phrase": "Duusu, Spread My Feathers!",
        "detransform": "Duusu, Fall My Feathers!",
        "signature_move": "Amok / Sentimonster",
        "tool": "Fan",
        "description": (
            "Duusu grants the power of Emotion (Amokization). The wielder "
            "infuses an object with emotion to create an 'Amok' that animates "
            "it, or shapes raw emotion into a living 'Sentimonster' that obeys "
            "its creator. The exact power is entirely up to whoever holds "
            "this Miraculous."
        ),
        "color": 0x00CED1,
        "use_category": "target_member_text",
        "use_prompt": "Who receives the Amok/Sentimonster, and what power does it have?",
    },
    "Butterfly": {
        "emoji": "🦋",
        "jewel": "Brooch",
        "kwami": "Nooroo",
        "food": "flowers",
        "concept": "Transmission",
        "phrase": "Nooroo, Dark Wings Rise!",
        "detransform": "Nooroo, Dark Wings Fall!",
        "signature_move": "Akumatize",
        "tool": "Cane",
        "description": (
            "Nooroo grants the power of Transmission (Akumatization). The "
            "wielder infuses a butterfly with a power of their own choosing "
            "and sends it to a person, granting them that power under the "
            "wielder's control — heroic or villainous, canon or homebrew, "
            "entirely the wielder's call."
        ),
        "color": 0x800080,
        "use_category": "target_member_text",
        "use_prompt": "Who do you akumatize, and what power do you give them?",
    },
    # ---- The 12 Chinese zodiac Miraculous ----
    "Mouse": {
        "emoji": "🐭",
        "jewel": "Pendant",
        "kwami": "Mullo",
        "food": "cheese",
        "concept": "Multiplication",
        "phrase": "Mullo, Get Squeaky!",
        "detransform": "Mullo, Get Quiet!",
        "signature_move": "Multitude",
        "tool": "Bracelet Beads",
        "description": (
            "Mullo grants the power of Multiplication. The wielder can split "
            "into several miniature clones of themselves, which can later "
            "merge back together into one full-sized person. (Represents the "
            "Rat of the zodiac.)"
        ),
        "color": 0x808080,
        "use_category": "no_input",
        "use_prompt": None,
    },
    "Ox": {
        "emoji": "🐂",
        "jewel": "Nose Ring",
        "kwami": "Stompp",
        "food": None,
        "concept": "Determination",
        "phrase": "Stompp, Make Way!",
        "detransform": None,
        "signature_move": "Resistance",
        "tool": "Mallet",
        "description": (
            "Stompp grants the power of Determination. 'Resistance' makes the "
            "wielder invulnerable to harm for a short time."
        ),
        "color": 0x1B3A5C,
        "use_category": "no_input",
        "use_prompt": None,
    },
    "Tiger": {
        "emoji": "🐅",
        "jewel": "Bracelet",
        "kwami": "Roaar",
        "food": "durian",
        "concept": "Exaltation",
        "phrase": "Roaar, Stripes On!",
        "detransform": "Roaar, Stripes Off!",
        "leaves_damage": True,
        "signature_move": "Clout",
        "tool": "Gauntlet",
        "description": (
            "Roaar grants the power of Exaltation. 'Clout' unleashes a "
            "deafening super-powered roar/punch that stuns anyone caught in "
            "its range."
        ),
        "color": 0xC71585,
        "use_category": "target_member",
        "use_prompt": "Who is stunned by Clout?",
    },
    "Rabbit": {
        "emoji": "🐇",
        "jewel": "Pocket Watch",
        "kwami": "Fluff",
        "food": "carrots",
        "concept": "Space",
        "phrase": "Fluff, Clockwise!",
        "detransform": "Fluff, Counter Clockwise!",
        "signature_move": "Burrow",
        "tool": "Pocket Watch",
        "description": (
            "Fluff grants the power of Space. The wielder can open portals to "
            "travel across time and between alternate dimensions."
        ),
        "color": 0xFFC0CB,
        "use_category": "text_input",
        "use_prompt": "Where (or when) does Burrow take you?",
    },
    "Dragon": {
        "emoji": "🐉",
        "jewel": "Choker",
        "kwami": "Longg",
        "food": "dragon fruit",
        "concept": "Perfection",
        "phrase": "Longg, Bring the Storm!",
        "detransform": "Longg, Storm Subsides!",
        "leaves_damage": True,
        "signature_move": "Gale Force",
        "tool": "Sword",
        "description": (
            "Longg grants Elemental power over wind and water, often combined "
            "with another Miraculous (as seen with Ryuko), letting the "
            "wielder command the elements around them."
        ),
        "color": 0x2E8B57,
        "use_category": "text_input",
        "use_prompt": "Describe the elemental effect you create with Gale Force.",
    },
    "Snake": {
        "emoji": "🐍",
        "jewel": "Bracelet",
        "kwami": "Sass",
        "food": "tofu",
        "concept": "Intuition",
        "phrase": "Sass, Scales Slither!",
        "detransform": "Sass, Scales Rest!",
        "signature_move": "Second Chance",
        "tool": "Lyre",
        "description": (
            "Sass grants the power of Intuition. Activating 'Second Chance' "
            "lets the wielder rewind time by five seconds if something goes "
            "wrong, giving them a chance to try again."
        ),
        "color": 0x9932CC,
        "use_category": "no_input",
        "use_prompt": None,
    },
    "Horse": {
        "emoji": "🐴",
        "jewel": "Pocket Watch",
        "kwami": "Kaalki",
        "food": "apples",
        "concept": "Teleportation",
        "phrase": "Kaalki, Full Gallop!",
        "detransform": "Kaalki, Dismount!",
        "signature_move": "Voyage",
        "tool": "Pocket Watch",
        "description": (
            "Kaalki grants the power of Teleportation. 'Voyage' opens a "
            "dimensional portal that instantly transports the wielder (and "
            "others) to any place they choose."
        ),
        "color": 0x1E90FF,
        "use_category": "text_input",
        "use_prompt": "Where does Voyage take you (and anyone with you)?",
    },
    "Goat": {
        "emoji": "🐐",
        "jewel": "Hair Clips",
        "kwami": "Ziggy",
        "food": None,
        "concept": "Passion",
        "phrase": "Ziggy, Bleat It!",
        "detransform": None,
        "signature_move": "Genesis",
        "tool": "Paintbrush",
        "description": (
            "Ziggy grants the power of Passion. 'Genesis' brings the "
            "wielder's own drawings to life."
        ),
        "color": 0x36454F,
        "use_category": "text_input",
        "use_prompt": "What do you draw and bring to life with Genesis?",
    },
    "Monkey": {
        "emoji": "🐒",
        "jewel": "Headband",
        "kwami": "Xuppu",
        "food": "bananas",
        "concept": "Derision",
        "phrase": "Xuppu, Show Time!",
        "detransform": None,
        "signature_move": "Uproar",
        "tool": "Staff",
        "description": (
            "Xuppu grants the power of Derision. 'Uproar' lets the wielder "
            "copy the power of a nearby hero and create chaotic, "
            "hallucination-like duplicates to confuse enemies."
        ),
        "color": 0xDAA520,
        "use_category": "target_member",
        "use_prompt": "Whose power do you copy with Uproar?",
    },
    "Rooster": {
        "emoji": "🐓",
        "jewel": "Thumb Ring",
        "kwami": "Orikko",
        "food": "corn",
        "concept": "Pretension",
        "phrase": "Orikko, Sunrise!",
        "detransform": None,
        "signature_move": "Sublimation",
        "tool": "Fountain Pen",
        "description": (
            "Orikko grants the power of Pretension. 'Sublimation' grants the "
            "wielder any power that isn't already the domain of another "
            "Kwami (invisibility, flight, super-strength, and so on — "
            "the wielder's choice)."
        ),
        "color": 0xB22222,
        "use_category": "text_input",
        "use_prompt": "What power do you sublimate into for this scene?",
    },
    "Dog": {
        "emoji": "🐕",
        "jewel": "Collar Necklace",
        "kwami": "Barkk",
        "food": None,
        "concept": "Adoration",
        "phrase": "Barkk, On the Hunt!",
        "detransform": "Barkk, Lay Down!",
        "signature_move": "Fetch",
        "tool": "Ball",
        "description": (
            "Barkk grants the power of Adoration. 'Fetch' lets the wielder "
            "instantly recall any object they've touched before, no matter "
            "where it currently is."
        ),
        "color": 0x8B5A2B,
        "use_category": "text_input",
        "use_prompt": "What object do you Fetch, and from where?",
    },
    "Pig": {
        "emoji": "🐖",
        "jewel": "Pearl Anklet",
        "kwami": "Daizzi",
        "food": "cheese",
        "concept": "Jubilation",
        "phrase": "Daizzi, Rejoice!",
        "detransform": None,
        "signature_move": "Gift",
        "tool": "Tambourine",
        "description": (
            "Daizzi grants the power of Jubilation. 'Gift' lets the wielder "
            "see someone's deepest desire."
        ),
        "color": 0xFFB6C1,
        "use_category": "target_member",
        "use_prompt": "Whose deepest desire do you reveal with Gift?",
    },
}

# ------------------------------------------------------------------ #
#  Server / gameplay constants
# ------------------------------------------------------------------ #

# The exact role name that is treated as "the Guardian" of the Miracle Box.
GUARDIAN_ROLE_NAME = "Guardian"

# How long a transformation lasts, and how much warning is given (seconds).
TRANSFORM_DURATION_SECONDS = 15 * 60
TRANSFORM_WARNING_SECONDS = 2 * 60

# Canon: once the signature power is used, a ~5 minute countdown starts and
# the transformation ends when it runs out. Set CANON_POWER_COUNTDOWN = False
# to keep the plain fixed timer instead.
CANON_POWER_COUNTDOWN = True
POWER_COUNTDOWN_SECONDS = 5 * 60

# Canon: using a power tires the Kwami; they need food before the next
# transformation. (The Guardian can turn this off per server in Settings.)
# Everyone loses Kwami tiredness the moment the Kwami is fed.

# --- Unification (canon) --------------------------------------------- #
# From civilian form: kwami names + "Dual Metamorphosis!" (2) /
# "Triple Morphosis!" (3) / "Unify!" (4+).  Adding while transformed:
# the NEW kwami names + "Unify!".  Undo everything: names + "Reverse
# Morphosis!".  Release only some: released names, kept names, "Divide!".
UNIFY_PHRASES = {2: "Dual Metamorphosis!", 3: "Triple Morphosis!"}
UNIFY_ADD_PHRASE = "Unify!"
UNIFY_RELEASE_ALL_PHRASE = "Reverse Morphosis!"
UNIFY_DIVIDE_PHRASE = "Divide!"

# Names these fusions go by in the show (flavour only; everyone keeps the
# hero name they chose).
FUSION_FORMS = {
    frozenset({"Ladybug", "Dragon"}): "Dragon Bug",
    frozenset({"Ladybug", "Mouse"}): "Multibug",
    frozenset({"Ladybug", "Bee"}): "Lady Bee",
    frozenset({"Ladybug", "Horse"}): "Pegabug",
    frozenset({"Ladybug", "Horse", "Rabbit"}): "Pennybug",
    frozenset({"Ladybug", "Rabbit"}): "Bunnybug",
    frozenset({"Ladybug", "Snake"}): "Viperbug",
    frozenset({"Ladybug", "Black Cat"}): "Bug Noire",
    frozenset({"Ladybug", "Butterfly"}): "Monarch Bug",
    frozenset({"Black Cat", "Snake"}): "Snake Noir",
    frozenset({"Black Cat", "Rabbit"}): "Rabbit Noir",
    frozenset({"Black Cat", "Mouse"}): "Multinoir",
    frozenset({"Fox", "Mouse"}): "Multifox",
}

# In the show "Miraculous Ladybug!" is only ever called with the Lucky
# Charm object. True = Lucky Charm must be used first.
REQUIRE_LUCKY_CHARM_FOR_CURE = True

# --- Duels / theft ----------------------------------------------------- #
DUEL_INVITE_TIMEOUT = 120      # seconds the opponent has to accept
DUEL_ACTIVE_TIMEOUT = 15 * 60  # an accepted duel fades after this long
STEAL_RESIST_WINDOW = 60       # seconds the victim has to resist
STEAL_COOLDOWN_SECONDS = 10 * 60
STEAL_RESIST_BONUS = 25        # added to the defender's roll if they resist

# --- Misc -------------------------------------------------------------- #
HISTORY_LIMIT = 300            # entries kept in a server's Miraculous history
DEFAULT_IDLE_DAYS = 0          # 0 = never reclaim idle Miraculous
