"""
core.py — the shared foundation every entity sits on.

→ Godot map:
    move_toward()  → Vector2.move_toward() (this is an exact reimplementation)
    Signal         → `signal x` / x.connect(fn) / x.emit(...)
    Layer          → collision layers & masks on the physics bodies
    Entity         → Node2D with _process/_physics_process/_draw
    Camera         → Camera2D with limit_* set to the room bounds
    resolve_circle_rects() → move_and_slide(), i.e. DELETE ON PORT (§4: keep the
      collision scaffolding isolated in one place so removing it is a clean cut)
"""

import math
import random
import pygame
from pygame.math import Vector2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def move_toward(current: Vector2, target: Vector2, max_delta: float) -> Vector2:
    """Step `current` toward `target` by at most `max_delta`. Exact
    reimplementation of Godot's Vector2.move_toward(), so the movement code
    that uses it ports across unchanged."""
    diff = target - current
    dist = diff.length()
    if dist <= max_delta or dist == 0:
        return Vector2(target)
    return current + diff * (max_delta / dist)


def approach(current: float, target: float, max_delta: float) -> float:
    """Scalar move_toward — for timers and eased HUD values."""
    if abs(target - current) <= max_delta:
        return target
    return current + math.copysign(max_delta, target - current)


def from_angle(rad: float) -> Vector2:
    return Vector2(math.cos(rad), math.sin(rad))


def angle_of(v: Vector2) -> float:
    return math.atan2(v.y, v.x)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def tint(color, other, t):
    """Blend two RGB triples."""
    return (int(lerp(color[0], other[0], t)),
            int(lerp(color[1], other[1], t)),
            int(lerp(color[2], other[2], t)))


def shade(color, f):
    """Scale brightness, clamped."""
    return (clamp(int(color[0] * f), 0, 255),
            clamp(int(color[1] * f), 0, 255),
            clamp(int(color[2] * f), 0, 255))


def desaturate(color, t):
    g = color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114
    return tint(color, (g, g, g), t)


# ---------------------------------------------------------------------------
# Signal  ──  §4: "Events use the signal pattern." Decoupled events (hit, death,
# possess) all go through this rather than through direct calls.
# ---------------------------------------------------------------------------
class Signal:
    __slots__ = ("_fns",)

    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)
        return fn

    def disconnect(self, fn):
        if fn in self._fns:
            self._fns.remove(fn)

    def emit(self, *args):
        for fn in list(self._fns):
            fn(*args)


# ---------------------------------------------------------------------------
# Layer  ──  who can hit whom. → Godot: collision_layer / collision_mask bits.
# Kept as plain ints so the port is a copy of the numbers into the inspector.
# ---------------------------------------------------------------------------
class Layer:
    WALL        = 1 << 0
    PLAYER      = 1 << 1
    ENEMY       = 1 << 2
    PLAYER_SHOT = 1 << 3
    ENEMY_SHOT  = 1 << 4
    PICKUP      = 1 << 5


# ---------------------------------------------------------------------------
# Entity  ──  §4: "Entities share a base." Player, enemies, projectiles and
# pickups all inherit this, which is what lets the possession system swap
# control between any two of them without caring what they are.
# ---------------------------------------------------------------------------
class Entity:
    def __init__(self, pos, radius: float = 8.0, layer: int = 0):
        self.position = Vector2(pos)
        self.velocity = Vector2(0, 0)
        self.radius = radius
        self.layer = layer
        self.alive = True

    # ≈ _process(delta): render-rate logic only (visuals, aim).
    def process(self, delta: float, ctx):
        pass

    # ≈ _physics_process(delta): all movement and collision.
    def physics_process(self, delta: float, ctx):
        pass

    def draw(self, surface, camera):
        pass

    def kill(self):
        self.alive = False

    def distance_to(self, other) -> float:
        return (other.position - self.position).length()


# ---------------------------------------------------------------------------
# Camera  ──  Godot Camera2D with limits. Follows with a little lag so dashes
# read as fast, plus screenshake on impacts.
# ---------------------------------------------------------------------------
class Camera:
    def __init__(self, viewport, bounds: pygame.Rect):
        self.viewport = viewport
        self.bounds = bounds
        self.offset = Vector2(0, 0)
        self.center = Vector2(bounds.center)
        self._shake = 0.0
        self._shake_off = Vector2(0, 0)
        self.lag = 12.0            # higher = snappier follow

    def set_bounds(self, bounds: pygame.Rect):
        self.bounds = bounds

    def snap_to(self, target: Vector2):
        self.center = Vector2(target)
        self._recompute()

    def shake(self, amount: float):
        self._shake = min(22.0, self._shake + amount)

    def follow(self, target: Vector2, delta: float):
        # exponential smoothing, framerate-independent
        t = 1.0 - math.exp(-self.lag * delta)
        self.center += (Vector2(target) - self.center) * t
        if self._shake > 0.01:
            self._shake = max(0.0, self._shake - 60.0 * delta)
            self._shake_off = Vector2(random.uniform(-1, 1), random.uniform(-1, 1)) * self._shake
        else:
            self._shake_off = Vector2(0, 0)
        self._recompute()

    def _recompute(self):
        vw, vh = self.viewport
        x = self.center.x - vw / 2
        y = self.center.y - vh / 2
        # clamp to the room (≈ Camera2D limit_left/right/top/bottom)
        x = max(self.bounds.left, min(self.bounds.right - vw, x))
        y = max(self.bounds.top,  min(self.bounds.bottom - vh, y))
        # If the room is smaller than the view, center it — relative to the
        # room's OWN origin, since rooms are laid out across a grid and almost
        # never start at (0, 0).
        if vw > self.bounds.width:
            x = self.bounds.left + (self.bounds.width - vw) / 2
        if vh > self.bounds.height:
            y = self.bounds.top + (self.bounds.height - vh) / 2
        self.offset = Vector2(x, y) + self._shake_off

    def to_screen(self, world: Vector2) -> Vector2:
        return Vector2(world) - self.offset

    def to_world(self, screen) -> Vector2:
        return Vector2(screen) + self.offset

    def visible_rect(self) -> pygame.Rect:
        vw, vh = self.viewport
        return pygame.Rect(int(self.offset.x) - 40, int(self.offset.y) - 40, vw + 80, vh + 80)


