"""
config.py — every tunable in the game, in one place.

→ Godot: each dataclass here becomes a Resource (.tres) or a block of @export
  vars on the matching scene. This module imports no game code, so it ports
  first and everything else follows it.

Rule from GAME-CONCEPT.md §4: tunables live in data objects, never hardcoded in
entities. If you find yourself typing a number inside a class in another file,
it belongs here.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Palette  ──  placeholder art is colored shapes (§5), so the palette *is* the
# art direction for now. → Godot: a theme / a set of exported colors.
# ---------------------------------------------------------------------------
class C:
    BG          = (18, 21, 28)
    FLOOR       = (27, 31, 41)
    FLOOR_ALT   = (24, 28, 37)
    GRID        = (35, 40, 54)
    WALL        = (45, 51, 66)
    WALL_EDGE   = (58, 66, 85)
    CRATE       = (68, 75, 94)
    CRATE_EDGE  = (86, 95, 118)

    TEXT        = (218, 224, 237)
    TEXT_DIM    = (120, 128, 146)
    ACCENT      = (90, 209, 192)
    GOOD        = (122, 199, 130)
    BAD         = (224, 108, 96)
    WARN        = (232, 176, 75)

    DOOR_OPEN   = (90, 209, 192)
    DOOR_SHUT   = (150, 70, 80)
    STAIRS      = (140, 210, 255)

    HEAL        = (122, 199, 130)
    UPGRADE     = (196, 150, 240)

    WITCH       = (120, 190, 255)   # slow-mo tint
    CRIT        = (255, 226, 130)
    LOCKED      = (110, 116, 132)   # the dash-trail tell for a locked dodge


# ---------------------------------------------------------------------------
# MovementStats  ──  §3.1/§3.2/§3.3. Per BODY now, not per game: possessing a
# brute should feel like driving a truck. → Godot: Resource.
# ---------------------------------------------------------------------------
@dataclass
class MovementStats:
    max_speed: float = 520.0        # px/s   top movement speed
    accel: float = 2400.0           # px/s²  how fast you reach top speed
    friction: float = 800.0         # px/s²  how fast you stop (low = drifty)
    dash_speed: float = 940.0       # px/s   speed during a dash
    dash_time: float = 0.16         # s      how long a dash lasts
    dash_cooldown: float = 0.0      # s      ~none: dash again the instant one ends
    radius: float = 16.0            # px     body radius (collision + draw)
    # ── dash-chain → perfect-dodge gating (§3.3) ──
    # These live on the body, but the CHAIN ITSELF lives on the controller —
    # see the note in possession, below.
    chain_reset_time: float = 0.9   # s  pause this long AFTER a dash to reset
    max_chain_for_perfect: int = 3  #    dashing MORE than this in a row locks


# ---------------------------------------------------------------------------
# WeaponStats  ──  §Phase 1. Every body carries one; possessing a body means
# inheriting its gun, which is most of why possession is interesting.
# ---------------------------------------------------------------------------
@dataclass
class WeaponStats:
    name: str = "pistol"
    damage: float = 10.0
    fire_rate: float = 5.0          # shots/s
    speed: float = 780.0            # px/s projectile speed
    spread_deg: float = 3.0         # cone half-angle
    pellets: int = 1
    lifetime: float = 1.4           # s before the shot expires
    knockback: float = 60.0         # px/s imparted to whatever it hits
    recoil: float = 0.0             # px/s pushed back onto the shooter
    proj_radius: float = 5.0
    color: tuple = C.WARN
    auto: bool = True               # hold to fire, vs one shot per press
    burst: int = 1                  # shots per trigger pull
    burst_gap: float = 0.08         # s between shots in a burst
    radial: bool = False            # ignore aim, fire evenly in all directions
    poison: int = 0                 # poison stacks a hit applies (PoisonStats)
    sound: str = "shot_light"       # key into audio.py's bank


# ---------------------------------------------------------------------------
# BrainStats  ──  the AI half of an archetype. Only read by AI controllers, so
# a possessed body simply stops consulting it. → Godot: Resource on the enemy.
# ---------------------------------------------------------------------------
@dataclass
class BrainStats:
    aggro_range: float = 620.0      # px  start chasing
    keep_distance: float = 0.0      # px  preferred range (0 = close the gap)
    attack_range: float = 64.0      # px  how close before committing
    telegraph_time: float = 0.45    # s   WINDUP — the perfect-dodge window lives here
    attack_time: float = 0.22       # s   the strike itself
    recover_time: float = 0.5       # s   vulnerable afterwards
    lunge_speed: float = 0.0        # px/s melee charge speed (0 = ranged attacker)
    melee_damage: float = 0.0
    melee_radius: float = 42.0
    wander_speed: float = 0.35      # fraction of max_speed when idle
    strafe: float = 0.0             # 0..1 sideways drift while engaging
    sight_line: float = 0.0         # px  laser sight drawn along a ranged windup (0 = none)
    melee_poison: int = 0           # poison stacks a melee strike applies


# ---------------------------------------------------------------------------
# BlastStats  ──  the detonator. A body with one of these doesn't shoot: pulling
# the trigger lights its fuse, and when the fuse runs out the body goes off —
# for an enemy that's its attack, for you it's spending a life as a bomb.
# ---------------------------------------------------------------------------
@dataclass
class BlastStats:
    fuse: float = 1.05              # s   countdown once lit (world time — Witch Time slows it)
    radius: float = 125.0           # px  everything hostile inside this is hit
    damage: float = 24.0
    knockback: float = 560.0
    trigger_range: float = 22.0     # px  gap between bodies that lights an enemy's fuse
    detonate_on_death: bool = True  # killed while lit → it goes off early
    beep_slow: float = 0.32         # s   between warning beeps as the fuse starts…
    beep_fast: float = 0.07         # s   …and as it runs out


# ---------------------------------------------------------------------------
# BackstabStats  ──  the assassin. Armoured everywhere except one tiny spot on
# its back, and a hit there is lethal. Its attack is a five-dash dagger combo
# with a fixed rhythm; every dash ends PAST you, so it finishes with its back
# turned — that, or a perfect dodge's slow-mo, is the opening.
# ---------------------------------------------------------------------------
@dataclass
class BackstabStats:
    weak_radius: float = 7.0        # px  the only spot that takes damage
    weak_offset: float = 0.85       #     how far behind centre, as a fraction of body radius
    combo: int = 5
    rhythm: tuple = (0.55, 0.26, 0.26, 0.42, 0.22)   # s windup before each dash
    skew_deg: tuple = (0.0, 14.0, -14.0, 24.0, 0.0)  # each dash's angle off the direct line
    overshoot: float = 150.0        # px  each dash ends this far beyond you
    strike_min: float = 0.10        # s   dash duration clamp
    strike_max: float = 0.42
    between: float = 0.05           # s   beat between a dash landing and the next windup
    exposed_time: float = 1.9       # s   dazed after the fifth dash, back turned
    lethal: bool = True             # a weak-point hit kills outright…
    weak_mult: float = 2.5          # …or, if not, deals the shot's damage × this
    front_mult: float = 0.0         # damage the armour lets through (0 = none)


# ---------------------------------------------------------------------------
# PoisonStats  ──  damage over time. It belongs to the BODY, like health: a
# body you swap out of stops being simulated, so its poison waits for you.
# ---------------------------------------------------------------------------
@dataclass
class PoisonStats:
    duration: float = 10.0          # s   a fresh application resets the clock
    dps_per_stack: float = 1.6      # hp/s per stack
    max_stacks: int = 3
    color: tuple = (140, 220, 90)


# ---------------------------------------------------------------------------
# ShrikeStats  ──  the floor-2 boss, the Shrike. The assassin's combo
# plus three more moves; it picks between them by range and cooldown.
# ---------------------------------------------------------------------------
@dataclass
class ShrikeStats:
    # dagger fan: five throws, one at a time, sweeping a fan aimed at you
    fan_count: int = 5
    fan_deg: float = 30.0           # total width of the fan
    fan_windup: float = 0.55
    fan_gap: float = 0.12           # s between throws
    fan_recover: float = 0.6
    fan_cooldown: float = 2.4
    # shadow sneak: vanish, reappear just ahead of you, stab
    sneak_fade: float = 0.42        # s gone (untouchable) — the cue that it's coming
    sneak_distance: float = 78.0    # px in front of you it reappears
    stab_windup: float = 0.38       # s — THE dodge window for this move
    stab_time: float = 0.14
    stab_recover: float = 1.4       # s, back turned — the opening
    stab_damage: float = 30.0
    stab_poison: int = 2
    sneak_cooldown: float = 5.0
    # summon: marks spots on the floor, then detonators climb out of them
    summon_min: int = 2
    summon_max: int = 4
    summon_windup: float = 0.9
    summon_recover: float = 0.5
    summon_cooldown: float = 9.0
    summon_cap: int = 6             # live summons, max
    summon_min_dist: float = 200.0  # px from you, so they can't pop out on top of you
    # under half health
    enrage_at: float = 0.5
    enrage_speed: float = 0.8       # multiplier on windups and cooldowns — never on the dazes


# ---------------------------------------------------------------------------
# BodyStats  ──  one controllable body. THE key type for §3.5: player, party
# member and enemy are all just a BodyStats + a controller.
# ---------------------------------------------------------------------------
@dataclass
class BodyStats:
    name: str
    max_health: float
    color: tuple
    movement: MovementStats
    weapon: WeaponStats
    brain: BrainStats = field(default_factory=BrainStats)
    possessable: bool = True
    score: int = 10
    # drawn as a ring count above the body so you can read a fight at a glance
    threat: int = 1
    elite: bool = False             # set on a spawn's private copy, never a template
    pack: tuple = (1, 1)            # spawns arrive as a group of this many (min, max)
    blast: BlastStats = None        # detonator: the trigger lights a fuse instead of firing
    shrike: ShrikeStats = None      # the Shrike's extra moves
    display: str = ""               # shown name, if it differs from the key
    backstab: BackstabStats = None  # assassin: only the weak point on its back takes damage

    @property
    def title(self) -> str:
        name = self.display or self.name
        return f"elite {name}" if self.elite else name


# ---------------------------------------------------------------------------
# Archetypes. Each is a body you can END UP PLAYING, so every one of them is
# balanced as a player character as well as an enemy.
# ---------------------------------------------------------------------------

VESSEL = BodyStats(
    name="vessel",
    max_health=100.0,
    color=(232, 176, 75),
    movement=MovementStats(),                       # the §3.1 numbers, untouched
    weapon=WeaponStats(name="sidearm", damage=11.0, fire_rate=6.0, speed=820.0,
                       spread_deg=2.5, knockback=70.0, color=(244, 213, 138),
                       sound="shot_light"),
    possessable=False,                              # it's you; nothing to possess
)

GRUNT = BodyStats(
    name="grunt",
    max_health=38.0,
    color=(203, 89, 84),
    movement=MovementStats(max_speed=430.0, accel=2100.0, friction=900.0,
                           dash_speed=880.0, dash_time=0.15, radius=15.0),
    # as a player body: a short-range shotgun. Fast and fragile.
    weapon=WeaponStats(name="shiv-burst", damage=6.0, fire_rate=2.6, speed=660.0,
                       spread_deg=15.0, pellets=4, lifetime=0.34, knockback=90.0,
                       proj_radius=4.0, color=(240, 140, 130),
                       sound="shot_shotgun"),
    brain=BrainStats(aggro_range=640.0, attack_range=88.0, telegraph_time=0.42,
                     attack_time=0.20, recover_time=0.45, lunge_speed=1020.0,
                     melee_damage=12.0, melee_radius=44.0, wander_speed=0.35),
    score=10, threat=1,
)

GUNNER = BodyStats(
    name="gunner",
    max_health=30.0,
    color=(150, 120, 205),
    movement=MovementStats(max_speed=380.0, accel=1700.0, friction=1100.0,
                           dash_speed=820.0, dash_time=0.17, radius=15.0),
    weapon=WeaponStats(name="burst-rifle", damage=9.0, fire_rate=1.5, speed=700.0,
                       spread_deg=4.0, lifetime=1.6, knockback=50.0,
                       burst=3, burst_gap=0.09, color=(186, 156, 240),
                       sound="shot_burst"),
    brain=BrainStats(aggro_range=760.0, keep_distance=300.0, attack_range=520.0,
                     telegraph_time=0.5, attack_time=0.3, recover_time=0.8,
                     wander_speed=0.3, strafe=0.55),
    score=14, threat=1,
)

TURRET = BodyStats(
    name="turret",
    max_health=54.0,
    color=(80, 170, 180),
    movement=MovementStats(max_speed=150.0, accel=700.0, friction=1400.0,
                           dash_speed=520.0, dash_time=0.2, radius=19.0),
    weapon=WeaponStats(name="spiral", damage=7.0, fire_rate=0.85, speed=330.0,
                       spread_deg=0.0, pellets=9, lifetime=2.6, knockback=30.0,
                       proj_radius=6.0, radial=True, color=(120, 215, 225),
                       sound="shot_radial"),
    brain=BrainStats(aggro_range=900.0, keep_distance=9999.0, attack_range=820.0,
                     telegraph_time=0.65, attack_time=0.25, recover_time=1.0,
                     wander_speed=0.0),
    score=18, threat=2,
)

BRUTE = BodyStats(
    name="brute",
    max_health=120.0,
    color=(190, 120, 70),
    movement=MovementStats(max_speed=300.0, accel=1000.0, friction=520.0,
                           dash_speed=1100.0, dash_time=0.26, radius=25.0),
    weapon=WeaponStats(name="slugger", damage=26.0, fire_rate=1.1, speed=560.0,
                       spread_deg=1.5, lifetime=1.8, knockback=260.0, recoil=110.0,
                       proj_radius=9.0, color=(240, 170, 110),
                       sound="shot_heavy"),
    brain=BrainStats(aggro_range=700.0, attack_range=150.0, telegraph_time=0.72,
                     attack_time=0.34, recover_time=0.85, lunge_speed=1180.0,
                     melee_damage=24.0, melee_radius=62.0, wander_speed=0.25),
    score=30, threat=3,
)

# The lancer is a sniper, and the game's cleanest perfect-dodge teacher: its
# windup paints a laser along the exact line the shot will take (the aim is
# frozen for the whole telegraph, see ai.py). Step off the line, or dash
# through the shot at the last moment. As a player body: a slow, heavy rifle
# that rewards aim over volume.
LANCER = BodyStats(
    name="lancer",
    max_health=34.0,
    color=(96, 190, 120),
    movement=MovementStats(max_speed=400.0, accel=1900.0, friction=1000.0,
                           dash_speed=900.0, dash_time=0.16, radius=15.0),
    weapon=WeaponStats(name="longshot", damage=22.0, fire_rate=0.9, speed=1250.0,
                       spread_deg=0.5, lifetime=1.2, knockback=150.0, recoil=40.0,
                       proj_radius=5.0, auto=False, color=(170, 240, 180),
                       sound="shot_rail"),
    brain=BrainStats(aggro_range=900.0, keep_distance=440.0, attack_range=760.0,
                     telegraph_time=0.85, attack_time=0.2, recover_time=1.1,
                     wander_speed=0.25, strafe=0.4, sight_line=900.0),
    score=20, threat=2,
)

# The detonator is a swarm body: small, quick, fragile, and it comes in packs.
# Touch it and it roots itself and counts down; the ring it draws is the blast.
# Get out, or dash out on the last beat for a perfect dodge. As a player body
# it's a bomb you drive: the trigger lights the fuse, and it costs you the body.
DETONATOR = BodyStats(
    name="detonator",
    max_health=16.0,
    color=(236, 96, 176),
    movement=MovementStats(max_speed=470.0, accel=2600.0, friction=1200.0,
                           dash_speed=900.0, dash_time=0.14, radius=12.0),
    # never fires — the trigger lights the fuse (Actor._shoot). The stats are
    # here because every body carries a weapon.
    weapon=WeaponStats(name="fuse", damage=0.0, fire_rate=1.0, auto=False,
                       color=(255, 150, 210), sound="fuse"),
    brain=BrainStats(aggro_range=720.0, attack_range=0.0, wander_speed=0.45),
    blast=BlastStats(),
    pack=(3, 5),
    score=6, threat=1,
)

# The assassin can't be possessed: it has no weakened state to take — one clean
# hit to the back and it's dead.
ASSASSIN = BodyStats(
    name="assassin",
    max_health=40.0,
    color=(70, 80, 110),
    movement=MovementStats(max_speed=430.0, accel=2400.0, friction=1300.0,
                           dash_speed=1000.0, dash_time=0.14, radius=15.0),
    weapon=WeaponStats(name="dagger", damage=0.0, fire_rate=1.0, auto=False,
                       color=(200, 210, 235), sound="slash"),
    brain=BrainStats(aggro_range=820.0, keep_distance=260.0, attack_range=380.0,
                     telegraph_time=0.55, attack_time=0.3, recover_time=0.05,
                     lunge_speed=1500.0, melee_damage=14.0, melee_radius=30.0,
                     wander_speed=0.3, strafe=0.8),
    backstab=BackstabStats(),
    possessable=False, score=40, threat=3,
)

# The floor-2 boss. Every hit that isn't on its back glances off, like its
# smaller kin — but a back hit wounds rather than kills.
SHRIKE = BodyStats(
    name="shrike",
    display="shrike",
    max_health=520.0,
    color=(58, 50, 96),
    movement=MovementStats(max_speed=460.0, accel=2600.0, friction=1400.0,
                           dash_speed=1050.0, dash_time=0.14, radius=22.0),
    weapon=WeaponStats(name="fan-daggers", damage=8.0, fire_rate=10.0, speed=640.0,
                       spread_deg=0.0, lifetime=1.7, knockback=70.0, proj_radius=5.0,
                       auto=False, poison=1, color=(150, 230, 110),
                       sound="dagger_throw"),
    brain=BrainStats(aggro_range=4000.0, keep_distance=300.0, attack_range=400.0,
                     telegraph_time=0.5, attack_time=0.3, recover_time=0.05,
                     lunge_speed=1550.0, melee_damage=16.0, melee_radius=38.0,
                     wander_speed=0.3, strafe=0.9),
    backstab=BackstabStats(weak_radius=9.0, weak_offset=0.8, lethal=False,
                           weak_mult=2.0, front_mult=0.2, rhythm=(0.5, 0.24, 0.24, 0.38, 0.2),
                           exposed_time=1.8),
    shrike=ShrikeStats(),
    possessable=False, score=300, threat=5,
)

# The boss is the one body you can't take. Flavour: too strong-willed to hollow.
# Mechanically: possessing it would trivialise the floor you just fought through.
WARDEN = BodyStats(
    name="warden",
    max_health=520.0,
    color=(215, 70, 90),
    movement=MovementStats(max_speed=330.0, accel=1300.0, friction=700.0,
                           dash_speed=1250.0, dash_time=0.3, radius=38.0),
    weapon=WeaponStats(name="judgement", damage=12.0, fire_rate=1.0, speed=460.0,
                       spread_deg=0.0, pellets=13, lifetime=3.0, knockback=90.0,
                       proj_radius=8.0, radial=True, color=(255, 120, 140),
                       sound="shot_radial"),
    brain=BrainStats(aggro_range=4000.0, attack_range=190.0, telegraph_time=0.6,
                     attack_time=0.36, recover_time=0.7, lunge_speed=1320.0,
                     melee_damage=28.0, melee_radius=86.0, wander_speed=0.4,
                     strafe=0.3),
    possessable=False, score=250, threat=5,
)

# Spawn table per floor depth (0-indexed). Weights, not counts.
# A detonator pick brings a whole pack (BodyStats.pack), so its weight is low.
SPAWN_TABLE = [
    {"grunt": 6, "gunner": 3, "turret": 1, "brute": 0, "lancer": 1, "detonator": 2, "assassin": 0},
    {"grunt": 5, "gunner": 4, "turret": 2, "brute": 1, "lancer": 2, "detonator": 2, "assassin": 1},
    {"grunt": 4, "gunner": 3, "turret": 3, "brute": 3, "lancer": 2, "detonator": 3, "assassin": 2},
]
MAX_ROOM_ENEMIES = 14
BOSS_BY_DEPTH = ("warden", "shrike", "warden")
ARCHETYPES = {b.name: b for b in (VESSEL, GRUNT, GUNNER, TURRET, BRUTE, LANCER,
                                  DETONATOR, ASSASSIN, SHRIKE, WARDEN)}


# ---------------------------------------------------------------------------
# EliteStats  ──  Phase 7. A tougher cut of a normal archetype, rolled at floor
# generation. The stats are written to the spawn's PRIVATE body, so an elite
# you possess stays elite — the reason to go hunting for the gold ring.
# ---------------------------------------------------------------------------
@dataclass
class EliteStats:
    chance_by_depth: tuple = (0.0, 0.12, 0.22)   # per combat spawn
    health_mult: float = 1.8
    damage_mult: float = 1.3
    speed_mult: float = 1.1
    radius_mult: float = 1.15
    telegraph_mult: float = 0.85    # a quicker tell, never a missing one
    fire_rate_mult: float = 1.15
    score_mult: float = 2.5
    drop_chance: float = 1.0        # health drop on kill (replaces the normal roll)
    color: tuple = (255, 214, 110)  # the ring that marks one


# ---------------------------------------------------------------------------
# CombatStats  ──  damage-side globals.
# ---------------------------------------------------------------------------
@dataclass
class CombatStats:
    player_invuln: float = 0.65     # s of i-frames after taking a hit
    enemy_invuln: float = 0.05      # s — just enough to stop one shot double-dipping
    contact_cooldown: float = 0.7   # s between touch-damage ticks from one enemy
    hit_stop: float = 0.045         # s of freeze-frame when you land a hit
    crit_hit_stop: float = 0.11     # s of freeze-frame on a Witch Time crit
    shake_on_hurt: float = 9.0
    shake_on_kill: float = 4.0


# ---------------------------------------------------------------------------
# WitchTimeStats  ──  §3.4. These are the answers to the doc's open questions.
#
#   "What counts as frame-perfect?"  →  perfect_window, below. Physics runs at
#   60Hz (§4), so one tick is 16.7ms; anything under ~3 ticks is a coin flip
#   once input timing is quantised to the render frame. 0.13s ≈ 8 ticks, which
#   is the action-game norm and is generous enough to learn but tight enough to
#   miss when you panic.
#
#   "Does the counter need a specific input?"  →  no. Everything you do during
#   Witch Time crits. Adding a counter button would punish players twice for
#   one hard read.
#
#   "How long is the slow-mo?"  →  duration, below — long enough to cross a
#   room and empty a clip, short enough that you can't farm it.
# ---------------------------------------------------------------------------
@dataclass
class WitchTimeStats:
    perfect_window: float = 0.13    # s before impact that a dash counts as perfect
    duration: float = 1.15          # s of slow-mo (real time)
    world_scale: float = 0.22       # delta multiplier for everything but you
    player_scale: float = 0.88      # delta multiplier for you (§3.4: near-full)
    crit_multiplier: float = 3.0
    dodge_iframes: float = 0.3      # s of grace on a successful read
    refund_chain: bool = True       # a perfect dodge clears your dash chain


# ---------------------------------------------------------------------------
# PossessionStats  ──  §3.5. The doc left three questions open; these are the
# calls this build makes. All three are one-line reversible.
#
#   "Fixed roster or acquired at runtime?"  →  BOTH, resolved as: a party you
#   BUILD by possessing. You start as the vessel and carry up to max_roster
#   bodies. Your roster IS your health pool — when the body you're driving
#   dies you fall into the next one, and the run ends only when the last one
#   does. Possession is therefore how you heal, which is what makes walking
#   into a weakened enemy at point-blank range worth the risk.
#
#   "What carries over on swap?"  →  health, weapon and movement belong to the
#   BODY. The dash chain and the perfect-dodge lock belong to YOU and follow
#   you across bodies (see PlayerController). That's deliberate: the chain
#   measures the player's restraint, not the body's, and if it reset on swap
#   then swapping would launder a locked dodge and §3.3 would collapse.
#
#   "Is there a cost, and does it tie into the momentum theme?"  →  yes, and
#   yes: possession costs you all forward momentum (you arrive stationary) plus
#   a lockout, so it's a commitment you make out of a safe position, never a
#   dodge. Swapping to a body you already own is cheap and fast — that one is
#   meant to be used mid-fight.
# ---------------------------------------------------------------------------
@dataclass
class PossessionStats:
    weaken_fraction: float = 0.3    # ≤ this much HP left → possessable
    weaken_duration: float = 6.0    # s the window stays open once it opens
    possess_range: float = 96.0     # px  you must be this close
    possess_time: float = 0.28      # s   channel; you're invulnerable during it
    possess_cooldown: float = 0.8   # s
    possess_heal: float = 0.55      # fraction of max HP the taken body arrives at
    swap_cooldown: float = 0.55     # s
    swap_invuln: float = 0.45       # s of grace so swapping can save you
    max_roster: int = 3
    husk_decay: float = 0.0         # reserved: 0 = a spent body is simply gone


# ---------------------------------------------------------------------------
# DungeonStats  ──  Phase 5. Room-based like Soul Knight: doors lock, you clear,
# doors open. → Godot: each room is a scene, the grid is a resource.
# ---------------------------------------------------------------------------
@dataclass
class DungeonStats:
    room_w: int = 1280
    room_h: int = 860
    grid_w: int = 6
    grid_h: int = 5
    rooms_per_floor: tuple = (7, 9, 11)   # by depth
    door_width: int = 150
    wall_thickness: int = 26
    floors: int = 3                       # clear this many and you win
    enemies_base: int = 3                 # per combat room at depth 0
    enemies_per_depth: float = 1.6
    obstacle_min: int = 2
    obstacle_max: int = 6
    health_drop_chance: float = 0.16
    health_drop_amount: float = 22.0


# ---------------------------------------------------------------------------
# Upgrades handed out in treasure rooms. (label, apply_fn) — apply_fn mutates
# the run's permanent modifiers, which are re-applied to every body you take.
# ---------------------------------------------------------------------------
UPGRADES = [
    ("VITALITY",  "+25% max health",     lambda m: m.__setitem__("health_mult", m["health_mult"] + 0.25)),
    ("MALICE",    "+20% damage",         lambda m: m.__setitem__("damage_mult", m["damage_mult"] + 0.20)),
    ("HASTE",     "+18% fire rate",      lambda m: m.__setitem__("fire_mult",   m["fire_mult"] + 0.18)),
    ("MOMENTUM",  "+12% move speed",     lambda m: m.__setitem__("speed_mult",  m["speed_mult"] + 0.12)),
    ("HOLLOW",    "+1 body slot",        lambda m: m.__setitem__("roster_bonus", m["roster_bonus"] + 1)),
    ("PATIENCE",  "+1 dash before lock", lambda m: m.__setitem__("chain_bonus",  m["chain_bonus"] + 1)),
]

# ---------------------------------------------------------------------------
# Relics  ──  boss rewards. Beat a boss that isn't the last and you choose one
# of three: a WEAPON mod, an ABILITY (on F) or a PASSIVE. Each is a real stat
# jump plus a gimmick. Like upgrades they belong to the player, not the body,
# so they work in anything you wear. The effects live in relics.py; every
# number they use lives here.
# ---------------------------------------------------------------------------
@dataclass
class RelicStats:
    # weapon mods
    echo_every: int = 5             # every Nth volley…
    echo_count: int = 10            # …also fires a ring of this many
    echo_damage: float = 0.5        # × the weapon's damage
    split_angle: float = 13.0       # deg — two extra shots either side
    split_damage: float = 0.55
    pierce: int = 2                 # enemies a shot passes through
    pierce_speed: float = 1.3
    venom_stacks: int = 1
    # passives
    heart_count: int = 10           # the ring you answer a hit with
    heart_damage: float = 12.0
    instinct_mult: float = 2.0      # shots into an enemy's back
    instinct_dot: float = 0.35      # how "behind" counts (shot dir · its facing)
    vamp_heal: float = 4.0
    chain_radius: float = 95.0
    chain_damage: float = 16.0
    overclock_duration: float = 1.5 # × Witch Time
    overclock_window: float = 0.04  # s added to the perfect-dodge window
    # abilities
    nova_count: int = 16
    nova_damage: float = 16.0
    nova_speed: float = 600.0
    nova_knockback: float = 260.0
    nova_cooldown: float = 7.0
    step_range: float = 480.0       # px — how far you can blink
    step_cone: float = 40.0         # deg either side of your aim it looks for a target
    step_gap: float = 26.0          # px behind the target you land
    step_invuln: float = 0.35
    step_crit_time: float = 1.3     # s your shots crit after landing
    step_cooldown: float = 6.0
    bomb_range: float = 380.0
    bomb_speed: float = 760.0
    bomb_fuse: float = 0.6
    bomb_radius: float = 120.0
    bomb_damage: float = 48.0
    bomb_cooldown: float = 5.0
    # timed abilities: F starts a buff, the cooldown runs from the press
    buff_time: float = 5.0
    seeker_turn: float = 540.0      # deg/s a seeking shot can turn
    seeker_range: float = 560.0     # px it looks for a target
    seeker_cooldown: float = 12.0
    shrapnel_count: int = 4         # fragments per hit, in an X
    shrapnel_damage: float = 0.45   # × the shot that burst
    shrapnel_speed: float = 0.85
    shrapnel_life: float = 0.45
    shrapnel_cooldown: float = 12.0
    ram_damage: float = 34.0        # to them
    ram_self: float = 6.0           # to you (never below 1 hp)
    ram_reach: float = 8.0          # px of slack on contact
    ram_knockback: float = 520.0
    ram_cooldown: float = 10.0


@dataclass
class Relic:
    key: str
    name: str
    kind: str                       # "weapon" | "ability" | "passive"
    boost: str                      # the stat line, as shown
    gimmick: str                    # the fun part, as shown
    mods: dict                      # added to the run modifiers on pickup
    bosses: tuple = ()              # who drops it; () = any boss


RELICS = [
    # -- weapon mods --
    Relic("judgement_rounds", "JUDGEMENT ROUNDS", "weapon", "+20% damage",
          "every 5th volley also fires a ring of 10 shots",
          {"damage_mult": 0.20}, ("warden",)),
    Relic("venom_rounds", "VENOM ROUNDS", "weapon", "+20% fire rate",
          "your shots poison enemies",
          {"fire_mult": 0.20}, ("shrike",)),
    Relic("split_shot", "SPLIT SHOT", "weapon", "+10% damage",
          "every shot fires two more at an angle",
          {"damage_mult": 0.10}),
    Relic("piercing", "PIERCING ROUNDS", "weapon", "+15% damage",
          "shots fly faster and pass through 2 enemies",
          {"damage_mult": 0.15}),
    # -- abilities (one slot; a new one replaces the old) --
    Relic("judgement", "JUDGEMENT", "ability", "+20% max health",
          "[F] a ring of 16 heavy shots (7s)",
          {"health_mult": 0.20}, ("warden",)),
    Relic("shadow_step", "SHADOW STEP", "ability", "+12% move speed",
          "[F] blink behind the enemy you aim at; your shots crit briefly (6s)",
          {"speed_mult": 0.12}, ("shrike",)),
    Relic("fuse_bomb", "FUSE BOMB", "ability", "+15% damage",
          "[F] lob a bomb at your cursor (5s)",
          {"damage_mult": 0.15}),
    Relic("seeker_rounds", "SEEKER ROUNDS", "ability", "+15% fire rate",
          "[F] for 5s your shots curve into the nearest enemy (12s)",
          {"fire_mult": 0.15}),
    Relic("shrapnel", "SHRAPNEL", "ability", "+15% damage",
          "[F] for 5s every shot that hits bursts into 4 more (12s)",
          {"damage_mult": 0.15}),
    Relic("battering_ram", "BATTERING RAM", "ability", "+20% max health",
          "[F] for 5s your dashes slam into enemies — hurting you a little, "
          "them a lot — until your dodge locks (10s)",
          {"health_mult": 0.20}),
    # -- passives --
    Relic("wardens_heart", "TURNKEY'S HEART", "passive", "+40% max health",
          "when you're hit, you answer with a ring of shots",
          {"health_mult": 0.40}, ("warden",)),
    Relic("killer_instinct", "KILLER INSTINCT", "passive", "+25% damage",
          "shots into an enemy's back deal double",
          {"damage_mult": 0.25}, ("shrike",)),
    Relic("vampiric", "VAMPIRIC", "passive", "+10% damage",
          "every kill heals 4",
          {"damage_mult": 0.10}),
    Relic("chain_fuse", "CHAIN FUSE", "passive", "+15% fire rate",
          "enemies you kill explode",
          {"fire_mult": 0.15}),
    Relic("overclock", "OVERCLOCK", "passive", "+15% move speed",
          "Witch Time lasts 50% longer and is easier to trigger",
          {"speed_mult": 0.15}),
]
RELICS_BY_KEY = {r.key: r for r in RELICS}
RELIC_COLORS = {"weapon": (255, 170, 90), "ability": (120, 190, 255),
                "passive": (196, 150, 240)}


def fresh_modifiers() -> dict:
    """The run-scoped multipliers upgrades feed into. Applied on top of any
    body you possess, so upgrades follow the player, not the corpse."""
    return {
        "health_mult": 1.0,
        "damage_mult": 1.0,
        "fire_mult": 1.0,
        "speed_mult": 1.0,
        "roster_bonus": 0,
        "chain_bonus": 0,
        "relics": [],               # keys, in the order you took them
        "ability": None,            # the relic key on F, if any
    }


# ---------------------------------------------------------------------------
# AssistStats  ──  aim assist. A trackpad (and, later, a thumbstick) can't hold
# a 9px weak point on a moving body, so a shot that would narrowly miss is
# nudged onto its target. It never turns a wild shot into a hit.
# ---------------------------------------------------------------------------
@dataclass
class AssistStats:
    enabled: bool = True            # default; T toggles it in game
    reach_px: float = 40.0          # how far off-target (at the target's range) still counts
    max_deg: float = 12.0           # …capped, so point-blank shots don't swing wildly
    range: float = 850.0            # px — beyond this, no help


# ---------------------------------------------------------------------------
# Engine-level constants.
# ---------------------------------------------------------------------------
PHYSICS_FPS = 60
PHYSICS_DELTA = 1.0 / PHYSICS_FPS
RENDER_FPS_CAP = 144
MAX_FRAME = 0.05                 # spiral-of-death guard
VIEWPORT = (1120, 700)

INPUT_BUFFER_TIME = 0.12         # s — see inputs.py
