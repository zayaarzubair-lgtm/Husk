"""
fx.py — feedback that carries information, as opposed to decoration.

Sparks live in weapons.py because they're part of a shot. What's here is the
stuff that tells you something you'd otherwise have to infer:

    FloatText  how much damage that actually did, and whether it crit
    Decal      where things have been dying — a room you've fought in should
               look like it

→ Godot: FloatText is a Label on a Tween; Decal is a Sprite2D you add to the
  level and never touch again (or a MultiMeshInstance2D if they ever get dense).
"""

import math
import random

import pygame
from pygame.math import Vector2

from .core import Entity, shade, tint
from .config import C


class FloatText(Entity):
    """A damage number. Rises, drifts, fades."""

    def __init__(self, pos, text, color, size=15, life=0.75, rise=64.0, drift=None):
        super().__init__(pos, 1.0, 0)
        self.text = text
        self.color = color
        self.size = size
        self.life = life
        self.max_life = life
        # story text passes drift=0 so it never draws from the game's random stream
        self.drift = Vector2(random.uniform(-26, 26), 0) if drift is None else Vector2(drift, 0)
        self.rise = rise
        self._img = None

    def physics_process(self, delta, ctx):
        self.life -= delta
        if self.life <= 0:
            self.kill()
            return
        t = 1.0 - self.life / self.max_life
        self.position += (self.drift + Vector2(0, -self.rise * (1.0 - t))) * delta

    def draw(self, surface, camera, font_for=None):
        if font_for is None:
            return
        t = max(0.0, self.life / self.max_life)
        if self._img is None:
            self._img = font_for(self.size).render(self.text, True, self.color)
        img = self._img
        if t < 0.5:
            img = img.copy()
            img.set_alpha(int(255 * (t / 0.5)))
        sp = camera.to_screen(self.position)
        surface.blit(img, img.get_rect(center=(int(sp.x), int(sp.y))))


def damage_text(pos, amount, crit=False, to_player=False):
    if to_player:
        return FloatText(pos + Vector2(0, -22), f"-{int(math.ceil(amount))}",
                         C.BAD, size=18, life=0.85, rise=52)
    if crit:
        return FloatText(pos + Vector2(0, -18), f"{int(math.ceil(amount))}!",
                         C.CRIT, size=20, life=0.9, rise=82)
    return FloatText(pos + Vector2(0, -18), str(int(math.ceil(amount))),
                     (232, 236, 245), size=14, life=0.6, rise=58)


class Decal:
    """A permanent smear on a room's floor. Not an Entity — it never updates,
    it just gets drawn with the room. Rooms own their own."""

    __slots__ = ("pos", "radius", "color", "blobs")

    def __init__(self, pos, radius, color, rng=None):
        rng = rng or random
        self.pos = Vector2(pos)
        self.radius = radius
        self.color = shade(color, 0.42)
        # a few overlapping blobs read as a splat; one circle reads as a bug
        self.blobs = []
        for _ in range(rng.randint(3, 6)):
            a = rng.uniform(0, math.tau)
            d = rng.uniform(0, radius * 0.75)
            self.blobs.append((math.cos(a) * d, math.sin(a) * d,
                               rng.uniform(radius * 0.35, radius * 0.8)))

    def draw(self, surface, ox, oy):
        for dx, dy, r in self.blobs:
            pygame.draw.circle(surface, self.color,
                               (int(self.pos.x + dx - ox), int(self.pos.y + dy - oy)),
                               int(r))


class Shockwave(Entity):
    """An expanding ring. Used for possession and for the Witch Time trigger —
    both are moments that need to read as *events*, not as state changes."""

    def __init__(self, pos, color, r0=10.0, r1=150.0, life=0.42, width=4):
        super().__init__(pos, 1.0, 0)
        self.color = color
        self.r0 = r0
        self.r1 = r1
        self.life = life
        self.max_life = life
        self.width = width

    def physics_process(self, delta, ctx):
        self.life -= delta
        if self.life <= 0:
            self.kill()

    def draw(self, surface, camera, font_for=None):
        t = 1.0 - max(0.0, self.life / self.max_life)
        # ease-out so it snaps open and settles
        e = 1.0 - (1.0 - t) ** 3
        r = int(self.r0 + (self.r1 - self.r0) * e)
        w = max(1, int(self.width * (1.0 - t)))
        sp = camera.to_screen(self.position)
        pygame.draw.circle(surface, shade(self.color, 0.4 + 0.6 * (1.0 - t)),
                           (int(sp.x), int(sp.y)), max(2, r), w)


def directional_sparks(pos, direction, color, count=7, spread=1.0,
                       speed=(120, 380), life=0.28):
    """Impact spray that follows the hit rather than puffing symmetrically —
    tells you which way the shot came from."""
    from .weapons import Spark
    out = []
    base = math.atan2(direction.y, direction.x) if direction.length() > 0.001 else 0.0
    for _ in range(count):
        a = base + random.uniform(-spread, spread)
        sp = random.uniform(*speed)
        out.append(Spark(pos, Vector2(math.cos(a), math.sin(a)) * sp,
                         tint(color, (255, 255, 255), random.uniform(0, 0.4)),
                         life=life * random.uniform(0.6, 1.3)))
    return out
