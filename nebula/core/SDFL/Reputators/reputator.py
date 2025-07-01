from abc import ABC, abstractmethod

from nebula.config.config import Config


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
    async def update_reputation(self, node: str, round_num: int):
        """
        Update the reputation score of the given node.

        Args:
            node: Node of which the reputation should be updated.
            round_num: round for which the reputation should be updated.
        """
        pass

    @abstractmethod
    async def is_trustworthy(self, node):
        """
        Takes address string of Node. Returns True if the node is trustworthy.

        Returns: True if node is trustworthy, False otherwise.
        """
        pass

    @abstractmethod
    async def subscribe_to_events(self):
        """
        Subscribes to relevant events
        """
        pass


def create_reputator(config: Config) -> Reputator:
    from nebula.core.SDFL.Reputators.NoReputator import NoReputator
    from nebula.core.SDFL.Reputators.TimeBasedReputator import TimeBasedReputator

    r_type = config.participant["sdfl_args"]["reputator"]
    match r_type:
        case "NoReputator":
            return NoReputator()
        case "TimeBasedReputator":
            return TimeBasedReputator()
    raise InvalidReputatorError(r_type)


def get_reputator_string(rep: type[Reputator]) -> str:
    return rep.__name__
