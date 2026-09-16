"""
app.py — the Game object: the loop, the run, and the glue between systems.

→ Godot: the Main scene plus the engine's own loop. The fixed-timestep split we
  implement by hand here (physics at a locked 60Hz, process every rendered
  frame) is exactly what Godot does for you (§4).

Game is also the `ctx` that every entity receives. Entities never reach for each
other directly — they ask ctx for what they need (ctx.hostiles_of, ctx.shake,
ctx.spawn_projectiles). That indirection is what keeps Actor ignorant of whether
it's being driven by a player or a brain, which is the whole basis of §3.5.
"""

import random
from types import SimpleNamespace

import pygame
from pygame.math import Vector2

from .config import (C, PHYSICS_DELTA, RENDER_FPS_CAP, MAX_FRAME, VIEWPORT,
                     DungeonStats, PossessionStats, WitchTimeStats, CombatStats,
                     ARCHETYPES, UPGRADES, VESSEL, fresh_modifiers)
from .core import Camera, Layer
from .inputs import InputState
from .actors import Actor, Controller, ELITE
from .controllers import PlayerController
from .ai import brain_for
from .world import Floor, OPPOSITE
from .pickups import Pickup
from .hud import HUD
from .audio import Audio
from .fx import Decal, Shockwave, FloatText, damage_text
from .actors import POISON
from . import combat, weapons, relics, lore
from .config import RELIC_COLORS, RELICS_BY_KEY, AssistStats

TITLE, PLAYING, PAUSED, CHOOSING, GAME_OVER, VICTORY = range(6)
INTRO = 6                        # the story card before the title

