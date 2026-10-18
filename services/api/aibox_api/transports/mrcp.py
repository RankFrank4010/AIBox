"""Minimal MRCPv2 speech-recognizer server.

Implements the common IVR path:

  SIP/UDP INVITE + SDP  ->  MRCPv2 control channel over TCP
  RTP audio (PCMU / PCMA / L16)  ->  AIBox Whisper job
  RECOGNIZE / STOP  ->  IN-PROGRESS + RECOGNITION-COMPLETE (NLSML)

It intentionally exposes one speechrecog resource per SIP dialog and supports
SIP over UDP only. See docs/transports.md for the compatibility boundary.
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import logging
import re
import sys
import time
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

from ..config import AppConfig
from ..external import ExternalAsrGateway, ExternalServiceError

logger = logging.getLogger("aibox.mrcp")

_ULAW_TABLE: list[int] = []
_ALAW_TABLE: list[int] = []
for _value in range(256):
    _u = ~_value & 0xFF
    _sign = _u & 0x80
    _exponent = (_u >> 4) & 0x07
    _mantissa = _u & 0x0F
    _sample = ((_mantissa << 3) + 0x84) << _exponent
    _sample -= 0x84
    _ULAW_TABLE.append(-_sample if _sign else _sample)

    _a = _value ^ 0x55
    _sign = _a & 0x80
    _exponent = (_a >> 4) & 0x07
    _mantissa = _a & 0x0F
    if _exponent == 0:
        _sample = (_mantissa << 4) + 8
    else:
        _sample = ((_mantissa << 4) + 0x108) << (_exponent - 1)
    _ALAW_TABLE.append(-_sample if _sign else _sample)

CODEC_INFO = {
    0: ("PCMU", 8000, "ulaw"),
    8: ("PCMA", 8000, "alaw"),
    96: ("L16", 16000, "l16"),
    97: ("L16", 8000, "l16"),
}


def _pcm_from_payloads(pt: int, payloads: list[bytes]) -> tuple[int, bytes] | None:
    info = CODEC_INFO.get(pt)
    if info is None:
        return None
    _name, rate, codec = info
    raw = b"".join(payloads)
    if codec == "ulaw":
        return rate, array.array("h", (_ULAW_TABLE[b] for b in raw)).tobytes()
    if codec == "alaw":
        return rate, array.array("h", (_ALAW_TABLE[b] for b in raw)).tobytes()
    if len(raw) % 2:
        raw = raw[:-1]
    values = array.array("h")
    values.frombytes(raw)
    if sys.byteorder != "big":
        values.byteswap()
    return rate, values.tobytes()


def _parse_sip(data: bytes) -> tuple[str, dict[str, str], str] | None:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return None
    head, _, body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")
    if not lines:
        return None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return lines[0].strip(), headers, body


def _sip_uri_host(uri: str) -> str:
    match = re.search(r"sip:[^@;>]+@?([^;>]+)", uri)
    return match.group(1) if match else ""


@dataclass
class SipSession:
    call_id: str
    remote: tuple[str, int]
    from_header: str
    to_header: str
    via_header: str
    cseq: str
    contact: str
    to_tag: str
    channel_id: str
    session_id: str
    control_port: int = 0
    rtp_port: int = 0
    rtp_transport: asyncio.DatagramTransport | None = None
    control_writer: asyncio.StreamWriter | None = None
    invite_response: bytes = b""
    params: dict[str, Any] = field(
        default_factory=lambda: {
            "language": "auto",
            "no_input_timeout": 5000,
            "speech_complete_timeout": 900,
            "recognition_timeout": 120000,
            "save_waveform": False,
        }
    )
    recognizing: bool = False
    finishing: bool = False
    finished: bool = False
    request_id: str = ""
    recognize_started: float = 0.0
    packets: list[tuple[int, bytes]] = field(default_factory=list)
    payload_type: int = 0
    first_packet_at: float = 0.0
    last_packet_at: float = 0.0
    start_of_input_sent: bool = False
    watchdog: asyncio.Task[None] | None = None
    job_id: str | None = None
    proxy_sync_id: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RtpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: MRCPv2Server, session: SipSession) -> None:
        self.server = server
        self.session = session

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        del addr
        self.server.handle_rtp(self.session, data)

    def error_received(self, exc: Exception) -> None:
        logger.debug("MRCP RTP error: %s", exc)


class SipProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: MRCPv2Server) -> None:
        self.server = server
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        asyncio.create_task(self.server.handle_sip(data, addr, self.transport))

    def error_received(self, exc: Exception) -> None:
        logger.debug("MRCP SIP error: %s", exc)


class MRCPv2Server:
    def __init__(self, config: AppConfig, gateway: ExternalAsrGateway) -> None:
        self.config = config
        self.gateway = gateway
        self.sip_transport: asyncio.DatagramTransport | None = None
        self.control_server: asyncio.AbstractServer | None = None
        self.control_port = 0
        self.sessions: dict[str, SipSession] = {}
        self.channels: dict[str, SipSession] = {}
        self.used_rtp_ports: set[int] = set()
        self.advertise_host = config.mrcp_advertise_host or "127.0.0.1"
        self.bind_host = config.mrcp_host
        self.port = config.mrcp_port
        self._stopped = False

    # ------------------------------------------------------------------ server
    async def start(self) -> dict[str, Any]:
        if not self.config.mrcp_enabled or self.config.mrcp_port <= 0:
            return {
                "status": "disabled",
                "enabled": False,
                "host": self.bind_host,
                "advertise_host": self.advertise_host,
                "port": self.config.mrcp_port,
                "control_port": self.config.mrcp_control_port,
                "rtp_port_range": [
                    self.config.mrcp_rtp_port_start,
                    self.config.mrcp_rtp_port_end,
                ],
                "transport": "SIP/UDP + RTP/AVP + MRCPv2/TCP",
                "codecs": ["PCMU/8000", "PCMA/8000", "L16/16000", "L16/8000"],
                "resource": "speechrecog",
                "auth_required": False,
            }
        try:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: SipProtocol(self),
                local_addr=(self.bind_host, self.config.mrcp_port),
            )
            self.sip_transport = transport  # type: ignore[assignment]
            self.port = int(transport.get_extra_info("sockname")[1])

            self.control_server = await asyncio.start_server(
                self._handle_control_connection,
                host=self.bind_host,
                port=self.config.mrcp_control_port,
            )
            self.control_port = int(self.control_server.sockets[0].getsockname()[1])
            return {
                "status": "running",
                "enabled": True,
                "host": self.bind_host,
                "advertise_host": self.advertise_host,
                "port": self.port,
                "control_port": self.control_port,
                "rtp_port_range": [
                    self.config.mrcp_rtp_port_start,
                    self.config.mrcp_rtp_port_end,
                ],
                "transport": "SIP/UDP + RTP/AVP + MRCPv2/TCP",
                "codecs": ["PCMU/8000", "PCMA/8000", "L16/16000", "L16/8000"],
                "resource": "speechrecog",
                "auth_required": False,
                "note": "SIP over UDP, shared MRCP control port, RTP port range",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("MRCPv2 server failed to start: %s", exc)
            await self.stop()
            return {
                "status": "error",
                "enabled": True,
                "host": self.bind_host,
                "port": self.config.mrcp_port,
                "error": str(exc),
            }

    async def stop(self) -> None:
        self._stopped = True
        if self.control_server is not None:
            self.control_server.close()
            with contextlib.suppress(Exception):
                await self.control_server.wait_closed()
            self.control_server = None
        for session in list(self.sessions.values()):
            await self.close_session(session)
        if self.sip_transport is not None:
            self.sip_transport.close()
            self.sip_transport = None

    async def close_session(self, session: SipSession) -> None:
        self.sessions.pop(session.call_id, None)
        self.channels.pop(session.channel_id, None)
        if session.watchdog is not None:
            session.watchdog.cancel()
        if session.job_id:
            self.gateway.jobs.cancel(session.job_id)
        writer = session.control_writer
        session.control_writer = None
        if writer is not None and not any(
            other.control_writer is writer for other in self.sessions.values()
        ):
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
        if session.rtp_transport is not None:
            session.rtp_transport.close()
            session.rtp_transport = None
        if session.rtp_port in self.used_rtp_ports:
            self.used_rtp_ports.discard(session.rtp_port)

    # --------------------------------------------------------------------- SIP
    def _send_sip(self, payload: bytes, addr: tuple[str, int]) -> None:
        if self.sip_transport is not None:
            self.sip_transport.sendto(payload, addr)

    def _sip_response(
        self,
        request: tuple[str, dict[str, str], str],
        status: int,
        reason: str,
        *,
        body: str = "",
        content_type: str | None = None,
        to_tag: str | None = None,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> bytes:
        _, headers, _ = request
        lines = [f"SIP/2.0 {status} {reason}"]
        canonical = {
            "via": "Via",
            "from": "From",
            "call-id": "Call-ID",
            "cseq": "CSeq",
        }
        for name in ("via", "from", "call-id", "cseq"):
            if name in headers:
                lines.append(f"{canonical[name]}: {headers[name]}")
        to_value = headers.get("to", "<sip:aibox@localhost>")
        if to_tag and "tag=" not in to_value:
            to_value = f"{to_value};tag={to_tag}"
        lines.append(f"To: {to_value}")
        lines.append(f"Contact: <sip:aibox@{self.advertise_host}:{self.port}>")
        lines.append("Server: AIBox MRCPv2")
        for name, value in extra_headers:
            lines.append(f"{name}: {value}")
        if body:
            lines.append(f"Content-Type: {content_type or 'application/sdp'}")
        encoded_body = body.encode("utf-8")
        lines.append(f"Content-Length: {len(encoded_body)}")
        lines.append("")
        lines.append("")
        return "\r\n".join(lines).encode("utf-8") + encoded_body

    async def handle_sip(
        self,
        data: bytes,
        addr: tuple[str, int],
        transport: asyncio.DatagramTransport | None,
    ) -> None:
        del transport
        parsed = _parse_sip(data)
        if parsed is None:
            return
        start_line, headers, body = parsed
        method = start_line.split(" ", 1)[0].upper()
        call_id = headers.get("call-id", "")
        try:
            if method == "INVITE":
                await self._handle_invite(parsed, addr)
            elif method == "ACK":
                return
            elif method == "BYE":
                session = self.sessions.get(call_id)
                if session is not None:
                    await self.close_session(session)
                self._send_sip(
                    self._sip_response(parsed, 200, "OK", to_tag="aibox"),
                    addr,
                )
            elif method == "CANCEL":
                session = self.sessions.get(call_id)
                if session is not None:
                    await self.close_session(session)
                self._send_sip(
                    self._sip_response(parsed, 200, "OK", to_tag="aibox"),
                    addr,
                )
            elif method == "OPTIONS":
                self._send_sip(
                    self._sip_response(
                        parsed,
                        200,
                        "OK",
                        extra_headers=(("Allow", "INVITE, ACK, BYE, CANCEL, OPTIONS"),),
                    ),
                    addr,
                )
            elif call_id in self.sessions:
                session = self.sessions[call_id]
                if session.invite_response:
                    self._send_sip(session.invite_response, addr)
        except Exception:
            logger.exception("MRCP SIP message handling failed")

    async def _handle_invite(
        self,
        request: tuple[str, dict[str, str], str],
        addr: tuple[str, int],
    ) -> None:
        _, headers, _body = request
        call_id = headers.get("call-id", "")
        if not call_id:
            return
        existing = self.sessions.get(call_id)
        if existing is not None and existing.invite_response:
            self._send_sip(existing.invite_response, addr)
            return

        self._send_sip(self._sip_response(request, 100, "Trying"), addr)

        session_id = uuid.uuid4().hex[:12]
        channel_id = f"{session_id}@speechrecog"
        session = SipSession(
            call_id=call_id,
            remote=addr,
            from_header=headers.get("from", ""),
            to_header=headers.get("to", ""),
            via_header=headers.get("via", ""),
            cseq=headers.get("cseq", ""),
            contact=headers.get("contact", ""),
            to_tag=uuid.uuid4().hex[:8],
            channel_id=channel_id,
            session_id=session_id,
            control_port=self.control_port,
        )
        try:
            session.rtp_transport = await self._allocate_rtp(session)
        except RuntimeError as exc:
            logger.warning("MRCP RTP allocation failed: %s", exc)
            return
        session.params["language"] = "auto"

        sdp = "\r\n".join(
            [
                "v=0",
                f"o=- {uuid.uuid4().int & 0x7FFFFFFF} 1 IN IP4 {self.advertise_host}",
                "s=AIBox MRCPv2 Recognizer",
                f"c=IN IP4 {self.advertise_host}",
                "t=0 0",
                f"m=application {session.control_port} TCP/MRCPv2 1",
                "a=connection:new",
                "a=setup:passive",
                f"a=channel:{channel_id}",
                "a=cmid:1",
                f"m=audio {session.rtp_port} RTP/AVP 0 8 96",
                "a=rtpmap:0 PCMU/8000",
                "a=rtpmap:8 PCMA/8000",
                "a=rtpmap:96 L16/16000",
                "a=recvonly",
                "a=mid:1",
                "",
            ]
        )
        response = self._sip_response(
            request,
            200,
            "OK",
            body=sdp,
            content_type="application/sdp",
            to_tag=session.to_tag,
            extra_headers=(
                ("Allow", "INVITE, ACK, BYE, CANCEL, OPTIONS"),
                ("Supported", "timer"),
            ),
        )
        session.invite_response = response
        self.sessions[call_id] = session
        self.channels[channel_id] = session
        self._send_sip(response, addr)
        logger.info(
            "MRCP session %s from %s: control=%s rtp=%s",
            call_id,
            addr[0],
            session.control_port,
            session.rtp_port,
        )

    async def _allocate_rtp(self, session: SipSession) -> asyncio.DatagramTransport:
        loop = asyncio.get_running_loop()
        start = max(1024, self.config.mrcp_rtp_port_start)
        end = max(start, self.config.mrcp_rtp_port_end)
        for port in range(start, end + 1):
            if port in self.used_rtp_ports:
                continue
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: RtpProtocol(self, session),
                    local_addr=(self.bind_host, port),
                )
            except OSError:
                continue
            self.used_rtp_ports.add(port)
            session.rtp_port = port
            return transport  # type: ignore[return-value]
        raise RuntimeError(
            f"no free RTP port in configured range {start}-{end}"
        )

    # ----------------------------------------------------------------- control
    async def _read_mrcp(
        self, reader: asyncio.StreamReader
    ) -> tuple[str, dict[str, str], str] | None:
        try:
            start = (await reader.readuntil(b"\r\n")).decode("utf-8", errors="replace").strip()
            raw_headers = await reader.readuntil(b"\r\n\r\n")
            headers: dict[str, str] = {}
            for line in raw_headers.decode("utf-8", errors="replace").split("\r\n"):
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()
            length = int(headers.get("content-length", "0") or 0)
            body = await reader.readexactly(length) if length else b""
            return start, headers, body.decode("utf-8", errors="replace")
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            return None

    @staticmethod
    def _request_parts(start: str) -> tuple[str, str]:
        tokens = start.split()
        if len(tokens) < 4 or not tokens[0].startswith("MRCP/"):
            return "", ""
        # MRCP/2.0 <length> <method> <request-id>
        return tokens[2].upper(), tokens[3]

    def _frame(
        self,
        session: SipSession,
        start_rest: str,
        *,
        headers: list[tuple[str, str]] | None = None,
        body: str = "",
        content_type: str | None = None,
    ) -> bytes:
        all_headers = [("Channel-Identifier", session.channel_id)]
        if headers:
            all_headers.extend(headers)
        if body:
            all_headers.append(("Content-Type", content_type or "text/plain"))
        body_bytes = body.encode("utf-8")
        if body:
            all_headers.append(("Content-Length", str(len(body_bytes))))
        header_text = "\r\n".join(f"{name}: {value}" for name, value in all_headers)
        length = 0
        message = b""
        for _ in range(4):
            start_line = f"MRCP/2.0 {length} {start_rest}\r\n"
            message = (start_line + header_text + "\r\n\r\n").encode("utf-8") + body_bytes
            if len(message) == length:
                break
            length = len(message)
        if len(message) != length:
            start_line = f"MRCP/2.0 {len(message)} {start_rest}\r\n"
            message = (start_line + header_text + "\r\n\r\n").encode("utf-8") + body_bytes
        return message

    async def _send_mrcp(
        self,
        session: SipSession,
        start_rest: str,
        *,
        headers: list[tuple[str, str]] | None = None,
        body: str = "",
        content_type: str | None = None,
    ) -> None:
        writer = session.control_writer
        if writer is None:
            return
        writer.write(
            self._frame(
                session,
                start_rest,
                headers=headers,
                body=body,
                content_type=content_type,
            )
        )
        try:
            await writer.drain()
        except (ConnectionError, RuntimeError):
            pass

    async def _handle_control_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        bound_sessions: set[str] = set()
        try:
            while True:
                message = await self._read_mrcp(reader)
                if message is None:
                    break
                start, headers, _body = message
                method, request_id = self._request_parts(start)
                if not method:
                    continue
                channel = headers.get("channel-identifier", "").strip()
                session = self.channels.get(channel)
                if session is None:
                    session = next(
                        (
                            candidate
                            for channel_id, candidate in self.channels.items()
                            if channel and channel_id in channel
                        ),
                        None,
                    )
                if session is None:
                    logger.debug("MRCP control message for unknown channel %s", channel)
                    continue
                session.control_writer = writer
                bound_sessions.add(session.call_id)
                await self._dispatch_control(session, method, request_id, headers)
        except (ConnectionError, asyncio.IncompleteReadError, RuntimeError):
            pass
        finally:
            for call_id in bound_sessions:
                session = self.sessions.get(call_id)
                if session is not None and session.control_writer is writer:
                    session.control_writer = None
                    await self.close_session(session)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def _dispatch_control(
        self,
        session: SipSession,
        method: str,
        request_id: str,
        headers: dict[str, str],
    ) -> None:
        if method == "SET-PARAMS":
            self._apply_params(session, headers)
            await self._send_mrcp(session, f"{request_id} 200 COMPLETE")
        elif method == "GET-PARAMS":
            await self._send_mrcp(
                session,
                f"{request_id} 200 COMPLETE",
                headers=[
                    ("Language", str(session.params["language"])),
                    ("No-Input-Timeout", str(session.params["no_input_timeout"])),
                    ("Recognition-Timeout", str(session.params["recognition_timeout"])),
                    (
                        "Speech-Complete-Timeout",
                        str(session.params["speech_complete_timeout"]),
                    ),
                ],
            )
        elif method == "RECOGNIZE":
            if session.recognizing or session.finishing:
                await self._send_mrcp(
                    session,
                    f"{request_id} 407 COMPLETE",
                    headers=[("Completion-Cause", "005 busy")],
                )
                return
            self._apply_params(session, headers)
            session.recognizing = True
            session.finished = False
            session.finishing = False
            session.request_id = request_id
            session.recognize_started = time.monotonic()
            session.packets.clear()
            session.first_packet_at = 0.0
            session.last_packet_at = 0.0
            session.start_of_input_sent = False
            session.proxy_sync_id = uuid.uuid4().hex[:12]
            await self._send_mrcp(session, f"{request_id} 200 IN-PROGRESS")
            session.watchdog = asyncio.create_task(self._watch(session))
            logger.info("MRCP RECOGNIZE %s on %s", request_id, session.call_id)
        elif method == "STOP":
            await self._send_mrcp(session, f"{request_id} 200 COMPLETE")
            if session.recognizing or session.finishing:
                await self._finish(session, "000 success", request_id)
        elif method in {"START-INPUT-TIMERS", "PAUSE", "RESUME", "GET-RESULT"}:
            await self._send_mrcp(session, f"{request_id} 200 COMPLETE")
        elif method in {"DEFINE-GRAMMAR", "INTERPRET"}:
            await self._send_mrcp(
                session,
                f"{request_id} 200 COMPLETE",
                headers=[("Completion-Cause", "000 success")],
            )
        else:
            await self._send_mrcp(session, f"{request_id} 405 COMPLETE")

    def _apply_params(self, session: SipSession, headers: dict[str, str]) -> None:
        language = headers.get("language") or headers.get("speech-language")
        if language:
            code = language.split("-")[0].split("_")[0].lower()
            session.params["language"] = code or "auto"
        for key, header in (
            ("no_input_timeout", "no-input-timeout"),
            ("speech_complete_timeout", "speech-complete-timeout"),
            ("recognition_timeout", "recognition-timeout"),
        ):
            if header in headers:
                try:
                    session.params[key] = max(100, int(headers[header]))
                except ValueError:
                    pass
        if "save-waveform" in headers:
            session.params["save_waveform"] = headers["save-waveform"].lower() == "true"

    # ------------------------------------------------------------------- media
    def handle_rtp(self, session: SipSession, data: bytes) -> None:
        if not session.recognizing or session.finishing or len(data) < 12:
            return
        first = data[0]
        if (first >> 6) & 0x03 != 2:
            return
        padding = bool(first & 0x20)
        extension = bool(first & 0x10)
        csrc_count = first & 0x0F
        offset = 12 + csrc_count * 4
        if extension:
            if len(data) < offset + 4:
                return
            ext_words = int.from_bytes(data[offset + 2 : offset + 4], "big")
            offset += 4 + ext_words * 4
        if padding and data:
            pad = data[-1]
            data = data[:-pad] if pad and pad <= len(data) else data
        if len(data) <= offset:
            return
        payload_type = data[1] & 0x7F
        seq = int.from_bytes(data[2:4], "big")
        payload = data[offset:]
        now = time.monotonic()
        if not session.packets:
            session.payload_type = payload_type
            session.first_packet_at = now
            session.last_packet_at = now
            self._schedule_start_of_input(session)
        else:
            session.last_packet_at = now
        if len(session.packets) < 400_000:
            session.packets.append((seq, payload))

    def _schedule_start_of_input(self, session: SipSession) -> None:
        if session.start_of_input_sent or session.control_writer is None:
            return
        session.start_of_input_sent = True

        async def send() -> None:
            await self._send_mrcp(
                session,
                f"START-OF-INPUT {session.request_id} IN-PROGRESS",
                headers=[
                    ("Input-Type", "speech"),
                    ("Proxy-Sync-Id", session.proxy_sync_id),
                ],
            )

        asyncio.create_task(send())

    async def _watch(self, session: SipSession) -> None:
        try:
            while session.recognizing and not session.finished:
                await asyncio.sleep(0.1)
                now = time.monotonic()
                if session.packets:
                    silence = (now - session.last_packet_at) * 1000
                    duration = (now - session.first_packet_at) * 1000
                    if silence >= int(session.params["speech_complete_timeout"]):
                        await self._finish(session, "000 success", session.request_id)
                        return
                    if duration >= int(session.params["recognition_timeout"]):
                        await self._finish(session, "000 success", session.request_id)
                        return
                elif (now - session.recognize_started) * 1000 >= int(
                    session.params["no_input_timeout"]
                ):
                    await self._send_mrcp(
                        session,
                        f"RECOGNITION-COMPLETE {session.request_id} COMPLETE",
                        headers=[("Completion-Cause", "001 no-input-timeout")],
                    )
                    self._reset_recognition(session)
                    return
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MRCP watchdog failed")

    async def _finish(
        self,
        session: SipSession,
        cause: str,
        request_id: str,
    ) -> None:
        if session.finishing or session.finished:
            return
        session.finishing = True
        if session.watchdog is not None and session.watchdog is not asyncio.current_task():
            session.watchdog.cancel()
        packets = list(session.packets)
        if not packets:
            await self._send_mrcp(
                session,
                f"RECOGNITION-COMPLETE {request_id} COMPLETE",
                headers=[("Completion-Cause", cause)],
            )
            self._reset_recognition(session)
            return
        converted = _pcm_from_payloads(
            session.payload_type,
            [payload for _, payload in sorted(packets, key=lambda item: item[0])],
        )
        if converted is None:
            await self._send_mrcp(
                session,
                f"RECOGNITION-COMPLETE {request_id} COMPLETE",
                headers=[
                    ("Completion-Cause", "007 grammar-load-failure"),
                    ("Completion-Reason", "unsupported RTP payload type"),
                ],
            )
            self._reset_recognition(session)
            return
        sample_rate, pcm = converted
        temp = self.config.uploads_dir / f".mrcp_{session.session_id}.wav"
        try:
            with wave.open(str(temp), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sample_rate)
                handle.writeframes(pcm)
            try:
                record = self.gateway.submit(
                    temp,
                    filename=f"mrcp-{session.call_id}.wav",
                    model=None,
                    options={
                        "language": session.params.get("language") or "auto",
                        "task": "transcribe",
                        "vad_filter": True,
                    },
                    transport="mrcp",
                )
                session.job_id = record["id"]
                result = await asyncio.to_thread(
                    self.gateway.wait, record["id"], timeout=300
                )
                text = str(result.get("text") or "")
            except ExternalServiceError as exc:
                await self._send_mrcp(
                    session,
                    f"RECOGNITION-COMPLETE {request_id} COMPLETE",
                    headers=[
                        ("Completion-Cause", "002 error"),
                        ("Completion-Reason", exc.message[:200]),
                    ],
                )
                self._reset_recognition(session)
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("MRCP transcription failed")
                await self._send_mrcp(
                    session,
                    f"RECOGNITION-COMPLETE {request_id} COMPLETE",
                    headers=[
                        ("Completion-Cause", "002 error"),
                        ("Completion-Reason", str(exc)[:200]),
                    ],
                )
                self._reset_recognition(session)
                return
            nlsml = (
                '<?xml version="1.0"?>\n'
                '<result xmlns="urn:ietf:params:xml:ns:mrcpv2">\n'
                "  <interpretation>\n"
                f"    <input>{escape(text)}</input>\n"
                "  </interpretation>\n"
                "</result>\n"
            )
            await self._send_mrcp(
                session,
                f"RECOGNITION-COMPLETE {request_id} COMPLETE",
                headers=[("Completion-Cause", cause)],
                body=nlsml,
                content_type="application/nlsml+xml",
            )
            logger.info("MRCP recognition completed on %s: %s", session.call_id, text[:80])
        finally:
            temp.unlink(missing_ok=True)
            self._reset_recognition(session)

    def _reset_recognition(self, session: SipSession) -> None:
        session.recognizing = False
        session.finishing = False
        session.finished = True
        session.job_id = None
        session.packets.clear()


async def start_mrcp_server(
    config: AppConfig,
    gateway: ExternalAsrGateway,
) -> tuple[dict[str, Any], MRCPv2Server | None]:
    if not config.mrcp_enabled or config.mrcp_port <= 0:
        return {"status": "disabled", "enabled": False, "port": 0}, None
    server = MRCPv2Server(config, gateway)
    status = await server.start()
    if status["status"] == "running":
        return status, server
    await server.stop()
    return status, None


async def stop_mrcp_server(server: MRCPv2Server | None) -> None:
    if server is not None:
        await server.stop()
