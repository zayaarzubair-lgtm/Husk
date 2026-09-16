"""
pickups.py — things on the floor you walk into.

→ Godot: Area2D scenes with a `body_entered` signal; this file's `collect()`
  becomes that signal's handler.
"""

import math
import pygame

from .core import Entity, Layer, shade, tint
from .config import C
from . import art


class Pickup(Entity):
    """kind: "health" | "upgrade" | "relic" | "stairs"."""

    def __init__(self, pos, kind, amount=0.0):
        super().__init__(pos, 16.0, Layer.PICKUP)
        self.kind = kind
        self.amount = amount
        self.t = 0.0
        self.armed = 0.35        # s before it can be picked up (so drops don't
                                 # get eaten by the shot that created them)

    @property
    def color(self):
        return {"health": C.HEAL, "upgrade": C.UPGRADE, "relic": C.CRIT,
                "stairs": C.STAIRS}[self.kind]

    def physics_process(self, delta, ctx):
        self.t += delta
        self.armed = max(0.0, self.armed - delta)
        player = ctx.player_actor
        if player is None or not player.alive or self.armed > 0:
            return
        # health drifts toward you when you're close — nothing is more annoying
        # than clipping the edge of a heal at 4hp
        d = player.position - self.position
        dist = d.length()
        if self.kind == "health" and dist < 150 and dist > 1:
            self.position += d.normalize() * (420.0 - dist * 1.6) * delta
        if dist <= player.radius + self.radius:
            ctx.collect(self)

    def draw(self, surface, camera):
        sp = camera.to_screen(self.position)
        bob = math.sin(self.t * 3.4) * 3.0
        x, y = int(sp.x), int(sp.y + bob)
        col = self.color
        r = int(self.radius)

        if self.kind == "relic":
            # a boss's leavings: a slowly turning gold star
            rr = 15 + 2 * math.sin(self.t * 2.2)
            pts = []
            for i in range(10):
                a = self.t * 0.8 + i * math.pi / 5
                d = rr if i % 2 == 0 else rr * 0.45
                pts.append((x + math.cos(a) * d, y + math.sin(a) * d))
            pygame.draw.circle(surface, shade(col, 0.3), (x, y), int(rr + 8))
            pygame.draw.polygon(surface, col, pts)
            pygame.draw.circle(surface, tint(col, (255, 255, 255), 0.6), (x, y), 3)
            return

        if self.kind == "stairs":
            if art.draw_pickup(surface, "stairs", (x, int(sp.y))):
                return
            rect = pygame.Rect(x - 22, y - 22, 44, 44)
            pygame.draw.rect(surface, shade(col, 0.35), rect, border_radius=6)
            pygame.draw.rect(surface, col, rect, 3, border_radius=6)
            for i in range(3):
                yy = y - 11 + i * 9
                pygame.draw.line(surface, col, (x - 13 + i * 4, yy), (x + 14, yy), 3)
            return

        # a soft glow under the item so it reads on any floor
        pygame.draw.circle(surface, shade(col, 0.25), (x, int(sp.y) + 10), r)
        if art.draw_pickup(surface, self.kind, (x, y)):
            return
        pygame.draw.circle(surface, shade(col, 0.3), (x, y), r + 3)
        pygame.draw.circle(surface, col, (x, y), r, 2)
        if self.kind == "health":
            pygame.draw.line(surface, col, (x - 6, y), (x + 6, y), 4)
            pygame.draw.line(surface, col, (x, y - 6), (x, y + 6), 4)
        else:
            pts = [(x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)]
            pygame.draw.polygon(surface, tint(col, (255, 255, 255), 0.3), pts)
