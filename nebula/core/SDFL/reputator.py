from abc import ABC, abstractmethod


class Reputator(ABC):
    """
    Abstract base class that handles reputation rules.

    Reputation is used to assess the trustworthiness of a node. Subclasses
    should implement the logic for updating the reputation and evaluating
    whether a node is trustworthy based on that reputation.
    """

    @abstractmethod
    def update_reputation(self, sdfl_node, node_addr):
        """
        Update the reputation score of the given node.

        Args:
            sdfl_node: Reference to sdfl_node object to access information required for reputation.
            node_addr: Address of the node.
        """
        pass

    @abstractmethod
    def is_trustworthy(self, node):
        """
        Takes address string of Node. Returns True if the node is trustworthy.

        Returns: True if node is trustworthy, False otherwise.y
        """
        pass
