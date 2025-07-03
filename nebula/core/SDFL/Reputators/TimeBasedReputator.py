import asyncio

from nebula.core.SDFL.Reputators.reputator import Reputator
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import LeaderElectedEvent


class TimeBasedReputator(Reputator):
    """
    Implements a time based reputation.
    """

    def __init__(self, time_limit=5, leader_limit=2):
        self.time_limit = time_limit
        self.leader_limit = leader_limit
        self.leader = {}
        self.lock = asyncio.Lock()
        # Dict from node to score, score is a tuple of form (join_time, leader_num)
        self.nodes: dict[str, tuple[int, int]] = {}

    async def subscribe_to_events(self):
        await EventManager.get_instance().subscribe_node_event(LeaderElectedEvent, self._leader_elected)

    async def _get_leader(self, r):
        """
        Safe leader retrieval, retrievs leader of current round.
        Avoids potential KeyErrors from dict retrieval.
        Waits for the leader to be updated.
        """
        while True:
            leader = self.leader.get(r, None)
            if leader is not None:
                return leader
            await asyncio.sleep(0.5)

    async def _leader_elected(self, le: LeaderElectedEvent):
        leader, _, r, _ = await le.get_event_data()
        async with self.lock:
            self.leader[r] = leader

    async def update_reputation(self, node: str, r):
        # first round is 0
        if r < 0:
            return

        prev_rep = self.nodes.get(node, (0, 0))
        time = prev_rep[0] + 1
        leader_num = prev_rep[1]
        if await self._get_leader(r) == node:
            leader_num += 1
        self.nodes[node] = (time, leader_num)

    async def is_trustworthy(self, node):
        rep = self.nodes.get(node, (0, 0))
        time = rep[0] >= self.time_limit
        leader = rep[1] >= self.leader_limit
        return time and leader
