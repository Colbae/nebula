from abc import ABC, abstractmethod

from nebula.core.nebulaevents import ReputationEvent


class Reputator(ABC):
    """
    Abstract base class that handles reputation rules.

    Reputation is used to assess the trustworthiness of a node. Subclasses
    should implement the logic for updating the reputation and evaluating
    whether a node is trustworthy based on that reputation.
    """

    @abstractmethod
    def update_reputation(self, re: ReputationEvent):
        """
        Update the reputation score of the given node.

        Args:
            re (ReputationEvent): Instance of ReputationEvent.
        """
        pass

    @abstractmethod
    def is_trustworthy(self, node):
        """
        Takes address string of Node. Returns True if the node is trustworthy.

        Returns: True if node is trustworthy, False otherwise.y
        """
        pass
