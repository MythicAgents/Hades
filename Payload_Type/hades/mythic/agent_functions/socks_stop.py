from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class SocksStopArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class SocksStopCommand(CommandBase):
    cmd            = "socks_stop"
    needs_admin    = False
    help_cmd       = "socks_stop"
    description    = "Stop the SOCKS5 native messaging host and close the 127.0.0.1:1080 listener."
    version        = 1
    author         = "@asaurusrex"
    argument_class = SocksStopArguments
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
