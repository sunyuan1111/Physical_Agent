from __future__ import annotations

import base64
import hashlib
import socket
import struct
import threading
import time
from collections.abc import Callable

import pytest

from physical_agent.drivers.transport import (
    ReconnectPolicy,
    TransportClosedError,
    TransportProtocolError,
    TransportTimeoutError,
    WebSocketTransport,
)


def test_websocket_transport_successful_handshake_and_health():
    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        _send_handshake(conn, key)
        opcode, _payload = _read_frame(conn)
        assert opcode == 0x8

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        assert transport.health().status == "closed"

        transport.open()
        health = transport.health()
        assert health.ok is True
        assert health.status == "open"

        transport.close()
        assert transport.health().status == "closed"

    server.assert_no_errors()
    assert b"Upgrade: websocket" in server.request
    assert b"Sec-WebSocket-Key:" in server.request


def test_websocket_transport_text_round_trip():
    received: list[tuple[int, bytes]] = []

    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        _send_handshake(conn, key)
        received.append(_read_frame(conn))
        _send_frame(conn, b'{"ok":true}', opcode=0x1)
        opcode, _payload = _read_frame(conn)
        assert opcode == 0x8

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        transport.open()
        transport.write_text('{"hello":"world"}')
        assert transport.read(timeout_s=0.5) == b'{"ok":true}'
        transport.close()

    server.assert_no_errors()
    assert received == [(0x1, b'{"hello":"world"}')]


def test_websocket_transport_binary_write_is_masked():
    received: list[tuple[int, bytes]] = []

    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        _send_handshake(conn, key)
        received.append(_read_frame(conn))
        opcode, _payload = _read_frame(conn)
        assert opcode == 0x8

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        transport.open()
        transport.write(b"\x00binary")
        transport.close()

    server.assert_no_errors()
    assert received == [(0x2, b"\x00binary")]


def test_websocket_transport_rejects_invalid_scheme():
    transport = WebSocketTransport("http://127.0.0.1:8080/ws")

    with pytest.raises(ValueError, match="Unsupported WebSocket URL scheme"):
        transport.open()


def test_websocket_transport_rejects_invalid_accept():
    def handler(conn: socket.socket, _key: str, _request: bytes) -> None:
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: definitely-wrong\r\n"
            "\r\n"
        )
        conn.sendall(response.encode("ascii"))

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        with pytest.raises(TransportProtocolError, match="invalid Sec-WebSocket-Accept"):
            transport.open()
        health = transport.health()
        assert health.ok is False
        assert health.status == "error"
        assert "invalid Sec-WebSocket-Accept" in health.message

    server.assert_no_errors()


def test_websocket_transport_closed_peer_has_clear_error():
    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        _send_handshake(conn, key)

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        transport.open()

        with pytest.raises(TransportClosedError, match="closed by peer"):
            transport.read(timeout_s=0.5)

        health = transport.health()
        assert health.ok is False
        assert health.status == "error"
        assert "closed by peer" in health.message

    server.assert_no_errors()


def test_websocket_transport_timeout_has_clear_error():
    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        _send_handshake(conn, key)
        time.sleep(0.2)
        opcode, _payload = _read_frame(conn)
        assert opcode == 0x8

    with _FakeWebSocketServer(handler) as server:
        transport = WebSocketTransport(server.url, connect_timeout_s=0.5, timeout_s=0.5)
        transport.open()

        with pytest.raises(TransportTimeoutError, match="timed out"):
            transport.read(timeout_s=0.05)

        health = transport.health()
        assert health.ok is True
        assert health.status == "open"
        assert "timed out" in health.details["last_error"]
        transport.close()

    server.assert_no_errors()


def test_websocket_transport_reconnects_after_server_disconnect():
    connections: list[int] = []
    received: list[tuple[int, bytes]] = []

    def handler(conn: socket.socket, key: str, _request: bytes) -> None:
        connection_number = len(connections) + 1
        connections.append(connection_number)
        _send_handshake(conn, key)
        if connection_number == 1:
            return
        received.append(_read_frame(conn))
        _send_frame(conn, b'{"again":true}', opcode=0x1)
        opcode, _payload = _read_frame(conn)
        assert opcode == 0x8

    with _FakeWebSocketServer(handler, max_connections=2) as server:
        transport = WebSocketTransport(
            server.url,
            connect_timeout_s=0.5,
            timeout_s=0.5,
            reconnect_policy=ReconnectPolicy(
                enabled=True,
                max_retries=5,
                backoff_base_ms=10,
                backoff_cap_ms=10,
            ),
        )
        transport.open()

        with pytest.raises(TransportClosedError, match="closed by peer"):
            transport.read(timeout_s=0.5)

        assert _wait_until(lambda: transport.is_open)
        transport.write_text('{"hello":"again"}')
        assert transport.read(timeout_s=0.5) == b'{"again":true}'
        transport.close()

    server.assert_no_errors()
    assert connections == [1, 2]
    assert received == [(0x1, b'{"hello":"again"}')]


class _FakeWebSocketServer:
    def __init__(
        self,
        handler: Callable[[socket.socket, str, bytes], None],
        *,
        max_connections: int = 1,
    ) -> None:
        self._handler = handler
        self._max_connections = max_connections
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self.request = b""
        self.requests: list[bytes] = []
        self.url = ""

    def __enter__(self) -> _FakeWebSocketServer:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(0.1)
        port = self._listener.getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/ws"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def assert_no_errors(self) -> None:
        if self._error is not None:
            raise AssertionError("fake WebSocket server failed") from self._error

    def _run(self) -> None:
        assert self._listener is not None
        try:
            for _ in range(self._max_connections):
                conn = self._accept_one()
                if conn is None:
                    return
                with conn:
                    conn.settimeout(2)
                    request = _read_http_request(conn)
                    self.request = request
                    self.requests.append(request)
                    key = _header(request, "sec-websocket-key")
                    self._handler(conn, key, request)
        except BaseException as exc:
            self._error = exc

    def _accept_one(self) -> socket.socket | None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
                return conn
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return None
                raise
        return None


def _read_http_request(conn: socket.socket) -> bytes:
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = conn.recv(4096)
        if not chunk:
            raise AssertionError("client closed before handshake request")
        request += chunk
    return request


def _header(request: bytes, name: str) -> str:
    header_name = name.lower()
    head = request.split(b"\r\n\r\n", 1)[0].decode("latin1")
    for line in head.split("\r\n")[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() == header_name:
            return value.strip()
    raise AssertionError(f"missing header: {name}")


def _send_handshake(conn: socket.socket, key: str) -> None:
    accept = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    conn.sendall(response.encode("ascii"))


def _send_frame(conn: socket.socket, payload: bytes, *, opcode: int) -> None:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    conn.sendall(header + payload)


def _read_frame(conn: socket.socket) -> tuple[int, bytes]:
    byte1, byte2 = _recv_exact(conn, 2)
    opcode = byte1 & 0x0F
    masked = bool(byte2 & 0x80)
    length = byte2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(conn, 8))[0]
    if not masked:
        raise AssertionError("client frame was not masked")
    mask = _recv_exact(conn, 4)
    payload = _recv_exact(conn, length) if length else b""
    return opcode, bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise AssertionError("socket closed while reading frame")
        data.extend(chunk)
    return bytes(data)


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
