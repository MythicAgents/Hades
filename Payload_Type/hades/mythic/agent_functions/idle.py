from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class IdleArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class IdleCommand(CommandBase):
    cmd            = "idle"
    needs_admin    = False
    help_cmd       = "idle"
    description    = "Query whether Chrome is active, idle, or screen-locked."
    version        = 1
    author         = "@asaurusrex"
    argument_class = IdleArguments
    parameters     = []
    attackmapping  = ["T1497"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
