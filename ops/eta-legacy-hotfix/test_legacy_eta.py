"""Bounded legacy ETA artifact tests, no network or current runtime imports."""
import ast
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).with_name('eta.py')
def load():
    tree = ast.parse(SOURCE.read_text())
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    env = dict(logging=logging, datetime=datetime, timedelta=timedelta, AsyncConnection=object, WorkloadItem=object)
    exec(compile(tree, str(SOURCE), 'exec'), env)
    return env

class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows
    async def fetchone(self): return self.rows[0] if self.rows else None

class Connection:
    def __init__(self, at, previous, created=-61):
        self.at=at; self.previous=previous; self.created=at+timedelta(seconds=created); self.pending=False; self.queries=[]
    async def execute(self, sql, args):
        self.queries.append((sql,args))
        if 'FROM eta_targets' in sql:
            return Cursor([dict(id=1,checkpoint_id=17,target_at=self.at+timedelta(hours=4),tolerance_seconds=900,created_at=self.created)])
        if 'FROM observations' in sql:
            checkpoint,at,created=args
            valid=[p for p in self.previous if p['checkpoint_id']==checkpoint and created<=p['time']<at]
            return Cursor(sorted(valid,key=lambda p:p['time'],reverse=True)[:1])
        if 'INSERT INTO eta_alerts' in sql:
            if self.pending:return Cursor([])
            self.pending=True; return Cursor([dict(id=2)])
        raise AssertionError('unexpected SQL')

class LegacyETA(unittest.TestCase):
    def exercise(self, *, previous=10800,status='legacy_unknown',current=18000,paused=False,previous_paused=False,created=-61,offset=-60,vehicles=0,expected=1):
        at=datetime(2026,10,14,12,tzinfo=timezone.utc)
        history=[] if previous is None else [dict(checkpoint_id=17,time=at+timedelta(seconds=offset),wait_time_seconds=previous,wait_time_status=status,is_paused=previous_paused,vehicles_in_queue=0)]
        conn=Connection(at,history,created)
        item=SimpleNamespace(id=17,wait_time=current,is_paused=paused,vehicles_in_queue=vehicles)
        module=load()
        self.assertEqual(asyncio.run(module['evaluate'](conn,at,[item])),expected)
        self.assertEqual(asyncio.run(module['evaluate'](conn,at,[item])),0)
    def test_forward_jump(self): self.exercise()
    def test_existing_window(self):
        for current in [13500,14400,15300]:
            with self.subTest(current=current):self.exercise(previous=None,current=current)
    def test_legacy_positive_paused(self): self.exercise(previous_paused=True,paused=True)
    def test_legacy_zero_barrier(self): self.exercise(previous=0,expected=0)
    def test_missing_barrier(self): self.exercise(previous=0,status='missing',expected=0)
    def test_paused_zero_barrier(self): self.exercise(previous=0,status='reported',previous_paused=True,expected=0)
    def test_previous_before_subscription(self): self.exercise(created=-30,expected=0)
    def test_previous_at_subscription(self): self.exercise(created=-60)
    def test_current_row_excluded(self): self.exercise(offset=0,expected=0)
    def test_reverse(self): self.exercise(previous=18000,current=10800,expected=0)
    def test_already_above(self): self.exercise(previous=18000,expected=0)
    def test_current_legacy_zero_filter(self):
        self.exercise(current=0,paused=True,expected=0)
        self.exercise(current=0,vehicles=1,expected=0)

if __name__=='__main__': unittest.main()
