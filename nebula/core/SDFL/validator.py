from abc import ABC, abstractmethod


class InvalidValidatorError(ValueError):
    def __init__(self, v_type: str):
        super().__init__(f"Invalid validator type: '{v_type}'")


class Validator(ABC):
    """
    Abstract base class for validating a proposed model.

    The `Validator` class is responsible for validating a model based on custom
    criteria defined in subclasses. The validation logic should ensure that the
    proposed model meets the required standards.
    """

    @abstractmethod
    async def validate(self, model) -> bool:
        """
        Validates a proposed model.
        Args:
            model: The model to validate.
        Returns: True if the proposed model meets the required standards.
        """
        pass


class NoValidator(Validator):
    """
    Implementation to skip validation of proposed model.
    """

    async def validate(self, model):
        """
        Always returns True. Skips validation of proposed model.
        Args:
            model:

        Returns:

        """
        return True


def create_validator(v_type: str) -> Validator:
    match v_type:
        case "NoValidator":
            return NoValidator()
    raise InvalidValidatorError(v_type)


def get_validator_string(rep: type[Validator]) -> str:
    return rep.__name__
