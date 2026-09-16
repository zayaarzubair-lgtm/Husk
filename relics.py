"""
relics.py — what boss rewards actually do.

Beat a boss that isn't the last and it leaves a relic: a choice of one WEAPON
mod, one ABILITY and one PASSIVE (config.RELICS). Relics live in the run
modifiers, next to the treasure-room upgrades, so like those they belong to the
player and work in any body you wear.

Every effect hangs off one of five seams, so nothing else in the codebase has
to know which relics exist:

    modify_volley()   a player body fires          (Actor._volley → ctx)
    back_mult()       a player shot lands          (combat.py)
    on_kill()         an enemy dies                (Game._on_enemy_died)
    on_player_hurt()  the player's body is hit     (Game feedback bindings)
    use_ability()     the player presses F         (PlayerController → ctx)

→ Godot: RELICS become Resources; this module becomes a RelicManager autoload
  whose functions are connected to the same signals.
"""

import math

import pygame
from pygame.math import Vector2

from .config import C, RelicStats, RELICS, RELIC_COLORS
from .core import Layer, from_angle, angle_of, shade, tint, clamp, lerp
from .weapons import Projectile, CRIT_MULT

R = RelicStats()

ABILITY_COOLDOWN = {
    "judgement": R.nova_cooldown,
    "shadow_step": R.step_cooldown,
    "fuse_bomb": R.bomb_cooldown,
    "seeker_rounds": R.seeker_cooldown,
    "shrapnel": R.shrapnel_cooldown,
    "battering_ram": R.ram_cooldown,
}
# abilities that run for a while instead of firing once
TIMED = {"seeker_rounds", "shrapnel", "battering_ram"}


def has(mods, key) -> bool:
    return bool(mods) and key in mods["relics"]


# ---------------------------------------------------------------------------
# offering and taking
# ---------------------------------------------------------------------------
def offer(rng, boss_name, mods):
    """One card per kind. A boss's own relics are twice as likely as the
    generic ones; relics you already hold are never offered again."""
    owned = set(mods["relics"])
    cards = []
    for kind in ("weapon", "ability", "passive"):
        pool = [r for r in RELICS if r.kind == kind and r.key not in owned
                and (not r.bosses or boss_name in r.bosses)]
        if not pool:
            continue
        weights = [2.0 if r.bosses else 1.0 for r in pool]
        cards.append(rng.choices(pool, weights=weights)[0])
    return cards


def take(relic, mods):
    """Returns the ability this one replaced, if any."""
    for k, v in relic.mods.items():
        mods[k] += v
    mods["relics"].append(relic.key)
    if relic.kind == "ability":
        old = mods["ability"]
        mods["ability"] = relic.key
        return old
    return None


# ---------------------------------------------------------------------------
# shots
# ---------------------------------------------------------------------------
def ring(pos, count, damage, speed, color, knockback=90.0, crit=False,
         radius=6.0, lifetime=1.1, owner=None, phase=0.0):
    """An even ring of player shots — the warden relics' signature."""
    shots = []
    for i in range(count):
        ang = phase + math.tau * i / count
        shots.append(Projectile(
            Vector2(pos) + from_angle(ang) * 16.0, from_angle(ang) * speed,
            damage * (CRIT_MULT if crit else 1.0), lifetime, radius, color,
            knockback, Layer.PLAYER_SHOT, Layer.ENEMY, owner=owner, crit=crit))
    return shots


def _clone(s, velocity, damage):
    c = Projectile(Vector2(s.position), velocity, damage, s.max_life, s.radius,
                   s.color, s.knockback, s.layer, s.hit_mask, owner=s.owner,
                   crit=s.crit)
    c.poison = s.poison
    return c


def modify_volley(ctx, actor, shots):
    mods = actor.mods
    if not mods or not mods["relics"]:
        return shots
    w = actor.weapon
    if has(mods, "split_shot") and not w.radial:
        extra = []
        for s in shots:
            for sign in (-1, 1):
                extra.append(_clone(s, s.velocity.rotate(sign * R.split_angle),
                                    s.damage * R.split_damage))
        shots = shots + extra
    if has(mods, "piercing"):
        for s in shots:
            s.velocity *= R.pierce_speed
            s.pierce = R.pierce
            s.hits = set()
    if has(mods, "venom_rounds"):
        for s in shots:
            s.poison = max(s.poison, R.venom_stacks)
    if ctx.buff_active("seeker_rounds") or ctx.buff_active("shrapnel"):
        seek = ctx.buff_active("seeker_rounds")
        for s in shots:
            if seek:
                s.seek = (R.seeker_turn, R.seeker_range)
            else:
                s.shatter = R.shrapnel_count
            s.color = RELIC_COLORS["ability"]
    if has(mods, "judgement_rounds"):
        ctx.relic_state["volleys"] += 1
        if ctx.relic_state["volleys"] % R.echo_every == 0:
            crit = shots[0].crit if shots else False
            shots = shots + ring(actor.position, R.echo_count,
                                 w.damage * R.echo_damage * actor.damage_mult,
                                 w.speed * 0.8, RELIC_COLORS["weapon"], crit=crit,
                                 owner=actor, phase=actor.aim)
            ctx.sfx("shot_radial", None, 0.6)
    return shots


