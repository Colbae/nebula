import asyncio

from nebula.core.SDFL.Reputators.reputator import Reputator
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import LeaderElectedEvent


class TimeBasedReputator(Reputator):
    """
    Implements a time based reputation.
    """

    def __init__(self, leader_limit=5):
        self.leader_limit = leader_limit
        self.leader = {}
        self.leader_queues: dict[int, asyncio.Queue] = {}
        self.lock = asyncio.Lock()
        # Dict from node to how many times it was a leader
        self.nodes: dict[str, int] = {}

    async def subscribe_to_events(self):
        await EventManager.get_instance().subscribe_node_event(LeaderElectedEvent, self._leader_elected)

    async def _get_leader(self, r):
        """
        Safe leader retrieval, retrievs leader of current round.
        Avoids potential KeyErrors from dict retrieval.
        Waits for the leader to be updated.
        """
        async with self.lock:
            if r in self.leader:
                return self.leader[r]

            if r not in self.leader_queues:
                self.leader_queues[r] = asyncio.Queue()
            queue = self.leader_queues[r]

        leader = await queue.get()
        return leader

    async def _leader_elected(self, le: LeaderElectedEvent):
        leader, _, r, _ = await le.get_event_data()

        async with self.lock:
            self.leader[r] = leader
            if r in self.leader_queues:
                queue = self.leader_queues.pop(r, None)
                if queue is not None:
                    await queue.put(leader)

    async def update_reputation(self, node: str, r):
        # first round is 0
        if r < 0:
            return

        leader_num = self.nodes.get(node, 0)
        if await self._get_leader(r) == node:
            leader_num += 1
        self.nodes[node] = leader_num

    async def is_trustworthy(self, node):
        rep = self.nodes.get(node, 0)
        return rep >= self.leader_limit
