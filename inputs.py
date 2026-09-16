"""
inputs.py — named actions and a buffered input state.

→ Godot: the InputMap (Project Settings > Input Map) plus the Input singleton.
  ACTIONS below is the InputMap; InputState mirrors the two query methods game
  logic actually calls. Adding an action = add a row to ACTIONS (§4).

Why presses are BUFFERED rather than per-frame
----------------------------------------------
Events arrive at render rate, but game logic runs on the 60Hz physics tick, and
at 144fps most rendered frames run no physics tick at all. A per-frame
"just pressed" flag gets cleared before anything can act on it — measured, that
dropped ~58% of dash inputs. So a press stays actionable for INPUT_BUFFER_TIME
until a physics tick CONSUMES it.

That also buys press-buffering for free: tap dash slightly early and it fires
the instant the current dash ends, which is the fluid chaining §3.2 wants.
"""

import pygame
from .config import INPUT_BUFFER_TIME

# Device tags — an action binds to keys and/or mouse buttons.
KEY = "k"
MOUSE = "m"

ACTIONS = {
    "move_left":  [(KEY, pygame.K_a), (KEY, pygame.K_LEFT)],
    "move_right": [(KEY, pygame.K_d), (KEY, pygame.K_RIGHT)],
    "move_up":    [(KEY, pygame.K_w), (KEY, pygame.K_UP)],
    "move_down":  [(KEY, pygame.K_s), (KEY, pygame.K_DOWN)],
    "dash":       [(KEY, pygame.K_SPACE), (KEY, pygame.K_LSHIFT), (MOUSE, 3)],
    "fire":       [(MOUSE, 1), (KEY, pygame.K_j)],
    "possess":    [(KEY, pygame.K_e), (MOUSE, 2)],
    "swap":       [(KEY, pygame.K_q), (KEY, pygame.K_TAB)],
    "ability":    [(KEY, pygame.K_f)],
    "confirm":    [(KEY, pygame.K_RETURN), (KEY, pygame.K_SPACE)],
    "pause":      [(KEY, pygame.K_ESCAPE)],
    "restart":    [(KEY, pygame.K_r)],
}


class InputState:
    def __init__(self):
        self._held = set()
        self._buffered = {}       # action -> seconds of buffer remaining

    # -- event plumbing ------------------------------------------------------
    def feed_event(self, event):
        if event.type == pygame.KEYDOWN:
            self._press(KEY, event.key)
        elif event.type == pygame.KEYUP:
            self._release(KEY, event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self._press(MOUSE, event.button)
        elif event.type == pygame.MOUSEBUTTONUP:
            self._release(MOUSE, event.button)

    def _press(self, device, code):
        for action, binds in ACTIONS.items():
            if (device, code) in binds:
                self._held.add(action)
                self._buffered[action] = INPUT_BUFFER_TIME

    def _release(self, device, code):
        for action, binds in ACTIONS.items():
            if (device, code) in binds:
                self._held.discard(action)

    def update(self, delta: float):
        """Age the buffer by REAL time, once per rendered frame, before this
        frame's events land."""
        for action in list(self._buffered):
            self._buffered[action] -= delta
            if self._buffered[action] <= 0.0:
                del self._buffered[action]

    def release_all(self):
        """Drop every held key and buffered press — used on state changes so a
        held fire button doesn't carry into the next screen."""
        self._held.clear()
        self._buffered.clear()

    # -- queries -------------------------------------------------------------
    def pressed(self, action: str) -> bool:
        """≈ Input.is_action_pressed(name) — is it held right now."""
        return action in self._held

    def just_pressed(self, action: str) -> bool:
        """≈ Input.is_action_just_pressed(name). A PEEK: does not consume."""
        return action in self._buffered

    def consume(self, action: str) -> bool:
        """Take the buffered press. Game logic in physics_process uses this, so
        one press can only be acted on once even when a slow frame runs several
        physics ticks back to back.

        Guard readiness FIRST — `if ready and inp.consume("dash")` — so a press
        isn't eaten by a tick that couldn't have acted on it anyway.
        """
        if action in self._buffered:
            del self._buffered[action]
            return True
        return False

    def get_vector(self, left, right, up, down):
        """≈ Input.get_vector(...) — length <= 1, so diagonals aren't faster."""
        from pygame.math import Vector2
        v = Vector2(self.pressed(right) - self.pressed(left),
                    self.pressed(down) - self.pressed(up))
        if v.length() > 1.0:
            v = v.normalize()
        return v
