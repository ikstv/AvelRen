"""Local tests for the fixture TCP proxy; no AvelRen runtime or network calls."""

import asyncio
import importlib.util
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "tcp_proxy", Path(__file__).with_name("tcp-proxy.py")
)
proxy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(proxy)


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend_messages = []

        async def backend(reader, writer):
            data = await reader.read(1024)
            self.backend_messages.append(data)
            writer.write(b"response-after-eof")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        self.backend = await asyncio.start_server(backend, "127.0.0.1", 0)
        proxy.BACKEND_HOST = "127.0.0.1"
        proxy.BACKEND_PORT = self.backend.sockets[0].getsockname()[1]
        self.slots = asyncio.BoundedSemaphore(2)
        self.active = set()
        self.front = await asyncio.start_server(
            proxy.make_handler(self.slots, self.active), "127.0.0.1", 0
        )

    async def asyncTearDown(self):
        self.front.close()
        self.backend.close()
        await self.front.wait_closed()
        await self.backend.wait_closed()
        await asyncio.gather(*self.active, return_exceptions=True)

    async def test_half_close_preserves_response(self):
        port = self.front.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"request")
        await writer.drain()
        writer.write_eof()
        self.assertEqual(await reader.read(), b"response-after-eof")
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.backend_messages, [b"request"])

    async def test_unavailable_backend_is_bounded(self):
        self.backend.close()
        await self.backend.wait_closed()
        proxy.BACKEND_PORT = 1
        port = self.front.sockets[0].getsockname()[1]
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=1
        )
        self.assertEqual(await asyncio.wait_for(reader.read(), timeout=1), b"")
        writer.close()
        await writer.wait_closed()

    async def test_connection_limit_rejects_excess_client(self):
        proxy.CONNECT_TIMEOUT = 0.05
        self.slots = asyncio.BoundedSemaphore(1)
        gate = asyncio.Event()

        async def holding_backend(reader, writer):
            await gate.wait()
            writer.close()
            await writer.wait_closed()

        self.backend.close()
        await self.backend.wait_closed()
        self.backend = await asyncio.start_server(holding_backend, "127.0.0.1", 0)
        proxy.BACKEND_PORT = self.backend.sockets[0].getsockname()[1]
        self.front.close()
        await self.front.wait_closed()
        self.front = await asyncio.start_server(
            proxy.make_handler(self.slots, self.active), "127.0.0.1", 0
        )
        port = self.front.sockets[0].getsockname()[1]
        first = await asyncio.open_connection("127.0.0.1", port)
        second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
        self.assertEqual(await asyncio.wait_for(second_reader.read(), timeout=1), b"")
        second_writer.close()
        await second_writer.wait_closed()
        gate.set()
        first[1].close()
        await first[1].wait_closed()


if __name__ == "__main__":
    unittest.main()
