import asyncio
import secrets

from nebula.core.SDFL.Electors.elector import Elector, publish_election_event
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import TrustNodeAddedEvent, LeaderElectedEvent
from nebula.core.network.communications import CommunicationsManager


class RoundRobinElector(Elector):
    def __init__(self, config, trusted=None, current=0):
        trust_nodes: list[str] = list(trusted) if trusted is not None else list(
            config.participant["sdfl_args"]["trust_nodes"])
        trust_nodes.sort()

        self.trust_nodes = trust_nodes
        self.received_leader = None
        self.current = current
        self.lock = asyncio.Lock()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]
        self.current_leader = None
        self.queue = None

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def subscribe_to_events(self):
        em: EventManager = EventManager.get_instance()
        await em.subscribe_node_event(LeaderElectedEvent, self._leader_received)
        await em.subscribe_node_event(TrustNodeAddedEvent, self._add_node)

    async def elect(self, round_num: int, election_num: int, rep: set[str]):
        if self.trust_nodes[self.current] == self.addr:
            leader = secrets.choice(list(rep))
            async with self.lock:
                self.current_leader = (leader, round_num, election_num)
            await self._send_choice(leader, round_num, rep, election_num)
            await publish_election_event(leader, self.addr, round_num, election_num)
        else:
            await self._await_leader(round_num, election_num, rep)

        self.current = (self.current + 1) % len(self.trust_nodes)
        async with self.lock:
            self.current_leader = None
            self.queue = None

    async def _await_leader(self, round_num, election_num, reps):
        async with self.lock:
            if self.current_leader is not None:
                await self._send_choice(self.current_leader, round_num, reps, election_num, trusted=False)
                self.current_leader = None
                return
            self.queue = asyncio.Queue()

        leader = await self.queue.get()
        await self._send_choice(leader, round_num, reps, election_num, trusted=False)

    async def _leader_received(self, lee: LeaderElectedEvent):
        leader, _, _, _ = await lee.get_event_data()
        async with self.lock:
            self.current_leader = leader
            if self.queue is not None:
                await self.queue.put(leader)

    async def _send_choice(self, leader, round_num, rep, election_num, trusted=True):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("leader", "elect", leader_addr=leader, round=round_num, election_num=election_num)
        if trusted:
            for n in self.trust_nodes:
                if n == self.addr:
                    continue
                await cm.send_message(n, m)
        for n in rep:
            if n == self.addr:
                continue
            await cm.send_message(n, m)

    async def _add_node(self, te: TrustNodeAddedEvent):
        nodes_addr = await te.get_event_data()
        async with self.lock:
            self.trust_nodes = list(nodes_addr)
            self.trust_nodes.sort()

    async def get_current(self):
        return self.current
