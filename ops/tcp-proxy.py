"""Bounded TCP proxy for the disposable PostgreSQL fixture."""

import asyncio
import os
import signal


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5432
BACKEND_HOST = os.environ.get("PROXY_BACKEND_HOST", "test-db-process")
BACKEND_PORT = int(os.environ.get("PROXY_BACKEND_PORT", "5432"))
CONNECT_TIMEOUT = float(os.environ.get("PROXY_CONNECT_TIMEOUT", "3"))
MAX_CONNECTIONS = int(os.environ.get("PROXY_MAX_CONNECTIONS", "64"))
RELAY_LIMIT = 64 * 1024
SHUTDOWN_TIMEOUT = 5


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(RELAY_LIMIT):
            writer.write(data)
            await writer.drain()
    finally:
        if not writer.is_closing():
            if writer.can_write_eof():
                writer.write_eof()
                await writer.drain()


async def proxy_pair(client_reader, client_writer, backend_reader, backend_writer) -> None:
    tasks = {
        asyncio.create_task(relay(client_reader, backend_writer)),
        asyncio.create_task(relay(backend_reader, client_writer)),
    }
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise errors[0]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for writer in (client_writer, backend_writer):
            if not writer.is_closing():
                writer.close()
        await asyncio.gather(
            client_writer.wait_closed(), backend_writer.wait_closed(), return_exceptions=True
        )


def make_handler(slots, active):
    async def handle(client_reader, client_writer):
        task = asyncio.current_task()
        active.add(task)
        try:
            await asyncio.wait_for(slots.acquire(), timeout=CONNECT_TIMEOUT)
        except TimeoutError:
            client_writer.close()
            await client_writer.wait_closed()
            return
        try:
            try:
                backend_reader, backend_writer = await asyncio.wait_for(
                    asyncio.open_connection(BACKEND_HOST, BACKEND_PORT),
                    timeout=CONNECT_TIMEOUT,
                )
            except (OSError, TimeoutError):
                client_writer.close()
                await client_writer.wait_closed()
                return
            await proxy_pair(client_reader, client_writer, backend_reader, backend_writer)
        finally:
            slots.release()
            active.discard(task)

    return handle


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    slots = asyncio.BoundedSemaphore(MAX_CONNECTIONS)
    active = set()
    server = await asyncio.start_server(
        make_handler(slots, active), LISTEN_HOST, LISTEN_PORT, limit=RELAY_LIMIT
    )
    async with server:
        await stop.wait()
        server.close()
        await server.wait_closed()
        if active:
            _, pending = await asyncio.wait(active, timeout=SHUTDOWN_TIMEOUT)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
