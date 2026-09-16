# husk/assets — drop-in art

Anything here replaces the matching code-drawn art in `husk/art.py`, one file
at a time. Missing files just keep the generated look, so you can replace the
game piece by piece. All art is scaled with nearest-neighbour, so pixel art
stays crisp.

| What | Path | Format |
|---|---|---|
| Body animation | `bodies/<design>/<anim>.png` | A horizontal strip of **square** frames, the body **facing right**, feet on the bottom row (2px margin). Frame count = width ÷ height. |
| Weapon | `weapons/<design>.png` | Facing right, **grip at the middle of the left edge**. Drawn at 2× its pixel size. |
| Floor tiles | `tiles/<depth>/*.png` | Any number of tiles, scaled to 32×32. Depth is `0`, `1` or `2`. Picked at random. |
| Props (the obstacles) | `props/<kind>.png` | Stretched to the obstacle's box. Kinds: `crate`, `barrels`, `cage`, `coffin`, `desk`. |
| Pickups | `pickups/<kind>.png` | `health`, `upgrade`, `stairs`. |

**Designs** (folder names): `vessel`, `grunt`, `gunner`, `lancer`, `brute`,
`turret`, `detonator`, `assassin`, `shrike`, `turnkey`, `warden`.
(`turnkey` is the floor-1 boss, `warden` the floor-3 one; they share a body.)

**Animations** (file names): `idle`, `walk`, `dash`, `windup`, `strike`,
`dazed`. Only `idle.png` is required — a missing animation falls back to it.

**Sizes the generated art uses** (pixels, before the 2× scale), a good guide:
vessel/grunt/assassin 20, gunner/lancer 22, turret 24, shrike 28, brute 30,
turnkey/warden 40, detonator 16.

Keep the things the game relies on readable: the assassin and the Shrike need a
clear **back**, the detonator a visible **core**. Telegraphs, the weak point,
the elite ring and poison are drawn on top by the game, so don't paint them in.
