"""Захист тестів від випадкових справжніх мережевих запитів."""

import socket

import pytest


def test_real_network_is_blocked():
    with socket.socket() as client:
        with pytest.raises(RuntimeError, match="мережа заборонена"):
            client.connect(("192.0.2.1", 443))
