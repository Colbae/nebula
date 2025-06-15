from abc import ABC, abstractmethod

from nebula.core.nebulaevents import ReputationEvent


class InvalidReputatorError(ValueError):
    def __init__(self, r_type: str):
        super().__init__(f"Invalid reputator type: '{r_type}'")


class Reputator(ABC):
    """
    Abstract base class that handles reputation rules.

    Reputation is used to assess the trustworthiness of a node. Subclasses
    should implement the logic for updating the reputation and evaluating
    whether a node is trustworthy based on that reputation.
    """

    @abstractmethod
    async def update_reputation(self, re: ReputationEvent):
        """
        Update the reputation score of the given node.

        Args:
            re (ReputationEvent): Instance of ReputationEvent.
        """
        pass

    @abstractmethod
    async def is_trustworthy(self, node):
        """
        Takes address string of Node. Returns True if the node is trustworthy.

        Returns: True if node is trustworthy, False otherwise.y
        """
        pass


class NoReputator(Reputator):
    """
    Implements to skip Reputation.
    """

    async def update_reputation(self, re: ReputationEvent):
        """
        Reputation skipped, does nothing.
        """
        pass

    async def is_trustworthy(self, node):
        """
        Reputation skipped, always returns False.
        """
        return False


def create_reputator(r_type: str) -> Reputator:
    match r_type:
        case "NoReputator":
            return NoReputator()
    raise InvalidReputatorError(r_type)


def get_reputator_string(rep: type[Reputator]) -> str:
    return rep.__name__