# ---------------------------------------------------------------------------
# COLLISION SCAFFOLDING
# ---------------------------------------------------------------------------
# Everything below is Pygame doing by hand what Godot's move_and_slide() does
# natively. §4: keep it isolated here so the port is a clean deletion. No game
# logic should do collision maths of its own.
# ---------------------------------------------------------------------------

def circle_rect_overlap(pos: Vector2, r: float, rect: pygame.Rect) -> float:
    """Penetration depth (>0 when overlapping), else 0."""
    cx = max(rect.left, min(pos.x, rect.right))
    cy = max(rect.top, min(pos.y, rect.bottom))
    d = math.hypot(pos.x - cx, pos.y - cy)
    return r - d if d < r else 0.0


def _resolve_axis(pos: Vector2, vel: Vector2, r: float, axis: str, rects, extra=None):
    for o in rects:
        cx = max(o.left, min(pos.x, o.right))
        cy = max(o.top, min(pos.y, o.bottom))
        dx, dy = pos.x - cx, pos.y - cy
        if dx * dx + dy * dy < r * r:
            if axis == "x":
                pos.x = o.right + r if pos.x > o.centerx else o.left - r
                vel.x = 0
                if extra is not None:
                    extra.x = 0
            else:
                pos.y = o.bottom + r if pos.y > o.centery else o.top - r
                vel.y = 0
                if extra is not None:
                    extra.y = 0


def resolve_circle_rects(pos: Vector2, vel: Vector2, r: float, delta: float,
                         rects, bounds: pygame.Rect = None, dash_dir: Vector2 = None):
    """Move by `vel * delta`, resolving X then Y separately so we slide along a
    wall instead of sticking to it.

    `dash_dir` is zeroed on the blocked axis alongside velocity. Without that, a
    dash into a wall keeps rewriting velocity at full dash speed every tick and
    grinds in place for its whole duration; with it, the dash slides along the
    wall on the free axis and a head-on dash simply stops. We deliberately do
    NOT renormalize dash_dir — losing the blocked component costs you speed on a
    glancing hit, which is what move_and_slide() does natively.

    → Godot: this entire function is `move_and_slide()`.
    """
    pos.x += vel.x * delta
    _resolve_axis(pos, vel, r, "x", rects, dash_dir)
    pos.y += vel.y * delta
    _resolve_axis(pos, vel, r, "y", rects, dash_dir)
    if bounds is not None:
        pos.x = max(bounds.left + r, min(bounds.right - r, pos.x))
        pos.y = max(bounds.top + r, min(bounds.bottom - r, pos.y))


def separate(a, b, push: float = 0.5):
    """Push two overlapping bodies apart. → Godot: physics does this for you."""
    d = b.position - a.position
    dist = d.length()
    min_d = a.radius + b.radius
    if dist <= 0.0001:
        d = Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
        dist = d.length() or 1.0
    if dist < min_d:
        n = d / dist
        overlap = (min_d - dist) * push
        a.position -= n * overlap
        b.position += n * overlap


def segment_hits_rects(a: Vector2, b: Vector2, rects) -> bool:
    """Cheap line-of-sight test: does the segment a→b cross any rect?
    Sampled rather than analytic — it only feeds AI decisions, so being a few
    pixels off never shows. → Godot: a real raycast on the wall layer."""
    d = b - a
    steps = max(2, int(d.length() / 24))
    for i in range(1, steps + 1):
        p = a + d * (i / steps)
        for r in rects:
            if r.collidepoint(p.x, p.y):
                return True
    return False


def time_to_impact(shooter_pos: Vector2, shooter_vel: Vector2,
                   target_pos: Vector2, hit_radius: float, horizon: float):
    """When will a body travelling at constant velocity come within hit_radius
    of target_pos? Returns seconds, or None if it never does inside `horizon`.

    This is the maths behind perfect-dodge detection (§3.4): a dash is "perfect"
    if something was about to land on you when you started it.
    """
    rel = shooter_pos - target_pos
    v = shooter_vel
    vv = v.dot(v)
    if vv < 1e-6:
        return None
    # |rel + v*t| = hit_radius  →  quadratic in t
    b = 2.0 * rel.dot(v)
    c = rel.dot(rel) - hit_radius * hit_radius
    if c <= 0.0:
        return 0.0                      # already touching
    disc = b * b - 4.0 * vv * c
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    t = (-b - sq) / (2.0 * vv)
    if t < 0.0:
        t = (-b + sq) / (2.0 * vv)
    if t < 0.0 or t > horizon:
        return None
    return t
