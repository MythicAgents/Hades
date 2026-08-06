from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class FileDeleteArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                display_name="Path",
                type=ParameterType.String,
                description="Full path to delete (file or empty directory)",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                # Accept plain path typed directly
                self.add_arg("path", self.command_line.strip())



class FileDeleteCommand(CommandBase):
    cmd            = "file_delete"
    needs_admin    = False
    help_cmd       = "file_delete /path/to/file"
    description    = (
        "Delete a file or empty directory on the victim via native host."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = FileDeleteArguments
    attackmapping  = ["T1485"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = task.args.get_arg("path") or ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
