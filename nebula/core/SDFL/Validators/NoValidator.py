from nebula.core.SDFL.Validators.validator import Validator


class NoValidator(Validator):
    """
    Implementation to skip validation of proposed model.
    """

    async def validate(self, model):
        """
        Always returns True. Skips validation of proposed model.
        """
        return True

    async def start_communication(self):
        pass
