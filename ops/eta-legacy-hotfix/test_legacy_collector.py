"""Behavior contract for the bounded legacy collector overlay."""

import ast
import logging
import signal
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

SOURCE = Path(__file__).with_name("collector.py")
DOCKERFILE = Path(__file__).with_name("Dockerfile")


def load():
    tree = ast.parse(SOURCE.read_text())
    tree.body = [
        node
        for node in tree.body
        if not isinstance(node, (ast.Import, ast.ImportFrom))
        and not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        )
    ]
    env = {
        "asyncio": __import__("asyncio"),
        "logging": logging,
        "signal": signal,
        "datetime": __import__("datetime").datetime,
        "UTC": __import__("datetime").UTC,
        "httpx": SimpleNamespace(AsyncClient=object),
    }
    exec(compile(tree, str(SOURCE), "exec"), env)
    return env


class ConnectionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return None


class Pool:
    def connection(self):
        return ConnectionContext()


def run_immediate(coroutine):
    """Drive fakes that complete without I/O; avoids platform event-loop setup."""
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("fixture unexpectedly performed real asynchronous I/O")


class LegacyCollector(unittest.TestCase):
    def test_cycle_evaluates_but_never_auto_expires_monitors(self):
        module = load()
        item = SimpleNamespace(for_vehicle_type=1)
        result = SimpleNamespace(
            response=SimpleNamespace(data=[item], filters=SimpleNamespace(countries=[])),
            error=None,
            http_status=200,
            duration_ms=10,
            body_sha256="fixture",
        )
        alerts = SimpleNamespace(evaluate=AsyncMock(), expire_stale=AsyncMock())
        eta = SimpleNamespace(evaluate=AsyncMock(), expire_passed=AsyncMock())
        module.update(
            settings=SimpleNamespace(echerha_vehicle_type=1),
            fetch_workload=AsyncMock(return_value=result),
            get_pool=lambda: Pool(),
            upsert_countries=AsyncMock(),
            upsert_checkpoints=AsyncMock(),
            insert_observations=AsyncMock(return_value=1),
            record_run=AsyncMock(),
            record_derived=AsyncMock(),
            describe_exception=lambda exc: str(exc),
            alerts=alerts,
            eta=eta,
        )

        run_immediate(module["run_cycle"](object()))

        alerts.evaluate.assert_awaited_once()
        eta.evaluate.assert_awaited_once()
        alerts.expire_stale.assert_not_awaited()
        eta.expire_passed.assert_not_awaited()
        module["record_derived"].assert_awaited_once()

    def test_image_overlays_only_eta_and_collector(self):
        copies = [
            line.strip()
            for line in DOCKERFILE.read_text().splitlines()
            if line.strip().startswith("COPY ")
        ]
        self.assertEqual(
            copies,
            [
                "COPY --chown=0:0 --chmod=0644 eta.py "
                "/usr/local/lib/python3.14/site-packages/avelren/eta.py",
                "COPY --chown=0:0 --chmod=0644 collector.py "
                "/usr/local/lib/python3.14/site-packages/avelren/collector.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
