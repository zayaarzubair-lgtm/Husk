"""
ai.py — enemy brains.

Each brain is a small finite state machine reading its BrainStats. Because a
brain is just a Controller, "possessing" an enemy means unplugging its brain and
plugging the player's controller into the same body (§3.5) — no conversion, no
special enemy-to-player class.

→ Godot: a Node child of the enemy scene running the same FSM, or a
  LimboAI/BehaviourTree if you want it authored visually later.

The FSM, shared by every archetype:

    idle/wander ──(player within aggro_range)──► engage
    engage ──(in attack_range, gate open, line of sight)──► windup
    windup ──► strike ──► recover ──► engage

`windup` is the important state: it's the telegraph, it does not track the
player, and its final WitchTimeStats.perfect_window is what a perfect dodge
reads (§3.4). An attack that homed in during its windup would be undodgeable,
which is why attack_dir is frozen when the windup begins.
"""

import math
import random
from pygame.math import Vector2

from .actors import Controller, Intent
from .core import from_angle, angle_of, segment_hits_rects, clamp


class AIController(Controller):
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.awake = False
        self.gate = self.rng.uniform(0.0, 0.7)      # desyncs a pack's attacks
        self.wander_dir = from_angle(self.rng.uniform(0, math.tau))
        self.wander_t = self.rng.uniform(0.4, 1.6)
        self.strafe_sign = self.rng.choice((-1, 1))
        self.strafe_t = self.rng.uniform(0.8, 2.2)
        self._last_pos = None
        self._stuck_t = 0.0
        self._avoid_t = 0.0
        self._avoid_dir = Vector2(0, 0)

    # -- main ----------------------------------------------------------------
    def decide(self, actor, delta, ctx) -> Intent:
        intent = Intent(aim=actor.aim)
        self.gate = max(0.0, self.gate - delta)
        target = ctx.player_actor
        br = actor.body.brain

        if actor.attack_phase:
            return self._attack_intent(actor, delta, intent, target, br)

        if target is None or not target.alive:
            return self._wander(actor, delta, intent, br, ctx)

        to = target.position - actor.position
        dist = to.length()

        if not self.awake:
            if dist > br.aggro_range:
                return self._wander(actor, delta, intent, br, ctx)
            self.awake = True

        n = to.normalize() if dist > 0.001 else Vector2(1, 0)
        intent.aim = angle_of(n)
        intent.move = self._avoid(actor, ctx, self._position(actor, br, n, dist, delta))

        if self._should_attack(actor, ctx, target, dist, br):
            kind = self._attack_kind(actor, dist, br)
            actor.begin_attack(n, kind)
            self.gate = self.rng.uniform(0.15, 0.6)
            intent.move = Vector2(0, 0)

        self._unstick(actor, delta, intent)
        return intent

    # -- states --------------------------------------------------------------
    def _attack_intent(self, actor, delta, intent, target, br):
        actor.advance_attack(delta)
        # Frozen direction: the telegraph commits, so dodging it actually works.
        intent.aim = angle_of(actor.attack_dir)
        phase = actor.attack_phase
        if phase == "strike":
            # Ranged archetypes let go here; melee ones lunge (Actor._move).
            intent.fire = actor.attack_kind == "shot"
        elif phase == "recover" and target is not None and target.alive:
            # Vulnerable and backing off — the opening you're meant to punish.
            to = target.position - actor.position
            if to.length() > 0.001 and br.keep_distance > 0:
                intent.move = -to.normalize() * 0.6
        return intent

    def _wander(self, actor, delta, intent, br, ctx=None):
        if br.wander_speed <= 0.0:
            return intent
        self.wander_t -= delta
        if self.wander_t <= 0.0:
            self.wander_t = self.rng.uniform(0.7, 2.0)
            if self.rng.random() < 0.35:
                self.wander_dir = Vector2(0, 0)
            else:
                self.wander_dir = from_angle(self.rng.uniform(0, math.tau))
        intent.move = self._avoid(actor, ctx, self.wander_dir) * br.wander_speed
        if self.wander_dir.length() > 0.01:
            intent.aim = angle_of(self.wander_dir)
        self._unstick(actor, delta, intent)
        return intent

    def _position(self, actor, br, n, dist, delta):
        """Where the body wants to be relative to the player."""
        if br.keep_distance <= 0.0:
            return n                                  # close the gap
        self.strafe_t -= delta
        if self.strafe_t <= 0.0:
            self.strafe_t = self.rng.uniform(0.9, 2.4)
            self.strafe_sign *= -1
        if dist < br.keep_distance * 0.75:
            return -n                                 # too close, back off
        if dist > br.keep_distance * 1.25:
            return n                                  # too far, close in
        perp = Vector2(-n.y, n.x) * self.strafe_sign
        return perp * max(0.25, br.strafe)            # orbit

    def _should_attack(self, actor, ctx, target, dist, br):
        if self.gate > 0.0 or actor.stagger > 0.0 or dist > br.attack_range:
            return False
        # Don't fire through crates. → Godot: a raycast on the wall layer.
        return not segment_hits_rects(actor.position, target.position,
                                      ctx.room.obstacles)

    def _attack_kind(self, actor, dist, br):
        return None      # let Actor.begin_attack pick from melee_damage

    def _avoid(self, actor, ctx, want):
        """Steer around crates instead of into them.

        A short probe along the intended heading, then progressively wider
        turns until one is clear. This is a steering behaviour, not pathfinding
        — it handles the convex crates this game actually has, and will not
        solve a concave pocket. _unstick() below is the backstop for that case.

        → Godot: a NavigationAgent2D makes both of these unnecessary.
        """
        if ctx is None or want.length() < 0.01:
            return want
        want = want.normalize()
        pad = actor.radius * 1.7
        reach = actor.radius + 64
        room = ctx.room
        for turn in (0.0, 0.45, -0.45, 0.95, -0.95, 1.5, -1.5):
            d = want.rotate_rad(turn)
            probe = actor.position + d * reach
            if not room.inner.collidepoint(probe.x, probe.y):
                continue
            if any(o.inflate(pad, pad).collidepoint(probe.x, probe.y)
                   for o in room.obstacles):
                continue
            return d
        return want

    # -- anti-stuck ----------------------------------------------------------
    def _unstick(self, actor, delta, intent):
        """Crates are convex and brains are not. If a body is pushing into
        geometry and going nowhere, slide along it for a moment.

        → Godot: navigation agents make this unnecessary; it's here because
          steering straight at a target is all this prototype does for pathing.
        """
        if self._last_pos is None:
            self._last_pos = Vector2(actor.position)
            return
        moved = (actor.position - self._last_pos).length()
        self._last_pos = Vector2(actor.position)
        # Scale the threshold by delta so Witch Time's slowed ticks don't read
        # as being stuck.
        expected = actor.max_speed * delta * 0.25
        if intent.move.length() > 0.1 and moved < expected:
            self._stuck_t += delta
        else:
            self._stuck_t = 0.0
        if self._stuck_t > 0.2:
            self._stuck_t = 0.0
            self._avoid_t = 0.5
            perp = Vector2(-intent.move.y, intent.move.x)
            if perp.length() > 0.001:
                self._avoid_dir = perp.normalize() * self.rng.choice((-1, 1))
        if self._avoid_t > 0.0:
            self._avoid_t -= delta
            if self._avoid_dir.length() > 0.001:
                intent.move = self._avoid_dir


