from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class ShellExecArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="cmd",
                display_name="Command",
                type=ParameterType.String,
                description="Command or Python code to execute.",
            ),
            CommandParameter(
                name="mode",
                display_name="Exec Mode",
                type=ParameterType.ChooseOne,
                description=(
                    "direct: shlex-split + exec binary directly, no shell wrapper on any platform (default). "
                    "python: in-process exec(), no subprocess at all. "
                    "shell: explicit /bin/sh or cmd.exe — use only when pipes/redirects are needed."
                ),
                choices=["direct", "python", "shell"],
                default_value="direct",
            ),
            CommandParameter(
                name="cwd",
                display_name="Working Directory",
                type=ParameterType.String,
                description="Working directory (optional)",
                default_value="",
            ),
            CommandParameter(
                name="timeout",
                display_name="Timeout (seconds)",
                type=ParameterType.Number,
                description="Max seconds to wait",
                default_value=60,
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            try:
                self.load_args_from_json_string(self.command_line)
            except Exception:
                self.add_arg("cmd", self.command_line.strip())


class ShellExecCommand(CommandBase):
    cmd            = "exec"
    needs_admin    = False
    help_cmd       = 'exec whoami  |  exec {"cmd": "ls /tmp", "mode": "direct"}  |  exec {"cmd": "import os; print(os.getcwd())", "mode": "python"}'
    description    = (
        "Execute a command via the native messaging host. "
        "Default mode (direct): binary is exec'd directly via subprocess — no shell process in the tree on any platform. "
        "Use mode=python for in-process Python exec() with no subprocess at all. "
        "Use mode=shell only when pipes/redirects are needed (launches /bin/sh or cmd.exe). "
        "Requires native host built with exec or all features."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = ShellExecArguments
    attackmapping  = ["T1059"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        mode = task.args.get_arg("mode") or "direct"
        cmd  = task.args.get_arg("cmd") or ""
        task.display_params = f"[{mode}] {cmd}"
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
