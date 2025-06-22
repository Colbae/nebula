from nebula.core.SDFL.Reputators.reputator import Reputator


class NoReputator(Reputator):
    """
    Implementation to skip Reputation.
    """

    async def update_reputation(self, node: str, trust_node):
        """
        Reputation skipped, does nothing.
        """
        pass

    async def is_trustworthy(self, node):
        """
        Reputation skipped, always returns False.
        """
        return False
