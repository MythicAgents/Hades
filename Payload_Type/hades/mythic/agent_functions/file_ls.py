from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class FileLsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="path",
                display_name="Directory Path",
                type=ParameterType.String,
                description="Directory to list (e.g. /home/user, C:\\Users\\user, or ~ for home)",
                default_value="~",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                # Accept plain path typed directly
                self.add_arg("path", self.command_line.strip())



class FileLsCommand(CommandBase):
    cmd            = "file_ls"
    needs_admin    = False
    help_cmd       = "file_ls /path/to/dir"
    description    = (
        "List directory contents via native host. Shows names, types, sizes, permissions. Warns on macOS TCC-restricted paths."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = FileLsArguments
    attackmapping  = ["T1083"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = task.args.get_arg("path") or "~"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