class TurretBrain(AIController):
    """Rooted. Trades mobility for a radial barrage you have to move through —
    the archetype that punishes standing still, which is the whole point."""

    def _position(self, actor, br, n, dist, delta):
        return Vector2(0, 0)


class BossBrain(AIController):
    """The Warden. Alternates a reachable melee commitment with a room-filling
    radial volley, so neither hugging it nor kiting it is a solution on its own.

    Enrages under half health: attacks come faster and it stops letting you
    breathe between them.
    """

    def __init__(self, rng=None):
        super().__init__(rng)
        self.enraged = False

    def decide(self, actor, delta, ctx):
        if not self.enraged and actor.health_frac <= 0.5:
            self.enraged = True
            br = actor.body.brain
            br.telegraph_time *= 0.72
            br.recover_time *= 0.6
            actor.body.movement.max_speed *= 1.18
        return super().decide(actor, delta, ctx)

    def _should_attack(self, actor, ctx, target, dist, br):
        if self.gate > 0.0 or actor.stagger > 0.0:
            return False
        if dist <= br.attack_range:
            return True                       # melee lunge, no LOS needed
        if dist <= 1000.0:
            return True                       # radial volley ignores cover
        return False

    def _attack_kind(self, actor, dist, br):
        return "melee" if dist <= br.attack_range else "shot"


