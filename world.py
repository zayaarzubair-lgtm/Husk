"""
world.py — rooms and floor generation (roadmap Phase 5).

Soul Knight's structure: one room at a time, doors lock behind you, clear the
room and they open. That shape is worth copying because it makes every fight a
bounded arena — which is what the dodge-and-counter loop (§3.4) needs. An open
world would let you walk away from every telegraph.

Layout: rooms sit on a grid, each occupying its own slice of world space, so a
room's world rect doubles as the camera's limits and the minimap's coordinates.

→ Godot: each Room becomes a scene (TileMapLayer floor + StaticBody2D walls and
  crates), the grid becomes a Resource, and switching rooms is
  get_tree().change_scene_to_packed() or just moving the active scene node.
"""

import random
import pygame
from pygame.math import Vector2

from . import art
from .config import (C, DungeonStats, EliteStats, SPAWN_TABLE, ARCHETYPES,
                     MAX_ROOM_ENEMIES, BOSS_BY_DEPTH)

ELITE = EliteStats()

SIDES = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}


class Room:
    def __init__(self, gx, gy, kind, ds: DungeonStats):
        self.gx, self.gy = gx, gy
        self.kind = kind                  # start | combat | treasure | boss
        self.ds = ds
        self.rect = pygame.Rect(gx * ds.room_w, gy * ds.room_h, ds.room_w, ds.room_h)
        t = ds.wall_thickness
        self.inner = self.rect.inflate(-2 * t, -2 * t)
        self.doors = {}                   # side -> (gx, gy) of the neighbour
        self.obstacles = []
        self.spawns = []                  # [(archetype_name, Vector2)]
        self.pickups = []                 # [(kind, Vector2, amount)]
        self.cleared = kind in ("start", "treasure")
        self.visited = False
        self.spawned = False
        self.decals = []                  # permanent floor smears; rooms own them
        self.depth = 0                    # set by Floor; picks the room's look

    # -- doors ---------------------------------------------------------------
    def door_zone(self, side) -> pygame.Rect:
        """The strip of floor that counts as 'standing in the doorway'."""
        w = self.ds.door_width
        depth = 54
        if side == "n":
            return pygame.Rect(self.inner.centerx - w // 2, self.inner.top, w, depth)
        if side == "s":
            return pygame.Rect(self.inner.centerx - w // 2, self.inner.bottom - depth, w, depth)
        if side == "w":
            return pygame.Rect(self.inner.left, self.inner.centery - w // 2, depth, w)
        return pygame.Rect(self.inner.right - depth, self.inner.centery - w // 2, depth, w)

    def door_bar(self, side) -> pygame.Rect:
        """The visible slab in the wall itself."""
        w = self.ds.door_width
        t = self.ds.wall_thickness
        if side == "n":
            return pygame.Rect(self.inner.centerx - w // 2, self.inner.top - t, w, t)
        if side == "s":
            return pygame.Rect(self.inner.centerx - w // 2, self.inner.bottom, w, t)
        if side == "w":
            return pygame.Rect(self.inner.left - t, self.inner.centery - w // 2, t, w)
        return pygame.Rect(self.inner.right, self.inner.centery - w // 2, t, w)

    def entry_point(self, from_side) -> Vector2:
        """Where the player materialises when arriving through `from_side`."""
        z = self.door_zone(from_side)
        c = Vector2(z.center)
        dx, dy = SIDES[from_side]
        return c - Vector2(dx, dy) * 86.0

    def standing_in_door(self, pos: Vector2):
        for side in self.doors:
            if self.door_zone(side).collidepoint(pos.x, pos.y):
                return side
        return None

    # -- drawing -------------------------------------------------------------
    def draw(self, surface, camera):
        art.draw_room(surface, self, camera)

    def draw_placeholder(self, surface, camera):
        """The pre-art room: flat floor, grid, grey crates."""
        ox, oy = camera.offset.x, camera.offset.y
        vis = camera.visible_rect()

        surface.fill(C.BG)
        floor = self.inner.move(-ox, -oy)
        pygame.draw.rect(surface, C.FLOOR, floor)

        # grid (visible span only — ≈ a tiled floor)
        g = 64
        x0 = self.inner.left - (self.inner.left % g)
        for x in range(int(x0), self.inner.right, g):
            if vis.left <= x <= vis.right:
                pygame.draw.line(surface, C.GRID, (x - ox, floor.top), (x - ox, floor.bottom))
        y0 = self.inner.top - (self.inner.top % g)
        for y in range(int(y0), self.inner.bottom, g):
            if vis.top <= y <= vis.bottom:
                pygame.draw.line(surface, C.GRID, (floor.left, y - oy), (floor.right, y - oy))

        # walls
        pygame.draw.rect(surface, C.WALL, self.rect.move(-ox, -oy),
                         self.ds.wall_thickness * 2)
        pygame.draw.rect(surface, C.WALL_EDGE, floor.inflate(4, 4), 2)

        # doors
        for side in self.doors:
            bar = self.door_bar(side).move(-ox, -oy)
            col = C.DOOR_OPEN if self.cleared else C.DOOR_SHUT
            pygame.draw.rect(surface, col, bar)
            pygame.draw.rect(surface, (14, 16, 22), bar, 2)
            if not self.cleared:
                # bars, so a locked door reads as locked at a glance
                for i in range(1, 5):
                    if side in "ns":
                        x = bar.left + bar.width * i / 5
                        pygame.draw.line(surface, (20, 22, 30), (x, bar.top), (x, bar.bottom), 3)
                    else:
                        y = bar.top + bar.height * i / 5
                        pygame.draw.line(surface, (20, 22, 30), (bar.left, y), (bar.right, y), 3)

        # decals go down on the floor, under everything that moves
        for d in self.decals:
            d.draw(surface, ox, oy)

        # crates
        for o in self.obstacles:
            if not o.colliderect(vis):
                continue
            r = o.move(-ox, -oy)
            pygame.draw.rect(surface, C.CRATE, r)
            pygame.draw.rect(surface, C.CRATE_EDGE, r, 2)
            pygame.draw.line(surface, C.CRATE_EDGE, (r.left + 4, r.top + 4),
                             (r.right - 5, r.top + 4), 2)


# ---------------------------------------------------------------------------
# Floor generation
# ---------------------------------------------------------------------------
class Floor:
    def __init__(self, depth: int, ds: DungeonStats, rng: random.Random):
        self.depth = depth
        self.ds = ds
        self.rng = rng
        self.rooms = {}                   # (gx, gy) -> Room
        self.start = (0, 0)
        self.boss = None
        self._generate()

    # -- layout --------------------------------------------------------------
    def _generate(self):
        ds, rng = self.ds, self.rng
        target = ds.rooms_per_floor[min(self.depth, len(ds.rooms_per_floor) - 1)]

        # Random walk with a bias away from where we've been, so floors come out
        # sprawling rather than clumped. Grid bounds keep it finite.
        sx, sy = ds.grid_w // 2, ds.grid_h // 2
        cells = {(sx, sy)}
        cur = (sx, sy)
        guard = 0
        while len(cells) < target and guard < 800:
            guard += 1
            sides = list(SIDES.values())
            rng.shuffle(sides)
            moved = False
            for dx, dy in sides:
                nx, ny = cur[0] + dx, cur[1] + dy
                if not (0 <= nx < ds.grid_w and 0 <= ny < ds.grid_h):
                    continue
                if (nx, ny) in cells and rng.random() < 0.7:
                    continue
                cells.add((nx, ny))
                cur = (nx, ny)
                moved = True
                break
            if not moved:
                cur = rng.choice(sorted(cells))

        self.start = (sx, sy)
        # The boss goes as far from the entrance as the layout allows.
        self.boss = max(cells, key=lambda c: abs(c[0] - sx) + abs(c[1] - sy))

        # Treasure: prefer a dead end that isn't the boss or the start.
        others = [c for c in cells if c not in (self.start, self.boss)]
        treasure = None
        if others:
            dead_ends = [c for c in others if self._degree(c, cells) == 1]
            treasure = rng.choice(sorted(dead_ends) if dead_ends else sorted(others))

        for c in sorted(cells):
            kind = ("start" if c == self.start else
                    "boss" if c == self.boss else
                    "treasure" if c == treasure else "combat")
            self.rooms[c] = Room(c[0], c[1], kind, self.ds)
            self.rooms[c].depth = self.depth

        # Connect every pair of adjacent rooms — loops make a floor feel like a
        # place rather than a corridor.
        for c, room in self.rooms.items():
            for side, (dx, dy) in SIDES.items():
                n = (c[0] + dx, c[1] + dy)
                if n in self.rooms:
                    room.doors[side] = n

        for room in self.rooms.values():
            self._furnish(room)

    def _degree(self, cell, cells):
        return sum(1 for dx, dy in SIDES.values()
                   if (cell[0] + dx, cell[1] + dy) in cells)

    # -- contents ------------------------------------------------------------
    def _furnish(self, room: Room):
        rng = self.rng
        ds = self.ds

        # -- crates --
        keep_clear = [room.door_zone(s).inflate(140, 140) for s in room.doors]
        n = rng.randint(ds.obstacle_min, ds.obstacle_max)
        if room.kind == "boss":
            n = max(2, n // 2)            # the Warden needs room to charge
        placed = []
        field = room.inner.inflate(-110, -110)
        for _ in range(n * 14):
            if len(placed) >= n:
                break
            w = rng.choice((60, 80, 90, 120, 160))
            h = rng.choice((60, 80, 90, 120, 160))
            if w > 120 and h > 120:
                h = 80
            x = rng.randint(field.left, max(field.left, field.right - w))
            y = rng.randint(field.top, max(field.top, field.bottom - h))
            cand = pygame.Rect(x, y, w, h)
            if any(cand.colliderect(z) for z in keep_clear):
                continue
            # leave a body-width of slack between crates so nothing becomes a
            # pocket the AI (or the player) can wedge into
            if any(cand.inflate(76, 76).colliderect(p) for p in placed):
                continue
            if cand.inflate(90, 90).collidepoint(room.inner.center):
                continue
            placed.append(cand)
        room.obstacles = placed

        # -- occupants --
        if room.kind == "combat":
            count = int(round(ds.enemies_base + self.depth * ds.enemies_per_depth))
            count = max(2, min(9, count + rng.randint(-1, 1)))
            table = SPAWN_TABLE[min(self.depth, len(SPAWN_TABLE) - 1)]
            names = [k for k, v in table.items() for _ in range(v)]
            elite_p = ELITE.chance_by_depth[min(self.depth, len(ELITE.chance_by_depth) - 1)]
            for _ in range(count):
                pos = self._free_point(room)
                if pos is None:
                    continue
                name = rng.choice(names)
                lo, hi = ARCHETYPES[name].pack
                for k in range(rng.randint(lo, hi)):
                    if len(room.spawns) >= MAX_ROOM_ENEMIES:
                        break
                    # a pack arrives bunched up; the leader takes the free point
                    p = pos if k == 0 else self._near_point(room, pos)
                    if p is not None:
                        room.spawns.append((name, p, rng.random() < elite_p))
        elif room.kind == "boss":
            boss = BOSS_BY_DEPTH[min(self.depth, len(BOSS_BY_DEPTH) - 1)]
            room.spawns.append((boss, Vector2(room.inner.center), False))
        elif room.kind == "treasure":
            room.pickups.append(("upgrade", Vector2(room.inner.center), 0.0))

    def _near_point(self, room: Room, around: Vector2, spread=70, tries=20):
        rng = self.rng
        field = room.inner.inflate(-60, -60)
        for _ in range(tries):
            p = around + Vector2(rng.uniform(-spread, spread), rng.uniform(-spread, spread))
            if not field.collidepoint(p.x, p.y):
                continue
            if any(o.inflate(40, 40).collidepoint(p.x, p.y) for o in room.obstacles):
                continue
            return p
        return None

    def _free_point(self, room: Room, tries=60) -> Vector2:
        rng = self.rng
        field = room.inner.inflate(-90, -90)
        door_centers = [Vector2(room.door_zone(s).center) for s in room.doors]
        for _ in range(tries):
            p = Vector2(rng.randint(field.left, field.right),
                        rng.randint(field.top, field.bottom))
            if any(o.inflate(40, 40).collidepoint(p.x, p.y) for o in room.obstacles):
                continue
            if any((p - d).length() < 230 for d in door_centers):
                continue
            return p
        return None