def shatter(shot, enemy):
    """SHRAPNEL: the shot that hit bursts into an X of fragments. They skip the
    enemy that was hit and never burst again."""
    shot_dir = shot.velocity if shot.velocity.length_squared() > 1 else Vector2(1, 0)
    speed = shot_dir.length() * R.shrapnel_speed
    out = []
    for i in range(shot.shatter):
        ang = 45.0 + 360.0 * i / shot.shatter
        v = shot_dir.normalize().rotate(ang) * speed
        f = Projectile(Vector2(shot.position), v, shot.damage * R.shrapnel_damage,
                       R.shrapnel_life, max(3.0, shot.radius * 0.7), shot.color,
                       shot.knockback * 0.5, shot.layer, shot.hit_mask,
                       owner=shot.owner, crit=shot.crit)
        f.hits = {enemy}
        f.poison = shot.poison
        out.append(f)
    shot.shatter = 0
    return out


def ram(ctx, actor, controller):
    """BATTERING RAM: called every tick while the buff runs. A dash that isn't
    past the perfect-dodge limit hits each enemy it touches once."""
    state = ctx.relic_state
    if state.get("ram_dash") != controller.dashes:
        state["ram_dash"] = controller.dashes
        state["ram_hit"] = set()
    if not actor.dashing or controller.perfect_dodge_locked:
        return
    for e in ctx.enemies:
        if not e.alive or e in state["ram_hit"]:
            continue
        if (e.position - actor.position).length() > e.radius + actor.radius + R.ram_reach:
            continue
        state["ram_hit"].add(e)
        crit = ctx.player_crits
        dmg = R.ram_damage * actor.damage_mult * (CRIT_MULT if crit else 1.0)
        e.take_damage(dmg, ctx, source=actor, knockback=R.ram_knockback, crit=crit)
        # the cost: a little of it comes back. It never kills you.
        actor.health = max(1.0, actor.health - R.ram_self)
        actor.flash = 0.1
        ctx.fx_text(actor.position, f"-{int(R.ram_self)}", C.BAD)
        ctx.shake(6.0)
        ctx.sfx("hit", None, 1.0)


def back_mult(enemy, shot) -> float:
    """KILLER INSTINCT: a shot travelling the way the enemy faces hit it from
    behind."""
    owner = shot.owner
    if not has(getattr(owner, "mods", None), "killer_instinct"):
        return 1.0
    if shot.velocity.length_squared() < 1.0:
        return 1.0
    facing = from_angle(enemy.aim)
    if facing.dot(shot.velocity.normalize()) > R.instinct_dot:
        return R.instinct_mult
    return 1.0


# ---------------------------------------------------------------------------
# passives
# ---------------------------------------------------------------------------
def on_kill(ctx, enemy, summoned):
    mods = ctx.mods
    if not mods["relics"]:
        return
    player = ctx.player_actor
    if has(mods, "vampiric") and not summoned and player is not None and player.alive:
        player.heal(R.vamp_heal)
        ctx.fx_text(player.position, f"+{int(R.vamp_heal)}", C.HEAL)
    if has(mods, "chain_fuse"):
        dmg = R.chain_damage * (player.damage_mult if player else 1.0)
        ctx.area_damage(enemy.position, R.chain_radius, dmg, knockback=320.0)
        ctx.explosion(enemy.position, R.chain_radius, RELIC_COLORS["passive"], small=True)


def on_player_hurt(ctx, actor):
    if has(actor.mods, "wardens_heart") and actor.alive:
        ctx.spawn_projectiles(ring(actor.position, R.heart_count,
                                   R.heart_damage * actor.damage_mult, 560.0,
                                   RELIC_COLORS["passive"], knockback=200.0,
                                   owner=actor, phase=actor.aim))


def witch_duration(mods, base):
    return base * (R.overclock_duration if has(mods, "overclock") else 1.0)


def perfect_window(mods, base):
    return base + (R.overclock_window if has(mods, "overclock") else 0.0)


