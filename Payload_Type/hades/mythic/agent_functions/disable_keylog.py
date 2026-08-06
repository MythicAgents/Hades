from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class DisableKeylogArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class DisableKeylogCommand(CommandBase):
    cmd            = "disable_keylog"
    needs_admin    = False
    help_cmd       = "disable_keylog"
    description    = "Stop keystroke capture and flush any remaining buffer."
    version        = 1
    author         = "@asaurusrex"
    argument_class = DisableKeylogArguments
    parameters     = []
    attackmapping  = ["T1056.001"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
