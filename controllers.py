"""
controllers.py — the player's controller.

The one thing worth reading here: THE DASH CHAIN LIVES ON THIS OBJECT, not on
the body. That's the answer to GAME-CONCEPT.md §3.5's "what carries over on
swap?" — the chain measures the *player's* restraint, so it follows the player
between bodies. If it reset on a swap, swapping would launder a locked perfect
dodge and §3.3 would collapse into a free action.

→ Godot: a Node child of the Actor scene, or an autoload if you'd rather the
  player state outlive every body. The second reads better once possession
  exists, which is exactly why it's a separate object here.
"""

from .actors import Controller, Intent
from .core import angle_of
from .combat import threat_window
from .config import WitchTimeStats
from . import relics

WITCH = WitchTimeStats()


class PlayerController(Controller):
    is_player = True

    def __init__(self, inp, mods):
        self.input = inp
        self.mods = mods
        # §3.3 dash-chain state — persists across possession.
        self._chain = 0
        self._since_dash_end = 999.0
        self.perfect_dodge_locked = False
        # stats for the HUD / run summary
        self.perfect_dodges = 0
        self.dashes = 0

    # -- readouts for the HUD ------------------------------------------------
    @property
    def chain(self) -> int:
        return self._chain

    def max_chain(self, actor) -> int:
        return actor.stats.max_chain_for_perfect + self.mods["chain_bonus"]

    def chain_reset_progress(self, actor) -> float:
        """0→1 as the chain cools off. Drives the HUD ring so the player can
        see the lock lifting instead of guessing."""
        if self._chain == 0:
            return 1.0
        return min(1.0, self._since_dash_end / max(0.01, actor.stats.chain_reset_time))

    # -- per-tick ------------------------------------------------------------
    def decide(self, actor, delta, ctx) -> Intent:
        inp = self.input

        # The chain clock runs from the END of a dash, so chain_reset_time means
        # what §3.3 says: pause this long AFTER dashing to reset.
        self._since_dash_end = 0.0 if actor.dashing else self._since_dash_end + delta
        if self._since_dash_end > actor.stats.chain_reset_time and self._chain != 0:
            self._chain = 0
            self.perfect_dodge_locked = False

        intent = Intent()
        intent.move = inp.get_vector("move_left", "move_right", "move_up", "move_down")

        d = ctx.mouse_world - actor.position
        intent.aim = angle_of(d) if d.length() > 1 else actor.aim

        # `dash_ready and consume(...)`: the press stays buffered while a dash is
        # in flight and fires the tick it ends, instead of being thrown away.
        intent.dash = actor.dash_ready and inp.consume("dash")
        # Semi-auto: a click made during the cooldown is held in the buffer, not
        # thrown away by a tick that couldn't have fired it.
        intent.fire = (inp.pressed("fire") if actor.weapon.auto
                       else actor.fire_ready and inp.consume("fire"))

        if inp.consume("possess"):
            ctx.request_possess()
        if inp.consume("swap"):
            ctx.request_swap()
        if ctx.ability_ready and inp.consume("ability"):
            ctx.request_ability()
        return intent

    def notify_dash(self, actor, ctx):
        """Called the instant a dash starts — chain bookkeeping (§3.3) and the
        perfect-dodge read (§3.4) both happen here, in that order, because the
        read depends on whether this dash just locked you out."""
        reset = actor.stats.chain_reset_time
        self._chain = self._chain + 1 if self._since_dash_end <= reset else 1
        self._since_dash_end = 0.0
        self.perfect_dodge_locked = self._chain > self.max_chain(actor)
        self.dashes += 1

        if self.perfect_dodge_locked:
            return      # the whole point of §3.3: no slow-mo for dash spam
        window = relics.perfect_window(self.mods, WITCH.perfect_window)
        if threat_window(actor, ctx.enemies, ctx.projectiles, window):
            self.perfect_dodges += 1
            ctx.trigger_witch_time(actor)
            if WITCH.refund_chain:
                # Reading an attack correctly gives the mobility back. Restraint
                # is the cost of entry; precision is what buys it off.
                self._chain = 0
                self._since_dash_end = 999.0
                self.perfect_dodge_locked = False

    def reset_chain(self):
        self._chain = 0
        self._since_dash_end = 999.0
        self.perfect_dodge_locked = False
