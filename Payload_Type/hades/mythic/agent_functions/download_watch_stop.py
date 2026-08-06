from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadWatchStopArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class DownloadWatchStopCommand(CommandBase):
    cmd            = "download_watch_stop"
    needs_admin    = False
    help_cmd       = "download_watch_stop"
    description    = "Stop download monitoring and return a summary of all observed downloads."
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadWatchStopArguments
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
