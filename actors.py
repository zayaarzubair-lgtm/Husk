"""
actors.py — Actor: the one entity template every controllable body uses.

§3.5 / §4, the load-bearing idea of the whole codebase:

    Player, party member and enemy are THE SAME CLASS. The only difference is
    which Controller is plugged into `.controller`. "Swapping" and "possessing"
    are therefore not special mechanics — they're an assignment:

        a.controller, b.controller = b.controller, a.controller

→ Godot: Actor is a CharacterBody2D scene (Sprite2D + CollisionShape2D +
  a `controller` child node). `velocity` is built in there; everything from
  `resolve_circle_rects` down is replaced by move_and_slide().
"""

import copy
import math
import pygame
from pygame.math import Vector2
from dataclasses import dataclass, field

from .core import (Entity, Layer, Signal, move_toward, from_angle,
                   resolve_circle_rects, shade, tint, clamp, lerp)
from .config import (C, CombatStats, PossessionStats, WitchTimeStats, EliteStats,
                     PoisonStats)
from . import weapons, art

COMBAT = CombatStats()
POSSESS = PossessionStats()
WITCH = WitchTimeStats()
ELITE = EliteStats()
POISON = PoisonStats()


# ---------------------------------------------------------------------------
# Intent  ──  what a controller wants the body to do this tick. Keeping this as
# data (rather than controllers calling actor methods) is what lets any
# controller drive any body. → Godot: a small RefCounted, or just out-params.
# ---------------------------------------------------------------------------
@dataclass
class Intent:
    move: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    aim: float = 0.0
    dash: bool = False
    fire: bool = False
    # Possession and swapping are deliberately NOT here: they don't act on a
    # body, they rearrange which controller drives which body. The player
    # controller asks the level for them directly (ctx.request_possess()).


class Controller:
    """Base. Subclasses: PlayerController (inputs.py-driven) and the AI brains."""
    is_player = False

    def decide(self, actor, delta, ctx) -> Intent:
        return Intent()

    def notify_dash(self, actor, ctx):
        pass

    def notify_possessed(self, actor):
        pass

    # Read by the perfect-dodge detector and the HUD. Bodies don't own this —
    # the PLAYER does — so it lives on the controller and rides along on a swap.
    perfect_dodge_locked = False


