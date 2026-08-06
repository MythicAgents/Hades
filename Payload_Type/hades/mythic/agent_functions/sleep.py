from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class SleepArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="interval",
                type=ParameterType.Number,
                description="New poll interval in seconds",
                default_value=10,
            )
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            try:
                self.add_arg("interval", int(self.command_line.strip()))
            except ValueError:
                self.load_args_from_json_string(self.command_line)


class SleepCommand(CommandBase):
    cmd            = "sleep"
    needs_admin    = False
    help_cmd       = "sleep <seconds>"
    description    = "Change the agent check-in (tasking poll) interval."
    version        = 1
    author         = "@asaurusrex"
    argument_class = SleepArguments
    parameters     = []
    attackmapping  = []
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        interval = task.args.get_arg("interval")
        task.display_params = f"{interval}s"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
