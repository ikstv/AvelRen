"""Disposable acceptance: real daemon and DB; only HTTP transport is synthetic."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import httpx
import psycopg
from avelren import collector
from avelren.collector_spool import SpoolStore
from avelren.config import settings

DIRECTORY = Path('/var/lib/avelren/collector-spool')
PATH = DIRECTORY / 'cycles.sqlite3'
TRACE = DIRECTORY / 'synthetic-requests.jsonl'
BACKUP = DIRECTORY / 'acceptance-backup.sqlite3'
DEVICE = '11111111-1111-4111-8111-111111111111'


def requests():
    return [json.loads(line) for line in TRACE.read_text().splitlines()] if TRACE.exists() else []


def response(request):
    assert str(request.url) == 'https://back.echerha.gov.ua/api/v5/workload/1'
    assert request.headers['X-Device-Id'] == DEVICE
    assert 'Authorization' not in request.headers and 'Cookie' not in request.headers
    number = len(requests()) + 1
    with TRACE.open('a') as stream:
        stream.write(json.dumps({'number': number, 'at': time.time()}) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return httpx.Response(200, json={
        'filters': {'countries': [{'id': 1, 'name': 'Poland'}]},
        'data': [{'id': 7, 'title': 'Synthetic truck', 'country_id': 1,
                  'for_vehicle_type': 1, 'wait_time': 60 if number <= 5 else 3600,
                  'vehicle_in_active_queues_counts': number + 59 if number <= 5 else 0}],
    })


def wait(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(f'acceptance condition not reached within {seconds}s')


def seed():
    with psycopg.connect(settings.database_dsn) as conn:
        conn.execute("INSERT INTO countries(id,name) VALUES (1,'Poland')")
        conn.execute("INSERT INTO checkpoints(id,title,country_id,for_vehicle_type) "
                     "VALUES (7,'Synthetic truck',1,1)")
        conn.execute("INSERT INTO devices(id,platform,fcm_token) VALUES (%s,'android','test-only')",
                     (DEVICE,))
        conn.execute("INSERT INTO subscriptions(device_id,checkpoint_id,threshold) VALUES (%s,7,50)",
                     (DEVICE,))
        conn.execute("INSERT INTO eta_targets(device_id,checkpoint_id,target_at,tolerance_seconds) "
                     "VALUES (%s,7,now()+interval '60 seconds',30)", (DEVICE,))
        conn.execute('CREATE TABLE spool_replay_order(seq bigserial, at timestamptz)')
        conn.execute("""CREATE FUNCTION spool_record_order() RETURNS trigger
                     LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
                     BEGIN INSERT INTO public.spool_replay_order(at) VALUES (NEW.time);
                     RETURN NEW; END $$""")
        conn.execute('CREATE TRIGGER spool_test_order AFTER INSERT ON collector_runs '
                     'FOR EACH ROW EXECUTE FUNCTION spool_record_order()')


def verify(store):
    backup = SpoolStore(BACKUP)
    try:
        captured = backup.conn.execute(
            "SELECT at,payload FROM cycles WHERE state='pending' ORDER BY seq"
        ).fetchall()
    finally:
        backup.close()
    assert len(captured) >= 6
    with psycopg.connect(settings.database_dsn) as conn:
        rows = conn.execute('SELECT time,wait_time_seconds,vehicles_in_queue FROM observations '
                            'WHERE checkpoint_id=7 ORDER BY time').fetchall()
        runs = conn.execute('SELECT time,rows_written,derived_error FROM collector_runs '
                            'ORDER BY time').fetchall()
        order = conn.execute('SELECT at FROM spool_replay_order ORDER BY seq').fetchall()
        assert conn.execute('SELECT count(*) FROM alerts').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM eta_alerts').fetchone()[0] == 0
    expected_times = [datetime.fromisoformat(at) for at, _ in captured]
    assert [row[0] for row in rows] == expected_times
    assert [row[0] for row in runs] == expected_times
    assert [row[0] for row in order] == expected_times
    assert [row[1:] for row in rows[:5]] == [(60,60),(60,61),(60,62),(60,63),(60,64)]
    assert all(row[1:] == (3600,0) for row in rows[5:])
    assert all(row[1] == 1 for row in runs)
    assert all('delayed_replay_over_120s' in row[2] for row in runs[:5])
    for row, (_, payload) in zip(rows, captured, strict=True):
        item = json.loads(payload)['items'][0]
        assert row[1:] == (item['wait_time'], item['vehicle_in_active_queues_counts'])
    calls = requests()
    assert len(calls) == len(rows), 'missing or duplicated captured cycle'
    assert all(b['at'] - a['at'] >= 59.5 for a,b in pairwise(calls))
    assert store.status().pending_count == 0
    assert store.capture_only() and store.status().mode_ack is True
    print(f'verified {len(rows)} cycles, actual FIFO inserts, no duplicate/stale alerts')


def main():
    os.umask(0o077)
    action = sys.argv[1]
    if action == 'run':
        client_type = httpx.AsyncClient
        collector.httpx.AsyncClient = lambda **kwargs: client_type(
            transport=httpx.MockTransport(response), **kwargs,
        )
        asyncio.run(collector.main())
        return
    if action == 'seed':
        seed()
        return
    if action == 'wait-next':
        time.sleep(max(0, requests()[-1]['at'] + 60.1 - time.time()))
        return
    store = SpoolStore(PATH)
    try:
        assert os.geteuid() == 10001
        assert DIRECTORY.stat().st_mode & 0o777 == 0o700
        assert PATH.stat().st_mode & 0o777 == 0o600
        if action == 'wait-cycles':
            count, seconds = map(int, sys.argv[2:])
            wait(lambda: len(requests()) >= count and store.status().pending_count >= count, seconds)
        elif action == 'wait-aged':
            wait(lambda: time.time() - requests()[4]['at'] > 121, 130)
        elif action == 'paused':
            assert store.capture_only() and store.status().mode_ack is True
            with psycopg.connect(settings.database_dsn) as conn:
                assert conn.execute('SELECT count(*) FROM collector_runs').fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM pg_stat_activity "
                                    "WHERE usename='avelren_collector'").fetchone()[0] == 0
        elif action == 'backup':
            store.backup_to(BACKUP)
        elif action == 'wait-empty':
            wait(lambda: store.status().pending_count == 0, 40)
        elif action == 'verify':
            verify(store)
        else:
            raise AssertionError(f'unknown action: {action}')
        print(action, 'PASS')
    finally:
        store.close()


if __name__ == '__main__':
    main()
