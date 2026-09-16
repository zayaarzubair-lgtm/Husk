"""
art.py — every sprite and texture, and where each one comes from.

Two sources, one seam:

  1. Real art. Drop PNGs into husk/assets/ (see assets/README.md) and they win,
     one file at a time — the same deal as audio.py's synthesised sounds.
  2. Code-drawn pixel art. Anything without a file is drawn here at boot, at a
     small "art resolution" and scaled up with nearest-neighbour (§4), so the
     whole game reads as one pixel-art style.

Bodies are drawn side-on, Soul Knight style: the body faces left or right
toward its aim, and its weapon is a separate sprite that rotates in its hand.
Hitboxes are unchanged — art is decoration. Everything the player must READ
(telegraphs, weak points, elite rings, the take-me window) is still drawn on top
by the entities themselves.

→ Godot: each body becomes an AnimatedSprite2D with a SpriteFrames resource
  (the same anim names as ANIMS below) and a child Sprite2D for the weapon;
  rooms become a TileMapLayer and the props are scenes.
"""

import math
import os
import random

import pygame
from pygame.math import Vector2

from .config import C, ARCHETYPES
from .core import shade, tint, clamp

SCALE = 2                                   # art pixel -> screen pixels
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

OUTLINE = (10, 10, 16)
BONE = (214, 206, 186)
IRON = (104, 108, 122)
IRON_D = (62, 64, 76)
WOOD = (104, 74, 50)
WOOD_D = (70, 50, 36)
LEATHER = (92, 62, 44)
GLOW = (255, 238, 190)

# animation name -> (seconds per frame, list of pose dicts)
ANIMS = {
    "idle":   (0.28, [dict(), dict(bob=1), dict(bob=1), dict()]),
    "walk":   (0.11, [dict(step=-1), dict(bob=1), dict(step=1), dict(bob=1)]),
    "dash":   (1.00, [dict(lean=2)]),
    "windup": (0.12, [dict(crouch=1, glow=0.5), dict(crouch=2, glow=1.0)]),
    "strike": (1.00, [dict(lean=3)]),
    "dazed":  (0.35, [dict(slump=2, tilt=-1), dict(slump=2, tilt=1)]),
}


def set_asset_dir(path):
    """Point the loader somewhere else (tests) and forget everything cached."""
    global ASSET_DIR
    ASSET_DIR = path
    _cache.clear()
    _files.clear()
    _rooms.clear()


_cache = {}                 # sprite surfaces, keyed by everything that shapes them
_files = {}                 # path -> Surface or None
_rooms = {}                 # id(room) -> (floor layer, prop layer), a tiny LRU


def _load(*parts):
    path = os.path.join(ASSET_DIR, *parts)
    if path not in _files:
        surf = None
        if os.path.isfile(path):
            try:
                surf = pygame.image.load(path)
                if pygame.display.get_surface() is not None:
                    surf = surf.convert_alpha()
            except pygame.error:
                surf = None
        _files[path] = surf
    return _files[path]


def _outlined(s):
    """A 1px dark outline around a sprite — most of what makes tiny pixel art
    read against a busy floor."""
    w, h = s.get_size()
    out = pygame.Surface((w + 2, h + 2), pygame.SRCALPHA)
    sil = pygame.mask.from_surface(s).to_surface(setcolor=OUTLINE, unsetcolor=(0, 0, 0, 0))
    for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2)):
        out.blit(sil, (dx, dy))
    out.blit(s, (1, 1))
    return out


def _px(s, col, x, y, w=1, h=1):
    s.fill(col, (int(x), int(y), int(w), int(h)))


# ===========================================================================
# body designs. Each draws one frame, facing right, onto an S x S surface.
# `P` is the palette from the body's colour; `p` the pose.
# ===========================================================================
def _pal(color):
    return dict(base=color, dark=shade(color, 0.62), deep=shade(color, 0.4),
                light=tint(color, (255, 255, 255), 0.3))


def _legs(s, cx, hip, ground, step, col, spread=2, w=2):
    for side, off in ((-1, step), (1, -step)):
        x = cx + side * spread
        pygame.draw.line(s, col, (x, hip), (x + off, ground), w)


