# Hades — Mythic C2 Chrome Extension Agent

Hades is a post-exploitation agent for the [Mythic C2 framework](https://github.com/its-a-feature/Mythic) that runs as a Chrome browser extension. It provides stealth persistence, browser data collection, SOCKS5 proxying, filesystem access, and arbitrary command execution — all through Chrome's extension APIs and native messaging.

## Capabilities

- **SOCKS5 proxy** — route operator traffic through the victim's Chrome (IP, network, cookies)
- **Browser data** — cookies, history, bookmarks, localStorage, session export
- **Filesystem** — list, download, upload, delete files via native host
- **Execution** — shell commands via native host (direct, Python in-process, or shell mode)
- **Screen/input** — screenshots, keylogger, clipboard
- **Network monitoring** — HTTP request logging, download interception

## Architecture

```
Mythic C2 ←→ WebSocket ←→ Chrome Extension (Hades)
                                    ↓
                         Native Messaging Host (Python)
                                    ↓
                           OS: files, exec, SOCKS relay
```

The SOCKS proxy relay (`server/socks_bridge.py`) runs on the C2 server and bridges the operator's browser to the victim's network via the extension.

## Setup

See [SETUP.md](SETUP.md) for full installation and build instructions.

## Requirements

- Mythic C2 framework
- Docker + Docker Compose
- Chrome browser on target machine (MV3 extension)
- Python 3.9+ on victim (for native host features)

## Legal

For authorized security testing only. Ensure you have written permission before deploying on any system.
