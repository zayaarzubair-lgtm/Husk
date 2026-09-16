"""
lore.py — every word of the story, and nothing else.

The Hollow is a prison dug straight down. Its keepers take souls out of bodies
and keep what they want; the emptied bodies — husks — are bound to guard it.
You are what they threw away, riding a clay vessel, and the rest of you is
further down.

The story is never stated outright. It's carried by an intro, floor names,
boss titles and last words, whispers when you enter a room, what a body was
before you wore it, the relics, the death lines, and one ending. The deepest
thread is left for the player to put together — so if you're editing this,
keep it that way: hint, don't explain.

→ Godot: a Resource (or a CSV for localisation) read by the same call sites.
"""

import random

# ---------------------------------------------------------------------------
# before the title
# ---------------------------------------------------------------------------
INTRO = [
    "they opened you like a letter.",
    "what they wanted, they kept.",
    "the rest they threw down the hole.",
    "you landed in clay.",
    "the part of you they kept is further down.",
]
INTRO_LINE_TIME = 1.7          # s between lines appearing
INTRO_HOLD = 2.2               # s after the last line before it moves on

# ---------------------------------------------------------------------------
# floors  (name, epigraph) by depth
# ---------------------------------------------------------------------------
FLOORS = [
    ("THE INTAKE", "where they empty the new ones."),
    ("THE KENNELS", "the ones that learned to hunt were kept."),
    ("THE KEEP", "something down here is warm."),
]

# ---------------------------------------------------------------------------
# bosses, by depth. `name` is what the HUD calls the body.
# ---------------------------------------------------------------------------
class Boss:
    def __init__(self, name, intro, last_words, wears_you=False):
        self.name = name
        self.intro = intro
        self.last_words = last_words
        # The final keeper: drawn in your colour, and it won't be taken.
        self.wears_you = wears_you


BOSSES = [
    Boss("turnkey",
         "it holds the keys to the first gate. none of them are yours.",
         "its keys scatter. one of them is still warm."),
    Boss("shrike",
         "it came down the hole the way you did. it chose to stay.",
         "“go on down. it kept it warm for you.”"),
    Boss("warden",
         "it moves the way you move.",
         "",
         wears_you=True),
]
WEARS_YOU_COLOR = (184, 136, 60)   # the vessel's gold, gone dull — familiar, not identical
OCCUPIED = "OCCUPIED"

# ---------------------------------------------------------------------------
# whispers — one may surface when you walk into a room for the first time.
# They get less subtle the deeper you go.
# ---------------------------------------------------------------------------
WHISPER_CHANCE = 0.35
WHISPERS = [
    [
        "scratches on the wall count to a number, then stop.",
        "someone left a shoe.",
        "the husks here all face the stairs.",
        "a name is carved into the door. you almost know it.",
        "the drain in the floor is stained a colour you don't like.",
        "a ledger: names, weights, and a column marked KEPT.",
    ],
    [
        "the floor is worn smooth where something paced.",
        "a mirror, broken on purpose.",
        "the air smells like a room you used to sleep in.",
        "tally marks. then a drawing of a door. then nothing.",
        "you catch yourself standing the way you used to.",
        "a collar, sized for a person.",
    ],
    [
        "a smear of gold on the stone. the same colour as you.",
        "further down, something breathes in time with you.",
        "footprints the size of yours, going the other way.",
        "the ledger again. one name, crossed out, written back in.",
        "somewhere close, a heartbeat you recognise.",
        "the walls are warm here.",
    ],
]

# ---------------------------------------------------------------------------
# what a body was, before — shown when you take one
# ---------------------------------------------------------------------------
ONCE = {
    "grunt": ["a dockhand, once.", "a debtor, once.", "someone's brother, once."],
    "gunner": ["a sentry, once.", "a hunter who missed, once."],
    "turret": ["a lighthouse keeper, once.", "a man who would not leave his post, once."],
    "brute": ["a miller, once.", "a mourner, once.", "a wrestler at fairs, once."],
    "lancer": ["a poacher, once.", "a surveyor, once."],
    "detonator": ["a lamplighter, once.", "a stoker, once."],
}

# ---------------------------------------------------------------------------
# relic flavour, keyed like config.RELICS
# ---------------------------------------------------------------------------
RELIC_LINES = {
    "judgement_rounds": "the turnkey counted every shot. now you do.",
    "venom_rounds": "a thorn from the shrike's larder.",
    "split_shot": "one thought, three directions.",
    "piercing": "it does not stop for flesh. neither should you.",
    "judgement": "the turnkey's last word, still ringing.",
    "shadow_step": "the shrike's trick. it was never taught willingly.",
    "fuse_bomb": "kindling, carried carefully.",
    "seeker_rounds": "the shot knows where the husk is. it always did.",
    "shrapnel": "what breaks down here doesn't stop.",
    "battering_ram": "the clay is harder than it looks. so are you.",
    "wardens_heart": "it still beats when it's struck.",
    "killer_instinct": "the shrike never met anyone's eyes.",
    "vampiric": "every husk had a little left in it.",
    "chain_fuse": "the kindling remembers the fire.",
    "overclock": "stay half out of the body. it gets easier.",
}

# ---------------------------------------------------------------------------
# endings
# ---------------------------------------------------------------------------
DEATH_TITLE = "HOLLOWED"
DEATH_LINES = [
    "the clay cracks. the rest of you waits.",
    "you are put away, finally.",
    "somewhere below, something stops holding its breath.",
    "back to the top of the hole.",
    "the ledger gets one more line.",
]

VICTORY_TITLE = "THE KEEP IS QUIET"
VICTORY_LINES = [
    "the warden goes still.",
    "its body doesn't come apart like the others did.",
    "it's the colour of you.",
    "you step inside. it fits.",
    "",
    "behind you, the clay you left on the floor is still moving.",
]
VICTORY_LINE_TIME = 1.4        # s between ending lines appearing


def floor(depth):
    return FLOORS[min(depth, len(FLOORS) - 1)]


def boss(depth):
    return BOSSES[min(depth, len(BOSSES) - 1)]


def whisper(depth, rng: random.Random, used: set):
    """A line for a fresh room, or None. Never repeats within a run: `used`
    is the run's record of what's been said."""
    if rng.random() >= WHISPER_CHANCE:
        return None
    pool = [w for w in WHISPERS[min(depth, len(WHISPERS) - 1)] if w not in used]
    if not pool:
        return None
    line = rng.choice(pool)
    used.add(line)
    return line


def once(body_name, rng: random.Random):
    lines = ONCE.get(body_name)
    return rng.choice(lines) if lines else None


def death_line(rng: random.Random):
    return rng.choice(DEATH_LINES)
