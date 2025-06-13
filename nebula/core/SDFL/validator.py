from abc import ABC, abstractmethod


class Validator(ABC):
    """
    Abstract base class for validating a proposed model.

    The `Validator` class is responsible for validating a model based on custom
    criteria defined in subclasses. The validation logic should ensure that the
    proposed model meets the required standards.
    """

    @abstractmethod
    async def validate(self, model):
        """
        Validates a proposed model.
        Args:
            model: The model to validate.
        Returns: True if the proposed model meets the required standards.
        """
        pass


def create_validator(v_type: str) -> Validator:
    return Validator()


def get_validator_string(rep: type[Validator]) -> str:
    return "Validator"
