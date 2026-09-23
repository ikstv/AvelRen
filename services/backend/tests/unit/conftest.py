"""Ізоляція модульних тестів від зовнішніх служб і налаштувань оператора."""

import os
import socket
import sys
import tempfile

import httpx
import psycopg
import pytest

# Налаштування читаються під час імпорту; очищаємо їх до збору тестів.
for name in tuple(os.environ):
    if name.startswith(("ECHERHA_", "AVELREN_", "FCM_")) or name.endswith("DATABASE_URL"):
        os.environ.pop(name, None)
os.environ["DATABASE_URL"] = "postgresql://unit:unit@127.0.0.1:1/avelren_unit_test"


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        # Windows asyncio створює локальну socketpair для циклу подій.
        if event == "socket.connect":
            if args[0].family == getattr(socket, "AF_UNIX", None):
                return
            if args[1][0] in {"127.0.0.1", "::1"}:
                return
        raise RuntimeError(f"Зовнішня мережа заборонена в unit-тестах: {event}")


sys.addaudithook(deny_network)


def pytest_sessionstart(session):
    session.original_directory = os.getcwd()
    session.isolated_directory = tempfile.TemporaryDirectory(prefix="avelren-unit-")
    os.chdir(session.isolated_directory.name)


def pytest_sessionfinish(session):
    os.chdir(session.original_directory)
    session.isolated_directory.cleanup()


@pytest.fixture(autouse=True)
def isolated_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def denied(*args, **kwargs):
        raise RuntimeError("Реальні HTTP і PostgreSQL заборонені в unit-тестах")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(psycopg.Connection, "connect", denied)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", denied)
