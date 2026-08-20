from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from physical_agent.drivers.transport.base import (
    ReconnectCallback,
    ReconnectPolicy,
    ReconnectSleeper,
    ReconnectableTransport,
    TransportClosedError,
    TransportError,
    TransportHealth,
    TransportProtocolError,
    TransportTimeoutError,
)


_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_HANDSHAKE_BYTES = 65536
_MAX_FRAME_BYTES = 16 * 1024 * 1024


class WebSocketTransport(ReconnectableTransport):
    """Small standard-library WebSocket transport for watch-side drivers."""

    def __init__(
        self,
        url: str,
        *,
        connect_timeout_s: float = 2.0,
        timeout_s: float = 10.0,
        headers: Mapping[str, str] | None = None,
        reconnect_policy: ReconnectPolicy | dict[str, Any] | None = None,
        reconnect_sleeper: ReconnectSleeper | None = None,
        on_reconnected: ReconnectCallback | None = None,
    ) -> None:
        super().__init__(
            reconnect_policy=reconnect_policy,
            reconnect_sleeper=reconnect_sleeper,
            on_reconnected=on_reconnected,
        )
        self.url = url
        self._safe_url = _redact_url(url)
        self.connect_timeout_s = float(connect_timeout_s)
        self.timeout_s = float(timeout_s)
        self.headers = dict(headers or {})
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._read_buffer = b""
        self._close_received = False

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def open(self) -> None:
        self._open_with_reconnect_policy(
            open_once=self._open_once,
            label=f"WebSocket transport {self._safe_url}",
        )

    def _open_once(self) -> None:
        self._drop_socket()
        self._last_error = None
        self._close_received = False
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError(f"Unsupported WebSocket URL scheme: {parsed.scheme}")
        if not parsed.hostname:
            raise ValueError(f"Invalid WebSocket URL: {self.url}")

        try:
            port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        except ValueError as exc:
            raise ValueError(f"Invalid WebSocket URL port: {self.url}") from exc

        sock: socket.socket | ssl.SSLSocket | None = None
        try:
            sock = socket.create_connection(
                (parsed.hostname, port),
                timeout=self.connect_timeout_s,
            )
            if parsed.scheme == "wss":
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=parsed.hostname)
            sock.settimeout(self.connect_timeout_s)

            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = self._handshake_request(parsed, port, key)
            sock.sendall(request)
            head, extra = self._read_http_response(sock)
            self._validate_handshake(head, key)
            sock.settimeout(self.timeout_s)
            self._sock = sock
            self._read_buffer = extra
        except (TransportError, OSError, ssl.SSLError) as exc:
            self._last_error = str(exc)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if isinstance(exc, TransportError):
                raise
            raise TransportError(f"WebSocket connection failed: {exc}") from exc

    def close(self) -> None:
        self._cancel_background_reconnect()
        sock = self._sock
        self._sock = None
        self._read_buffer = b""
        if sock is None:
            self._set_transport_error(None)
            self._mark_transport_disconnected()
            return
        try:
            self._send_frame(b"", opcode=0x8, sock=sock)
        except Exception:
            pass
        try:
            sock.close()
        except OSError:
            pass
        self._set_transport_error(None)
        self._mark_transport_disconnected()

    def write(self, data: bytes) -> None:
        self._send_frame(data, opcode=0x2)

    def write_text(self, message: str) -> None:
        self._send_frame(message.encode("utf-8"), opcode=0x1)

    def read(self, timeout_s: float) -> bytes:
        sock = self._require_sock()
        previous_timeout = sock.gettimeout()
        sock.settimeout(timeout_s)
        try:
            while True:
                opcode, payload = self._recv_frame()
                if opcode in {0x1, 0x2}:
                    return payload
                if opcode == 0x8:
                    self._close_received = True
                    self._last_error = "WebSocket closed by peer"
                    self._send_close_ack(payload)
                    self._drop_socket()
                    self._start_reconnect_after_disconnect()
                    raise TransportClosedError("WebSocket closed by peer")
                if opcode == 0x9:
                    self._send_frame(payload, opcode=0xA)
                    continue
                if opcode == 0xA:
                    continue
                raise TransportProtocolError(f"Unsupported WebSocket frame opcode: {opcode}")
        finally:
            if self._sock is sock:
                sock.settimeout(previous_timeout)

    def health(self) -> TransportHealth:
        if self._sock is not None:
            return TransportHealth(
                ok=True,
                status="open",
                message="WebSocket transport open",
                details={
                    "url": self._safe_url,
                    "last_error": self._last_error,
                    "connection_state": self.connection_state,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        if self.connection_state == "reconnecting":
            return TransportHealth(
                ok=False,
                status="reconnecting",
                message="WebSocket transport reconnecting",
                details={
                    "url": self._safe_url,
                    "last_error": self._last_error,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        if self._last_error:
            if not self.reconnect_exhausted:
                self._start_reconnect_after_disconnect()
            if self.connection_state == "reconnecting":
                return TransportHealth(
                    ok=False,
                    status="reconnecting",
                    message="WebSocket transport reconnecting",
                    details={
                        "url": self._safe_url,
                        "last_error": self._last_error,
                        "close_received": self._close_received,
                        "reconnect_attempts": self.reconnect_attempts,
                    },
                )
            return TransportHealth(
                ok=False,
                status="error",
                message=self._last_error,
                details={
                    "url": self._safe_url,
                    "close_received": self._close_received,
                    "connection_state": self.connection_state,
                    "reconnect_attempts": self.reconnect_attempts,
                },
            )
        return TransportHealth(
            ok=False,
            status="closed",
            message="WebSocket transport closed",
            details={
                "url": self._safe_url,
                "close_received": self._close_received,
                "connection_state": self.connection_state,
                "reconnect_attempts": self.reconnect_attempts,
            },
        )

    def _handshake_request(self, parsed: Any, port: int, key: str) -> bytes:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = _host_header(parsed.hostname, parsed.port, port)
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        for name, value in self.headers.items():
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise ValueError("WebSocket header names and values must not contain newlines")
            lines.append(f"{name}: {value}")
        lines.extend(["", ""])
        return "\r\n".join(lines).encode("ascii")

    def _read_http_response(self, sock: socket.socket | ssl.SSLSocket) -> tuple[bytes, bytes]:
        response = b""
        while b"\r\n\r\n" not in response:
            try:
                chunk = sock.recv(4096)
            except socket.timeout as exc:
                raise TransportTimeoutError("WebSocket handshake timed out") from exc
            if not chunk:
                raise TransportClosedError("WebSocket handshake closed before response")
            response += chunk
            if len(response) > _MAX_HANDSHAKE_BYTES:
                raise TransportProtocolError("WebSocket handshake response too large")
        head, extra = response.split(b"\r\n\r\n", 1)
        return head, extra

    def _validate_handshake(self, head: bytes, key: str) -> None:
        text = head.decode("latin1", errors="replace")
        lines = text.split("\r\n")
        if not lines or " 101 " not in f" {lines[0]} ":
            status = lines[0] if lines else text
            raise TransportProtocolError(f"WebSocket handshake failed: {status}")

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

        if headers.get("upgrade", "").lower() != "websocket":
            raise TransportProtocolError("WebSocket handshake failed: missing Upgrade header")
        if "upgrade" not in headers.get("connection", "").lower():
            raise TransportProtocolError("WebSocket handshake failed: missing Connection upgrade")

        accept = headers.get("sec-websocket-accept")
        expected = base64.b64encode(
            hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if accept != expected:
            raise TransportProtocolError("WebSocket handshake failed: invalid Sec-WebSocket-Accept")

    def _send_frame(
        self,
        payload: bytes,
        *,
        opcode: int,
        sock: socket.socket | ssl.SSLSocket | None = None,
    ) -> None:
        sock = sock or self._require_sock()
        if opcode >= 0x8 and len(payload) > 125:
            raise TransportProtocolError("WebSocket control frame payload too large")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        try:
            sock.sendall(header + masked)
        except socket.timeout as exc:
            self._last_error = "WebSocket write timed out"
            raise TransportTimeoutError(self._last_error) from exc
        except OSError as exc:
            self._last_error = str(exc)
            if self._sock is sock:
                self._drop_socket()
                self._start_reconnect_after_disconnect()
            raise TransportClosedError(f"WebSocket write failed: {exc}") from exc

    def _recv_frame(self) -> tuple[int, bytes]:
        first = self._recv_exact(2)
        byte1, byte2 = first
        fin = bool(byte1 & 0x80)
        opcode = byte1 & 0x0F
        masked = bool(byte2 & 0x80)
        length = byte2 & 0x7F
        if not fin:
            raise TransportProtocolError("WebSocket fragmented frames are not supported")
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if length > _MAX_FRAME_BYTES:
            raise TransportProtocolError("WebSocket frame too large")
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, size: int) -> bytes:
        sock = self._require_sock()
        data = bytearray()
        if self._read_buffer:
            take = self._read_buffer[:size]
            data.extend(take)
            self._read_buffer = self._read_buffer[len(take) :]
        while len(data) < size:
            try:
                chunk = sock.recv(size - len(data))
            except socket.timeout as exc:
                timeout = sock.gettimeout()
                timeout_text = "unknown" if timeout is None else f"{timeout:g}"
                self._last_error = f"WebSocket read timed out after {timeout_text}s"
                raise TransportTimeoutError(self._last_error) from exc
            except OSError as exc:
                self._last_error = f"WebSocket read failed: {exc}"
                self._drop_socket()
                self._start_reconnect_after_disconnect()
                raise TransportClosedError(self._last_error) from exc
            if not chunk:
                self._last_error = "WebSocket connection closed by peer"
                self._drop_socket()
                self._start_reconnect_after_disconnect()
                raise TransportClosedError(self._last_error)
            data.extend(chunk)
        return bytes(data)

    def _send_close_ack(self, payload: bytes) -> None:
        try:
            self._send_frame(payload, opcode=0x8)
        except Exception:
            pass

    def _require_sock(self) -> socket.socket | ssl.SSLSocket:
        self._ensure_transport_ready_for_io(
            is_open=self._sock is not None,
            label="WebSocket transport",
        )
        assert self._sock is not None
        return self._sock

    def _drop_socket(self) -> None:
        sock = self._sock
        self._sock = None
        self._read_buffer = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._mark_transport_disconnected(self._last_error)

    def _start_reconnect_after_disconnect(self) -> None:
        self._start_background_reconnect(
            open_once=self._open_once,
            label=f"WebSocket transport {self._safe_url}",
        )

    def _cleanup_after_cancelled_open(self) -> None:
        self._drop_socket()


def _host_header(hostname: str, explicit_port: int | None, port: int) -> str:
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    return host if explicit_port is None else f"{host}:{port}"


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    if parsed.username or parsed.password:
        hostname = f"***@{hostname}"
    path = parsed.path or ""
    return f"{parsed.scheme}://{hostname}{path}"
