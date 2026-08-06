from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class BookmarksArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class BookmarksCommand(CommandBase):
    cmd            = "bookmarks"
    needs_admin    = False
    help_cmd       = "bookmarks"
    description    = "Retrieve all browser bookmarks (including folder structure)."
    version        = 1
    author         = "@asaurusrex"
    argument_class = BookmarksArguments
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
