"""
hud.py — everything drawn in screen space rather than world space.

→ Godot: a CanvasLayer with Control children. Nothing here touches game state;
  it only reads it, which is why it can stay a straight port target.

Design rule this file follows: every mechanic that can silently deny you
something must show why. The dash-chain ring exists because §3.4 says a locked
perfect dodge "reads as a bug" unless the game tells you it's locked.
"""

import math
import pygame

from .core import clamp, shade, tint
from .config import (C, PossessionStats, PoisonStats, RelicStats, RELICS_BY_KEY,
                     RELIC_COLORS)
from .relics import ABILITY_COOLDOWN

R_BUFF = RelicStats().buff_time
from . import lore

POISON_C = PoisonStats().color

POSSESS = PossessionStats()


class HUD:
    def __init__(self, viewport):
        self.viewport = viewport
        self.f_big = pygame.font.SysFont("menlo,consolas,monospace", 34, bold=True)
        self.f_mid = pygame.font.SysFont("menlo,consolas,monospace", 19, bold=True)
        self.f = pygame.font.SysFont("menlo,consolas,monospace", 14)
        self.f_small = pygame.font.SysFont("menlo,consolas,monospace", 11)
        self.banner = ""
        self.banner_t = 0.0
        self.banner_col = C.ACCENT
        self._font_cache = {}
        # story text: a two-line caption up top, a whisper near the bottom
        self.cap_title = ""
        self.cap_sub = ""
        self.cap_col = C.STAIRS
        self.cap_t = 0.0
        self.cap_len = 1.0
        self.whisper_text = ""
        self.whisper_t = 0.0
        self.whisper_len = 1.0

    def font_for(self, size):
        """Shared font cache — damage numbers ask for odd sizes and creating a
        SysFont per number would cost more than the rest of the frame."""
        f = self._font_cache.get(size)
        if f is None:
            f = pygame.font.SysFont("menlo,consolas,monospace", size, bold=True)
            self._font_cache[size] = f
        return f

    def draw_screen_fx(self, surf, hurt, wipe):
        """Full-screen feedback drawn under the HUD: a red rim when you're hit,
        and a quick dark wipe when a room changes so the cut doesn't just pop."""
        w, h = self.viewport
        if hurt > 0:
            rim = pygame.Surface((w, h), pygame.SRCALPHA)
            band = 70
            for i in range(band):
                a = int(150 * (1 - i / band) * min(1.0, hurt))
                pygame.draw.rect(rim, (*C.BAD, a), (i, i, w - 2 * i, h - 2 * i), 1)
            surf.blit(rim, (0, 0))
        if wipe > 0:
            t = min(1.0, wipe / 0.28)
            veil = pygame.Surface((w, h), pygame.SRCALPHA)
            veil.fill((8, 9, 13, int(210 * t)))
            surf.blit(veil, (0, 0))

    # -- helpers -------------------------------------------------------------
    def say(self, text, color=C.ACCENT, seconds=1.8):
        self.banner = text
        self.banner_t = seconds
        self.banner_col = color

    def caption(self, title, sub="", seconds=3.0, color=C.STAIRS):
        self.cap_title, self.cap_sub, self.cap_col = title, sub, color
        self.cap_t = self.cap_len = seconds

    def whisper(self, text, seconds=4.5):
        self.whisper_text = text
        self.whisper_t = self.whisper_len = seconds

    @staticmethod
    def _fade(t, length, edge=0.5):
        """0→1→0 over a timer that counts down from `length`."""
        return clamp(min(t, length - t) / edge, 0.0, 1.0)

    def _draw_story(self, surf):
        cx = self.viewport[0] // 2
        if self.cap_t > 0:
            a = self._fade(self.cap_t, self.cap_len)
            self._text(surf, self.cap_title, (cx, 148), self.f_mid,
                       shade(self.cap_col, 0.25 + 0.75 * a), center=True)
            if self.cap_sub:
                self._text(surf, self.cap_sub, (cx, 176), self.f,
                           shade(C.TEXT_DIM, 0.25 + 0.75 * a), center=True)
        if self.whisper_t > 0:
            a = self._fade(self.whisper_t, self.whisper_len, 0.8)
            self._text(surf, self.whisper_text, (cx, self.viewport[1] - 96), self.f,
                       shade(C.TEXT_DIM, 0.2 + 0.8 * a), center=True)

    def draw_intro(self, surf, t):
        surf.fill(C.BG)
        w, h = self.viewport
        y = h // 2 - len(lore.INTRO) * 16
        for i, line in enumerate(lore.INTRO):
            a = clamp((t - i * lore.INTRO_LINE_TIME) / 0.7, 0.0, 1.0)
            if a > 0:
                col = C.WARN if i == len(lore.INTRO) - 1 else C.TEXT
                self._text(surf, line, (w // 2, y), self.f_mid, shade(col, 0.15 + 0.85 * a),
                           center=True, shadow=False)
            y += 34
        self._text(surf, "any key", (w // 2, h - 40), self.f_small, C.TEXT_DIM,
                   center=True, shadow=False)

    def update(self, delta):
        self.cap_t = max(0.0, self.cap_t - delta)
        self.whisper_t = max(0.0, self.whisper_t - delta)
        self.banner_t = max(0.0, self.banner_t - delta)

    def _text(self, surf, txt, pos, font=None, col=C.TEXT, center=False, shadow=True):
        font = font or self.f
        img = font.render(txt, True, col)
        r = img.get_rect()
        if center:
            r.center = pos
        else:
            r.topleft = pos
        if shadow:
            sh = font.render(txt, True, (10, 12, 16))
            surf.blit(sh, (r.x + 1, r.y + 1))
        surf.blit(img, r)
        return r

    def _panel(self, surf, rect, alpha=170):
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        s.fill((14, 16, 22, alpha))
        surf.blit(s, rect.topleft)
        pygame.draw.rect(surf, (48, 54, 70), rect, 1)

    # -- in-game -------------------------------------------------------------
    def draw(self, surf, game):
        player = game.player_actor
        if player is not None:
            self._draw_vitals(surf, game, player)
            self._draw_chain(surf, game, player)
            self._draw_ability(surf, game)
        self._draw_relics(surf, game)
        self._draw_boss(surf, game)
        self._draw_floor(surf, game)
        self._draw_minimap(surf, game)
        self._draw_prompts(surf, game)
        self._draw_witch(surf, game)
        self._draw_story(surf)
        if self.banner_t > 0:
            a = clamp(self.banner_t / 0.5, 0.0, 1.0)
            self._text(surf, self.banner, (self.viewport[0] // 2, 108),
                       self.f_mid, shade(self.banner_col, 0.4 + 0.6 * a), center=True)

    def _draw_vitals(self, surf, game, player):
        x, y = 18, self.viewport[1] - 86
        w = 268

        # current body
        self._text(surf, player.body.title.upper(), (x, y - 20), self.f_mid,
                   player.body.color)
        bar = pygame.Rect(x, y, w, 20)
        pygame.draw.rect(surf, (14, 16, 22), bar.inflate(4, 4), border_radius=3)
        fill = pygame.Rect(x, y, int(w * player.health_frac), 20)
        col = C.GOOD if player.health_frac > 0.5 else (C.WARN if player.health_frac > 0.25 else C.BAD)
        pygame.draw.rect(surf, col, fill, border_radius=3)
        pygame.draw.rect(surf, shade(col, 1.4), bar, 1, border_radius=3)
        self._text(surf, f"{int(math.ceil(player.health))}/{int(player.max_health)}",
                   (x + w - 6, y + 2), self.f_small, C.TEXT)
        if player.poison_t > 0:
            self._text(surf, f"POISON x{player.poison_stacks}  {int(math.ceil(player.poison_t))}s",
                       (x + 150, y - 18), self.f_small, POISON_C)

        # the roster — your remaining lives, and the reason possession matters
        rx = x
        ry = y + 28
        cap = POSSESS.max_roster + game.mods["roster_bonus"]
        for i in range(cap):
            box = pygame.Rect(rx + i * 34, ry, 28, 28)
            member = game.roster[i] if i < len(game.roster) else None
            if member is None:
                pygame.draw.rect(surf, (32, 36, 46), box, 1, border_radius=4)
                continue
            active = member is game.player_actor
            pygame.draw.rect(surf, shade(member.body.color, 0.35), box, border_radius=4)
            fh = int(26 * member.health_frac)
            pygame.draw.rect(surf, member.body.color,
                             (box.x + 1, box.bottom - 1 - fh, 26, fh), border_radius=3)
            pygame.draw.rect(surf, C.TEXT if active else (60, 66, 82), box,
                             2 if active else 1, border_radius=4)
        self._text(surf, "Q swap", (rx + cap * 34 + 8, ry + 8), self.f_small, C.TEXT_DIM)

    def _draw_chain(self, surf, game, player):
        """§3.3/§3.4's required tell. Shows the chain, the lock, and — crucially
        — how long until the lock lifts, so restraint is a visible timer rather
        than a guess."""
        ctrl = game.player_controller
        cx, cy = self.viewport[0] - 78, self.viewport[1] - 78
        locked = ctrl.perfect_dodge_locked
        cap = ctrl.max_chain(player)

        col = C.BAD if locked else C.ACCENT
        pygame.draw.circle(surf, (18, 20, 28), (cx, cy), 34)
        pygame.draw.circle(surf, shade(col, 0.5), (cx, cy), 34, 2)

        if locked:
            # cooldown arc — the lock lifting, drawn as it happens
            p = ctrl.chain_reset_progress(player)
            rect = pygame.Rect(cx - 30, cy - 30, 60, 60)
            try:
                pygame.draw.arc(surf, C.WARN, rect, -math.pi / 2,
                                -math.pi / 2 + math.tau * p, 5)
            except ValueError:
                pass
            self._text(surf, "LOCKED", (cx, cy + 46), self.f_small, C.BAD, center=True)
        else:
            self._text(surf, "DODGE", (cx, cy + 46), self.f_small, C.GOOD, center=True)

        # chain pips
        for i in range(cap):
            a = -math.pi / 2 + (i - (cap - 1) / 2) * 0.42
            px = cx + math.cos(a) * 20
            py = cy + math.sin(a) * 20
            on = i < ctrl.chain
            pygame.draw.circle(surf, col if on else (44, 50, 64), (int(px), int(py)), 5)
        self._text(surf, str(ctrl.chain), (cx, cy + 8), self.f_mid,
                   col, center=True)

    def _draw_ability(self, surf, game):
        key = game.mods["ability"]
        if key is None:
            return
        relic = RELICS_BY_KEY[key]
        col = RELIC_COLORS["ability"]
        cx, cy = self.viewport[0] - 170, self.viewport[1] - 70
        ready = game._ability_cd <= 0.0
        live = game.buffs.get(key, 0.0)
        pygame.draw.circle(surf, (18, 20, 28), (cx, cy), 26)
        pygame.draw.circle(surf, col if ready else shade(col, 0.4), (cx, cy), 26, 2)
        if live > 0:
            # running: a bright ring draining as the buff runs out
            rect = pygame.Rect(cx - 30, cy - 30, 60, 60)
            try:
                pygame.draw.arc(surf, tint(col, (255, 255, 255), 0.4), rect, -math.pi / 2,
                                -math.pi / 2 + math.tau * (live / R_BUFF), 4)
            except ValueError:
                pass
            self._text(surf, f"{live:.1f}s", (cx, cy + 50), self.f_small, col, center=True)
        if not ready:
            p = 1.0 - game._ability_cd / ABILITY_COOLDOWN[key]
            rect = pygame.Rect(cx - 22, cy - 22, 44, 44)
            try:
                pygame.draw.arc(surf, col, rect, -math.pi / 2,
                                -math.pi / 2 + math.tau * p, 4)
            except ValueError:
                pass
        self._text(surf, "F", (cx, cy - 10), self.f_mid,
                   col if ready else C.TEXT_DIM, center=True)
        self._text(surf, relic.name, (cx, cy + 36), self.f_small,
                   col if ready else C.TEXT_DIM, center=True)

    def _draw_relics(self, surf, game):
        """Held relics, top-left under the room line — a run's build at a glance."""
        y = 62
        for key in game.mods["relics"]:
            r = RELICS_BY_KEY[key]
            col = RELIC_COLORS[r.kind]
            if r.kind == "ability" and game.mods["ability"] != key:
                col = C.TEXT_DIM          # replaced: the stats stay, the button doesn't
            pts = [(22, y), (27, y + 5), (22, y + 10), (17, y + 5)]
            pygame.draw.polygon(surf, col, pts)
            self._text(surf, r.name, (32, y - 2), self.f_small, col)
            y += 16

    def _draw_floor(self, surf, game):
        alive = sum(1 for e in game.enemies if e.alive)
        kind = game.room.kind.upper()
        self._text(surf, f"DEPTH {game.depth + 1}/{game.ds.floors}   {kind}",
                   (18, 16), self.f_mid, C.TEXT)
        if alive:
            self._text(surf, f"{alive} hostile{'s' if alive != 1 else ''}",
                       (18, 40), self.f, C.BAD)
        elif not game.room.cleared:
            self._text(surf, "clear", (18, 40), self.f, C.GOOD)
        else:
            self._text(surf, "doors open", (18, 40), self.f, C.DOOR_OPEN)

    def _draw_minimap(self, surf, game):
        cell = 20
        pad = 3
        rooms = game.floor.rooms
        xs = [c[0] for c in rooms]
        ys = [c[1] for c in rooms]
        w = (max(xs) - min(xs) + 1) * (cell + pad) + pad
        h = (max(ys) - min(ys) + 1) * (cell + pad) + pad
        ox = self.viewport[0] - w - 16
        oy = 16
        self._panel(surf, pygame.Rect(ox - 4, oy - 4, w + 8, h + 8))

        for (gx, gy), room in rooms.items():
            # fog: only rooms you've seen, plus what's next door
            known = room.visited or any(
                n in rooms and rooms[n].visited for n in
                [(gx + dx, gy + dy) for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))])
            if not known:
                continue
            r = pygame.Rect(ox + (gx - min(xs)) * (cell + pad) + pad,
                            oy + (gy - min(ys)) * (cell + pad) + pad, cell, cell)
            if not room.visited:
                pygame.draw.rect(surf, (38, 43, 56), r, 1)
                continue
            base = {"boss": C.BAD, "treasure": C.UPGRADE,
                    "start": C.TEXT_DIM, "combat": (58, 66, 84)}[room.kind]
            fillc = base if room.cleared or room.kind != "combat" else shade(base, 0.7)
            pygame.draw.rect(surf, fillc, r)
            if room is game.room:
                pygame.draw.rect(surf, C.ACCENT, r, 2)
            if room.kind == "boss":
                self._text(surf, "B", r.center, self.f_small, (16, 18, 24),
                           center=True, shadow=False)
            elif room.kind == "treasure":
                self._text(surf, "?", r.center, self.f_small, (16, 18, 24),
                           center=True, shadow=False)

    def _draw_boss(self, surf, game):
        bosses = [e for e in game.enemies if e.alive and e.body.threat >= 5]
        if not bosses:
            return
        b = bosses[0]
        w = 420
        x = self.viewport[0] // 2 - w // 2
        y = 30
        self._text(surf, f"THE {b.body.title.upper()}", (self.viewport[0] // 2, y - 20),
                   self.f_mid, b.body.color if sum(b.body.color) > 300 else C.BAD,
                   center=True)
        bar = pygame.Rect(x, y, w, 10)
        pygame.draw.rect(surf, (14, 16, 22), bar.inflate(4, 4), border_radius=3)
        pygame.draw.rect(surf, C.BAD, (x, y, int(w * b.health_frac), 10), border_radius=3)
        pygame.draw.rect(surf, shade(C.BAD, 1.4), bar, 1, border_radius=3)
        if b.body.backstab is not None and not b.body.backstab.lethal:
            self._text(surf, "its back is its weak point", (self.viewport[0] // 2, y + 20),
                       self.f_small, C.TEXT_DIM, center=True)

    def _draw_prompts(self, surf, game):
        player = game.player_actor
        if player is None or not player.alive:
            return
        cx = self.viewport[0] // 2
        y = self.viewport[1] - 54
        target = game.possess_target()
        occupied = game.occupied_target()
        if occupied is not None and target is None:
            self._text(surf, f"[E]  {lore.OCCUPIED}", (cx, y), self.f_mid,
                       shade(C.BAD, 0.8), center=True)
        elif target is not None:
            self._text(surf, f"[E]  TAKE THE {target.body.title.upper()}",
                       (cx, y), self.f_mid, C.UPGRADE, center=True)
        elif player.body.blast is not None and not player.armed:
            last = sum(1 for b in game.roster if b.alive) <= 1
            self._text(surf, "[LMB]  DETONATE — this is your LAST body" if last
                       else "[LMB]  DETONATE — spends this body",
                       (cx, y), self.f_mid, C.BAD if last else C.WARN, center=True)
        elif game.room.cleared and game.room.standing_in_door(player.position):
            self._text(surf, "walk through the door", (cx, y), self.f,
                       C.DOOR_OPEN, center=True)

    def _draw_witch(self, surf, game):
        if not game.witch_active:
            return
        t = clamp(game.witch_t / 0.35, 0.0, 1.0)
        # edge vignette, so the slow-mo is unmistakable even mid-fight
        w, h = self.viewport
        edge = pygame.Surface((w, h), pygame.SRCALPHA)
        band = 90
        for i in range(band):
            a = int(120 * (1 - i / band) * t)
            col = (*C.WITCH, a)
            pygame.draw.rect(edge, col, (i, i, w - 2 * i, h - 2 * i), 1)
        surf.blit(edge, (0, 0))
        self._text(surf, "WITCH TIME", (w // 2, 62), self.f_big,
                   tint(C.WITCH, (255, 255, 255), 0.4), center=True)
        self._text(surf, "everything you land crits", (w // 2, 92), self.f,
                   C.WITCH, center=True)

    # -- full-screen states --------------------------------------------------
    def _dim(self, surf, alpha=185):
        s = pygame.Surface(self.viewport, pygame.SRCALPHA)
        s.fill((8, 9, 13, alpha))
        surf.blit(s, (0, 0))

    def draw_title(self, surf):
        self._dim(surf, 220)
        w, h = self.viewport
        self._text(surf, "HUSK", (w // 2, h // 2 - 120), self.f_big, C.WARN, center=True)
        lines = [
            ("you are not your body", C.TEXT_DIM),
            ("", C.TEXT),
            ("WASD move        mouse aim        LMB fire", C.TEXT),
            ("SPACE dash       E take a body    Q swap body", C.TEXT),
            ("F relic ability  J fire (trackpad)  T aim assist", C.TEXT),
            ("", C.TEXT),
            ("dash freely — but more than 3 in a row locks your", C.TEXT_DIM),
            ("perfect dodge. dodge an attack at the last moment", C.TEXT_DIM),
            ("with dashes in reserve and time slows to a crawl.", C.TEXT_DIM),
            ("", C.TEXT),
            ("hurt an enemy badly enough and you can TAKE it.", C.UPGRADE),
            ("your bodies are your lives. spend them well.", C.UPGRADE),
            ("", C.TEXT),
            ("press SPACE to descend", C.ACCENT),
        ]
        y = h // 2 - 74
        for txt, col in lines:
            if txt:
                self._text(surf, txt, (w // 2, y), self.f, col, center=True)
            y += 22

    def draw_pause(self, surf, game):
        self._dim(surf)
        w, h = self.viewport
        self._text(surf, "PAUSED", (w // 2, h // 2 - 40), self.f_big, C.TEXT, center=True)
        self._text(surf, "ESC resume     R restart run     Q quit",
                   (w // 2, h // 2 + 10), self.f, C.TEXT_DIM, center=True)
        state = "ON" if game.aim_assist else "OFF"
        self._text(surf, f"T  aim assist: {state}", (w // 2, h // 2 + 40), self.f,
                   C.GOOD if game.aim_assist else C.TEXT_DIM, center=True)
        self._text(surf, "J fires too — handy on a trackpad", (w // 2, h // 2 + 64),
                   self.f_small, C.TEXT_DIM, center=True)

    def draw_game_over(self, surf, game):
        self._dim(surf, 210)
        w, h = self.viewport
        self._text(surf, lore.DEATH_TITLE, (w // 2, h // 2 - 130), self.f_big, C.BAD,
                   center=True)
        self._text(surf, game.death_line, (w // 2, h // 2 - 90), self.f_mid,
                   C.TEXT, center=True)
        self._text(surf, "you ran out of bodies", (w // 2, h // 2 - 62), self.f,
                   C.TEXT_DIM, center=True)
        self._stats_block(surf, game, h // 2 - 34)
        self._text(surf, "press R to begin again", (w // 2, h // 2 + 118), self.f,
                   C.ACCENT, center=True)

    def draw_victory(self, surf, game):
        self._dim(surf, 210)
        w, h = self.viewport
        t = game._story_t
        self._text(surf, lore.VICTORY_TITLE, (w // 2, 70), self.f_big, lore.WEARS_YOU_COLOR,
                   center=True)
        y = 124
        for i, line in enumerate(lore.VICTORY_LINES):
            a = clamp((t - 0.6 - i * lore.VICTORY_LINE_TIME) / 0.8, 0.0, 1.0)
            if line and a > 0:
                col = C.TEXT_DIM if i == len(lore.VICTORY_LINES) - 1 else C.TEXT
                self._text(surf, line, (w // 2, y), self.f_mid, shade(col, 0.15 + 0.85 * a),
                           center=True)
            y += 28
        done = 0.6 + len(lore.VICTORY_LINES) * lore.VICTORY_LINE_TIME
        if t >= done:
            self._stats_block(surf, game, y + 24)
            self._text(surf, "you are not your body.", (w // 2, h - 70), self.f,
                       C.TEXT_DIM, center=True)
            self._text(surf, "press R to begin again", (w // 2, h - 42), self.f,
                       C.ACCENT, center=True)

    def _stats_block(self, surf, game, y):
        w = self.viewport[0]
        ctrl = game.player_controller
        rows = [
            ("depth reached", f"{game.depth + 1}"),
            ("rooms cleared", f"{game.stats['rooms']}"),
            ("kills", f"{game.stats['kills']}"),
            ("bodies worn", f"{game.stats['possessions']}"),
            ("perfect dodges", f"{ctrl.perfect_dodges}"),
            ("dashes", f"{ctrl.dashes}"),
            ("time", f"{int(game.stats['time'] // 60)}:{int(game.stats['time'] % 60):02d}"),
        ]
        for label, val in rows:
            self._text(surf, label, (w // 2 - 130, y), self.f, C.TEXT_DIM)
            self._text(surf, val, (w // 2 + 90, y), self.f, C.TEXT)
            y += 20

    def _wrap(self, text, font, width):
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] <= width:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    def draw_relic_choice(self, surf, cards, mods):
        self._dim(surf, 210)
        w, h = self.viewport
        self._text(surf, "A RELIC", (w // 2, 104), self.f_big, C.CRIT, center=True)
        self._text(surf, f"press 1-{len(cards)} — it stays with you, whatever body you wear",
                   (w // 2, 144), self.f, C.TEXT_DIM, center=True)
        cw, ch, gap = 300, 250, 22
        total = len(cards) * cw + (len(cards) - 1) * gap
        x = (w - total) // 2
        y = h // 2 - ch // 2 + 30
        for i, r in enumerate(cards):
            col = RELIC_COLORS[r.kind]
            rect = pygame.Rect(x + i * (cw + gap), y, cw, ch)
            self._panel(surf, rect, 220)
            pygame.draw.rect(surf, col, rect, 2)
            self._text(surf, f"{i + 1}", (rect.left + 16, rect.top + 12), self.f_mid,
                       C.TEXT_DIM)
            self._text(surf, r.kind.upper(), (rect.centerx, rect.top + 22), self.f_small,
                       col, center=True)
            self._text(surf, r.name, (rect.centerx, rect.top + 56), self.f_mid, col,
                       center=True)
            self._text(surf, r.boost, (rect.centerx, rect.top + 92), self.f, C.GOOD,
                       center=True)
            yy = rect.top + 124
            for line in self._wrap(r.gimmick, self.f, cw - 30):
                self._text(surf, line, (rect.centerx, yy), self.f, C.TEXT, center=True)
                yy += 20
            flavour = lore.RELIC_LINES.get(r.key, "")
            yy += 10
            for line in self._wrap(flavour, self.f_small, cw - 40):
                self._text(surf, line, (rect.centerx, yy), self.f_small, C.TEXT_DIM,
                           center=True)
                yy += 15
            if r.kind == "ability" and mods["ability"]:
                old = RELICS_BY_KEY[mods["ability"]].name
                self._text(surf, f"replaces {old} on F", (rect.centerx, rect.bottom - 22),
                           self.f_small, C.WARN, center=True)

    def draw_upgrade_choice(self, surf, options):
        self._dim(surf, 200)
        w, h = self.viewport
        self._text(surf, "A GIFT", (w // 2, 118), self.f_big, C.UPGRADE, center=True)
        self._text(surf, "press 1, 2 or 3", (w // 2, 158), self.f, C.TEXT_DIM, center=True)
        cw, ch = 260, 150
        gap = 24
        total = len(options) * cw + (len(options) - 1) * gap
        x = (w - total) // 2
        y = h // 2 - ch // 2 + 20
        for i, (name, desc, _fn) in enumerate(options):
            r = pygame.Rect(x + i * (cw + gap), y, cw, ch)
            self._panel(surf, r, 210)
            pygame.draw.rect(surf, C.UPGRADE, r, 2)
            self._text(surf, f"{i + 1}", (r.centerx, r.top + 26), self.f_mid,
                       C.TEXT_DIM, center=True)
            self._text(surf, name, (r.centerx, r.centery - 6), self.f_mid,
                       C.UPGRADE, center=True)
            self._text(surf, desc, (r.centerx, r.centery + 26), self.f,
                       C.TEXT, center=True)
