import asyncio
import secrets

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import RoundStartEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.SDFL.Electors.elector import Elector, publish_election_event


class RoundRobinElector(Elector):
    def __init__(self, config, trusted=None):
        trust_nodes = list(trusted) if trusted is not None else list(config.participant["sdfl_args"]["trusted_nodes"])
        trust_nodes.sort()

        self.trust_nodes = trust_nodes
        self.received_leader = None
        self.current = 0
        self.lock = asyncio.Lock()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def elect(self, re: RoundStartEvent, rep: set[str]):
        if self.trust_nodes[self.current] == self.addr:
            leader = secrets.choice(list(rep))
            await self._send_choice(leader)
        else:
            leader = await self._await_choice()

        self.current = (self.current + 1) % len(self.trust_nodes)
        r, _, _ = await re.get_event_data()
        await publish_election_event(leader, r)
        return leader

    async def start_communication(self):
        em: EventManager = EventManager.get_instance()
        await em.subscribe(("leader", "elect"), self._leader_received)
        await em.subscribe(("trustworthy", "add"), self._add_node)

    async def _await_choice(self, timeout=30):
        start_time = asyncio.get_running_loop().time()
        while True:
            if self.received_leader is not None:
                leader = self.received_leader
                self.received_leader = None
                return leader

            if (asyncio.get_running_loop().time() - start_time) > timeout:
                await self._handle_timeout()

            await asyncio.sleep(0.1)

    async def _leader_received(self, source, message):
        if source == self.trust_nodes[self.current]:
            async with self.lock:
                self.received_leader = message.leader_addr

    async def _handle_timeout(self):
        pass

    async def _send_choice(self, choice):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("leader", "elect", leader_addr=choice)
        for n in self.trust_nodes:
            if n == self.addr:
                continue
            await cm.send_message(n, m)

    async def _add_node(self, source, message):
        if source not in self.trust_nodes:
            return
        async with self.lock:
            self.trust_nodes.append(message.node_addr)
            self.trust_nodes.sort()