# ---------------------------------------------------------------------------
# Actor
# ---------------------------------------------------------------------------
class Actor(Entity):
    def __init__(self, pos, body, faction="enemy", mods=None):
        super().__init__(pos, body.movement.radius,
                         Layer.PLAYER if faction == "player" else Layer.ENEMY)
        # Every actor owns a PRIVATE copy of its archetype. The entries in
        # config.py are templates, and things like the Warden's enrage or a
        # per-floor difficulty scale write to these stats — mutating the shared
        # template would leak those changes into every later spawn and every
        # later run.
        self.body = copy.deepcopy(body)
        self.faction = faction
        self.mods = mods
        self.controller = Controller()

        self.max_health = self._scaled_max_health()
        self.health = self.max_health

        self.aim = 0.0
        self.facing = Vector2(1, 0)

        # dash (§3.2)
        self._dash_t = 0.0
        self._dash_cd = 0.0
        self._dash_dir = Vector2(1, 0)
        self.trail = []                  # [(Vector2, age)] — the §3.4 visual tell

        # weapon
        self._fire_cd = 0.0
        self._burst_left = 0
        self._burst_t = 0.0
        self._muzzle_t = 0.0

        # melee attack FSM — driven by brains, read by draw() and by the
        # perfect-dodge detector. Lives on the BODY so a possessed enemy could
        # in principle use its own swipe.
        self.attack_phase = ""           # "" | "windup" | "strike" | "recover"
        self.attack_kind = "melee"       # "melee" (lunge + hitbox) | "shot" (volley)
        self.attack_t = 0.0
        self.attack_dir = Vector2(1, 0)
        self._melee_spent = False
        # Per-attack overrides a brain may set right after begin_attack() — the
        # assassin's combo varies its rhythm dash by dash. None = BrainStats.
        self.windup_time = 0.0
        self.strike_time = None
        self.recover_time = None
        self.attack_damage = None
        self.attack_poison = None
        self.fan_offsets = ()            # degrees — drawn as sight lines on a windup
        self.summon_points = []          # world points — drawn as marks on a windup
        self.summoner = None             # the boss that called this body in, if any
        self.occupied = False            # lore: a body something else won't give up

        self.anim_t = 0.0                # drives sprite frames; world time, so slow-mo slows it

        # status
        self.poison_t = 0.0
        self.poison_stacks = 0
        self._poison_shown = 0.0         # drained hp not yet shown as a number

        # detonator (BlastStats)
        self._detonated = False
        self._beep_t = 0.0
        self._beep_flash = 0.0

        # damage state
        self.invuln_t = 0.0
        self.flash = 0.0
        self.stagger = 0.0               # brief control loss on a big hit
        self.knock = Vector2(0, 0)

        # possession (§3.5)
        self.weaken_t = 0.0              # >0 while the take-me window is open
        self.possess_channel = 0.0

        # signals (§4)
        self.on_dash = Signal()
        self.on_hurt = Signal()
        self.on_died = Signal()
        self.on_fired = Signal()
        self.on_weakened = Signal()
        self.on_attack = Signal()    # emitted when a windup begins (the dodge cue)
        self.on_poisoned = Signal()
        self.on_poison_tick = Signal()   # (actor, amount) every few hp drained

    # -- derived stats -------------------------------------------------------
    def _scaled_max_health(self):
        m = self.mods["health_mult"] if self.mods else 1.0
        return self.body.max_health * m

    @property
    def stats(self):
        return self.body.movement

    @property
    def weapon(self):
        return self.body.weapon

    @property
    def max_speed(self):
        m = self.mods["speed_mult"] if self.mods else 1.0
        return self.stats.max_speed * m

    @property
    def damage_mult(self):
        return self.mods["damage_mult"] if self.mods else 1.0

    @property
    def fire_interval(self):
        m = self.mods["fire_mult"] if self.mods else 1.0
        return 1.0 / max(0.05, self.weapon.fire_rate * m)

    @property
    def dashing(self) -> bool:
        return self._dash_t > 0

    @property
    def dash_ready(self) -> bool:
        return self._dash_cd <= 0 and self._dash_t <= 0 and self.stagger <= 0

    @property
    def armed(self) -> bool:
        """A detonator with its fuse lit."""
        return self.attack_kind == "blast" and self.attack_phase == "windup"

    @property
    def vanished(self) -> bool:
        """Mid shadow-sneak: gone, and nothing can touch it."""
        return self.attack_kind == "vanish" and self.attack_phase == "windup"

    @property
    def strike_duration(self) -> float:
        return self.strike_time if self.strike_time is not None else self.body.brain.attack_time

    @property
    def weak_point(self):
        """The assassin's back — the only place it can be hurt. None for
        bodies without one."""
        bs = self.body.backstab
        if bs is None:
            return None
        return self.position - from_angle(self.aim) * (self.radius * bs.weak_offset)

    @property
    def fire_ready(self) -> bool:
        return (self._fire_cd <= 0.0 and self._burst_left <= 0 and self.stagger <= 0
                and self.attack_phase != "windup")

    @property
    def health_frac(self) -> float:
        return clamp(self.health / self.max_health, 0.0, 1.0) if self.max_health else 0.0

    @property
    def possessable(self) -> bool:
        """The take-me window: hurt badly enough, recently enough, and not the
        kind of thing that can be taken at all."""
        return (self.alive and self.body.possessable and self.faction == "enemy"
                and self.weaken_t > 0.0)

    def set_modifiers(self, mods):
        """Run upgrades follow the PLAYER, not the corpse — so they're applied
        fresh to whatever body you're currently wearing."""
        self.mods = mods
        frac = self.health_frac
        self.max_health = self._scaled_max_health()
        self.health = self.max_health * frac

    # -- physics -------------------------------------------------------------
    def physics_process(self, delta: float, ctx):
        if not self.alive:
            return

        self._tick_timers(delta)
        self.anim_t += delta
        if self.poison_t > 0.0:
            self._tick_poison(delta, ctx)
            if not self.alive:
                return
        if self.armed:
            self._burn_fuse(delta, ctx)
            if not self.alive:
                return
        intent = self.controller.decide(self, delta, ctx)

        if self.possess_channel > 0.0:
            # Mid-possession: locked in place, untouchable. The cost of taking a
            # body is that you arrive with no momentum (§3.5 config note).
            self.velocity *= max(0.0, 1.0 - 12.0 * delta)
            self._integrate(delta, ctx)
            return

        self.aim = intent.aim
        if self.stagger <= 0:
            self._maybe_dash(intent, ctx)

        self._move(intent, delta)
        self._shoot(intent, delta, ctx)
        self._resolve_melee(ctx)
        self._integrate(delta, ctx)
        self._push_trail(delta)

    def _tick_timers(self, delta):
        self._dash_cd = max(0.0, self._dash_cd - delta)
        self._fire_cd = max(0.0, self._fire_cd - delta)
        self._muzzle_t = max(0.0, self._muzzle_t - delta)
        self.invuln_t = max(0.0, self.invuln_t - delta)
        self.flash = max(0.0, self.flash - delta)
        self.stagger = max(0.0, self.stagger - delta)
        self.possess_channel = max(0.0, self.possess_channel - delta)
        self._beep_flash = max(0.0, self._beep_flash - delta)
        if self.weaken_t > 0.0:
            self.weaken_t -= delta
            if self.weaken_t <= 0.0:
                # The window closed. It steels itself back above the threshold —
                # take the opening promptly or fight it the hard way.
                self.health = max(self.health, self.max_health * (POSSESS.weaken_fraction + 0.15))

    def _maybe_dash(self, intent, ctx):
        # `dash_ready and intent.dash` — the press stays buffered while a dash is
        # in flight and fires the tick that one ends (see inputs.py).
        if not (intent.dash and self.dash_ready):
            return
        d = intent.move if intent.move.length() > 0.1 else from_angle(self.aim)
        if d.length() < 0.001:
            return
        self._dash_dir = d.normalize()
        self._dash_t = self.stats.dash_time
        self._dash_cd = self.stats.dash_cooldown
        # Chain bookkeeping + the §3.4 perfect-dodge read both live with the
        # PLAYER, not the body, so they ride along when you swap.
        self.controller.notify_dash(self, ctx)
        self.on_dash.emit(self)

    def _move(self, intent, delta):
        if self._dash_t > 0:
            self._dash_t -= delta
            self.velocity = self._dash_dir * self.stats.dash_speed
        elif (self.attack_phase == "strike" and self.attack_kind == "melee"
              and self.body.brain.lunge_speed > 0):
            self.velocity = self.attack_dir * self.body.brain.lunge_speed
        elif self.attack_phase == "windup":
            self.velocity = move_toward(self.velocity, Vector2(0, 0),
                                        self.stats.friction * 2.2 * delta)
        elif self.stagger > 0:
            self.velocity = move_toward(self.velocity, Vector2(0, 0),
                                        self.stats.friction * delta)
        else:
            # The core feel (§3.1): ease toward target, ease to zero when idle.
            # In Godot this is one line:
            #   velocity = velocity.move_toward(target, accel * delta)
            move = intent.move
            target = move * self.max_speed
            if move.length() > 0.01:
                self.velocity = move_toward(self.velocity, target, self.stats.accel * delta)
                self.facing = move.normalize()
            else:
                self.velocity = move_toward(self.velocity, Vector2(0, 0),
                                            self.stats.friction * delta)
        # knockback rides on top and bleeds off fast
        if self.knock.length_squared() > 1.0:
            self.velocity += self.knock
            self.knock = move_toward(self.knock, Vector2(0, 0), 1600.0 * delta)

    def _shoot(self, intent, delta, ctx):
        w = self.weapon
        if self.body.blast is not None:
            # A detonator's trigger lights its fuse. Same input for a brain or
            # for you — which is why a worn detonator is a bomb you drive.
            if intent.fire and not self.attack_phase and self.stagger <= 0:
                self.arm()
            return
        if self._burst_left > 0:
            self._burst_t -= delta
            if self._burst_t <= 0.0:
                self._volley(ctx)
                self._burst_left -= 1
                self._burst_t = w.burst_gap
            return
        # A windup is a commitment — you can't shoot your way out of one. The
        # STRIKE phase is where ranged attackers actually let go, so it stays
        # open: brains set intent.fire there (see ai.py).
        if self.attack_phase == "windup":
            return
        if intent.fire and self._fire_cd <= 0.0 and self.stagger <= 0:
            self._fire_cd = self.fire_interval
            self._burst_left = max(1, w.burst)
            self._burst_t = 0.0

    def _volley(self, ctx):
        w = self.weapon
        if self.faction == "player":
            layer, mask = Layer.PLAYER_SHOT, Layer.ENEMY
        else:
            layer, mask = Layer.ENEMY_SHOT, Layer.PLAYER
        crit = self.faction == "player" and ctx.player_crits
        aim = self.aim
        if self.faction == "player" and not w.radial:
            aim = ctx.assisted_aim(self, aim)
        shots = weapons.fire(w, self.position, aim, layer, mask, owner=self,
                             crit=crit, damage_mult=self.damage_mult)
        if self.faction == "player":
            shots = ctx.modify_volley(self, shots)      # relics (relics.py)
        ctx.spawn_projectiles(shots)
        ctx.spawn_impact(self.position + from_angle(self.aim) * (self.radius + 6),
                         w.color, count=3, speed=(40, 160), life=0.16)
        if w.recoil:
            self.knock -= from_angle(self.aim) * w.recoil
        self._muzzle_t = 0.07
        self.on_fired.emit(self)

    def volley_at(self, angle, ctx):
        """Fire one volley at an exact angle. Brains with a scripted pattern
        (the Shrike's dagger fan) use this instead of the trigger."""
        self.aim = angle
        self._volley(ctx)

    def _resolve_melee(self, ctx):
        """The strike half of a telegraphed attack. The windup that precedes it
        is what §3.4's perfect dodge reads — see combat.threat_window()."""
        if (self.attack_phase != "strike" or self._melee_spent
                or self.attack_kind != "melee"):
            return
        br = self.body.brain
        damage = self.attack_damage if self.attack_damage is not None else br.melee_damage
        poison = self.attack_poison if self.attack_poison is not None else br.melee_poison
        if damage <= 0:
            return
        for other in ctx.hostiles_of(self):
            reach = br.melee_radius + other.radius
            if (other.position - self.position).length() <= reach:
                if other.take_damage(damage * self.damage_mult, ctx,
                                     source=self, knockback=240.0):
                    other.poison(poison)
                self._melee_spent = True
                break

    def _integrate(self, delta, ctx):
        room = ctx.room
        resolve_circle_rects(self.position, self.velocity, self.radius, delta,
                             room.obstacles, room.inner, self._dash_dir)

    def _push_trail(self, delta):
        if self.dashing:
            self.trail.append([Vector2(self.position), 0.0])
        for t in self.trail:
            t[1] += delta
        self.trail = [t for t in self.trail if t[1] < 0.26][-14:]

    # -- detonator ----------------------------------------------------------
    def arm(self):
        self.begin_attack(from_angle(self.aim), "blast")
        self.attack_t = self.windup_time = self.body.blast.fuse
        self._beep_t = 0.0

    def _burn_fuse(self, delta, ctx):
        """The fuse runs on the body, not the brain, so it burns the same
        whether an enemy lit it or you did."""
        bl = self.body.blast
        self.attack_t -= delta
        self._beep_t -= delta
        if self._beep_t <= 0.0:
            left = clamp(self.attack_t / max(0.01, self.windup_time), 0.0, 1.0)
            self._beep_t = lerp(bl.beep_fast, bl.beep_slow, left)
            self._beep_flash = 0.05
            ctx.sfx("fuse_beep", None if self.faction == "player" else self.position,
                    0.55 + 0.35 * (1.0 - left))
        if self.attack_t <= 0.0:
            self.detonate(ctx)

    def detonate(self, ctx):
        if self._detonated or not self.alive or self.body.blast is None:
            return
        self._detonated = True
        bl = self.body.blast
        for other in ctx.hostiles_of(self):
            if (other.position - self.position).length() <= bl.radius + other.radius:
                other.take_damage(bl.damage * self.damage_mult, ctx, source=self,
                                  knockback=bl.knockback)
        ctx.explosion(self.position, bl.radius, self.body.color)
        self.die(ctx)

    # -- attack FSM (driven by brains) --------------------------------------
    def begin_attack(self, direction: Vector2, kind: str = None):
        br = self.body.brain
        self.attack_phase = "windup"
        self.attack_kind = kind or ("melee" if br.melee_damage > 0 else "shot")
        self.attack_t = self.windup_time = br.telegraph_time
        self.strike_time = None
        self.recover_time = None
        self.attack_damage = None
        self.attack_poison = None
        self.fan_offsets = ()
        self.summon_points = []
        self.attack_dir = direction.normalize() if direction.length() > 0.001 else Vector2(1, 0)
        self._melee_spent = False
        self.on_attack.emit(self)

    def advance_attack(self, delta) -> bool:
        """Returns True while an attack is still running."""
        if not self.attack_phase:
            return False
        br = self.body.brain
        self.attack_t -= delta
        if self.attack_t > 0:
            return True
        if self.attack_phase == "windup":
            self.attack_phase = "strike"
            self.attack_t = self.strike_duration
        elif self.attack_phase == "strike":
            self.attack_phase = "recover"
            self.attack_t = (self.recover_time if self.recover_time is not None
                             else br.recover_time)
        else:
            self.attack_phase = ""
            self.attack_t = 0.0
            return False
        return True

    def cancel_attack(self):
        self.attack_phase = ""
        self.attack_t = 0.0
        self._melee_spent = False

    # -- damage --------------------------------------------------------------
    def take_damage(self, amount, ctx, source=None, knockback=0.0, crit=False,
                    weak_hit=False):
        if not self.alive or self.invuln_t > 0 or self.possess_channel > 0:
            return False
        if self.vanished:
            return False
        if self.body.backstab is not None and not weak_hit:
            # Armour everywhere but the back. combat.py decides what a weak hit
            # is. Some armour (the Shrike's) lets a fraction through.
            if self.body.backstab.front_mult <= 0.0:
                ctx.deflect(self, self.position)
                return False
            amount *= self.body.backstab.front_mult
            crit = False

        self.health -= amount
        self.flash = 0.14
        self.invuln_t = (COMBAT.player_invuln if self.faction == "player"
                         else COMBAT.enemy_invuln)
        if knockback and source is not None:
            d = self.position - source.position
            if d.length() > 0.001:
                self.knock += d.normalize() * knockback
        if amount >= self.max_health * 0.25 and not self.armed:
            # (a lit fuse can't be knocked out — shooting it only sets it off)
            self.stagger = max(self.stagger, 0.12)
            self.cancel_attack()

        self.on_hurt.emit(self, amount)
        ctx.spawn_impact(self.position, C.CRIT if crit else self.body.color,
                         count=9 if crit else 5)
        ctx.hit_stop(COMBAT.crit_hit_stop if crit else COMBAT.hit_stop)

        if self.health <= 0:
            self.die(ctx)
            return True

        # Crossing the weaken threshold opens the possession window (§3.5).
        if (self.body.possessable and self.faction == "enemy"
                and self.weaken_t <= 0.0
                and self.health <= self.max_health * POSSESS.weaken_fraction):
            self.weaken_t = POSSESS.weaken_duration
            self.on_weakened.emit(self)
        return True

    def make_elite(self):
        """Phase 7. Rewrites this actor's PRIVATE body, so the upgrade survives
        a possession — and never touches the archetype template."""
        b = self.body
        if b.elite or not b.possessable:
            return
        b.elite = True
        b.max_health *= ELITE.health_mult
        b.weapon.damage *= ELITE.damage_mult
        b.weapon.fire_rate *= ELITE.fire_rate_mult
        b.brain.melee_damage *= ELITE.damage_mult
        if b.blast is not None:
            b.blast.damage *= ELITE.damage_mult
        b.brain.telegraph_time *= ELITE.telegraph_mult
        b.movement.max_speed *= ELITE.speed_mult
        b.movement.radius *= ELITE.radius_mult
        b.score = int(b.score * ELITE.score_mult)
        b.threat += 1
        self.radius = b.movement.radius
        self.max_health = self._scaled_max_health()
        self.health = self.max_health

    # -- poison --------------------------------------------------------------
    def poison(self, stacks):
        if not stacks or stacks <= 0 or not self.alive:
            return
        self.poison_stacks = min(POISON.max_stacks, self.poison_stacks + stacks)
        self.poison_t = POISON.duration
        self.on_poisoned.emit(self)

    def _tick_poison(self, delta, ctx):
        """Damage over time. It skips take_damage on purpose: no i-frames, no
        hit-stop, no flash — a tick is a drain, not a hit."""
        dmg = POISON.dps_per_stack * self.poison_stacks * delta
        self.health -= dmg
        self._poison_shown += dmg
        self.poison_t -= delta
        if self._poison_shown >= 3.0 or (self.poison_t <= 0 and self._poison_shown > 0.5):
            self.on_poison_tick.emit(self, self._poison_shown)
            self._poison_shown = 0.0
        if self.poison_t <= 0.0:
            self.poison_t = 0.0
            self.poison_stacks = 0
        if self.health <= 0.0:
            self.die(ctx)

    def heal(self, amount):
        self.health = min(self.max_health, self.health + amount)

    def die(self, ctx):
        if not self.alive:
            return
        bl = self.body.blast
        if self.armed and bl.detonate_on_death and not self._detonated:
            self.detonate(ctx)          # which calls die() again, once
            return
        self.health = 0.0
        self.alive = False
        self.cancel_attack()
        ctx.spawn_impact(self.position, self.body.color, count=18,
                         speed=(120, 460), life=0.5)
        ctx.shake(COMBAT.shake_on_kill)
        self.on_died.emit(self)

    # -- drawing -------------------------------------------------------------
    def draw(self, surface, camera):
        if not self.alive:
            return
        sp = camera.to_screen(self.position)
        r = int(self.radius)
        col = self.body.color

        if self.vanished:
            # gone: a collapsing outline where it stood, nothing to shoot at
            t = clamp(self.attack_t / max(0.01, self.windup_time), 0.0, 1.0)
            pygame.draw.circle(surface, shade(col, 0.6 + 0.6 * t), (int(sp.x), int(sp.y)),
                               max(2, int(r * (0.3 + 0.9 * t))), 2)
            return
        if self.summon_points and self.attack_phase == "windup":
            t = 1.0 - clamp(self.attack_t / max(0.01, self.windup_time), 0.0, 1.0)
            for pt in self.summon_points:
                q = camera.to_screen(pt)
                pygame.draw.circle(surface, shade(C.UPGRADE, 0.5 + 0.5 * t),
                                   (int(q.x), int(q.y)), int(lerp(26, 12, t)), 2)
                pygame.draw.circle(surface, C.BAD, (int(q.x), int(q.y)), max(2, int(5 * t)))

        self._draw_trail(surface, camera)
        self._draw_telegraph(surface, sp)
        if self.body.elite:
            # the elite ring rides on the BODY, so it follows a possession
            pygame.draw.circle(surface, ELITE.color, (int(sp.x), int(sp.y)), r + 5, 2)

        tip = art.draw_body(surface, self, sp, self._art_effects())
        if tip is None:
            tip = self._draw_placeholder(surface, sp, r, col)
        self._draw_overlays(surface, camera, sp, r, tip)

    def _art_effects(self):
        """How the sprite should be tinted this frame — the same cues the
        placeholder circles used, as sprite effects."""
        fx = {"mine": self.faction == "player"}
        if self.flash > 0 or self._beep_flash > 0:
            fx["white"] = True
        elif self.possess_channel > 0:
            fx["tint"] = (0.6, C.UPGRADE)
        elif self.poison_t > 0:
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.012)
            fx["tint"] = (0.25 + 0.3 * pulse, POISON.color)
        if self.invuln_t > 0 and self.faction == "player" and self.flash <= 0:
            fx["fade"] = 0.55 + 0.25 * math.sin(self.invuln_t * 44.0)
        return fx

    def _draw_placeholder(self, surface, sp, r, col):
        """The pre-art look: a circle and a barrel. Used for any body art.py
        has no design for."""
        if self.possess_channel > 0:
            col = tint(col, C.UPGRADE, 0.6)
        if self._beep_flash > 0:
            col = tint(col, (255, 255, 255), 0.8)
        if self.poison_t > 0:
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.012)
            col = tint(col, POISON.color, 0.25 + 0.25 * pulse)
        if self.flash > 0:
            col = tint(col, (255, 255, 255), min(1.0, self.flash / 0.14))
        elif self.invuln_t > 0 and self.faction == "player":
            # i-frame shimmer, so "why didn't that hurt" is always answerable
            col = tint(col, C.BG, 0.35 + 0.25 * math.sin(self.invuln_t * 44.0))

        pygame.draw.circle(surface, shade(col, 0.55), (int(sp.x), int(sp.y)), r)
        pygame.draw.circle(surface, col, (int(sp.x), int(sp.y)), max(1, r - 3))
        pygame.draw.circle(surface, tint(col, (255, 255, 255), 0.5),
                           (int(sp.x), int(sp.y)), r, 2)

        # aim barrel (≈ Sprite2D rotated to `aim`)
        tip = sp + from_angle(self.aim) * (self.radius + 11)
        pygame.draw.line(surface, shade(col, 0.35), (sp.x, sp.y), (tip.x, tip.y), 6)
        pygame.draw.line(surface, tint(col, (255, 255, 255), 0.35),
                         (sp.x, sp.y), (tip.x, tip.y), 2)
        return tip

    def _draw_overlays(self, surface, camera, sp, r, tip):
        wp = self.weak_point
        if wp is not None:
            # The weak point is always shown — the skill is getting to it.
            wsp = camera.to_screen(wp)
            exposed = self.attack_phase == "recover" and self.recover_time is not None \
                and self.recover_time > self.body.backstab.between
            glow = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.02)
            wr = int(self.body.backstab.weak_radius)
            pygame.draw.circle(surface, shade(C.CRIT, 0.4), (int(wsp.x), int(wsp.y)), wr + 1)
            pygame.draw.circle(surface, tint(C.CRIT, (255, 255, 255), glow * 0.6)
                               if exposed else C.CRIT, (int(wsp.x), int(wsp.y)),
                               max(2, wr - 2))
            if exposed:
                pygame.draw.circle(surface, C.CRIT, (int(wsp.x), int(wsp.y)),
                                   wr + 5 + int(3 * glow), 2)

        if self._muzzle_t > 0:
            t = self._muzzle_t / 0.07
            wcol = self.weapon.color
            flare = int(9 + 13 * t)
            pygame.draw.circle(surface, tint(wcol, (255, 255, 255), 0.55),
                               (int(tip.x), int(tip.y)), flare)
            pygame.draw.circle(surface, (255, 255, 255),
                               (int(tip.x), int(tip.y)), max(2, flare // 3))

        if self.faction == "enemy":
            self._draw_enemy_chrome(surface, sp, r)

    def _draw_trail(self, surface, camera):
        if not self.trail:
            return
        # §3.4's required tell: a LOCKED perfect dodge drains the trail of
        # colour, so a dodge that doesn't fire reads as a choice you made and
        # not as a bug.
        locked = getattr(self.controller, "perfect_dodge_locked", False)
        base = C.LOCKED if locked else tint(self.body.color, (255, 255, 255), 0.35)
        for pos, age in self.trail:
            t = max(0.0, 1.0 - age / 0.26)
            sp = camera.to_screen(pos)
            rr = max(1, int(self.radius * t * 0.85))
            pygame.draw.circle(surface, shade(base, 0.25 + 0.5 * t),
                               (int(sp.x), int(sp.y)), rr, 0 if locked else 2)

    def _draw_telegraph(self, surface, sp):
        if not self.attack_phase:
            return
        br = self.body.brain
        if self.attack_kind == "blast":
            self._draw_fuse(surface, sp)
            return
        melee = self.attack_kind == "melee"
        if self.attack_phase == "windup":
            # The ring closes in as the strike approaches — that shrinking ring
            # IS the dodge cue, so it has to be readable at a glance. The last
            # WitchTimeStats.perfect_window of it is the scoring window (§3.4).
            t = 1.0 - clamp(self.attack_t / max(0.01, self.windup_time), 0.0, 1.0)
            rr = int(lerp(br.melee_radius * 2.1, br.melee_radius, t)) if melee else \
                 int(lerp(self.radius * 3.4, self.radius * 1.5, t))
            width = 2 + int(3 * t)
            col = tint(C.BAD, (255, 255, 255), t * 0.6)
            if melee and self.attack_t <= WITCH.perfect_window:
                col = C.CRIT          # "now" — the frame that rewards a read
            pygame.draw.circle(surface, col, (int(sp.x), int(sp.y)), max(2, rr), width)
            for off in self.fan_offsets:
                end = sp + self.attack_dir.rotate(off) * 420
                lc = shade(tint(POISON.color, (255, 255, 255), t * 0.4), 0.35 + 0.6 * t)
                pygame.draw.line(surface, lc, (sp.x, sp.y), (end.x, end.y), 1 + int(t * 1.5))
            if not melee and br.sight_line > 0:
                # The lancer's tell: the exact line the shot will take, because
                # attack_dir is frozen for the whole windup (ai.py).
                end = sp + self.attack_dir * br.sight_line
                lc = (C.CRIT if self.attack_t <= WITCH.perfect_window
                      else shade(tint(C.BAD, (255, 255, 255), t * 0.5), 0.45 + 0.55 * t))
                pygame.draw.line(surface, lc, (sp.x, sp.y), (end.x, end.y),
                                 1 + int(2 * t))
            if melee:
                # a lunge shows its whole path; a swipe just its reach
                length = (br.lunge_speed * self.strike_time if self.strike_time
                          else br.melee_radius * lerp(1.4, 1.0, t))
                end = sp + self.attack_dir * length
                pygame.draw.line(surface, shade(C.BAD, 0.7 + 0.3 * t),
                                 (sp.x, sp.y), (end.x, end.y), 3)
        elif self.attack_phase == "strike" and melee:
            pygame.draw.circle(surface, C.BAD, (int(sp.x), int(sp.y)),
                               int(br.melee_radius), 5)

    def _draw_fuse(self, surface, sp):
        """The blast radius, and a second ring racing out to meet it. When they
        touch, it goes off."""
        if self.attack_phase != "windup":
            return
        bl = self.body.blast
        t = 1.0 - clamp(self.attack_t / max(0.01, self.windup_time), 0.0, 1.0)
        c = (int(sp.x), int(sp.y))
        now = self.attack_t <= WITCH.perfect_window
        edge = C.CRIT if now else tint(C.BAD, (255, 255, 255), t * 0.4)
        pygame.draw.circle(surface, shade(edge, 0.55 + 0.45 * t), c,
                           int(bl.radius), 2 + int(2 * t))
        inner = int(lerp(self.radius + 4, bl.radius, t))
        pygame.draw.circle(surface, shade(C.BAD, 0.5 + 0.5 * t), c, inner, 2)

    def _draw_enemy_chrome(self, surface, sp, r):
        # health pip
        if self.health_frac < 0.999:
            w = int(self.radius * 2.4)
            x = int(sp.x - w / 2)
            y = int(sp.y - self.radius - 12)
            pygame.draw.rect(surface, (14, 16, 22), (x - 1, y - 1, w + 2, 6))
            pygame.draw.rect(surface, shade(self.body.color, 1.1),
                             (x, y, int(w * self.health_frac), 4))
        # the take-me window (§3.5)
        if self.possessable:
            pulse = 0.5 + 0.5 * math.sin(self.weaken_t * 11.0)
            rr = int(self.radius + 9 + 4 * pulse)
            pygame.draw.circle(surface, tint(C.UPGRADE, (255, 255, 255), pulse * 0.5),
                               (int(sp.x), int(sp.y)), rr, 2)
            # the window is closing — the arc says how much is left
            frac = clamp(self.weaken_t / POSSESS.weaken_duration, 0.0, 1.0)
            rect = pygame.Rect(int(sp.x - rr), int(sp.y - rr), rr * 2, rr * 2)
            try:
                pygame.draw.arc(surface, C.UPGRADE, rect, -math.pi / 2,
                                -math.pi / 2 + math.tau * frac, 3)
            except ValueError:
                pass