class DetonatorBrain(AIController):
    """Swarm fodder with a sting. Rushes you; on contact it pulls the trigger,
    which lights the fuse (Actor._shoot) and roots it. The fuse itself burns on
    the body, so this brain has nothing left to do once it's lit."""

    def decide(self, actor, delta, ctx):
        if actor.attack_phase:
            return Intent(aim=actor.aim)          # rooted, counting down
        intent = super().decide(actor, delta, ctx)
        target = ctx.player_actor
        if self.awake and target is not None and target.alive:
            gap = ((target.position - actor.position).length()
                   - actor.radius - target.radius)
            if gap <= actor.body.blast.trigger_range:
                intent.fire = True
                intent.move = Vector2(0, 0)
        return intent

    def _should_attack(self, actor, ctx, target, dist, br):
        return False                              # contact, not range, lights it


class AssassinBrain(AIController):
    """Circles at range facing you — its back, the only place it can be hurt,
    always turned away. Then a five-dash dagger combo with a fixed rhythm
    (BackstabStats). Each dash is aimed when its windup starts and frozen, like
    every telegraph in the game, and ends past you, so the assassin finishes
    the combo dazed with its back turned: the opening."""

    def __init__(self, rng=None):
        super().__init__(rng)
        self.combo_i = 0

    def decide(self, actor, delta, ctx):
        if actor.attack_phase:
            return self._combo(actor, delta, ctx)
        intent = super().decide(actor, delta, ctx)       # engage / strafe / wander
        target = ctx.player_actor
        if (self.awake and target is not None and target.alive
                and AIController._should_attack(self, actor, ctx, target,
                                                (target.position - actor.position).length(),
                                                actor.body.brain)):
            self.combo_i = 0
            self._dash(actor, target)
            intent.move = Vector2(0, 0)
        return intent

    def _should_attack(self, actor, ctx, target, dist, br):
        return False                                     # decide() starts combos

    def _combo(self, actor, delta, ctx):
        before = actor.attack_phase
        actor.advance_attack(delta)
        after = actor.attack_phase
        intent = Intent(aim=angle_of(actor.attack_dir))  # frozen: back stays turned
        if before == "windup" and after == "strike":
            ctx.sfx("slash", actor.position, 0.9)
        elif before == "strike" and after == "recover":
            self.combo_i += 1
            # A dash stops dead instead of sliding off at lunge speed — the
            # daze is only an opening if the weak point holds still.
            actor.velocity = actor.attack_dir * min(actor.velocity.length(), 180.0)
        elif not after:
            target = ctx.player_actor
            bs = actor.body.backstab
            if self.combo_i < bs.combo and target is not None and target.alive:
                self._dash(actor, target)
            else:
                self.combo_i = 0
                self.gate = self.rng.uniform(0.7, 1.3)
        return intent

    def _dash(self, actor, target):
        bs = actor.body.backstab
        br = actor.body.brain
        i = self.combo_i
        to = target.position - actor.position
        dist = max(1.0, to.length())
        d = (to / dist).rotate(bs.skew_deg[i % len(bs.skew_deg)])
        actor.begin_attack(d, "melee")
        actor.attack_t = actor.windup_time = bs.rhythm[i % len(bs.rhythm)]
        actor.strike_time = clamp((dist + bs.overshoot) / br.lunge_speed,
                                  bs.strike_min, bs.strike_max)
        actor.recover_time = bs.exposed_time if i >= bs.combo - 1 else bs.between


