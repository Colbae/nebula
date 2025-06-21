import asyncio
import secrets
from abc import ABC, abstractmethod

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import LeaderElectedEvent, RoundStartEvent
from nebula.core.network.communications import CommunicationsManager


class InvalidElectorError(ValueError):
    def __init__(self, e_type: str):
        super().__init__(f"Invalid reputator type: '{e_type}'")


async def publish_election_event(leader, round_num):
    em: EventManager = EventManager.get_instance()
    le = LeaderElectedEvent(leader, round_num)
    await em.publish_node_event(le)


class Elector(ABC):
    """
    Abstract base class for electing a leader from a set of trustworthy nodes.

    The `Elector` class is responsible for electing a leader among nodes that are
    considered trustworthy. Subclasses should implement the logic for determining the leader.

    The leader's address is expected to be consistent across all trustworthy nodes.
    This consistency ensures that all trustworthy nodes agree on whom the leader is.
    """

    @abstractmethod
    async def elect(self, re: RoundStartEvent):
        """
        Elects a leader for the aggregation.
        Args:
            re: ElectionEvent object
        Returns: Address of the leader.
        """
        pass


class RoundRobinElector(Elector):
    def __init__(self, config, represented=None, trusted=None):
        if trusted is not None:
            trust_nodes = list(trusted)
        else:
            trust_nodes = list(config.participant["sdfl_args"]["trusted_nodes"])
        trust_nodes.sort()

        if represented is not None:
            rep = list(represented)
        else:
            rep = list(config.participant["sdfl_args"]["representated_nodes"])

        self.represented = rep
        self.trust_nodes = trust_nodes
        self.received_leader = None
        self.current = 0
        self.lock = asyncio.Lock()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def elect(self, re: RoundStartEvent):
        if self.trust_nodes[self.current] == self.addr:
            leader = secrets.choice(self.represented)
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


def create_elector(config: Config, represented=None, trusted=None) -> Elector:
    e_type = config.participant["sdfl_args"]["elector"]
    match e_type:
        case "RoundRobinElector":
            return RoundRobinElector(config, represented, trusted)
    raise InvalidElectorError(e_type)


def get_elector_string(rep: type[Elector]) -> str:
    return rep.__name__
