from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class UptimeArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class UptimeCommand(CommandBase):
    cmd            = "uptime"
    needs_admin    = False
    help_cmd       = "uptime"
    description    = (
        "Report how long the extension has been installed and how long the current "
        "service worker context has been running."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = UptimeArguments
    parameters     = []
    attackmapping  = ["T1082"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
