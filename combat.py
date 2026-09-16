"""
combat.py — the rules that connect bodies to each other: who a shot hits, who
bumps whom, and (the important one) what counts as a perfect dodge.

→ Godot: most of this becomes Area2D signals — `body_entered` on the projectile,
  layer/mask pairs doing the filtering. threat_window() stays as real code,
  because "is something about to hit me" is a question no engine answers for you.
"""

import math

from .core import Layer, time_to_impact, from_angle, angle_of, segment_hits_rects
from . import relics
from .config import CombatStats, WitchTimeStats, AssistStats

COMBAT = CombatStats()
WITCH = WitchTimeStats()
ASSIST = AssistStats()


def aim_point(e):
    """Where a helpful shot should go: an armoured body's weak point, else its
    centre. Aim assist and seeking shots both use this."""
    wp = e.weak_point
    return wp if wp is not None else e.position


# ---------------------------------------------------------------------------
# Aim assist
# ---------------------------------------------------------------------------
def assist_aim(shooter, aim, enemies, obstacles):
    """Nudge `aim` onto the target it narrowly misses, if there is one.

    The allowance is a distance at the target (reach_px), turned into an angle,
    so a far target gets a small correction and a near one a bigger one — up
    to max_deg. Of the targets inside their allowance, the one needing the
    smallest turn wins. Targets behind a crate are ignored.
    """
    best, best_off = None, None
    for e in enemies:
        if not e.alive or e.vanished:
            continue
        pt = aim_point(e)
        to = pt - shooter.position
        dist = to.length()
        if dist < 1.0 or dist > ASSIST.range:
            continue
        allow = min(ASSIST.max_deg, math.degrees(math.atan2(ASSIST.reach_px, dist)))
        off = (from_angle(aim).angle_to(to) + 180.0) % 360.0 - 180.0
        if abs(off) > allow:
            continue
        if segment_hits_rects(shooter.position, pt, obstacles):
            continue
        if best_off is None or abs(off) < abs(best_off):
            best, best_off = pt, off
    return aim if best is None else angle_of(best - shooter.position)


# ---------------------------------------------------------------------------
# §3.4 — PERFECT DODGE DETECTION
# ---------------------------------------------------------------------------
def threat_window(player, enemies, projectiles, window: float) -> bool:
    """Is something going to land on `player` within `window` seconds?

    Called the instant a dash STARTS. If this is True and the player hasn't
    burnt their dash chain (§3.3), the dash was a read rather than a panic and
    Witch Time fires.

    Two kinds of threat, and deliberately only two:

      1. A shot already in the air whose path intersects the player inside the
         window. Solved exactly — see core.time_to_impact().
      2. A melee windup whose remaining telegraph is inside the window AND
         whose lunge can actually reach the player.
      3. A lit detonator whose fuse runs out inside the window, with the
         player inside its blast — dashing clear on the last beat is a read.

    Note what is NOT a threat: an enemy that has merely decided to shoot. You
    can't dodge a bullet that doesn't exist yet, and counting it would let you
    farm Witch Time by dashing at any gunner drawing a bead on you.
    """
    for p in projectiles:
        if not p.alive or p.layer != Layer.ENEMY_SHOT:
            continue
        t = time_to_impact(p.position, p.velocity, player.position,
                           player.radius + p.radius + 4.0, window)
        if t is not None:
            return True

    for e in enemies:
        if not e.alive or e.attack_phase != "windup":
            continue
        if e.attack_kind == "blast":
            if (e.attack_t <= window and (player.position - e.position).length()
                    <= e.body.blast.radius + player.radius):
                return True
            continue
        if e.attack_kind != "melee":
            continue
        br = e.body.brain
        if br.melee_damage <= 0 or e.attack_t > window:
            continue
        # Would the strike have connected? Lunge carries it forward during the
        # strike phase, so include that distance in the reach test.
        reach = (br.melee_radius + player.radius
                 + br.lunge_speed * e.strike_duration * 0.6)
        if (player.position - e.position).length() <= reach:
            return True
    return False


