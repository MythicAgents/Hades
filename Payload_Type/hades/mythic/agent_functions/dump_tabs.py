from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class DumpTabsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class DumpTabsCommand(CommandBase):
    cmd            = "dump_tabs"
    needs_admin    = False
    help_cmd       = "dump_tabs"
    description    = "List all open browser tabs with id, title, URL, and window."
    version        = 1
    author         = "@asaurusrex"
    argument_class = DumpTabsArguments
    parameters     = []
    attackmapping  = ["T1217"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
