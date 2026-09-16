"""
HUSK — a momentum-driven top-down roguelite. Desktop build (Pygame-CE).

Module map, and what each becomes in Godot 4 (GAME-CONCEPT.md §4):

    config.py       tunables            → Resources / @export vars
    inputs.py       named actions       → InputMap + Input singleton
    core.py         Entity, Signal,     → Node2D base, signals, Camera2D,
                    Camera, collision      and move_and_slide() replaces the
                                           collision block wholesale
    weapons.py      Projectile          → Area2D scene
    actors.py       Actor               → CharacterBody2D scene  ← the key type
    controllers.py  PlayerController    → a Node on the actor (or an autoload)
    ai.py           enemy brains        → a Node running the same FSM
    combat.py       hit resolution      → Area2D signals + layer masks
    world.py        rooms, floor gen    → level scenes + a layout Resource
    pickups.py      Pickup              → Area2D with body_entered
    relics.py       boss rewards        → Resources + a RelicManager autoload
    lore.py         the story's text    → a Resource / CSV for localisation
    hud.py          HUD                 → CanvasLayer + Control
    app.py          Game                → Main scene + the engine loop

The one idea holding it together: Player, party member and enemy are all
`Actor`. The only difference is which Controller is plugged into `.controller`,
so possession (§3.5) is an assignment rather than a subsystem.
"""

__all__ = ["app"]
