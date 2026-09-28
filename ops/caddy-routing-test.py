"""Синтетичний upstream і клієнт маршрутизації Caddy в ізольованій мережі."""
import gzip
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import socket
import sys
import time

HOST = "api.bordersignal.pp.ua"


class Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path, "headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.connection.settimeout(3)
        try:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()
        except (OSError, TimeoutError):
            pass  # Caddy aborts the upstream body when the limit is exceeded.


def request(path, *, tls=True, method="GET", body=None, headers=None):
    # Only the test container's private CA is used; no production certificate.
    conn = (HTTPSConnection(HOST, context=ssl._create_unverified_context(), timeout=5)
            if tls else HTTPConnection(HOST, timeout=5))
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def check():
    deadline = time.monotonic() + 30
    while True:
        try:
            if request("/api/health")[0] == 200:
                break
        except OSError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Caddy/upstream readiness timeout")
        time.sleep(0.3)
    status, _, body = request("/api/health?probe=1", headers={
        "X-Forwarded-For": "198.51.100.123",
        "X-AvelRen-Client-IP": "198.51.100.123",
    })
    data = json.loads(body)
    headers = {k.lower(): v for k, v in data["headers"].items()}
    assert status == 200 and data["path"] == "/health?probe=1", data
    assert "x-forwarded-for" not in headers, headers
    client_ip = socket.gethostbyname(socket.gethostname())
    assert headers.get("x-avelren-client-ip") == client_ip, headers
    status, _, body = request("/api/health")
    assert status == 200
    headers = {k.lower(): v for k, v in json.loads(body)["headers"].items()}
    assert headers["x-avelren-client-ip"] == client_ip
    assert "x-forwarded-for" not in headers, headers
    status, _, body = request("/privacy")
    assert status == 200 and body == Path("/workspace/ops/static/privacy-policy.html").read_bytes()
    assert request("/")[::2] == (200, b"AvelRen API")
    status, headers, _ = request("/api/health?probe=1", tls=False)
    assert status == 308 and headers["Location"] == f"https://{HOST}/api/health?probe=1"
    assert request("/api/devices", method="POST", body=b"x" * 1024)[0] == 200
    assert request("/api/devices", method="POST", body=b"x" * 65537)[0] == 413
    status, headers, body = request("/privacy", headers={"Accept-Encoding": "gzip"})
    assert status == 200 and headers.get("Content-Encoding") == "gzip"
    assert gzip.decompress(body) == Path("/workspace/ops/static/privacy-policy.html").read_bytes()
    print(f"Caddy routing: client={client_ip}; prefix/query, IP headers, privacy, fallback, redirect, body limit, gzip OK")


if __name__ == "__main__":
    if sys.argv[1:] == ["server"]:
        ThreadingHTTPServer(("0.0.0.0", 8000), Stub).serve_forever()
    else:
        check()
