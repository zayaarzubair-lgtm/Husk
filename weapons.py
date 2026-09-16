"""
weapons.py — projectiles and the firing logic every body shares.

→ Godot: Projectile is an Area2D scene with a CollisionShape2D and a
  VisibleOnScreenNotifier; `fire()` becomes the weapon scene's shoot()
  spawning instances. WeaponStats is a Resource on that scene.

Phase 1 of the roadmap, but written once for everyone: the player, every
enemy, and every body you possess all fire through this. That's what makes
inheriting an enemy's gun (§3.5) free rather than a special case.
"""

import math
import random
import pygame
from pygame.math import Vector2

from .core import Entity, from_angle, shade, tint
from .config import C, WitchTimeStats

CRIT_MULT = WitchTimeStats().crit_multiplier


class Projectile(Entity):
    __slots__ = ("damage", "life", "max_life", "color", "knockback", "owner",
                 "crit", "hit_mask", "trail", "poison", "pierce", "hits", "seek",
                 "shatter")

    def __init__(self, pos, velocity, damage, lifetime, radius, color,
                 knockback, layer, hit_mask, owner=None, crit=False):
        super().__init__(pos, radius, layer)
        self.velocity = Vector2(velocity)
        self.damage = damage
        self.life = lifetime
        self.max_life = lifetime
        self.color = color
        self.knockback = knockback
        self.owner = owner
        self.crit = crit
        self.hit_mask = hit_mask
        self.trail = Vector2(pos)
        self.poison = 0
        self.pierce = 0          # enemies it can still pass through
        self.hits = None         # the ones it already has
        self.seek = None         # (turn deg/s, range px) while it homes
        self.shatter = 0         # fragments it bursts into on a hit

    def physics_process(self, delta: float, ctx):
        self.life -= delta
        if self.life <= 0.0:
            self.kill()
            return
        self.trail = Vector2(self.position)
        if self.seek is not None:
            self._steer(delta, ctx)
        self.position += self.velocity * delta
        # Walls stop shots. The room bounds count as walls.
        room = ctx.room
        if not room.inner.collidepoint(self.position.x, self.position.y):
            ctx.spawn_impact(self.position, self.color)
            ctx.sfx("wall_hit", self.position, 0.5)
            self.kill()
            return
        for o in room.obstacles:
            if o.collidepoint(self.position.x, self.position.y):
                ctx.spawn_impact(self.position, self.color)
                ctx.sfx("wall_hit", self.position, 0.5)
                self.kill()
                return

    def _steer(self, delta, ctx):
        """SEEKER ROUNDS: turn toward the nearest live enemy, at a capped rate."""
        turn, reach = self.seek
        best, best_d = None, reach
        for e in ctx.enemies:
            if not e.alive or e.vanished or (self.hits and e in self.hits):
                continue
            d = (e.position - self.position).length()
            if d < best_d:
                best, best_d = e, d
        if best is None or self.velocity.length_squared() < 1.0:
            return
        # an armoured body is sought at its weak point, not its middle
        wp = best.weak_point
        goal = wp if wp is not None else best.position
        off = (self.velocity.angle_to(goal - self.position) + 180.0) % 360.0 - 180.0
        step = turn * delta
        self.velocity.rotate_ip(max(-step, min(step, off)))

    def draw(self, surface, camera):
        sp = camera.to_screen(self.position)
        tp = camera.to_screen(self.trail)
        col = C.CRIT if self.crit else self.color
        r = int(self.radius * (1.25 if self.crit else 1.0))
        # motion streak — reads much better than a bare dot at these speeds
        if (sp - tp).length_squared() > 4:
            pygame.draw.line(surface, shade(col, 0.55), (tp.x, tp.y), (sp.x, sp.y), max(2, r))
        pygame.draw.circle(surface, col, (int(sp.x), int(sp.y)), r)
        pygame.draw.circle(surface, tint(col, (255, 255, 255), 0.55),
                           (int(sp.x), int(sp.y)), max(1, r - 2))


def fire(stats, origin: Vector2, aim: float, layer: int, hit_mask: int,
         owner=None, crit: bool = False, damage_mult: float = 1.0):
    """Build the projectiles for one trigger pull. Returns a list so burst and
    shotgun weapons are the same code path as a single shot."""
    shots = []
    n = max(1, stats.pellets)
    for i in range(n):
        if stats.radial:
            # even ring, rotated by aim so it still reads as "aimed"
            ang = aim + (math.tau * i / n)
        else:
            spread = math.radians(stats.spread_deg)
            ang = aim + random.uniform(-spread, spread)
        vel = from_angle(ang) * stats.speed
        shots.append(Projectile(
            pos=origin + from_angle(ang) * 14.0,
            velocity=vel,
            # §3.4: everything you land in Witch Time crits
            damage=stats.damage * damage_mult * (CRIT_MULT if crit else 1.0),
            lifetime=stats.lifetime,
            radius=stats.proj_radius,
            color=stats.color,
            knockback=stats.knockback,
            layer=layer,
            hit_mask=hit_mask,
            owner=owner,
            crit=crit,
        ))
    for sh in shots:
        sh.poison = stats.poison
    return shots


# ---------------------------------------------------------------------------
# Impact / muzzle sparks. Pure decoration, but the game reads as broken without
# some acknowledgement that a bullet stopped existing.
# → Godot: a GPUParticles2D one-shot scene.
# ---------------------------------------------------------------------------
class Spark(Entity):
    __slots__ = ("life", "max_life", "color", "drag")

    def __init__(self, pos, velocity, color, life=0.3, drag=4.0):
        super().__init__(pos, 2.0, 0)
        self.velocity = Vector2(velocity)
        self.color = color
        self.life = life
        self.max_life = life
        self.drag = drag

    def physics_process(self, delta, ctx):
        self.life -= delta
        if self.life <= 0:
            self.kill()
            return
        self.position += self.velocity * delta
        self.velocity *= max(0.0, 1.0 - self.drag * delta)

    def draw(self, surface, camera):
        t = max(0.0, self.life / self.max_life)
        sp = camera.to_screen(self.position)
        r = max(1, int(3 * t))
        pygame.draw.circle(surface, shade(self.color, 0.4 + 0.6 * t),
                           (int(sp.x), int(sp.y)), r)


def burst_sparks(pos, color, count=7, speed=(90, 320), life=0.3):
    out = []
    for _ in range(count):
        ang = random.uniform(0, math.tau)
        sp = random.uniform(*speed)
        out.append(Spark(pos, from_angle(ang) * sp, color, life=life * random.uniform(0.6, 1.2)))
    return out
