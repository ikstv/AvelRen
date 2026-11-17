"""Refresh the source vehicle time independently of the workload collector."""

import asyncio
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .echerha import REQUIRED_HEADERS

log = logging.getLogger(__name__)
MONTHS = dict(zip(
    ('січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
     'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'), range(1, 13),
))


def source_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        match = re.fullmatch(r'\s*(\d{1,2})\s+(\S+)\s+(\d{1,2}):(\d{2})\s*', value)
        if not match or match[2] not in MONTHS:
            return None
        now = datetime.now(ZoneInfo('Europe/Kyiv'))
        candidates = []
        for year in (now.year - 1, now.year, now.year + 1):
            try:
                candidates.append(datetime(year, MONTHS[match[2]], int(match[1]),
                                           int(match[3]), int(match[4]), tzinfo=now.tzinfo))
            except ValueError:
                pass
        return min(candidates, key=lambda d: abs((d - now).total_seconds())).isoformat() if candidates else None


def select_vehicle(rows):
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        extra = row.get('additional') or {}
        if not isinstance(extra, dict):
            continue
        icons = extra.get('icons', [])
        if not isinstance(icons, list) or 4 in icons or 10 in icons:
            continue
        value = source_time(row.get('estimated_time'))
        if value is not None:
            return value
    return None


async def pause(stop, seconds):
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0.01, seconds))
    except TimeoutError:
        pass


async def refresh_loop(stop):
    # One sequential details worker, fewer than 10 attempts/minute, no immediate retries.
    last_request = None
    headers = {**REQUIRED_HEADERS,
        'X-User-Agent': f'UABorder/{settings.echerha_client_version} Web/1.1.0 User/guest',
        'X-Device-Id': settings.echerha_device_id,
        'X-Device-Name': settings.echerha_device_name,
        'User-Agent': settings.user_agent}
    async with AsyncConnectionPool(settings.database_dsn, min_size=0, max_size=1,
                                   open=False) as pool:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds,
                                     headers=headers, follow_redirects=False) as client:
            async def get(checkpoint, page):
                nonlocal last_request
                if last_request is not None:
                    await pause(stop, 6.1 - (time.monotonic() - last_request))
                if stop.is_set():
                    raise asyncio.CancelledError
                last_request = time.monotonic()
                url = settings.workload_url + f'/checkpoints/{checkpoint}/details/1/30'
                response = await client.get(url, params={'page': page}, auth=None)
                if response.status_code == 429:
                    retry = response.headers.get('retry-after', '')
                    await pause(stop, max(60, min(int(retry), 3600)) if retry.isdigit() else 60)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                    raise ValueError('invalid details payload')
                return payload

            await pause(stop, 65)
            while not stop.is_set():
                try:
                    async with pool.connection() as conn:
                        rows = await (await conn.execute(
                            'SELECT id FROM checkpoints WHERE for_vehicle_type=1 '
                            "AND last_seen > now()-interval '1 hour' ORDER BY id"
                        )).fetchall()
                    if not rows:
                        await pause(stop, 30)
                    for (checkpoint,) in rows:
                        if stop.is_set():
                            break
                        try:
                            first = await get(checkpoint, 1)
                            last = int((first.get('meta') or {}).get('last_page', 1))
                            if not 1 <= last <= 10000:
                                raise ValueError('invalid last page')
                            # Bound per-checkpoint work, retaining round-robin fairness.
                            value = None
                            for page in range(last, max(0, last - 8), -1):
                                payload = first if page == 1 else await get(checkpoint, page)
                                value = select_vehicle(payload['data'])
                                if value is not None:
                                    break
                            if value is not None:
                                async with pool.connection() as conn:
                                    await conn.execute(
                                        'UPDATE observations SET stable_entry_time=%s '
                                        "WHERE time > now()-interval '1 hour' AND checkpoint_id=%s AND time="
                                        '(SELECT max(time) FROM observations WHERE checkpoint_id=%s)',
                                        (value, checkpoint, checkpoint),
                                    )
                                log.info('source vehicle time refreshed checkpoint=%s value=%s', checkpoint, value)
                        except (httpx.HTTPError, ValueError, TypeError) as exc:
                            log.warning('source vehicle time unavailable checkpoint=%s reason=%s',
                                        checkpoint, type(exc).__name__)
                            await pause(stop, 6.1)
                except Exception as exc:
                    log.warning('source vehicle worker unavailable reason=%s', type(exc).__name__)
                    await pause(stop, 30)