# ---------------------------------------------------------------------------
# Projectile resolution
# ---------------------------------------------------------------------------
def _segment_dist(a, b, c):
    """Distance from point c to segment a→b. Shots move up to ~20px a tick,
    so a point test would step straight over a 7px weak spot."""
    ab = b - a
    L = ab.length_squared()
    if L <= 1e-9:
        return (c - a).length()
    t = max(0.0, min(1.0, (c - a).dot(ab) / L))
    return (a + ab * t - c).length()


def _hit_backstab(ctx, e, p):
    """The assassin: a shot that touches the body either finds the weak point on
    its back (lethal) or glances off. Returns True if the shot touched it."""
    if _segment_dist(p.trail, p.position, e.position) > e.radius + p.radius:
        return False
    if e.vanished:
        return False                    # mid shadow-sneak: shots pass through
    bs = e.body.backstab
    if _segment_dist(p.trail, p.position, e.weak_point) <= bs.weak_radius + p.radius:
        if bs.lethal:
            if e.take_damage(e.health + e.max_health, ctx, source=p,
                             knockback=p.knockback, crit=True, weak_hit=True):
                ctx.backstabbed(e)
        else:
            # the boss: a back hit wounds, harder than a normal hit would
            if e.take_damage(p.damage * bs.weak_mult * relics.back_mult(e, p), ctx,
                             source=p, knockback=p.knockback, crit=p.crit,
                             weak_hit=True):
                e.poison(p.poison)
    else:
        ctx.deflect(e, p.position)
        if bs.front_mult > 0.0:
            # the boss's armour lets a little through (Actor.take_damage scales it)
            e.take_damage(p.damage, ctx, source=p, knockback=p.knockback * 0.3,
                          crit=p.crit)
    return True


def resolve_projectiles(ctx):
    """Shots vs bodies. Layer/mask decides who is hittable. → Godot: Area2D."""
    player = ctx.player_actor
    for p in ctx.projectiles:
        if not p.alive:
            continue
        if p.hit_mask & Layer.ENEMY:
            for e in ctx.enemies:
                if not e.alive or e is p.owner:
                    continue
                if p.hits is not None and e in p.hits:
                    continue                    # a piercing shot already went through
                if e.body.backstab is not None:
                    if _hit_backstab(ctx, e, p):
                        if p.shatter:
                            ctx.spawn_projectiles(relics.shatter(p, e))
                        p.kill()
                        break
                    continue
                if (e.position - p.position).length() <= e.radius + p.radius:
                    back = relics.back_mult(e, p)
                    if e.take_damage(p.damage * back, ctx, source=p,
                                     knockback=p.knockback, crit=p.crit or back > 1.0):
                        e.poison(p.poison)
                    if p.shatter:
                        ctx.spawn_projectiles(relics.shatter(p, e))
                    if p.pierce > 0:
                        p.pierce -= 1
                        p.hits.add(e)
                        continue
                    p.kill()
                    break
        elif p.hit_mask & Layer.PLAYER:
            if player is not None and player.alive and player is not p.owner:
                if (player.position - p.position).length() <= player.radius + p.radius:
                    if player.take_damage(p.damage, ctx, source=p,
                                          knockback=p.knockback):
                        ctx.shake(COMBAT.shake_on_hurt)
                        player.poison(p.poison)
                    p.kill()


# ---------------------------------------------------------------------------
# Body separation — stops enemies stacking into one super-enemy.
# → Godot: the physics server does this natively for CharacterBody2D.
# ---------------------------------------------------------------------------
def resolve_bodies(ctx):
    from .core import separate
    live = [e for e in ctx.enemies if e.alive]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            separate(a, b, 0.5)
    player = ctx.player_actor
    if player is not None and player.alive:
        for e in live:
            if e.body.backstab is not None and e.attack_phase == "strike":
                continue        # the assassin's dash goes THROUGH you
            # The player is heavier than a grunt but shoves less than a brute.
            separate(player, e, 0.65)
