"""
audio.py — every sound in the game, synthesised at boot. No asset files.

Why synthesis rather than .wav files: the game has no art budget yet, and
placeholder *sound* is far more load-bearing than placeholder art. A dash with
no whoosh and a hit with no crunch read as broken even when the systems are
perfect. These are deliberately cheap, dry, arcade-ish noises — good enough to
make the game feel like it's responding, and easy to replace one at a time.

→ Godot: this whole file is replaced by AudioStreamPlayer nodes pointing at real
  samples. Keep `Audio.play(name)` as the call site and the port is a swap of
  the backend, not of the ~30 places that make noise.

Everything degrades to silence: if the mixer won't initialise (CI, a headless
box, no audio device) every call becomes a no-op rather than an exception.
"""

import array
import math
import random

import pygame

SR = 44100           # must match the mixer; Sound(buffer=) is format-sensitive


# ---------------------------------------------------------------------------
# tiny synth
# ---------------------------------------------------------------------------
def _env(i, n, attack=0.01, release=0.6, curve=2.0):
    """Percussive envelope: fast attack, exponential-ish decay."""
    a = max(1, int(n * attack))
    if i < a:
        return i / a
    t = (i - a) / max(1, n - a)
    return max(0.0, (1.0 - t) ** curve) * (1.0 if release else 1.0)


def _sine(ph):
    return math.sin(ph)


def _square(ph):
    return 1.0 if math.sin(ph) >= 0 else -1.0


def _saw(ph):
    return (ph / math.pi) % 2.0 - 1.0


def _tri(ph):
    return 2.0 * abs((ph / math.pi) % 2.0 - 1.0) - 1.0


WAVES = {"sine": _sine, "square": _square, "saw": _saw, "tri": _tri}


def tone(dur, f0, f1=None, wave="sine", attack=0.005, curve=2.0, gain=1.0,
         vibrato=0.0, vib_hz=18.0):
    """A pitch-swept oscillator with a percussive envelope."""
    n = int(SR * dur)
    f1 = f0 if f1 is None else f1
    w = WAVES[wave]
    out = [0.0] * n
    ph = 0.0
    for i in range(n):
        t = i / n
        f = f0 + (f1 - f0) * t
        if vibrato:
            f *= 1.0 + vibrato * math.sin(2 * math.pi * vib_hz * i / SR)
        ph += 2 * math.pi * f / SR
        out[i] = w(ph) * _env(i, n, attack, 1, curve) * gain
    return out


def noise(dur, attack=0.001, curve=3.0, gain=1.0, lp=0.0, rng=None):
    """White noise, optionally smoothed into something closer to a whoosh.
    `lp` in 0..1 — higher is duller."""
    rng = rng or random
    n = int(SR * dur)
    out = [0.0] * n
    prev = 0.0
    for i in range(n):
        s = rng.uniform(-1.0, 1.0)
        if lp:
            s = prev + (s - prev) * (1.0 - lp)
            prev = s
        out[i] = s * _env(i, n, attack, 1, curve) * gain
    return out


def mix(*layers):
    n = max(len(x) for x in layers)
    out = [0.0] * n
    for layer in layers:
        for i, v in enumerate(layer):
            out[i] += v
    return out


def delay(samples, seconds, feedback=0.35, mixamt=0.5):
    """One cheap echo tap — makes a flat blip sound like it happened somewhere."""
    d = int(SR * seconds)
    out = list(samples) + [0.0] * d
    for i in range(len(samples)):
        j = i + d
        if j < len(out):
            out[j] += samples[i] * feedback * mixamt
    return out


def to_sound(samples, volume=1.0):
    """Clip, convert to int16 and duplicate to stereo."""
    buf = array.array("h")
    for s in samples:
        v = s * volume
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        iv = int(v * 32000)
        buf.append(iv)
        buf.append(iv)
    return pygame.mixer.Sound(buffer=buf.tobytes())


