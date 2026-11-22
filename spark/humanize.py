"""拟人化的随机延时与文案抽取。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence


def random_seconds(low: float, high: float) -> float:
    if high <= low:
        return max(0.0, low)
    return random.uniform(low, high)


async def sleep_between(low: float, high: float) -> float:
    delay = random_seconds(low, high)
    await asyncio.sleep(delay)
    return delay


def pick_message(pool: Sequence[str], last_message: str | None = None) -> str:
    """随机挑一条文案，尽量避开上一条。"""
    candidates = [item for item in pool if item != last_message]
    if not candidates:
        candidates = list(pool)
    return random.choice(candidates)


def typing_delay_ms() -> int:
    return random.randint(40, 110)
