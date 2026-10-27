"""Shared, bounded cooldown for report-provider rate limits."""
import asyncio
import math
import time
import weakref
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_delay(response, attempt):
    minimum = min(120.0, 30.0 * (2 ** attempt))
    value = response.headers.get('Retry-After', '')
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
            delay = (date-datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):delay=minimum
    return max(minimum, delay) if math.isfinite(delay) else minimum


class Cooldown:
    def __init__(self, clock=time.monotonic, sleep=asyncio.sleep):
        self.clock=clock;self.sleep=sleep;self.until=0.0

    def defer(self, delay):
        self.until=max(self.until,self.clock()+delay)

    async def wait(self):
        while (remaining:=self.until-self.clock())>0:
            await self.sleep(min(remaining,30.0))


_COOLDOWNS=weakref.WeakKeyDictionary()


def report_cooldown():
    loop=asyncio.get_running_loop()
    if loop not in _COOLDOWNS:_COOLDOWNS[loop]=Cooldown()
    return _COOLDOWNS[loop]
