"""Human-like behavioral jitter for anti-detection.

All deterministic cooldowns, thresholds, and delays in the automation system
should pass through this module to add natural human variance — humans don't
click at exactly 0.500s intervals or move to exactly the same pixel.

Usage:
    from src.core.behavior_randomizer import jitter, maybe, human_interval

    # Flask cooldown: 0.5s ±30%
    if now - last_flask >= jitter(0.5, 0.3):
        press_flask()

    # Skip an action 10% of the time (humans get distracted)
    if maybe(0.1):
        skip_this_tick()

    # Return a randomized interval that lasts for one comparison
    next_click_at = human_interval(1.5, 0.25)  # → e.g. 1.73s from now
"""

from __future__ import annotations

import random
import time


_global_seed = int(time.time_ns() % (2**32))
_rng = random.Random(_global_seed)


def reseed() -> None:
    """Reseed the RNG (e.g. on nav session restart)."""
    global _rng
    _rng = random.Random(int(time.time_ns() % (2**32)))


def jitter(base: float, pct: float = 0.2) -> float:
    """Return base ± pct% with uniform distribution.

    jitter(1.0, 0.2)  → 0.80..1.20
    jitter(0.5, 0.3)  → 0.35..0.65
    """
    return base * (1.0 + _rng.uniform(-pct, pct))


def jitter_up(base: float, pct: float = 0.3) -> float:
    """Return base + [0, pct%] — only increase, never decrease.

    jitter_up(1.0, 0.3) → 1.00..1.30
    """
    return base * (1.0 + _rng.uniform(0, pct))


def jitter_down(base: float, pct: float = 0.3) -> float:
    """Return base - [0, pct%] — only decrease, never increase.

    jitter_down(1.0, 0.3) → 0.70..1.00
    """
    return base * (1.0 - _rng.uniform(0, pct))


def maybe(chance: float = 0.1) -> bool:
    """Return True with probability `chance` (0.0–1.0).

    maybe(0.15) → True 15% of the time.
    """
    return _rng.random() < chance


def between(lo: float, hi: float) -> float:
    """Return uniform float in [lo, hi]."""
    return _rng.uniform(lo, hi)


def human_interval(base: float, jitter_pct: float = 0.25) -> float:
    """Return an absolute timestamp (monotonic seconds) at least `base` seconds
    from now, with added jitter. Use this to set next-action deadlines.

    next_flask = human_interval(0.5, 0.2)  # 0.50..0.60s from now
    ...
    if time.monotonic() >= next_flask:
        press_flask()
        next_flask = human_interval(0.5, 0.2)
    """
    return time.monotonic() + jitter_up(base, jitter_pct)


def position_jitter(x: float, y: float, spread: float = 3.0) -> tuple[float, float]:
    """Add small random offset to a target position.

    position_jitter(100, 200, 3.0) → (97.2, 201.8) etc.
    """
    return (x + _rng.uniform(-spread, spread), y + _rng.uniform(-spread, spread))
