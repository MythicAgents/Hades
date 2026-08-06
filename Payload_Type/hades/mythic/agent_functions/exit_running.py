from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class ExitRunningArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class ExitRunningCommand(CommandBase):
    cmd                  = "exit_running"
    needs_admin          = False
    help_cmd             = "exit_running"
    description          = "Stop the C2 callback loop and close the socket. The extension remains installed and dormant — it does not uninstall itself."
    version              = 1
    author               = "@asaurusrex"
    supported_ui_features = []
    argument_class       = ExitRunningArguments
    parameters           = []
    attackmapping        = []
    attributes           = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