class ShrikeBrain(AssassinBrain):
    """The Shrike, floor 2's boss. Its armour works like the assassin's,
    and it has four moves, picked by range and cooldown and weighted away from
    whatever it did last:

      combo   the assassin's five-dash pattern, ending dazed with its back turned
      fan     five poisoned daggers thrown one at a time across a fan; the fan
              is drawn during the windup, and the daggers in flight are
              ordinary perfect-dodge threats
      sneak   vanish (untouchable), reappear just ahead of you, stab. The stab
              has its own windup — that's the dodge — hits hard, poisons, and
              carries it past you with its back turned
      summon  marks spots on the floor, then detonators climb out of them.
              Its summons die with it.

    Under half health it speeds up: shorter windups, gaps and cooldowns.
    """

    def __init__(self, rng=None):
        super().__init__(rng)
        self.move = ""
        self.last = ""
        self.cd = {"fan": 1.0, "sneak": 2.5, "summon": 4.0}
        self.enraged = False
        self.fan_i = 0
        self.fan_t = 0.0

    def decide(self, actor, delta, ctx):
        st = actor.body.shrike
        for k in self.cd:
            self.cd[k] = max(0.0, self.cd[k] - delta)
        if not self.enraged and actor.health_frac <= st.enrage_at:
            self._enrage(actor)

        if actor.attack_phase:
            run = {"fan": self._fan, "sneak": self._sneak,
                   "summon": self._summon}.get(self.move, self._combo)
            return run(actor, delta, ctx)

        self.move = ""
        intent = AIController.decide(self, actor, delta, ctx)   # circle, facing you
        target = ctx.player_actor
        if (not self.awake or target is None or not target.alive
                or self.gate > 0.0 or actor.stagger > 0.0):
            return intent
        move = self._choose(actor, ctx, target)
        if move:
            getattr(self, "_start_" + move)(actor, ctx, target)
            self.move = self.last = move
            intent.move = Vector2(0, 0)
        return intent

    # -- choosing ------------------------------------------------------------
    def _choose(self, actor, ctx, target):
        st = actor.body.shrike
        br = actor.body.brain
        dist = (target.position - actor.position).length()
        los = not segment_hits_rects(actor.position, target.position, ctx.room.obstacles)
        opts = []
        if los and dist <= br.attack_range:
            opts.append(("combo", 3.0))
        if los and dist >= 160 and self.cd["fan"] <= 0:
            opts.append(("fan", 3.0))
        if self.cd["sneak"] <= 0:
            opts.append(("sneak", 2.5 if (dist > 260 or not los) else 1.0))
        if self.cd["summon"] <= 0 and ctx.summons_of(actor) < st.summon_cap:
            opts.append(("summon", 2.0))
        opts = [(m, w * (0.35 if m == self.last else 1.0)) for m, w in opts]
        if not opts:
            return None
        roll = self.rng.uniform(0, sum(w for _, w in opts))
        for m, w in opts:
            roll -= w
            if roll <= 0:
                return m
        return opts[-1][0]

    def _finish(self):
        self.move = ""
        self.combo_i = 0
        self.gate = self.rng.uniform(0.35, 0.8) * (0.7 if self.enraged else 1.0)

    def _enrage(self, actor):
        self.enraged = True
        st = actor.body.shrike
        bs = actor.body.backstab
        m = st.enrage_speed
        # Everything speeds up except the dazes: a good read earns the same
        # opening at 10% health as at 90%.
        for name in ("fan_windup", "fan_gap", "fan_cooldown", "sneak_fade",
                     "sneak_cooldown", "summon_windup", "summon_cooldown"):
            setattr(st, name, getattr(st, name) * m)
        bs.rhythm = tuple(r * m for r in bs.rhythm)
        actor.body.movement.max_speed *= 1.12

    # -- combo ---------------------------------------------------------------
    def _start_combo(self, actor, ctx, target):
        self.combo_i = 0
        self._dash(actor, target)

    def _combo(self, actor, delta, ctx):
        intent = super()._combo(actor, delta, ctx)
        if not actor.attack_phase and self.combo_i == 0:
            self._finish()
        return intent

    # -- dagger fan ----------------------------------------------------------
    def _start_fan(self, actor, ctx, target):
        st = actor.body.shrike
        actor.begin_attack(target.position - actor.position, "shot")
        actor.attack_t = actor.windup_time = st.fan_windup
        n = max(1, st.fan_count)
        actor.fan_offsets = tuple(
            (-st.fan_deg / 2 + st.fan_deg * i / (n - 1)) if n > 1 else 0.0
            for i in range(n))
        actor.strike_time = st.fan_gap * n + 0.05
        actor.recover_time = st.fan_recover
        self.fan_i = 0
        self.fan_t = 0.0
        self.cd["fan"] = st.fan_cooldown

    def _fan(self, actor, delta, ctx):
        st = actor.body.shrike
        offsets = actor.fan_offsets
        actor.advance_attack(delta)
        intent = Intent(aim=angle_of(actor.attack_dir))
        if actor.attack_phase == "strike":
            self.fan_t -= delta
            if self.fan_t <= 0.0 and self.fan_i < len(offsets):
                actor.volley_at(angle_of(actor.attack_dir.rotate(offsets[self.fan_i])), ctx)
                self.fan_i += 1
                self.fan_t = st.fan_gap
            intent.aim = actor.aim
        if not actor.attack_phase:
            self._finish()
        return intent

    # -- shadow sneak --------------------------------------------------------
    def _start_sneak(self, actor, ctx, target):
        st = actor.body.shrike
        actor.begin_attack(target.position - actor.position, "vanish")
        actor.attack_t = actor.windup_time = st.sneak_fade
        self.cd["sneak"] = st.sneak_cooldown
        ctx.sfx("sneak", actor.position)

    def _sneak(self, actor, delta, ctx):
        st = actor.body.shrike
        if actor.vanished:
            actor.attack_t -= delta
            if actor.attack_t <= 0.0:
                target = ctx.player_actor
                if target is None or not target.alive:
                    actor.cancel_attack()
                    self._finish()
                    return Intent(aim=actor.aim)
                dest = self._sneak_point(actor, ctx, target, st)
                ctx.shadow_step(actor, Vector2(actor.position), dest)
                actor.position = dest
                actor.velocity = Vector2(0, 0)
                actor.begin_attack(target.position - dest, "melee")
                actor.attack_t = actor.windup_time = st.stab_windup
                actor.strike_time = st.stab_time
                actor.recover_time = st.stab_recover
                actor.attack_damage = st.stab_damage
                actor.attack_poison = st.stab_poison
            return Intent(aim=actor.aim)

        before = actor.attack_phase
        actor.advance_attack(delta)
        after = actor.attack_phase
        intent = Intent(aim=angle_of(actor.attack_dir))
        if before == "windup" and after == "strike":
            ctx.sfx("slash", actor.position, 1.0)
        elif before == "strike" and after == "recover":
            actor.velocity = actor.attack_dir * min(actor.velocity.length(), 180.0)
        elif not after:
            self._finish()
        return intent

    def _sneak_point(self, actor, ctx, target, st):
        """Just ahead of where you're going — or, standing still, between you
        and where it was. Never inside a crate or a wall."""
        v = target.velocity
        ahead = v if v.length() > 60 else actor.position - target.position
        if ahead.length() < 0.001:
            ahead = Vector2(1, 0)
        ahead = ahead.normalize()
        room = ctx.room
        pad = actor.radius + 4
        field = room.inner.inflate(-pad * 2, -pad * 2)
        for turn in (0, 35, -35, 70, -70, 110, -110, 180):
            p = target.position + ahead.rotate(turn) * st.sneak_distance
            if not field.collidepoint(p.x, p.y):
                continue
            if any(o.inflate(pad * 2, pad * 2).collidepoint(p.x, p.y)
                   for o in room.obstacles):
                continue
            return p
        return Vector2(actor.position)

    # -- summon --------------------------------------------------------------
    def _start_summon(self, actor, ctx, target):
        st = actor.body.shrike
        actor.begin_attack(target.position - actor.position, "summon")
        actor.attack_t = actor.windup_time = st.summon_windup
        actor.strike_time = 0.05
        actor.recover_time = st.summon_recover
        n = self.rng.randint(st.summon_min, st.summon_max)
        n = min(n, st.summon_cap - ctx.summons_of(actor))
        actor.summon_points = self._summon_points(ctx, target, n, st)
        self.cd["summon"] = st.summon_cooldown
        ctx.sfx("summon", actor.position)

    def _summon(self, actor, delta, ctx):
        before = actor.attack_phase
        points = actor.summon_points
        actor.advance_attack(delta)
        if before == "windup" and actor.attack_phase == "strike":
            for pt in points:
                ctx.summon(actor, "detonator", pt)
            actor.summon_points = []
        if not actor.attack_phase:
            self._finish()
        return Intent(aim=angle_of(actor.attack_dir))

    def _summon_points(self, ctx, target, n, st):
        room = ctx.room
        field = room.inner.inflate(-80, -80)
        pts = []
        for _ in range(n * 25):
            if len(pts) >= n:
                break
            p = Vector2(self.rng.uniform(field.left, field.right),
                        self.rng.uniform(field.top, field.bottom))
            if (p - target.position).length() < st.summon_min_dist:
                continue
            if any(o.inflate(40, 40).collidepoint(p.x, p.y) for o in room.obstacles):
                continue
            if any((p - q).length() < 70 for q in pts):
                continue
            pts.append(p)
        return pts


BRAINS = {
    "grunt": AIController,
    "gunner": AIController,
    "brute": AIController,
    "turret": TurretBrain,
    "warden": BossBrain,
    "detonator": DetonatorBrain,
    "assassin": AssassinBrain,
    "shrike": ShrikeBrain,
}


def brain_for(body, rng=None):
    return BRAINS.get(body.name, AIController)(rng)
