from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class ReloadExtensionArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class ReloadExtensionCommand(CommandBase):
    cmd            = "reload_extension"
    needs_admin    = False
    help_cmd       = "reload_extension"
    description    = (
        "Reload the extension via chrome.runtime.reload(). All in-memory state is "
        "discarded — active sockets, timers, proxy sessions, in-flight tasks. The "
        "agent re-initialises and reconnects to C2 automatically within a few seconds. "
        "Persisted state (proxy URL, native host PSK, sleep interval) is restored from "
        "chrome.storage.local on startup.\n\n"
        "Use this to recover from a stuck connection, leaked timer, or any bad runtime "
        "state without uninstalling the extension.\n\n"
        "NOTE: this does NOT clear the chrome://extensions error panel. That panel is "
        "owned by the browser process and can only be cleared manually: "
        "chrome://extensions → click the error badge → 'Clear all'."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = ReloadExtensionArguments
    attackmapping  = []
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
