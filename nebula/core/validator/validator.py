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
    async def validate(self, model, round_num, election_num) -> bool:
        """
        Validates a proposed model.
        Args:
            model: The model to validate.
            round_num: The current round number.
            election_num: The current election number.
        Returns: True if the proposed model meets the required standards.
        """
        pass

    @abstractmethod
    async def subscribe_to_events(self):
        """
        Subscribes to relevant events
        """
        pass


def create_validator(config: Config, model, datamodule) -> Validator:
    from nebula.core.validator.NoValidator import NoValidator
    from nebula.core.SDFL.SDFLValidators.SDFLAccuracyValidator import SDFLAccuracyValidator

    v_type = config.participant["sdfl_args"]["validator"]
    match v_type:
        case "NoValidator":
            return NoValidator()
        case "SDFLAccuracyValidator":
            return SDFLAccuracyValidator(config=config, model=model, datamodule=datamodule)
    return NoValidator()


def get_validator_string(rep: type[Validator]) -> str:
    return rep.__name__
