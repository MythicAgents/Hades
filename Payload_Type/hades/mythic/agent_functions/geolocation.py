from mythic_container.MythicCommandBase import (
    CommandBase, TaskArguments, CommandParameter, ParameterType,
    MythicTask, PTTaskMessageAllData, PTTaskProcessResponseMessageResponse,
    CommandAttributes,
)


class GeolocationArguments(TaskArguments):
    def __init__(self, command_line, **kwargs):
        super().__init__(command_line, **kwargs)
        self.args = []

    async def parse_arguments(self):
        pass


class GeolocationCommand(CommandBase):
    cmd            = "geolocation"
    needs_admin    = False
    help_cmd       = "geolocation"
    description    = (
        "Request the browser's geolocation from the active tab. Only succeeds if "
        "the current page has been granted geolocation permission by the user "
        "(e.g. Google Maps, weather apps)."
    )
    version        = 1
    author         = "@asaurusrex"
    argument_class = GeolocationArguments
    parameters     = []
    attackmapping  = ["T1430"]
    attributes     = CommandAttributes(filter_by_build_parameter={}, supported_os=[])

    async def create_tasking(self, task: MythicTask) -> MythicTask:
        task.display_params = ""
        return task

    async def process_response(
        self, task: PTTaskMessageAllData, response: any
    ) -> PTTaskProcessResponseMessageResponse:
        return PTTaskProcessResponseMessageResponse(TaskID=task.Task.ID, Success=True)
