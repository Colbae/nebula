from nebula.core.SDFL.Reputators.reputator import Reputator


class TimeBasedReputator(Reputator):
    """
    Implements a time based reputation.
    """

    def __init__(self, time_limit=5, leader_limit=2):
        self.time_limit = time_limit
        self.leader_limit = leader_limit
        # Dict from node to score, score is a tuple of form (join_time, leader_num)
        self.nodes: dict[str, tuple[int, int]] = {}

    async def update_reputation(self, node: str, trust_node):
        prev_rep = self.nodes.get(node, (0, 0))
        time = prev_rep[0] + 1
        leader_num = prev_rep[1]
        if trust_node.leader == node:
            leader_num += 1
        self.nodes[node] = (time, leader_num)

    async def is_trustworthy(self, node):
        rep = self.nodes.get(node, (0, 0))
        time = rep[0] >= self.time_limit
        leader = rep[1] >= self.leader_limit
        return time and leader

    async def start_communication(self):
        pass
