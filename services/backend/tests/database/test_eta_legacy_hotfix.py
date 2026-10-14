"""Legacy ETA artifact against exact service-role PostgreSQL, no network."""
import asyncio
import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from avelren.models import WorkloadItem

if os.environ.get('AVELREN_TEST_INSTALLED_LEGACY_ETA') == '1':
    from avelren import eta
else:
    path=Path(__file__).resolve().parents[4]/'ops/eta-legacy-hotfix/eta.py'
    spec=importlib.util.spec_from_file_location('avelren.legacy_eta_backport',path)
    eta=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eta)

@pytest.mark.parametrize('wait,status,paused,vehicles,offset,created,current,current_paused,current_vehicles,expected',[
    (10800,'legacy_unknown',False,0,-60,-61,18000,False,0,1),
    (10800,None,False,0,-60,-61,18000,False,0,1),
    (0,'legacy_unknown',False,0,-60,-61,18000,False,0,1),
    (0,'legacy_unknown',False,1,-60,-61,18000,False,0,0),
    (0,'legacy_unknown',True,0,-60,-61,18000,False,0,0),
    (0,'missing',False,0,-60,-61,18000,False,0,0),
    (10800,'legacy_unknown',True,0,-60,-61,18000,True,0,1),
    (10800,'legacy_unknown',False,0,-60,-30,18000,False,0,0),
    (10800,'legacy_unknown',False,0,-60,-60,18000,False,0,1),
    (10800,'legacy_unknown',False,0,0,-61,18000,False,0,0),
    (18000,'legacy_unknown',False,0,-60,-61,10800,False,0,0),
    (18000,'legacy_unknown',False,0,-60,-61,19000,False,0,0),
    (0,'missing',False,0,-60,-61,13500,False,0,1),
    (0,'missing',False,0,-60,-61,15300,False,0,1),
    (10800,'legacy_unknown',False,0,-60,-61,0,True,0,0),
    (10800,'legacy_unknown',False,0,-60,-61,0,False,1,0),
])
def test_legacy_eta_service_role(database,wait,status,paused,vehicles,offset,created,current,current_paused,current_vehicles,expected):
    at=datetime.now(UTC)
    with psycopg.connect(database('admin')) as c:
        c.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'fixture',1)")
        device=c.execute("INSERT INTO devices(secret_hash) VALUES('fixture') RETURNING id").fetchone()[0]
        target=c.execute('INSERT INTO eta_targets(device_id,checkpoint_id,target_at,tolerance_seconds,created_at) VALUES(%s,17,%s,900,%s) RETURNING id',(device,at+timedelta(hours=4),at+timedelta(seconds=created))).fetchone()[0]
        # Current observation already inserted by replay; cannot count as predecessor.
        for t,w,s,p,v in [(at+timedelta(seconds=offset),wait,status,paused,vehicles),(at,current,'legacy_unknown',current_paused,current_vehicles)]:
            c.execute('INSERT INTO observations(time,checkpoint_id,wait_time_seconds,wait_time_status,is_paused,vehicles_in_queue) VALUES(%s,17,%s,%s,%s,%s) ON CONFLICT (checkpoint_id,time) DO UPDATE SET wait_time_seconds=EXCLUDED.wait_time_seconds,wait_time_status=EXCLUDED.wait_time_status,is_paused=EXCLUDED.is_paused,vehicles_in_queue=EXCLUDED.vehicles_in_queue',(t,w,s,p,v))
    async def run():
        async with await psycopg.AsyncConnection.connect(database('collector'),row_factory=dict_row) as c:
            assert (await(await c.execute('SELECT session_user')).fetchone())['session_user']=='avelren_collector'
            item=WorkloadItem(id=17,title='fixture',for_vehicle_type=1,wait_time=current,is_paused=current_paused,vehicles_in_queue=current_vehicles)
            assert await eta.evaluate(c,at,[item])==expected
            assert await eta.evaluate(c,at,[item])==0
    asyncio.run(run())
    with psycopg.connect(database('admin')) as c:
        rows=c.execute('SELECT target_id,wait_seconds_at_trigger,status FROM eta_alerts').fetchall()
    assert rows==([(target,current,'pending')] if expected else [])
