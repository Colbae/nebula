import asyncio
import secrets

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import RoundStartEvent, TrustNodeAddedEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.SDFL.Electors.elector import Elector, publish_election_event


class RoundRobinElector(Elector):
    def __init__(self, config, trusted=None):
        trust_nodes = list(trusted) if trusted is not None else list(config.participant["sdfl_args"]["trusted_nodes"])
        trust_nodes.sort()

        self.trust_nodes = trust_nodes
        self.rep = None
        self.received_leader = None
        self.current = 0
        self.lock = asyncio.Lock()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def elect(self, re: RoundStartEvent, rep: set[str]):
        async with self.lock:
            self.rep = rep

        if self.trust_nodes[self.current] == self.addr:
            leader = secrets.choice(list(rep))
            r, _, _ = await re.get_event_data()
            await self._send_choice(leader, r, rep)
            await publish_election_event(leader, r)

        self.current = (self.current + 1) % len(self.trust_nodes)

    async def start_communication(self):
        em: EventManager = EventManager.get_instance()
        await em.subscribe(("leader", "elect"), self._leader_received)
        await em.subscribe_node_event(TrustNodeAddedEvent, self._add_node)

    async def _send_choice(self, leader, round_num, rep, trusted=True):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("leader", "elect", leader_addr=leader, round=round_num)
        if trusted:
            for n in self.trust_nodes:
                if n == self.addr:
                    continue
                await cm.send_message(n, m)
        for n in rep:
            if n == self.addr:
                continue
            await cm.send_message(n, m)

    async def _leader_received(self, source, message):
        if source not in self.trust_nodes:
            return

        r = message.round
        leader = message.leader_addr
        await self._send_choice(leader, r, self.rep, trusted=False)

    async def _add_node(self, te: TrustNodeAddedEvent):
        node_addr = await te.get_event_data()
        async with self.lock:
            self.trust_nodes.append(node_addr)
            self.trust_nodes.sort()
