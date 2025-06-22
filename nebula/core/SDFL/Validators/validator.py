from abc import ABC, abstractmethod

from nebula.config.config import Config


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


def create_validator(config: Config) -> Validator:
    from nebula.core.SDFL.Validators.NoValidator import NoValidator

    v_type = config.participant["sdfl_args"]["validator"]
    match v_type:
        case "NoValidator":
            return NoValidator()
    raise InvalidValidatorError(v_type)


def get_validator_string(rep: type[Validator]) -> str:
    return rep.__name__
