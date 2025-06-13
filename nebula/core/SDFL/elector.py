from abc import ABC, abstractmethod


class Elector(ABC):
    """
    Abstract base class for electing a leader from a set of trustworthy nodes.

    The `Elector` class is responsible for electing a leader among nodes that are
    considered trustworthy. Subclasses should implement the logic for determining the leader.

    The leader's address is expected to be consistent across all trustworthy nodes.
    This consistency ensures that all trustworthy nodes agree on who the leader is.
    """

    @abstractmethod
    def elect(self):
        """
        Elects a leader for the aggregation.
        Returns: Address of the leader.
        """
        pass


def create_elector(e_type: str) -> Elector:
    return Elector()


def get_elector_string(rep: type[Elector]) -> str:
    return "Elector"