POSSESS = PossessionStats()
WITCH = WitchTimeStats()
COMBAT = CombatStats()


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("HUSK")
        self.viewport = VIEWPORT
        self.screen = self._open_window()
        self.clock = pygame.time.Clock()

        self.ds = DungeonStats()
        self.input = InputState()
        self.hud = HUD(self.viewport)
        self.audio = Audio()
        self.camera = Camera(self.viewport, pygame.Rect(0, 0, *self.viewport))
        self.rng = random.Random()
        # Story lines draw from their own stream, so what a whisper says never
        # changes how a seeded floor plays out.
        self.lore_rng = random.Random()

        self.state = INTRO
        self._story_t = 0.0              # clock for the intro and the ending
        self.aim_assist = AssistStats().enabled   # a setting: survives restarts
        self.running = True
        self._accum = 0.0
        self._hit_stop = 0.0
        self.mouse_world = Vector2(0, 0)

        self.new_run()

    def _open_window(self):
        """SCALED renders at the display's real resolution and scales our fixed
        logical viewport up — which is what stops the game looking soft on the
        M2's Retina panel, and is the same decision as texture_filter = Nearest
        on the Godot side (§4). vsync removes tearing; the fixed-timestep
        accumulator and the buffered input layer both already cope with
        whatever frame rate it hands us.

        Both flags are best-effort: some drivers refuse vsync, and a few refuse
        SCALED. Falling back to a plain window is better than failing to boot.

        Note for anyone verifying this: you CANNOT check it with
        `screen.get_flags() & pygame.SCALED`. Under SCALED you are handed an
        off-screen logical surface that pygame blits to the real window on
        flip, so its flags come back as 0 rather than the window's hardware
        bits — flags of 0 is itself the tell that SCALED took.

        `self.display_mode` records which request was accepted without error,
        which is not quite the same as what the driver delivered: headless
        (SDL_VIDEODRIVER=dummy) accepts SCALED and then quietly ignores it. On
        a real display, trust it.
        """
        for mode, kwargs in (("scaled+vsync", {"flags": pygame.SCALED, "vsync": 1}),
                             ("scaled", {"flags": pygame.SCALED}),
                             ("plain", {})):
            try:
                surf = pygame.display.set_mode(self.viewport, **kwargs)
                self.display_mode = mode
                return surf
            except pygame.error:
                continue
        self.display_mode = "plain"
        return pygame.display.set_mode(self.viewport)

    # =======================================================================
    # run lifecycle
    # =======================================================================
    def new_run(self):
        self.mods = fresh_modifiers()
        self.player_controller = PlayerController(self.input, self.mods)
        self.stats = {"kills": 0, "rooms": 0, "possessions": 0, "time": 0.0}
        self.depth = -1
        self.roster = []
        self.player_actor = None
        self.witch_t = 0.0
        self._possess_cd = 0.0
        self._swap_cd = 0.0
        self._door_cd = 0.0
        self._want_possess = False
        self._want_swap = False
        self._hurt_flash = 0.0
        self._wipe = 0.0
        self.fx = []
        self.pending_upgrades = []
        self.choice = "upgrade"          # what pending_upgrades holds: upgrades or relics
        self._ability_cd = 0.0
        self._want_ability = False
        self._ambush_t = 0.0             # SHADOW STEP's crit window
        self.relic_state = {"volleys": 0}
        self.buffs = {}                  # timed ability -> seconds left
        self._boss_name = "warden"
        self.whispered = set()
        self.death_line = ""
        self._story_t = 0.0
        self.next_floor()

        body = Actor(Vector2(self.room.inner.center), VESSEL, faction="player",
                     mods=self.mods)
        body.controller = self.player_controller
        self._bind_audio(body)
        self.roster.append(body)
        self.player_actor = body
        self.camera.snap_to(body.position)

    def next_floor(self):
        self.depth += 1
        self.floor = Floor(self.depth, self.ds, self.rng)
        self.enemies = []
        self.projectiles = []
        self.pickups = []
        self.sparks = []
        self.fx = []
        self.room = self.floor.rooms[self.floor.start]
        self.enter_room(self.room, entry_side=None)
        name, epigraph = lore.floor(self.depth)
        self.hud.caption(f"DEPTH {self.depth + 1}  ·  {name}", epigraph, 3.2)
        if self.player_actor is not None:
            self.player_actor.position = Vector2(self.room.inner.center)
            self.player_actor.velocity = Vector2(0, 0)
            self.camera.set_bounds(self.room.rect)
            self.camera.snap_to(self.player_actor.position)

    # =======================================================================
    # rooms
    # =======================================================================
    def enter_room(self, room, entry_side):
        self.room = room
        fresh = not room.spawned
        room.visited = True
        self._pending_spawns = []
        self.projectiles.clear()
        self.sparks.clear()
        self.fx = []
        self.enemies = []
        self.pickups = []

        if not room.spawned:
            room.spawned = True
            hp_scale = 1.0 + self.depth * 0.35
            dmg_scale = 1.0 + self.depth * 0.20
            for name, pos, elite in room.spawns:
                self.spawn_enemy(name, pos, hp_scale, dmg_scale, elite)
            for kind, pos, amount in room.pickups:
                self.pickups.append(Pickup(Vector2(pos), kind, amount))
        else:
            # A room you've already cleared stays cleared and stays empty.
            for kind, pos, amount in room.pickups:
                if kind in ("stairs", "relic"):
                    self.pickups.append(Pickup(Vector2(pos), kind, amount))

        if self.enemies:
            room.cleared = False
        else:
            room.cleared = True

        self.camera.set_bounds(room.rect)
        if self.player_actor is not None:
            if entry_side is not None:
                self.player_actor.position = room.entry_point(entry_side)
                self.player_actor.velocity = Vector2(0, 0)
            self.camera.snap_to(self.player_actor.position)

        self._wipe = 0.28
        bosses = [e for e in self.enemies if e.body.threat >= 5]
        if room.kind == "boss" and bosses:
            self._boss_name = bosses[0].body.name
            story = self._dress_boss(bosses[0])
            self.hud.caption(f"THE {bosses[0].body.title.upper()}", story.intro, 3.4,
                             color=C.BAD)
            self.sfx("boss")
        elif fresh and room.kind in ("combat", "treasure"):
            line = lore.whisper(self.depth, self.lore_rng, self.whispered)
            if line:
                self.hud.whisper(line)
        self._door_cd = 0.45

    def _dress_boss(self, e):
        """The same warden body is the Turnkey on floor 1 and the Warden on
        floor 3; lore decides which, and what the last one looks like."""
        story = lore.boss(self.depth)
        e.body.display = story.name
        if story.wears_you:
            e.body.color = lore.WEARS_YOU_COLOR
            e.occupied = True
        return story

    def spawn_enemy(self, name, pos, hp_scale=1.0, dmg_scale=1.0, elite=False):
        arch = ARCHETYPES[name]
        e = Actor(Vector2(pos), arch, faction="enemy")
        # Difficulty scaling writes to the actor's PRIVATE copy of the stats.
        e.body.max_health *= hp_scale
        e.max_health = e.body.max_health
        e.health = e.max_health
        e.body.weapon.damage *= dmg_scale
        e.body.brain.melee_damage *= dmg_scale
        if e.body.blast is not None:
            e.body.blast.damage *= dmg_scale
        if e.body.shrike is not None:
            e.body.shrike.stab_damage *= dmg_scale
        if elite:
            e.make_elite()
        e.controller = brain_for(e.body, self.rng)
        e.on_died.connect(self._on_enemy_died)
        self._bind_audio(e)
        self.enemies.append(e)
        return e

    def _on_enemy_died(self, actor):
        self.stats["kills"] += 1
        if actor in self.roster:
            return
        if actor.body.threat >= 5:
            words = lore.boss(self.depth).last_words
            if words:
                self.hud.whisper(words, 6.0)
        # A boss's summons die with it — quietly, lit fuses and all.
        for e in self.enemies:
            if e.summoner is actor and e.alive:
                e.cancel_attack()
                e.die(self)
        relics.on_kill(self, actor, summoned=actor.summoner is not None)
        if actor.summoner is not None:
            return                      # no health from summons: nothing to farm
        chance = ELITE.drop_chance if actor.body.elite else self.ds.health_drop_chance
        if self.rng.random() < chance:
            self.pickups.append(Pickup(Vector2(actor.position), "health",
                                       self.ds.health_drop_amount))

    @property
    def intro_length(self):
        return len(lore.INTRO) * lore.INTRO_LINE_TIME + lore.INTRO_HOLD

    def _check_room_cleared(self):
        room = self.room
        if room.cleared or any(e.alive for e in self.enemies):
            return
        room.cleared = True
        self.stats["rooms"] += 1
        self.hud.say("CLEARED", C.GOOD, 1.2)
        self.sfx("cleared")
        self.sfx("door_open", volume=0.7)
        if room.kind == "boss":
            pos = Vector2(room.inner.center)
            if self.depth + 1 < self.ds.floors:
                # A relic first; the stairs appear once it's taken, so you
                # can't walk past your reward by accident.
                room.pickups.append(("relic", pos, 0.0))
                self.pickups.append(Pickup(pos, "relic"))
                self.hud.say("it left something behind", C.CRIT, 2.6)
            else:
                self._open_stairs(room, pos)

    def _open_stairs(self, room, pos):
        room.pickups.append(("stairs", pos, 0.0))
        if room is self.room:
            self.pickups.append(Pickup(pos, "stairs"))
        self.hud.say("the way down opens", C.STAIRS, 2.6)

    def _check_doors(self):
        player = self.player_actor
        if player is None or not player.alive or not self.room.cleared:
            return
        if self._door_cd > 0:
            return
        side = self.room.standing_in_door(player.position)
        if side is None:
            return
        nxt = self.floor.rooms.get(self.room.doors[side])
        if nxt is None:
            return
        self.enter_room(nxt, entry_side=OPPOSITE[side])

    # =======================================================================
    # ctx interface — what entities are allowed to ask of the world
    # =======================================================================
    @property
    def witch_active(self) -> bool:
        return self.witch_t > 0.0

    def hostiles_of(self, actor):
        if actor.faction == "player":
            return [e for e in self.enemies if e.alive]
        return [self.player_actor] if (self.player_actor and self.player_actor.alive) else []

    def spawn_projectiles(self, shots):
        self.projectiles.extend(shots)

    def spawn_impact(self, pos, color, count=6, speed=(90, 320), life=0.3):
        self.sparks.extend(weapons.burst_sparks(pos, color, count, speed, life))

    def sfx(self, name, pos=None, volume=1.0):
        """The single audio entry point for game code. Positional sounds are
        attenuated against the player; UI and player-owned sounds are flat.
        → Godot: AudioStreamPlayer2D vs AudioStreamPlayer."""
        if pos is None or self.player_actor is None:
            self.audio.play(name, volume)
        else:
            self.audio.play_at(name, pos, self.player_actor.position, volume)

    def shake(self, amount):
        self.camera.shake(amount)

    def hit_stop(self, seconds):
        """Freeze-frame on impact. Tiny, but it's most of what makes a hit feel
        like it connected. → Godot: Engine.time_scale, or the same accumulator
        trick."""
        self._hit_stop = max(self._hit_stop, seconds)

    def collect(self, pickup):
        if not pickup.alive:
            return
        if pickup.kind == "health":
            self.player_actor.heal(pickup.amount)
            self.hud.say(f"+{int(pickup.amount)}", C.HEAL, 0.9)
            self.sfx("pickup")
            pickup.kill()
        elif pickup.kind == "upgrade":
            pickup.kill()
            self.pending_upgrades = self.rng.sample(UPGRADES, 3)
            self.choice = "upgrade"
            self.state = CHOOSING
            self.input.release_all()
        elif pickup.kind == "relic":
            cards = relics.offer(self.rng, self._boss_name, self.mods)
            pickup.kill()
            self.room.pickups = [x for x in self.room.pickups if x[0] != "relic"]
            if not cards:                       # you hold every relic there is
                self._open_stairs(self.room, self._stairs_spot(pickup.position))
                return
            self.pending_upgrades = cards
            self.choice = "relic"
            self._relic_at = Vector2(pickup.position)
            self.state = CHOOSING
            self.sfx("upgrade")
            self.input.release_all()
        elif pickup.kind == "stairs":
            pickup.kill()
            if self.depth + 1 >= self.ds.floors:
                self.sfx("victory")
                self.state = VICTORY
                self._story_t = 0.0
            else:
                self.next_floor()
                self.sfx("descend")

    def _stairs_spot(self, near):
        """Beside where you're standing, not under you — the stairs are a
        pickup, and landing on them would end the floor unasked."""
        room = self.room
        for d in (Vector2(0, -170), Vector2(0, 170), Vector2(-170, 0), Vector2(170, 0)):
            p = Vector2(near) + d
            if (room.inner.inflate(-60, -60).collidepoint(p.x, p.y) and
                    not any(o.inflate(50, 50).collidepoint(p.x, p.y) for o in room.obstacles)):
                return p
        return Vector2(near) + Vector2(0, -170)

    # -- relic interface (relics.py asks for these) --------------------------
    @property
    def player_crits(self) -> bool:
        return self.witch_active or self._ambush_t > 0.0

    @property
    def ability_ready(self) -> bool:
        p = self.player_actor
        return (self.mods["ability"] is not None and self._ability_cd <= 0.0
                and p is not None and p.alive and not p.armed)

    def buff_active(self, key) -> bool:
        return self.buffs.get(key, 0.0) > 0.0

    def start_buff(self, key, seconds):
        self.buffs[key] = seconds
        name = RELICS_BY_KEY[key].name
        self.hud.say(name, RELIC_COLORS["ability"], 1.0)
        self.sfx("upgrade", None, 0.8)
        if self.player_actor is not None:
            self.fx.append(Shockwave(self.player_actor.position, RELIC_COLORS["ability"],
                                     10, 90, 0.3, 3))

    def request_ability(self):
        self._want_ability = True

    def _do_ability(self):
        key = self.mods["ability"]
        p = self.player_actor
        if key is None or p is None or not p.alive:
            return
        if relics.use_ability(self, p, key):
            self._ability_cd = relics.ABILITY_COOLDOWN[key]

    def assisted_aim(self, actor, aim):
        if not self.aim_assist:
            return aim
        return combat.assist_aim(actor, aim, self.enemies, self.room.obstacles)

    def toggle_aim_assist(self):
        self.aim_assist = not self.aim_assist
        self.hud.say("AIM ASSIST " + ("ON" if self.aim_assist else "OFF"), C.TEXT_DIM, 1.2)

    def modify_volley(self, actor, shots):
        return relics.modify_volley(self, actor, shots)

    def ambush(self, seconds):
        self._ambush_t = max(self._ambush_t, seconds)
        self.hud.say("AMBUSH", C.CRIT, 0.8)

    def hud_say(self, text, color, seconds):
        self.hud.say(text, color, seconds)

    def fx_text(self, pos, text, color):
        self.fx.append(FloatText(Vector2(pos) + Vector2(0, -30), text, color,
                                 size=14, life=0.7, rise=40))

    def area_damage(self, pos, radius, damage, knockback=300.0, crit=False):
        """Player-side blasts (relics). Enemy blasts go through Actor.detonate."""
        src = SimpleNamespace(position=Vector2(pos))
        for e in list(self.enemies):
            if e.alive and (e.position - src.position).length() <= radius + e.radius:
                e.take_damage(damage, self, source=src, knockback=knockback, crit=crit)

    def nova_fx(self, pos, color):
        self.fx.append(Shockwave(pos, color, 16, 220, 0.4, 6))
        self.spawn_impact(pos, color, count=18, speed=(120, 380))
        self.sfx("shot_radial")
        self.shake(6.0)

    def explosion(self, pos, radius, color, small=False):
        """A detonator going off. The ring is drawn at the exact blast radius,
        so the thing you were running from matches the thing that hit."""
        pos = Vector2(pos)
        if small:
            self.fx.append(Shockwave(pos, color, 8, radius, 0.25, 4))
            self.spawn_impact(pos, color, count=10, speed=(100, 320), life=0.3)
            self.sfx("explode", pos, 0.45)
            self.shake(3.0)
            return
        self.fx.append(Shockwave(pos, color, 12, radius, 0.32, 7))
        self.fx.append(Shockwave(pos, C.CRIT, 6, radius * 0.7, 0.22, 3))
        self.spawn_impact(pos, color, count=28, speed=(160, 520), life=0.45)
        self.spawn_impact(pos, C.CRIT, count=12, speed=(80, 300), life=0.3)
        self.room.decals.append(Decal(pos, radius * 0.55, (40, 34, 38), self.rng))
        self.sfx("explode", pos)
        self.shake(11.0)
        self.hit_stop(0.05)

    def summon(self, owner, name, pos):
        """Queued, not spawned: this is called from inside the enemy loop."""
        self._pending_spawns.append((owner, name, Vector2(pos)))

    def summons_of(self, owner):
        return (sum(1 for e in self.enemies if e.alive and e.summoner is owner)
                + sum(1 for o, _, _ in self._pending_spawns if o is owner))

    def _flush_spawns(self):
        pending, self._pending_spawns = self._pending_spawns, []
        for owner, name, pos in pending:
            if not owner.alive:
                continue
            e = self.spawn_enemy(name, pos, 1.0 + self.depth * 0.35,
                                 1.0 + self.depth * 0.20)
            e.summoner = owner
            e.controller.awake = True
            self.fx.append(Shockwave(pos, C.UPGRADE, 4, 46, 0.3, 3))
            self.spawn_impact(pos, e.body.color, count=8, speed=(60, 200))
        if pending:
            self.sfx("summon_pop", pending[0][2], 0.8)

    def shadow_step(self, actor, frm, to):
        """The shadow sneak's cut: a puff where it left, a ring where it lands."""
        self.spawn_impact(frm, actor.body.color, count=14, speed=(60, 240), life=0.4)
        self.fx.append(Shockwave(to, actor.body.color, 30, 6, 0.25, 4))
        self.spawn_impact(to, (150, 140, 200), count=10, speed=(40, 180))
        self.sfx("sneak_in", to)

    def deflect(self, actor, pos):
        """A hit the assassin's armour turned aside."""
        self.spawn_impact(Vector2(pos), (225, 230, 245), count=4, speed=(120, 300), life=0.18)
        self.sfx("clink", pos, 0.7)

    def backstabbed(self, actor):
        self.hud.say("BACKSTAB", C.CRIT, 1.3)
        self.sfx("backstab")
        self.fx.append(Shockwave(actor.position, C.CRIT, 8, 150, 0.4, 4))
        self.shake(8.0)
        self.hit_stop(0.14)

    def trigger_witch_time(self, actor):
        """§3.4. Scale the WORLD's delta down while the player keeps near-full
        delta — the doc's stated implementation direction, and the reason
        nothing here touches Engine.time_scale."""
        self.witch_t = relics.witch_duration(self.mods, WITCH.duration)
        self.fx.append(Shockwave(actor.position, C.WITCH, 14, 260, 0.5, 6))
        self.sfx("perfect")
        actor.invuln_t = max(actor.invuln_t, WITCH.dodge_iframes)
        self.hud.say("PERFECT DODGE", C.WITCH, 1.4)
        self.shake(5.0)
        self.hit_stop(0.07)

    def request_possess(self):
        self._want_possess = True

    def request_swap(self):
        self._want_swap = True

    # =======================================================================
    # possession (§3.5)
    # =======================================================================
    @property
    def roster_cap(self):
        return POSSESS.max_roster + self.mods["roster_bonus"]

    def possess_target(self):
        """The nearest enemy whose take-me window is open and within reach."""
        p = self.player_actor
        if p is None or not p.alive or self._possess_cd > 0:
            return None
        best, best_d = None, POSSESS.possess_range
        for e in self.enemies:
            if not e.possessable:
                continue
            d = (e.position - p.position).length()
            if d <= best_d:
                best, best_d = e, d
        return best

    # -- feedback bindings ---------------------------------------------------
    # Bound ONCE per actor, and every handler branches on faction at CALL time
    # rather than at connect time. That matters: possession changes an actor's
    # faction while it keeps all its existing listeners, so a connect-time
    # decision would leave a worn enemy playing both halves of every cue.
    def _bind_audio(self, actor):
        if actor is None or getattr(actor, "_audio_bound", False):
            return
        actor._audio_bound = True
        actor.on_fired.connect(self._snd_fired)
        actor.on_dash.connect(self._snd_dash)
        actor.on_hurt.connect(self._snd_hurt)
        actor.on_died.connect(self._snd_died)
        actor.on_attack.connect(self._snd_attack)
        actor.on_weakened.connect(self._snd_weakened)
        actor.on_poisoned.connect(self._snd_poisoned)
        actor.on_poison_tick.connect(self._snd_poison_tick)

    def _mine(self, a):
        return a.faction == "player"

    def _snd_fired(self, a):
        if self._mine(a):
            self.sfx(a.weapon.sound, None, 0.85)
        else:
            self.sfx(a.weapon.sound, a.position, 0.7)

    def _snd_dash(self, a):
        self.sfx("dash", None if self._mine(a) else a.position, 0.9)

    def _snd_hurt(self, a, amount):
        if self._mine(a):
            self.sfx("player_hurt", None, 1.0)
            relics.on_player_hurt(self, a)
            self._hurt_flash = 1.0
            self.fx.append(damage_text(a.position, amount, to_player=True))
        else:
            self.sfx("hit", a.position, 0.8)
            self.fx.append(damage_text(a.position, amount,
                                       crit=self.witch_active))

    def _snd_died(self, a):
        # A room you've fought in should look like it afterwards.
        self.room.decals.append(Decal(a.position, a.radius * 1.9, a.body.color,
                                      self.rng))
        # A body you were wearing gets its own send-off in _on_body_lost.
        if not self._mine(a):
            self.sfx("enemy_die", a.position, 0.9)

    def _snd_attack(self, a):
        # The telegraph is half the dodge cue — it needs to carry across a room.
        name = "fuse" if a.attack_kind == "blast" else "telegraph"
        self.sfx(name, None if self._mine(a) else a.position, 0.85)

    def _snd_poisoned(self, a):
        if self._mine(a):
            self.sfx("poison", None, 0.8)
            self.fx.append(FloatText(a.position + Vector2(0, -40), "POISONED",
                                     POISON.color, size=14, life=0.8, rise=40))

    def _snd_poison_tick(self, a, amount):
        self.fx.append(FloatText(a.position + Vector2(8, -22), f"-{int(round(amount))}",
                                 POISON.color, size=13, life=0.7, rise=36))

    def _snd_weakened(self, a):
        self.sfx("upgrade", a.position, 0.45)

    def _committed(self):
        """A lit fuse can't be walked away from: the body you leave behind isn't
        simulated, so the bomb would just hang there."""
        p = self.player_actor
        if p is not None and p.armed:
            self.hud.say("NO WAY BACK", C.BAD, 0.8)
            return True
        return False

    def occupied_target(self):
        """The final keeper, weakened and in reach: the prompt you get instead
        of a body. It is never explained."""
        p = self.player_actor
        if p is None or not p.alive:
            return None
        for e in self.enemies:
            if (e.alive and e.occupied
                    and e.health <= e.max_health * POSSESS.weaken_fraction
                    and (e.position - p.position).length() <= POSSESS.possess_range):
                return e
        return None

    def _do_possess(self):
        target = self.possess_target()
        if target is None and self.occupied_target() is not None:
            self.hud.say(lore.OCCUPIED, C.BAD, 1.2)
            self.sfx("body_lost", volume=0.5)
            return
        if target is None or self._committed():
            return
        old = self.player_actor

        # THE ENTIRE MECHANIC: hand the player's controller to a different body.
        # Everything else here is bookkeeping around that one assignment.
        self.enemies.remove(target)
        target.faction = "player"
        target.layer = Layer.PLAYER
        target.controller = self.player_controller
        target.cancel_attack()
        target.weaken_t = 0.0
        target.set_modifiers(self.mods)
        target.health = target.max_health * POSSESS.possess_heal
        target.invuln_t = POSSESS.possess_time + 0.1
        target.possess_channel = POSSESS.possess_time
        target.velocity = Vector2(0, 0)      # the cost: you arrive with no momentum
        target.aim = old.aim

        if old is not None:
            old.controller = Controller()    # inert; it's furniture until you swap back

        self.roster.append(target)
        while len(self.roster) > self.roster_cap:
            for i, b in enumerate(self.roster):
                if b is not target:
                    self.roster.pop(i)
                    break
            else:
                break

        self.player_actor = target
        self._bind_audio(target)
        self.sfx("possess")
        self._possess_cd = POSSESS.possess_cooldown
        self.stats["possessions"] += 1
        self.hud.say(f"WORE THE {target.body.title.upper()}", C.UPGRADE, 1.6)
        before = lore.once(target.body.name, self.lore_rng)
        if before:
            self.fx.append(FloatText(target.position + Vector2(0, -44), before,
                                     C.TEXT_DIM, size=13, life=2.0, rise=26, drift=0))
        self.spawn_impact(target.position, C.UPGRADE, count=22, speed=(140, 380))
        self.fx.append(Shockwave(target.position, C.UPGRADE, 10, 190, 0.45, 5))
        self.shake(7.0)

    def _do_swap(self, forced=False):
        alive = [b for b in self.roster if b.alive]
        if len(alive) < 2 and not forced:
            return False
        if not forced and self._committed():
            return False
        if self._swap_cd > 0 and not forced:
            return False
        cur = self.player_actor
        pool = [b for b in alive if b is not cur]
        if not pool:
            return False
        # cycle in roster order
        order = [b for b in self.roster if b in pool]
        nxt = order[0]
        if cur is not None and cur in self.roster and not forced:
            i = self.roster.index(cur)
            for k in range(1, len(self.roster) + 1):
                cand = self.roster[(i + k) % len(self.roster)]
                if cand.alive and cand is not cur:
                    nxt = cand
                    break

        if cur is not None:
            nxt.position = Vector2(cur.position)
            nxt.aim = cur.aim
            cur.controller = Controller()
        nxt.velocity = Vector2(0, 0)
        nxt.controller = self.player_controller
        nxt.invuln_t = max(nxt.invuln_t, POSSESS.swap_invuln)
        nxt.set_modifiers(self.mods)
        self.player_actor = nxt
        self._bind_audio(nxt)
        self.sfx("swap")
        self._swap_cd = POSSESS.swap_cooldown
        self.spawn_impact(nxt.position, nxt.body.color, count=12, speed=(100, 280))
        return True

    def _on_body_lost(self):
        """The body you were wearing died. Fall into the next one; the run ends
        only when there's nothing left to fall into."""
        dead = self.player_actor
        if dead in self.roster:
            self.roster.remove(dead)
        self.shake(14.0)
        self.hit_stop(0.12)
        self.spawn_impact(dead.position, dead.body.color, count=26, speed=(150, 480), life=0.6)
        self.fx.append(Shockwave(dead.position, C.BAD, 12, 230, 0.55, 6))
        self.sfx("body_lost")
        self.player_actor = None
        # Inactive bodies are stored, not simulated, so their `position` is
        # wherever they were last worn — possibly a different room. The body you
        # fall into has to appear where you just died.
        if self._pick_next_body(dead.position, dead.aim):
            self.hud.say("BODY LOST", C.BAD, 1.6)
        else:
            self.sfx("game_over")
            self.state = GAME_OVER
            self.death_line = lore.death_line(self.lore_rng)
            self.input.release_all()

    def _pick_next_body(self, at: Vector2, aim: float) -> bool:
        alive = [b for b in self.roster if b.alive]
        if not alive:
            return False
        nxt = alive[0]
        nxt.position = Vector2(at)
        nxt.aim = aim
        nxt.velocity = Vector2(0, 0)
        nxt.controller = self.player_controller
        nxt.invuln_t = max(nxt.invuln_t, POSSESS.swap_invuln * 2)
        nxt.set_modifiers(self.mods)
        self.player_actor = nxt
        self._bind_audio(nxt)
        self.player_controller.reset_chain()
        return True

    def apply_upgrade(self, index):
        if not (0 <= index < len(self.pending_upgrades)):
            return
        if self.choice == "relic":
            self._apply_relic(self.pending_upgrades[index])
            return
        name, desc, fn = self.pending_upgrades[index]
        fn(self.mods)
        for b in self.roster:
            b.set_modifiers(self.mods)
        if self.player_actor is not None:
            # a fresh gift tops you up, so a chest is always worth walking to
            self.player_actor.heal(self.player_actor.max_health * 0.25)
        self.pending_upgrades = []
        self.state = PLAYING
        self.input.release_all()
        self.sfx("upgrade")
        self.hud.say(f"{name} — {desc}", C.UPGRADE, 2.2)

    def _apply_relic(self, relic):
        replaced = relics.take(relic, self.mods)
        for b in self.roster:
            b.set_modifiers(self.mods)
        if self.player_actor is not None:
            self.player_actor.heal(self.player_actor.max_health * 0.35)
        if relic.kind == "ability":
            self._ability_cd = 0.0
        self.pending_upgrades = []
        self.choice = "upgrade"
        self.state = PLAYING
        self.input.release_all()
        self.sfx("upgrade")
        self.fx.append(Shockwave(self.player_actor.position, RELIC_COLORS[relic.kind],
                                 10, 200, 0.5, 5))
        self._open_stairs(self.room, self._stairs_spot(self._relic_at))
        self.hud.say(f"{relic.name} — {relic.gimmick}", RELIC_COLORS[relic.kind], 3.0)

    # =======================================================================
    # main loop
    # =======================================================================
    def run(self):
        while self.running:
            frame = self.clock.tick(RENDER_FPS_CAP) / 1000.0
            frame = min(frame, MAX_FRAME)

            # Age buffered presses by real time before this frame's events land.
            self.input.update(frame)
            self.audio.update(frame)
            self._events()

            if self.state == PLAYING:
                self._update(frame)
            elif self.state in (INTRO, VICTORY):
                self._story_t += frame
                if self.state == INTRO and self._story_t >= self.intro_length:
                    self.state = TITLE
            self.hud.update(frame)

            self._draw()
            pygame.display.flip()
        pygame.quit()

    def _events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return
            self.input.feed_event(event)

            if event.type != pygame.KEYDOWN:
                continue
            k = event.key
            if k == pygame.K_m:
                self.hud.say("SOUND OFF" if self.audio.toggle_mute() else "SOUND ON",
                             C.TEXT_DIM, 1.0)
                continue
            if self.state == INTRO:
                self.state = TITLE              # any key skips the story card
            elif self.state == TITLE:
                if k in (pygame.K_SPACE, pygame.K_RETURN):
                    self.sfx("ui")
                    self.state = PLAYING
                    self.input.release_all()
                elif k == pygame.K_ESCAPE:
                    self.running = False
            elif k == pygame.K_t and self.state in (PLAYING, PAUSED):
                self.toggle_aim_assist()
            elif self.state == PLAYING:
                if k == pygame.K_ESCAPE:
                    self.state = PAUSED
                    self.input.release_all()
            elif self.state == PAUSED:
                if k == pygame.K_ESCAPE:
                    self.state = PLAYING
                    self.input.release_all()
                elif k == pygame.K_r:
                    self.new_run()
                    self.state = PLAYING
                elif k == pygame.K_q:
                    self.running = False
            elif self.state == CHOOSING:
                if k in (pygame.K_1, pygame.K_KP1):
                    self.apply_upgrade(0)
                elif k in (pygame.K_2, pygame.K_KP2):
                    self.apply_upgrade(1)
                elif k in (pygame.K_3, pygame.K_KP3):
                    self.apply_upgrade(2)
            elif self.state in (GAME_OVER, VICTORY):
                if k == pygame.K_r:
                    self.new_run()
                    self.state = PLAYING
                elif k == pygame.K_ESCAPE:
                    self.running = False

    def _update(self, frame):
        self.stats["time"] += frame

        # render-rate logic (≈ _process): aim tracks the mouse every frame, so
        # aiming stays smooth no matter what the physics tick is doing.
        self.mouse_world = self.camera.to_world(pygame.mouse.get_pos())

        self._accum += frame
        while self._accum >= PHYSICS_DELTA:
            self._accum -= PHYSICS_DELTA
            if self._hit_stop > 0.0:
                # Freeze-frame: consume the tick without simulating it, so the
                # accumulator can't build up a catch-up burst behind the pause.
                self._hit_stop -= PHYSICS_DELTA
                continue
            self._physics_tick()

        player = self.player_actor
        if player is not None:
            self.camera.follow(player.position, frame)

    def _physics_tick(self):
        d = PHYSICS_DELTA

        # §3.4: the world slows, you don't. Timers scale with their owner, so
        # enemy cooldowns crawl during Witch Time too.
        if self.witch_active:
            self.witch_t -= d
            if self.witch_t <= 0.0:
                self.sfx("witch_end")
            pd = d * WITCH.player_scale
            wd = d * WITCH.world_scale
        else:
            pd = wd = d

        self._possess_cd = max(0.0, self._possess_cd - d)
        self._swap_cd = max(0.0, self._swap_cd - d)
        self._door_cd = max(0.0, self._door_cd - d)
        self._ability_cd = max(0.0, self._ability_cd - d)
        self._ambush_t = max(0.0, self._ambush_t - d)
        for k in list(self.buffs):
            self.buffs[k] = max(0.0, self.buffs[k] - pd)

        player = self.player_actor
        if player is not None and player.alive:
            player.physics_process(pd, self)

        for e in self.enemies:
            if e.alive:
                e.physics_process(wd, self)

        for p in self.projectiles:
            if p.alive:
                # your shots keep their speed; theirs crawl
                p.physics_process(pd if p.layer == Layer.PLAYER_SHOT else wd, self)

        for pk in self.pickups:
            if pk.alive:
                pk.physics_process(pd, self)

        for s in self.sparks:
            if s.alive:
                s.physics_process(wd, self)

        for f in self.fx:
            if f.alive:
                f.physics_process(pd, self)

        self._hurt_flash = max(0.0, self._hurt_flash - d * 2.6)
        self._wipe = max(0.0, self._wipe - d)

        combat.resolve_projectiles(self)
        combat.resolve_bodies(self)
        if self.buff_active("battering_ram") and player is not None and player.alive:
            relics.ram(self, player, self.player_controller)
        if self._pending_spawns:
            self._flush_spawns()

        # Possession and swapping rearrange the actor lists, so they're applied
        # after the tick rather than in the middle of iterating them.
        if self._want_possess:
            self._want_possess = False
            self._do_possess()
        if self._want_swap:
            self._want_swap = False
            self._do_swap()
        if self._want_ability:
            self._want_ability = False
            self._do_ability()

        self.enemies = [e for e in self.enemies if e.alive]
        self.projectiles = [p for p in self.projectiles if p.alive]
        self.pickups = [p for p in self.pickups if p.alive]
        self.sparks = [s for s in self.sparks if s.alive]
        self.fx = [f for f in self.fx if f.alive]

        if self.player_actor is not None and not self.player_actor.alive:
            self._on_body_lost()

        self._check_room_cleared()
        self._check_doors()

    # =======================================================================
    # drawing
    # =======================================================================
    def _draw(self):
        self.room.draw(self.screen, self.camera)

        for p in self.pickups:
            p.draw(self.screen, self.camera)
        for s in self.sparks:
            s.draw(self.screen, self.camera)
        for e in self.enemies:
            e.draw(self.screen, self.camera)
        if self.player_actor is not None:
            self.player_actor.draw(self.screen, self.camera)
            if self.buff_active("battering_ram"):
                # the ram's tell: a ring that goes dim once your dodge locks
                pa = self.player_actor
                sp = self.camera.to_screen(pa.position)
                locked = self.player_controller.perfect_dodge_locked
                col = C.LOCKED if locked else RELIC_COLORS["ability"]
                pygame.draw.circle(self.screen, col, (int(sp.x), int(sp.y)),
                                   int(pa.radius + 7), 3 if pa.dashing and not locked else 2)
        for p in self.projectiles:
            p.draw(self.screen, self.camera)
        for f in self.fx:
            f.draw(self.screen, self.camera, self.hud.font_for)

        if self._hurt_flash > 0 or self._wipe > 0:
            self.hud.draw_screen_fx(self.screen, self._hurt_flash, self._wipe)

        if self.state in (PLAYING, PAUSED, CHOOSING):
            self.hud.draw(self.screen, self)

        if self.state == INTRO:
            self.hud.draw_intro(self.screen, self._story_t)
        elif self.state == TITLE:
            self.hud.draw_title(self.screen)
        elif self.state == PAUSED:
            self.hud.draw_pause(self.screen, self)
        elif self.state == CHOOSING:
            if self.choice == "relic":
                self.hud.draw_relic_choice(self.screen, self.pending_upgrades, self.mods)
            else:
                self.hud.draw_upgrade_choice(self.screen, self.pending_upgrades)
        elif self.state == GAME_OVER:
            self.hud.draw_game_over(self.screen, self)
        elif self.state == VICTORY:
            self.hud.draw_victory(self.screen, self)