# ---------------------------------------------------------------------------
# abilities
# ---------------------------------------------------------------------------
def use_ability(ctx, actor, key) -> bool:
    """True if it fired (and so should go on cooldown)."""
    if key in TIMED:
        ctx.start_buff(key, R.buff_time)
        return True
    if key == "judgement":
        crit = ctx.player_crits
        ctx.spawn_projectiles(ring(actor.position, R.nova_count,
                                   R.nova_damage * actor.damage_mult, R.nova_speed,
                                   RELIC_COLORS["ability"], knockback=R.nova_knockback,
                                   crit=crit, radius=8.0, owner=actor, phase=actor.aim))
        ctx.nova_fx(actor.position, RELIC_COLORS["ability"])
        return True
    if key == "shadow_step":
        return _shadow_step(ctx, actor)
    if key == "fuse_bomb":
        mouse = ctx.mouse_world
        to = mouse - actor.position
        if to.length() > R.bomb_range:
            to.scale_to_length(R.bomb_range)
        crit = ctx.player_crits
        dmg = R.bomb_damage * actor.damage_mult * (CRIT_MULT if crit else 1.0)
        ctx.spawn_projectiles([Bomb(actor.position, actor.position + to, dmg,
                                    owner=actor, crit=crit)])
        ctx.sfx("dagger_throw", None, 0.8)
        return True
    return False


def _shadow_step(ctx, actor):
    aim = from_angle(actor.aim)
    best, best_d = None, R.step_range
    for e in ctx.enemies:
        if not e.alive or e.vanished:
            continue
        to = e.position - actor.position
        d = to.length()
        if d < 1.0 or d > best_d:
            continue
        off = (aim.angle_to(to) + 180.0) % 360.0 - 180.0
        if abs(off) > R.step_cone:
            continue
        best, best_d = e, d
    if best is None:
        ctx.hud_say("NO TARGET", C.TEXT_DIM, 0.6)
        return False

    facing = from_angle(best.aim)
    room = ctx.room
    pad = actor.radius + 4
    field = room.inner.inflate(-pad * 2, -pad * 2)
    dist = best.radius + actor.radius + R.step_gap
    for turn in (0, 30, -30, 60, -60, 90, -90):
        dest = best.position - facing.rotate(turn) * dist
        if not field.collidepoint(dest.x, dest.y):
            continue
        if any(o.inflate(pad * 2, pad * 2).collidepoint(dest.x, dest.y)
               for o in room.obstacles):
            continue
        break
    else:
        ctx.hud_say("NO ROOM", C.TEXT_DIM, 0.6)
        return False

    frm = Vector2(actor.position)
    actor.position = Vector2(dest)
    actor.velocity = Vector2(0, 0)
    actor.aim = angle_of(best.position - dest)
    actor.invuln_t = max(actor.invuln_t, R.step_invuln)
    ctx.ambush(R.step_crit_time)
    ctx.shadow_step(actor, frm, dest)
    return True


class Bomb(Projectile):
    """FUSE BOMB: flies to a point, sits, blows. It rides in the projectile
    list with an empty hit mask, so shot resolution ignores it."""

    def __init__(self, pos, target, damage, owner=None, crit=False):
        to = Vector2(target) - Vector2(pos)
        vel = to.normalize() * R.bomb_speed if to.length() > 1 else Vector2(0, 0)
        super().__init__(pos, vel, damage, 99.0, 9.0, RELIC_COLORS["ability"],
                         0.0, Layer.PLAYER_SHOT, 0, owner=owner, crit=crit)
        self.target = Vector2(target)
        self.landed = to.length() <= 1
        self.fuse = R.bomb_fuse

    def physics_process(self, delta, ctx):
        self.trail = Vector2(self.position)
        if not self.landed:
            step = self.velocity * delta
            if (self.target - self.position).length() <= step.length():
                nxt = Vector2(self.target)
                self.landed = True
            else:
                nxt = self.position + step
            room = ctx.room
            blocked = (not room.inner.collidepoint(nxt.x, nxt.y) or
                       any(o.collidepoint(nxt.x, nxt.y) for o in room.obstacles))
            if blocked:
                self.landed = True          # stops against the wall it hit
            else:
                self.position = nxt
            if self.landed:
                self.velocity = Vector2(0, 0)
                ctx.sfx("fuse", self.position, 0.6)
            return
        self.fuse -= delta
        if self.fuse <= 0.0:
            ctx.area_damage(self.position, R.bomb_radius, self.damage,
                            knockback=420.0, crit=self.crit)
            ctx.explosion(self.position, R.bomb_radius, self.color)
            self.kill()

    def draw(self, surface, camera):
        sp = camera.to_screen(self.position)
        c = (int(sp.x), int(sp.y))
        if self.landed:
            t = 1.0 - clamp(self.fuse / R.bomb_fuse, 0.0, 1.0)
            pygame.draw.circle(surface, shade(self.color, 0.5 + 0.5 * t), c,
                               int(R.bomb_radius), 2)
            pygame.draw.circle(surface, shade(C.BAD, 0.6 + 0.4 * t), c,
                               int(lerp(10, R.bomb_radius, t)), 2)
        pygame.draw.circle(surface, shade(self.color, 0.4), c, 10)
        pygame.draw.circle(surface, tint(self.color, (255, 255, 255), 0.3), c, 7)
