from nebula.core.validator.validator import Validator


class NoValidator(Validator):
    """
    Implementation to skip validation of proposed model.
    """

    async def validate(self, model):
        """
        Always returns True. Skips validation of proposed model.
        """
        return True

    async def subscribe_to_events(self):
        pass