# ---------------------------------------------------------------------------
# the sound bank
# ---------------------------------------------------------------------------
def _build(rng):
    """name -> (samples, base volume, min seconds between retriggers)."""
    b = {}

    # -- weapons. each archetype needs its own voice or fights turn to mush --
    b["shot_light"] = (mix(tone(0.10, 900, 260, "square", gain=0.28, curve=3.5),
                           noise(0.05, gain=0.14, lp=0.3, rng=rng)), 0.34, 0.03)
    b["shot_burst"] = (mix(tone(0.09, 1250, 420, "saw", gain=0.24, curve=3.0),
                           noise(0.04, gain=0.12, lp=0.4, rng=rng)), 0.30, 0.03)
    b["shot_shotgun"] = (mix(noise(0.16, gain=0.40, lp=0.55, curve=2.4, rng=rng),
                             tone(0.10, 320, 120, "square", gain=0.20, curve=3.0)), 0.40, 0.05)
    b["shot_heavy"] = (mix(tone(0.26, 180, 54, "square", gain=0.42, curve=1.8),
                           noise(0.13, gain=0.26, lp=0.6, rng=rng)), 0.50, 0.06)
    b["shot_radial"] = (mix(tone(0.20, 520, 190, "tri", gain=0.30, curve=2.2,
                                 vibrato=0.05),
                            noise(0.07, gain=0.10, lp=0.5, rng=rng)), 0.34, 0.05)

    b["shot_rail"] = (delay(mix(tone(0.22, 2400, 300, "saw", gain=0.30, curve=2.6),
                                noise(0.06, gain=0.22, lp=0.15, rng=rng)),
                            0.045, feedback=0.3, mixamt=0.35), 0.46, 0.06)

    b["slash"] = (mix(noise(0.14, gain=0.36, lp=0.1, curve=2.0, rng=rng),
                      tone(0.12, 1800, 700, "saw", gain=0.14, curve=2.5)), 0.40, 0.04)
    b["fuse"] = (mix(noise(0.30, gain=0.22, lp=0.05, attack=0.02, curve=0.9, rng=rng),
                     tone(0.30, 500, 900, "square", gain=0.10, curve=1.2)), 0.34, 0.08)
    b["fuse_beep"] = (tone(0.045, 1760, 1760, "square", gain=0.22, curve=2.0), 0.26, 0.03)
    b["explode"] = (delay(mix(noise(0.55, gain=0.55, lp=0.72, curve=1.6, rng=rng),
                              tone(0.45, 130, 36, "square", gain=0.40, curve=1.3)),
                          0.09, feedback=0.4), 0.70, 0.05)
    b["clink"] = (mix(tone(0.08, 3200, 2600, "tri", gain=0.22, curve=3.0),
                      tone(0.06, 4700, 4100, "sine", gain=0.12, curve=3.0)), 0.30, 0.03)
    b["backstab"] = (delay(mix(tone(0.30, 2200, 500, "saw", gain=0.30, curve=1.8),
                               noise(0.18, gain=0.30, lp=0.2, curve=2.0, rng=rng)),
                           0.07, feedback=0.5), 0.62, 0.10)

    b["dagger_throw"] = (mix(noise(0.08, gain=0.26, lp=0.05, curve=2.5, rng=rng),
                             tone(0.07, 2600, 1400, "tri", gain=0.14, curve=2.5)), 0.32, 0.04)
    b["sneak"] = (mix(tone(0.40, 900, 140, "sine", gain=0.26, attack=0.02, curve=1.2,
                           vibrato=0.12, vib_hz=14),
                      noise(0.35, gain=0.18, lp=0.8, attack=0.05, curve=1.0, rng=rng)), 0.46, 0.2)
    b["sneak_in"] = (mix(noise(0.12, gain=0.30, lp=0.4, curve=2.5, rng=rng),
                         tone(0.14, 180, 720, "saw", gain=0.18, curve=2.2)), 0.46, 0.1)
    b["summon"] = (delay(tone(0.80, 70, 160, "saw", gain=0.34, attack=0.1, curve=0.8,
                              vibrato=0.1, vib_hz=5), 0.12, feedback=0.45), 0.52, 0.5)
    b["summon_pop"] = (mix(tone(0.12, 300, 900, "square", gain=0.18, curve=2.0),
                           noise(0.10, gain=0.2, lp=0.5, rng=rng)), 0.36, 0.1)
    b["poison"] = (mix(tone(0.25, 420, 300, "sine", gain=0.22, curve=1.6,
                            vibrato=0.2, vib_hz=18),
                       noise(0.18, gain=0.12, lp=0.85, curve=1.5, rng=rng)), 0.40, 0.15)

    # -- impacts --
    b["hit"] = (mix(noise(0.07, gain=0.36, lp=0.42, curve=3.5, rng=rng),
                    tone(0.06, 420, 150, "square", gain=0.20, curve=4.0)), 0.40, 0.02)
    b["crit"] = (delay(mix(tone(0.20, 1500, 620, "square", gain=0.30, curve=2.0),
                           noise(0.09, gain=0.26, lp=0.2, rng=rng)),
                       0.055, feedback=0.5), 0.52, 0.02)
    b["wall_hit"] = (noise(0.05, gain=0.22, lp=0.65, curve=4.0, rng=rng), 0.22, 0.03)
    b["player_hurt"] = (mix(tone(0.30, 300, 70, "saw", gain=0.40, curve=1.6),
                            noise(0.14, gain=0.30, lp=0.5, rng=rng)), 0.60, 0.10)
    b["enemy_die"] = (mix(tone(0.30, 420, 60, "tri", gain=0.34, curve=1.5),
                          noise(0.20, gain=0.30, lp=0.55, curve=2.0, rng=rng)), 0.42, 0.03)

    # -- movement --
    b["dash"] = (mix(noise(0.20, gain=0.34, lp=0.72, curve=2.2, rng=rng),
                     tone(0.16, 240, 620, "sine", gain=0.16, curve=2.0)), 0.34, 0.04)

    # -- the telegraph. this one matters more than any other sound in the game:
    #    it's the audio half of the dodge cue, and it has to cut through a fight
    b["telegraph"] = (tone(0.26, 220, 700, "saw", gain=0.26, attack=0.02,
                           curve=0.8), 0.34, 0.06)

    # -- §3.4 payoff --
    b["perfect"] = (delay(mix(tone(0.55, 300, 1750, "sine", gain=0.34, attack=0.01,
                                   curve=0.7),
                              tone(0.40, 900, 2600, "tri", gain=0.16, curve=1.2)),
                          0.09, feedback=0.55), 0.62, 0.30)
    b["witch_end"] = (tone(0.30, 900, 260, "sine", gain=0.22, curve=1.6), 0.30, 0.20)

    # -- §3.5 --
    b["possess"] = (delay(mix(tone(0.45, 120, 560, "saw", gain=0.32, attack=0.03,
                                   curve=1.0, vibrato=0.08, vib_hz=9),
                              noise(0.25, gain=0.20, lp=0.7, curve=1.6, rng=rng)),
                          0.11, feedback=0.45), 0.55, 0.15)
    b["swap"] = (mix(tone(0.16, 640, 1180, "tri", gain=0.26, curve=1.6),
                     noise(0.07, gain=0.10, lp=0.6, rng=rng)), 0.36, 0.08)
    b["body_lost"] = (mix(tone(0.70, 420, 48, "saw", gain=0.40, curve=1.1),
                          noise(0.35, gain=0.26, lp=0.72, curve=1.4, rng=rng)), 0.70, 0.25)

    # -- world / ui --
    b["pickup"] = (mix(tone(0.10, 780, 1170, "sine", gain=0.26, curve=2.0),
                       tone(0.14, 1170, 1560, "sine", gain=0.18, curve=2.0)), 0.36, 0.05)
    b["upgrade"] = (delay(mix(tone(0.18, 520, 780, "tri", gain=0.26, curve=1.8),
                              tone(0.30, 780, 1040, "sine", gain=0.22, curve=1.6)),
                          0.10, feedback=0.4), 0.46, 0.10)
    b["door_open"] = (mix(tone(0.40, 150, 92, "square", gain=0.26, curve=1.4),
                          noise(0.28, gain=0.20, lp=0.78, curve=1.5, rng=rng)), 0.38, 0.20)
    b["cleared"] = (mix(tone(0.14, 660, 880, "tri", gain=0.24, curve=2.0),
                        tone(0.26, 880, 1320, "sine", gain=0.20, curve=1.8)), 0.40, 0.20)
    b["boss"] = (delay(mix(tone(0.95, 110, 44, "saw", gain=0.46, attack=0.05,
                                curve=0.9, vibrato=0.10, vib_hz=6),
                           noise(0.55, gain=0.26, lp=0.80, curve=1.2, rng=rng)),
                       0.16, feedback=0.5), 0.72, 0.5)
    b["descend"] = (delay(tone(0.80, 520, 90, "sine", gain=0.34, attack=0.02,
                               curve=1.0), 0.13, feedback=0.5), 0.55, 0.5)
    b["ui"] = (tone(0.06, 900, 900, "square", gain=0.16, curve=3.0), 0.24, 0.02)
    b["game_over"] = (delay(tone(1.10, 260, 40, "saw", gain=0.44, attack=0.06,
                                 curve=0.8), 0.18, feedback=0.55), 0.70, 1.0)
    b["victory"] = (delay(mix(tone(0.30, 520, 780, "tri", gain=0.28, curve=2.0),
                              tone(0.55, 780, 1560, "sine", gain=0.24, curve=1.4)),
                          0.14, feedback=0.5), 0.62, 1.0)
    return b


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
class Audio:
    def __init__(self, master=0.7, seed=7):
        self.master = master
        self.muted = False
        self.ok = False
        self.sounds = {}
        self._last = {}
        self._gaps = {}
        self._clock = 0.0
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=512)
            pygame.mixer.set_num_channels(24)
            rng = random.Random(seed)
            for name, (samples, vol, gap) in _build(rng).items():
                self.sounds[name] = to_sound(samples, vol)
                self._gaps[name] = gap
                self._last[name] = -99.0
            self.ok = True
        except Exception:
            # No device, no mixer, no problem — the game runs silent.
            self.ok = False

    def update(self, delta):
        self._clock += delta

    def toggle_mute(self):
        self.muted = not self.muted
        if self.ok and self.muted:
            pygame.mixer.stop()
        return self.muted

    def play(self, name, volume=1.0, pitch=0.0):
        """`pitch` is cosmetic variance in semitone-ish units; pygame can't
        repitch a Sound, so it's folded into volume jitter instead. It's here so
        the call sites already read the way they will in Godot."""
        if not self.ok or self.muted:
            return
        snd = self.sounds.get(name)
        if snd is None:
            return
        # Rate-limit retriggers: a 13-shot radial volley firing 13 copies of the
        # same sample on the same frame is just clipping.
        if self._clock - self._last[name] < self._gaps[name]:
            return
        self._last[name] = self._clock
        try:
            ch = pygame.mixer.find_channel(True)
            if ch is None:
                return
            v = max(0.0, min(1.0, self.master * volume * (1.0 + 0.12 * pitch)))
            ch.set_volume(v)
            ch.play(snd)
        except Exception:
            pass

    def play_at(self, name, pos, listener, volume=1.0, falloff=900.0):
        """Distance-attenuated and panned. → Godot: AudioStreamPlayer2D does
        both for free; this exists so enemies across the room aren't as loud as
        the one chewing on you."""
        if not self.ok or self.muted or listener is None:
            return
        d = pos - listener
        dist = d.length()
        if dist > falloff:
            return
        self.play(name, volume * (1.0 - dist / falloff))