def d_vessel(s, S, P, p, k=1.0):
    """You: a clay figure, cracked, one bright eye."""
    cx, g = S // 2, S - 2
    bob, crouch, lean, slump = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0), p.get("slump", 0)
    hip = g - int(4 * k) + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["dark"], int(2 * k), max(2, int(2 * k)))
    tw, th = int(8 * k), int(7 * k)
    top = hip - th - bob + slump
    pygame.draw.rect(s, P["base"], (cx - tw // 2 + lean, top, tw, th + 1), border_radius=int(2 * k))
    pygame.draw.rect(s, P["dark"], (cx - tw // 2 + lean, top + th - int(2 * k), tw, int(2 * k)))
    hr = int(4 * k)
    hx, hy = cx + lean + 1 + p.get("tilt", 0), top - hr + 1 + slump
    pygame.draw.circle(s, P["base"], (hx, hy), hr)
    pygame.draw.circle(s, P["light"], (hx - 1, hy - 1), max(1, hr // 2))
    # cracks
    pygame.draw.line(s, P["deep"], (hx - 1, hy - hr + 1), (hx + 1, hy - 1), 1)
    pygame.draw.line(s, P["deep"], (cx - 2 + lean, top + 2), (cx + lean, top + th // 2 + 1), 1)
    # the eye
    _px(s, GLOW, hx + hr // 2, hy - 1, max(2, int(2 * k)), 1)


def d_grunt(s, S, P, p):
    """A hunched husk in red rags."""
    cx, g = S // 2, S - 2
    skin = (160, 156, 146)
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 4 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), shade(skin, 0.6))
    top = hip - 6 - bob + p.get("slump", 0)
    pygame.draw.ellipse(s, P["base"], (cx - 5 + lean, top, 10, 8))
    for i in range(3):                                   # rag strips
        _px(s, P["dark"], cx - 4 + i * 3 + lean, top + 7, 1, 2 + (i % 2))
    hx, hy = cx + 3 + lean + p.get("tilt", 0), top + 1 + p.get("slump", 0)
    pygame.draw.circle(s, skin, (hx, hy), 3)
    _px(s, (230, 90, 70), hx + 1, hy - 1, 2, 1)
    _px(s, shade(skin, 0.6), hx - 2, hy + 1, 2, 1)


def d_gunner(s, S, P, p):
    """Hooded, long-coated, patient."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 4 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["deep"])
    top = hip - 9 - bob + p.get("slump", 0)
    pygame.draw.polygon(s, P["base"], [(cx - 4 + lean, top), (cx + 3 + lean, top),
                                       (cx + 5 + lean, hip + 2), (cx - 5 + lean, hip + 2)])
    _px(s, P["dark"], cx - 5 + lean, hip + 1, 10, 1)
    hx, hy = cx + lean + p.get("tilt", 0), top - 3 + p.get("slump", 0)
    pygame.draw.polygon(s, P["dark"], [(hx - 4, hy + 3), (hx - 1, hy - 4), (hx + 4, hy + 3)])
    pygame.draw.circle(s, P["deep"], (hx + 1, hy + 1), 2)
    _px(s, (220, 220, 240), hx + 2, hy + 1)
    _px(s, (220, 220, 240), hx + 1, hy + 1)


def d_lancer(s, S, P, p):
    """Thin, long-limbed, a poacher's wide brim."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 6 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["deep"], spread=1)
    top = hip - 8 - bob + p.get("slump", 0)
    pygame.draw.rect(s, P["base"], (cx - 3 + lean, top, 6, 9), border_radius=1)
    _px(s, LEATHER, cx - 3 + lean, top + 5, 6, 1)
    hx, hy = cx + lean + p.get("tilt", 0), top - 3 + p.get("slump", 0)
    pygame.draw.circle(s, (196, 176, 150), (hx, hy), 2)
    _px(s, P["dark"], hx - 5, hy - 2, 11, 1)            # brim
    _px(s, P["dark"], hx - 2, hy - 4, 5, 2)             # crown
    _px(s, (255, 120, 90), hx + 1, hy)


def d_brute(s, S, P, p):
    """A hulk with chains, head sunk into its shoulders."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 5 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["deep"], spread=4, w=4)
    top = hip - 13 - bob + p.get("slump", 0)
    pygame.draw.ellipse(s, P["base"], (cx - 9 + lean, top, 18, 15))
    pygame.draw.ellipse(s, P["dark"], (cx - 9 + lean, top + 8, 18, 7))
    pygame.draw.circle(s, P["light"], (cx - 8 + lean, top + 6), 4)      # far arm
    pygame.draw.circle(s, P["base"], (cx + 8 + lean, top + 7), 4)       # near arm
    for i in range(6):                                                   # chain
        _px(s, IRON, cx - 7 + i * 3 + lean, top + 4 + (i % 2), 2, 1)
    hx, hy = cx + 4 + lean + p.get("tilt", 0), top + 1 + p.get("slump", 0)
    pygame.draw.circle(s, P["light"], (hx, hy), 3)
    _px(s, (255, 170, 60), hx + 1, hy, 2, 1)


def d_turret(s, S, P, p):
    """A lantern on a stone post — it never leaves its station."""
    cx, g = S // 2, S - 2
    glow = p.get("glow", 0)
    pygame.draw.polygon(s, (78, 80, 92), [(cx - 7, g), (cx + 7, g), (cx + 5, g - 4), (cx - 5, g - 4)])
    pygame.draw.rect(s, (96, 98, 112), (cx - 3, g - 12, 6, 9))
    _px(s, (70, 72, 84), cx - 3, g - 8, 6, 1)
    hy = g - 16 - p.get("bob", 0)
    pygame.draw.circle(s, IRON_D, (cx, hy), 6)
    lamp = tint(P["base"], (255, 255, 255), 0.25 + 0.5 * glow)
    pygame.draw.circle(s, lamp, (cx, hy), 4)
    _px(s, IRON_D, cx - 4, hy, 9, 1)
    _px(s, IRON_D, cx, hy - 4, 1, 9)
    pygame.draw.polygon(s, IRON, [(cx - 5, hy - 5), (cx + 5, hy - 5), (cx, hy - 9)])


def d_detonator(s, S, P, p):
    """A stitched, swollen sack of kindling on little legs — a lit fuse on top
    and a core that shows through the seams."""
    cx, g = S // 2, S - 2
    glow = p.get("glow", 0)
    lean = p.get("lean", 0)
    _legs(s, cx, g - 3, g, p.get("step", 0), (60, 40, 50), spread=2, w=1)
    cy = g - 8 - p.get("bob", 0) + p.get("crouch", 0)
    sack = shade(P["base"], 0.7)
    pygame.draw.circle(s, sack, (cx + lean, cy), 6)
    pygame.draw.circle(s, shade(sack, 0.7), (cx + lean, cy + 2), 5)
    pygame.draw.circle(s, P["base"], (cx - 1 + lean, cy - 2), 3)          # highlight
    core = tint((255, 170, 70), (255, 255, 255), glow)
    # the core shows through a split seam
    pygame.draw.line(s, core, (cx - 2 + lean, cy + 1), (cx + 3 + lean, cy - 1), 2 + int(glow))
    for i in range(4):                                                   # stitches
        _px(s, (40, 26, 34), cx - 3 + i * 2 + lean, cy - 1 + (i % 2) * 3, 1, 1)
    _px(s, WOOD_D, cx + 1 + lean, cy - 9, 1, 4)                          # fuse
    spark = (255, 250, 200) if glow else (255, 160, 60)
    _px(s, spark, cx + 1 + lean, cy - 10)
    if glow:
        _px(s, (255, 220, 120), cx + lean, cy - 11); _px(s, (255, 220, 120), cx + 2 + lean, cy - 11)


def d_assassin(s, S, P, p):
    """A slim cloak, a trailing scarf, one pale slit."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 4 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["deep"], spread=1)
    top = hip - 8 - bob + p.get("slump", 0)
    tail = 3 + lean                                        # the scarf streams behind
    pygame.draw.polygon(s, (120, 40, 50), [(cx - 1, top + 2), (cx - 4 - tail, top + 3 + (bob or 0)),
                                           (cx - 3 - tail, top + 5), (cx - 1, top + 4)])
    pygame.draw.polygon(s, P["base"], [(cx - 3 + lean, top), (cx + 3 + lean, top),
                                       (cx + 4 + lean, hip + 1), (cx - 4 + lean, hip + 1)])
    hx, hy = cx + lean + 1 + p.get("tilt", 0), top - 2 + p.get("slump", 0)
    pygame.draw.polygon(s, P["dark"], [(hx - 3, hy + 3), (hx - 2, hy - 4), (hx + 3, hy + 3)])
    _px(s, (220, 230, 255), hx, hy, 2, 1)


def d_shrike(s, S, P, p):
    """A feather cape and a bird-skull mask."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 5 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), P["deep"], spread=2)
    top = hip - 12 - bob + p.get("slump", 0)
    cape = [(cx - 1, top)]
    for i in range(6):                                     # ragged feather edge
        cape.append((cx - 9 - lean - (i % 2) * 2, top + 2 + i * 3))
    cape.append((cx + 1, hip + 2))
    pygame.draw.polygon(s, P["deep"], cape)
    pygame.draw.polygon(s, P["base"], [(cx - 4 + lean, top), (cx + 4 + lean, top),
                                       (cx + 5 + lean, hip + 1), (cx - 5 + lean, hip + 1)])
    _px(s, P["light"], cx - 4 + lean, top + 4, 9, 1)
    hx, hy = cx + lean + 1 + p.get("tilt", 0), top - 3 + p.get("slump", 0)
    pygame.draw.circle(s, BONE, (hx, hy), 4)
    pygame.draw.polygon(s, BONE, [(hx + 3, hy - 1), (hx + 9, hy + 1), (hx + 3, hy + 2)])
    pygame.draw.circle(s, (30, 22, 30), (hx + 1, hy - 1), 1)
    _px(s, (255, 60, 60), hx + 1, hy - 1)
    for i in range(3):                                     # crest
        _px(s, P["dark"], hx - 3 - i, hy - 4 + i, 1, 2)


def d_turnkey(s, S, P, p):
    """The jailer: bucket helm, leather apron, a ring of keys."""
    cx, g = S // 2, S - 2
    bob, crouch, lean = p.get("bob", 0), p.get("crouch", 0), p.get("lean", 0)
    hip = g - 9 + crouch
    _legs(s, cx, hip, g, p.get("step", 0), (60, 50, 44), spread=5, w=5)
    top = hip - 18 - bob + p.get("slump", 0)
    pygame.draw.ellipse(s, (88, 80, 76), (cx - 13 + lean, top, 26, 22))
    pygame.draw.rect(s, LEATHER, (cx - 8 + lean, top + 6, 16, 17), border_radius=2)
    _px(s, P["base"], cx - 12 + lean, top + 12, 24, 3)                 # sash
    kx, ky = cx - 7 + lean, top + 18                                    # the key ring
    pygame.draw.circle(s, IRON, (kx, ky), 4, 1)
    for i in range(5):
        a = math.pi * (0.2 + i * 0.15)
        _px(s, (200, 180, 110), kx + math.cos(a) * 5, ky + math.sin(a) * 5, 1, 3)
    pygame.draw.circle(s, (100, 92, 88), (cx + 11 + lean, top + 9), 5)  # arm
    hx, hy = cx + 2 + lean + p.get("tilt", 0), top - 5 + p.get("slump", 0)
    pygame.draw.rect(s, IRON, (hx - 6, hy - 6, 12, 12), border_radius=2)
    _px(s, IRON_D, hx - 6, hy - 6, 12, 2)
    _px(s, (20, 20, 26), hx - 1, hy - 1, 7, 2)                          # visor slit
    _px(s, (255, 90, 80), hx + 3, hy - 1, 2, 1)


def d_warden(s, S, P, p):
    """The last keeper. Look closely at the shape of it."""
    # a cloak first, then — underneath — a familiar figure, twice the size
    cx, g = S // 2, S - 2
    lean = p.get("lean", 0)
    dy = -p.get("bob", 0) + p.get("crouch", 0) + p.get("slump", 0)
    pygame.draw.polygon(s, (40, 34, 34), [(cx - 4 + lean, g - 22 + dy), (cx - 16 - lean, g - 1),
                                          (cx - 3, g - 4)])
    d_vessel(s, S, P, p, k=1.8)
    for i in range(4):                                     # an iron crown
        _px(s, IRON, cx - 4 + i * 3 + lean + p.get("tilt", 0), g - 34 - (i % 2) * 2 + dy, 2, 4)


DESIGNS = {
    # design: (drawer, art size, hand offset (x, y) from centre, in art px)
    "vessel": (d_vessel, 20, (3, 0)),
    "grunt": (d_grunt, 20, (4, 1)),
    "gunner": (d_gunner, 22, (3, 0)),
    "lancer": (d_lancer, 22, (2, 0)),
    "brute": (d_brute, 30, (7, 0)),
    "turret": (d_turret, 24, None),
    "detonator": (d_detonator, 18, None),
    "assassin": (d_assassin, 20, (3, 1)),
    "shrike": (d_shrike, 28, (4, 1)),
    "turnkey": (d_turnkey, 40, (10, 1)),
    "warden": (d_warden, 40, (7, -1)),
}


def design_of(body):
    d = body.display or body.name
    return d if d in DESIGNS else None


# ===========================================================================
# weapons: drawn facing right with the grip at the left edge's middle
# ===========================================================================
def _w_pistol(s):
    _px(s, IRON, 0, 1, 7, 2); _px(s, IRON_D, 1, 3, 2, 2)


def _w_blunderbuss(s):
    _px(s, WOOD, 0, 2, 4, 2); _px(s, IRON, 3, 1, 5, 2); _px(s, IRON, 8, 0, 2, 4)


def _w_rifle(s):
    _px(s, WOOD, 0, 2, 4, 2); _px(s, IRON, 3, 1, 9, 2); _px(s, IRON_D, 6, 3, 2, 2)


def _w_cannon(s):
    _px(s, IRON_D, 0, 1, 4, 5); _px(s, IRON, 3, 0, 11, 6); _px(s, (40, 40, 48), 13, 1, 2, 4)


def _w_longrifle(s):
    _px(s, WOOD, 0, 2, 5, 2); _px(s, IRON, 4, 2, 13, 1); _px(s, IRON_D, 6, 0, 5, 2)


def _w_dagger(s):
    _px(s, LEATHER, 0, 1, 2, 2); _px(s, IRON_D, 2, 0, 1, 4); _px(s, (210, 220, 235), 3, 1, 5, 2)


def _w_claws(s):
    _px(s, LEATHER, 0, 3, 3, 3)
    for i, dy in enumerate((0, 3, 6)):
        pygame.draw.line(s, (170, 230, 140), (3, 4), (10, dy + 1 - (i - 1)), 1)


def _w_key(s):
    pygame.draw.circle(s, (200, 180, 110), (3, 4), 3, 1)
    _px(s, (200, 180, 110), 6, 3, 12, 2)
    _px(s, (200, 180, 110), 15, 5, 2, 3); _px(s, (200, 180, 110), 12, 5, 1, 2)


def _w_staff(s):
    _px(s, WOOD_D, 0, 3, 16, 2)
    pygame.draw.circle(s, IRON, (18, 4), 3, 1)
    _px(s, (255, 220, 150), 17, 3, 2, 2)


WEAPONS = {
    # design -> (drawer, art size w, h)
    "vessel": (_w_pistol, 8, 5), "grunt": (_w_blunderbuss, 10, 4),
    "gunner": (_w_rifle, 12, 5), "lancer": (_w_longrifle, 17, 4),
    "brute": (_w_cannon, 15, 6), "assassin": (_w_dagger, 8, 4),
    "shrike": (_w_claws, 11, 8), "turnkey": (_w_key, 18, 8),
    "warden": (_w_staff, 22, 8),
}


# ===========================================================================
# body sprites
# ===========================================================================
def _body_frame(design, color, anim, i, height):
    """One frame at on-screen `height`, facing right, outlined. Cached."""
    key = ("body", design, color, anim, i, height)
    surf = _cache.get(key)
    if surf is not None:
        return surf
    strip = _load("bodies", design, f"{anim}.png") or _load("bodies", design, "idle.png")
    if strip is not None:
        fh = strip.get_height()
        n = max(1, strip.get_width() // fh)
        frame = strip.subsurface((i % n * fh, 0, fh, fh))
        surf = pygame.transform.scale(frame, (height, height))
    else:
        draw, S, _ = DESIGNS[design]
        poses = ANIMS[anim][1]
        art = pygame.Surface((S, S), pygame.SRCALPHA)
        draw(art, S, _pal(color), poses[i % len(poses)])
        art = _outlined(art)
        side = int(round(height * (S + 2) / S))
        surf = pygame.transform.scale(art, (side, side))
    _cache[key] = surf
    return surf


def frame_count(design, anim):
    strip = _load("bodies", design, f"{anim}.png")
    if strip is not None:
        return max(1, strip.get_width() // strip.get_height())
    return len(ANIMS[anim][1])


def _variant(surf, key, mode, amount=0.0, color=None):
    """Flipped / white / tinted / faded copies, cached where they're stable."""
    if mode == "flip":
        k = key + ("flip",)
        out = _cache.get(k)
        if out is None:
            out = _cache[k] = pygame.transform.flip(surf, True, False)
        return out
    if mode == "white":
        k = key + ("white",)
        out = _cache.get(k)
        if out is None:
            out = _cache[k] = pygame.mask.from_surface(surf).to_surface(
                setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
        return out
    out = surf.copy()
    if mode == "tint":
        c = [int(v * amount) for v in color]
        out.fill((*c, 0), special_flags=pygame.BLEND_RGBA_ADD)
    elif mode == "fade":
        out.set_alpha(int(255 * amount))
    return out


def pick_anim(actor):
    if actor.dashing:
        return "dash"
    if actor.attack_phase == "windup" or actor.armed:
        return "windup"
    if actor.attack_phase == "strike":
        return "strike"
    if (actor.attack_phase == "recover" and actor.recover_time is not None
            and actor.recover_time > 0.5):
        return "dazed"
    if actor.velocity.length_squared() > 40 * 40:
        return "walk"
    return "idle"


def _shadow(w, h):
    key = ("shadow", w, h)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0, 0, 0, 110), s.get_rect())
        _cache[key] = s
    return s


def body_height(actor, design):
    """On-screen sprite height: the design's art size scaled with the body, so
    an elite (bigger radius) draws bigger too."""
    _, S, _ = DESIGNS[design]
    base = ARCHETYPES.get(actor.body.name)
    base_r = base.movement.radius if base else actor.radius
    return int(round(S * SCALE * actor.radius / max(1.0, base_r)))


def draw_body(surface, actor, sp, effects):
    """Draw `actor` at screen point `sp`. Returns the muzzle point for the
    flash, or None if this body has no design (the caller falls back)."""
    design = design_of(actor.body)
    if design is None:
        return None
    anim = pick_anim(actor)
    ft, _ = ANIMS[anim]
    n = frame_count(design, anim)
    i = int(actor.anim_t / ft) % n
    height = body_height(actor, design)
    color = tuple(actor.body.color)
    key = ("body", design, color, anim, i, height)
    frame = _body_frame(design, color, anim, i, height)
    facing_right = math.cos(actor.aim) >= 0.0
    img = frame if facing_right else _variant(frame, key, "flip")

    if effects.get("white"):
        img = _variant(img, key + (facing_right,), "white")
    elif effects.get("tint"):
        amt, col = effects["tint"]
        img = _variant(img, key, "tint", amt, col)
    if effects.get("fade") is not None:
        img = _variant(img, key, "fade", effects["fade"])

    r = actor.radius
    feet = Vector2(sp.x, sp.y + r * 0.75)
    sh = _shadow(int(r * 2.2), int(r * 0.8))
    surface.blit(sh, (feet.x - sh.get_width() / 2, feet.y - sh.get_height() / 2))
    if effects.get("mine"):
        pygame.draw.ellipse(surface, C.ACCENT,
                            (feet.x - r * 1.15, feet.y - r * 0.42, r * 2.3, r * 0.84), 1)
    w, h = img.get_size()
    k = height / DESIGNS[design][1]            # screen px per art px
    # the art's ground row sits 2 art px (outline included) above its bottom edge
    surface.blit(img, (int(feet.x - w / 2), int(feet.y - h + 2 * k)))

    if design == "turret":
        _turret_eye(surface, actor, feet, k)
    return _draw_weapon(surface, actor, design, feet, facing_right, k)


def _turret_eye(surface, actor, feet, k):
    """The lantern's vents turn to face its aim."""
    c = Vector2(feet.x, feet.y - 17 * k)
    for j in range(3):
        d = Vector2(1, 0).rotate_rad(actor.aim + (j - 1) * 0.5)
        q = c + d * 6 * k
        pygame.draw.circle(surface, tint(actor.body.color, (255, 255, 255), 0.5),
                           (int(q.x), int(q.y)), max(1, int(k)))


def _weapon_sprite(design):
    key = ("weapon", design)
    surf = _cache.get(key)
    if surf is not None:
        return surf
    img = _load("weapons", f"{design}.png")
    if img is None:
        draw, w, h = WEAPONS[design]
        art = pygame.Surface((w, h), pygame.SRCALPHA)
        draw(art)
        art = _outlined(art)
        img = pygame.transform.scale(art, (art.get_width() * SCALE, art.get_height() * SCALE))
    # pad so the grip (left-middle) is the centre: rotation is then about the hand
    w, h = img.get_size()
    padded = pygame.Surface((w * 2, h), pygame.SRCALPHA)
    padded.blit(img, (w, 0))
    _cache[key] = (padded, w)
    return _cache[key]


def _draw_weapon(surface, actor, design, feet, facing_right, k):
    hand = DESIGNS[design][2]
    S = DESIGNS[design][1]
    if hand is None or design not in WEAPONS:
        body = Vector2(feet.x, feet.y - S * k * 0.45)
        return body + Vector2(math.cos(actor.aim), math.sin(actor.aim)) * (actor.radius + 6)
    padded, length = _weapon_sprite(design)
    # art (S/2 + hand) maps to screen relative to the feet (see draw_body)
    hx = feet.x + (hand[0] if facing_right else -hand[0]) * k
    hy = feet.y - (S / 2 - hand[1] - 1) * k
    deg = math.degrees(actor.aim)
    img = padded if facing_right else pygame.transform.flip(padded, False, True)
    rot = pygame.transform.rotate(img, -deg)
    surface.blit(rot, rot.get_rect(center=(int(hx), int(hy))))
    tip = Vector2(hx, hy) + Vector2(math.cos(actor.aim), math.sin(actor.aim)) * length
    return tip


def portrait(body, size):
    """An idle frame fitted into a HUD box."""
    design = design_of(body)
    if design is None:
        return None
    key = ("portrait", design, tuple(body.color), size)
    surf = _cache.get(key)
    if surf is None:
        _, S, _ = DESIGNS[design]
        frame = _body_frame(design, tuple(body.color), "idle", 0, S * SCALE)
        surf = pygame.transform.smoothscale(frame, (size, size)) if frame.get_width() > size * 2 \
            else pygame.transform.scale(frame, (size, size))
        _cache[key] = surf
    return surf


# ===========================================================================
# rooms: floor, walls and props, rendered once per room
# ===========================================================================
PALETTES = [
    # the Intake: cold, grey-blue
    dict(stone=(36, 40, 50), mortar=(24, 27, 34), hi=(46, 51, 63), stain=(46, 36, 38),
         wall=(52, 57, 72), wall_d=(34, 37, 48), wall_hi=(70, 76, 94)),
    # the Kennels: dirt and straw
    dict(stone=(42, 37, 33), mortar=(28, 25, 22), hi=(54, 48, 41), stain=(58, 46, 30),
         wall=(64, 55, 46), wall_d=(40, 34, 29), wall_hi=(84, 72, 60)),
    # the Keep: warm, and something gold in the cracks
    dict(stone=(44, 32, 32), mortar=(28, 20, 21), hi=(58, 42, 40), stain=(84, 64, 36),
         wall=(70, 46, 44), wall_d=(42, 28, 28), wall_hi=(92, 62, 56)),
]
TILE = 16                                   # art px; 32 on screen


def _tile(pal, kind, rng):
    t = pygame.Surface((TILE, TILE))
    t.fill(pal["stone"])
    # a little grit — kept faint, the floor must never compete with a bullet
    grit_hi = tint(pal["stone"], pal["hi"], 0.5)
    grit_lo = tint(pal["stone"], pal["mortar"], 0.5)
    for _ in range(6):
        _px(t, grit_hi if rng.random() < 0.5 else grit_lo, rng.randrange(TILE), rng.randrange(TILE))
    _px(t, pal["mortar"], 0, TILE - 1, TILE, 1)
    _px(t, pal["mortar"], TILE - 1, 0, 1, TILE)
    _px(t, tint(pal["stone"], pal["hi"], 0.6), 0, 0, TILE - 1, 1)
    if kind == "crack":
        x, y = rng.randrange(3, 12), 1
        while y < TILE - 2:
            _px(t, pal["mortar"], x, y)
            x = max(1, min(TILE - 2, x + rng.choice((-1, 0, 1))))
            y += 1
    elif kind == "stain":
        cx, cy = rng.randrange(4, 12), rng.randrange(4, 12)
        for _ in range(10):
            _px(t, pal["stain"], cx + rng.randint(-3, 3), cy + rng.randint(-2, 2), 2, 1)
    elif kind == "grate":
        pygame.draw.rect(t, pal["mortar"], (3, 3, 10, 10))
        for i in range(4):
            _px(t, IRON_D, 4 + i * 2 + (i > 1), 3, 1, 10)
    elif kind == "bones":
        _px(t, BONE, 4, 9, 6, 1); _px(t, BONE, 3, 8, 1, 3); _px(t, BONE, 10, 8, 1, 3)
        pygame.draw.circle(t, BONE, (11, 5), 2)
        _px(t, pal["mortar"], 11, 5)
    elif kind == "chain":
        for i in range(5):
            _px(t, IRON_D, 2 + i * 3, 7 + (i % 2), 2, 1)
    return pygame.transform.scale(t, (TILE * SCALE, TILE * SCALE))


def _tiles(depth):
    key = ("tiles", depth)
    tiles = _cache.get(key)
    if tiles is None:
        files = []
        folder = os.path.join(ASSET_DIR, "tiles", str(depth))
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                img = _load("tiles", str(depth), f) if f.endswith(".png") else None
                if img is not None:
                    files.append((pygame.transform.scale(img, (TILE * SCALE, TILE * SCALE)), 1.0))
        if files:
            tiles = files
        else:
            pal = PALETTES[min(depth, len(PALETTES) - 1)]
            rng = random.Random(1000 + depth)
            tiles = []
            # mostly plain stone; the rare tiles are seasoning, not texture
            for kind, weight, copies in (("plain", 30, 4), ("crack", 3, 3), ("stain", 1.5, 2),
                                         ("grate", 0.25, 1), ("bones", 0.15 + depth * 0.2, 1),
                                         ("chain", 0.2, 1)):
                for _ in range(copies):
                    tiles.append((_tile(pal, kind, rng), weight / copies))
        _cache[key] = tiles
    return tiles


def _bricks(surf, rect, pal, rng):
    pygame.draw.rect(surf, pal["wall_d"], rect)
    bw, bh = 26, 13
    y = rect.top
    row = 0
    while y < rect.bottom:
        x = rect.left - (bw // 2 if row % 2 else 0)
        while x < rect.right:
            b = pygame.Rect(x + 1, y + 1, bw - 2, bh - 2).clip(rect)
            if b.width > 0 and b.height > 0:
                c = shade(pal["wall"], rng.uniform(0.88, 1.08))
                surf.fill(c, b)
                surf.fill(pal["wall_hi"], (b.left, b.top, b.width, 1))
            x += bw
        y += bh
        row += 1


def _prop_kind(r, rng):
    ratio = max(r.w, r.h) / max(1, min(r.w, r.h))
    if ratio >= 1.5:
        return "desk" if r.w > r.h and r.h <= 80 else "coffin"
    if r.w >= 110 and r.h >= 110:
        return "cage"
    return rng.choice(("crate", "crate", "barrels")) if r.w <= 90 else rng.choice(("cage", "crate"))


def _prop(kind, w, h, pal, rng):
    """A prop at art resolution (w, h), with a lit top and a dark front face."""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    front = max(3, h // 6)
    if kind == "crate":
        s.fill(WOOD_D)
        pygame.draw.rect(s, WOOD, (0, 0, w, h - front))
        for x in range(0, w, 6):
            _px(s, WOOD_D, x, 0, 1, h - front)
        for cx in (0, w - 3):
            _px(s, IRON, cx, 0, 3, 3); _px(s, IRON, cx, h - front - 3, 3, 3)
        pygame.draw.line(s, WOOD_D, (1, 1), (w - 2, h - front - 2), 1)
    elif kind == "barrels":
        s.fill((0, 0, 0, 0))
        n = 2 if w < 40 else 3
        rr = min(w, h) // (n + 1) + 2
        for j in range(n):
            x = rr + j * (w - 2 * rr) // max(1, n - 1)
            y = rr + (j % 2) * (h - 2 * rr - front)
            pygame.draw.circle(s, WOOD_D, (x, y + 2), rr)
            pygame.draw.circle(s, WOOD, (x, y), rr)
            pygame.draw.circle(s, IRON, (x, y), rr, 1)
            pygame.draw.circle(s, WOOD_D, (x, y), rr // 2, 1)
    elif kind == "cage":
        s.fill((20, 20, 26))
        pygame.draw.rect(s, (30, 30, 38), (1, 1, w - 2, h - front - 2))
        # what's left of someone
        _px(s, BONE, w // 2 - 4, h // 2, 8, 1)
        pygame.draw.circle(s, BONE, (w // 2 + 6, h // 2 - 2), 2)
        for x in range(0, w, 5):
            _px(s, IRON, x, 0, 1, h)
        _px(s, IRON, 0, 0, w, 2); _px(s, IRON_D, 0, h - front, w, front)
    elif kind == "coffin":
        s.fill((0, 0, 0, 0))
        horiz = w > h
        L, T = (w, h) if horiz else (h, w)
        c = pygame.Surface((L, T), pygame.SRCALPHA)
        pts = [(0, T * 0.3), (L * 0.2, 0), (L - 1, T * 0.2), (L - 1, T * 0.8),
               (L * 0.2, T - 1), (0, T * 0.7)]
        pygame.draw.polygon(c, WOOD_D, pts)
        pygame.draw.polygon(c, WOOD, [(x, y * 0.85) for x, y in pts])
        _px(c, (180, 160, 110), L * 0.4, T * 0.2, 2, T * 0.45)
        _px(c, (180, 160, 110), L * 0.3, T * 0.35, L * 0.2, 2)
        s.blit(c if horiz else pygame.transform.rotate(c, 90), (0, 0))
    elif kind == "desk":
        s.fill(WOOD_D)
        pygame.draw.rect(s, WOOD, (0, 0, w, h - front))
        _px(s, (200, 190, 160), w // 4, 2, w // 4, (h - front) // 2)          # the ledger
        for yy in range(3, (h - front) // 2, 2):
            _px(s, (120, 100, 80), w // 4 + 1, yy, w // 4 - 2, 1)
        _px(s, (220, 210, 180), w * 3 // 4, 3, 2, 4)                          # candle
        _px(s, (255, 200, 90), w * 3 // 4, 1, 2, 2)
    return s


def room_layers(room):
    """(floor surface, prop surface) for a room, rendered once. Only the last
    couple of rooms are kept; everything is rebuilt deterministically."""
    key = id(room)
    layers = _rooms.get(key)
    if layers is not None and layers[2] is room:
        return layers[0], layers[1]
    depth = getattr(room, "depth", 0)
    pal = PALETTES[min(depth, len(PALETTES) - 1)]
    rng = random.Random(room.gx * 7919 + room.gy * 104729 + depth * 31)
    R = room.rect
    floor = pygame.Surface(R.size)
    if pygame.display.get_surface() is not None:
        floor = floor.convert()
    floor.fill(C.BG)
    _bricks(floor, pygame.Rect(0, 0, R.w, R.h), pal, rng)
    inner = room.inner.move(-R.x, -R.y)
    tiles = _tiles(depth)
    weights = [w for _, w in tiles]
    ts = TILE * SCALE
    floor.set_clip(inner)
    for y in range(inner.top, inner.bottom, ts):
        for x in range(inner.left, inner.right, ts):
            floor.blit(rng.choices(tiles, weights=weights)[0][0], (x, y))
    floor.set_clip(None)
    # depth: the top wall casts a shadow, the inner lip catches light
    shadow = pygame.Surface((inner.w, 14), pygame.SRCALPHA)
    for i in range(14):
        shadow.fill((0, 0, 0, int(120 * (1 - i / 14))), (0, i, inner.w, 1))
    floor.blit(shadow, inner.topleft)
    pygame.draw.rect(floor, pal["wall_hi"], inner.inflate(4, 4), 2)

    props = pygame.Surface(R.size, pygame.SRCALPHA)
    for o in room.obstacles:
        kind = _prop_kind(o, rng)
        img = _load("props", f"{kind}.png")
        if img is not None:
            img = pygame.transform.scale(img, o.size)
        else:
            art = _outlined(_prop(kind, max(4, o.w // SCALE - 2), max(4, o.h // SCALE - 2), pal, rng))
            img = pygame.transform.scale(art, (art.get_width() * SCALE, art.get_height() * SCALE))
        props.blit(img, img.get_rect(center=(o.centerx - R.x, o.centery - R.y)))

    if len(_rooms) >= 3:
        _rooms.pop(next(iter(_rooms)))
    _rooms[key] = (floor, props, room)
    return floor, props


def draw_room(surface, room, camera):
    ox, oy = camera.offset.x, camera.offset.y
    floor, props = room_layers(room)
    surface.fill(C.BG)
    dest = (int(room.rect.x - ox), int(room.rect.y - oy))   # blit clips to the screen
    surface.blit(floor, dest)
    for side in room.doors:
        _door(surface, room, side, ox, oy)
    for d in room.decals:
        d.draw(surface, ox, oy)
    surface.blit(props, dest)


def _door(surface, room, side, ox, oy):
    bar = room.door_bar(side).move(-ox, -oy)
    if room.cleared:
        # an open archway: dark passage, lit edges
        pygame.draw.rect(surface, (12, 13, 18), bar)
        glow = shade(C.DOOR_OPEN, 0.5)
        if side in "ns":
            pygame.draw.line(surface, glow, bar.topleft, bar.bottomleft, 3)
            pygame.draw.line(surface, glow, bar.topright, bar.bottomright, 3)
        else:
            pygame.draw.line(surface, glow, bar.topleft, bar.topright, 3)
            pygame.draw.line(surface, glow, bar.bottomleft, bar.bottomright, 3)
        return
    # a portcullis
    pygame.draw.rect(surface, (18, 16, 20), bar)
    col = C.DOOR_SHUT
    n = 9
    for j in range(n + 1):
        if side in "ns":
            x = bar.left + bar.width * j / n
            pygame.draw.line(surface, col, (x, bar.top), (x, bar.bottom), 3)
        else:
            y = bar.top + bar.height * j / n
            pygame.draw.line(surface, col, (bar.left, y), (bar.right, y), 3)
    pygame.draw.rect(surface, shade(col, 0.6), bar, 3)


# ===========================================================================
# pickups
# ===========================================================================
def _pickup_art(kind):
    key = ("pickup", kind)
    surf = _cache.get(key)
    if surf is not None:
        return surf
    img = _load("pickups", f"{kind}.png")
    if img is None:
        s = pygame.Surface((14, 14), pygame.SRCALPHA)
        if kind == "health":
            pygame.draw.rect(s, (200, 220, 230), (5, 1, 4, 3))           # neck
            pygame.draw.circle(s, (170, 200, 210), (7, 9), 5)            # glass
            pygame.draw.circle(s, C.HEAL, (7, 10), 4)                    # the draught
            _px(s, (240, 255, 240), 5, 7, 2, 1)
            _px(s, WOOD, 5, 0, 4, 1)
        elif kind == "upgrade":
            pygame.draw.rect(s, WOOD_D, (1, 5, 12, 8))
            pygame.draw.rect(s, WOOD, (1, 3, 12, 5), border_radius=2)
            _px(s, (220, 190, 110), 1, 7, 12, 1)
            _px(s, C.UPGRADE, 6, 6, 2, 3)
        elif kind == "stairs":
            s = pygame.Surface((22, 22), pygame.SRCALPHA)
            pygame.draw.rect(s, (14, 14, 20), (1, 1, 20, 20))
            for i in range(4):
                _px(s, shade(C.STAIRS, 0.45 + i * 0.15), 3, 3 + i * 5, 16 - i * 2, 2)
            pygame.draw.rect(s, WOOD, (0, 0, 22, 22), 2)
        img = pygame.transform.scale(_outlined(s), ((s.get_width() + 2) * SCALE,
                                                    (s.get_height() + 2) * SCALE))
    _cache[key] = img
    return img


def draw_pickup(surface, kind, center):
    if kind == "relic":
        return False                  # the turning star is drawn by the pickup itself
    img = _pickup_art(kind)
    surface.blit(img, img.get_rect(center=(int(center[0]), int(center[1]))))
    return True
