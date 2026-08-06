from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class ListPwasArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class ListPwasCommand(CommandBase):
    cmd            = "list_pwas"
    needs_admin    = False
    help_cmd       = "list_pwas"
    description    = "List installed Progressive Web Apps and hosted/packaged apps in the browser."
    version        = 1
    author         = "@asaurusrex"
    argument_class = ListPwasArguments
    parameters     = []
    attackmapping  = ["T1518"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
