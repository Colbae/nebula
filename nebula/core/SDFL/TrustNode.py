import asyncio
import logging

from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import RoundEndEvent, RoundStartEvent, ValidationEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.SDFL.Electors.elector import Elector, get_elector_string
from nebula.core.SDFL.Reputators.reputator import Reputator, get_reputator_string
from nebula.core.SDFL.Validators.validator import Validator, get_validator_string


class TrustNode:
    def __init__(
        self,
        represented_nodes,
        trusted_nodes,
        ip,
        port,
        elector: Elector,
        validator: Validator,
        reputator: Reputator,
    ):
        self.represented_nodes = set(represented_nodes)
        self.trusted_nodes = set(trusted_nodes)
        self.ip = ip
        self.port = port
        self.elector = elector
        self.validator = validator
        self.reputator = reputator
        self._leader = None
        self._lock = asyncio.Lock()

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def start_communications(self):
        em: EventManager = EventManager.get_instance()
        # Initiate election callback
        await em.subscribe_node_event(RoundStartEvent, self._elect_leader)
        # Initiate reputation callback
        await em.subscribe_node_event(RoundEndEvent, self._update_reputation)
        # Initiate validation callback
        await em.subscribe_node_event(ValidationEvent, self._validate_model)
        # Initiate adding trust node callback
        await em.subscribe(("trustworthy", "add"), self._add_trust_node_callback)

    @property
    def leader(self):
        return self._leader

    async def _elect_leader(self, re: RoundStartEvent):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        self._leader = await self.elector.elect(re, self.represented_nodes)
        r, _, _ = await re.get_event_data()
        m = cm.create_message("leader", "elect", leader_addr=self.leader, round=r)
        for n in self.represented_nodes:
            if n == self.addr:
                continue
            await cm.send_message(n, m)

    async def _update_reputation(self, re: RoundEndEvent):
        # self.represented_nodes can be edited from promotions,
        # create copy to iterate over
        for r_node in list(self.represented_nodes):
            if r_node == self.addr:
                continue
            await self.reputator.update_reputation(r_node, self)
            if await self.reputator.is_trustworthy(r_node):
                async with self._lock:
                    cm: CommunicationsManager = CommunicationsManager.get_instance()
                    m = cm.create_message("trustworthy", "add", node_addr=r_node)
                    for t_node in self.trusted_nodes:
                        if t_node == self.addr:
                            continue
                        await cm.send_message(t_node, m)
                await self._add_trust_node(r_node)

    async def _validate_model(self, ve: ValidationEvent):
        if not await self.validator.validate(ve):
            logging.info("Validation failed")

    async def _adjust_represented(self, new_rep):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        removed_nodes = []

        async with self._lock:
            # TODO: decide what rep nodes are to be changed
            if new_rep not in self.represented_nodes:
                return []
            r = [new_rep]

            for n in r:
                m = cm.create_message("representative", "update", node_addr=new_rep)
                if n == self.addr:
                    continue
                await cm.send_message(n, m)
                self.represented_nodes.remove(n)
                removed_nodes.append(n)
        return removed_nodes

    async def _add_trust_node_callback(self, source, message):
        if source not in self.trusted_nodes:
            return
        await self._add_trust_node(message.node_addr)

    async def _add_trust_node(self, node_addr):
        rep = await self._adjust_represented(node_addr)
        if rep:
            cm: CommunicationsManager = CommunicationsManager.get_instance()
            m = cm.create_message(
                "info",
                "trust_info",
                validator=get_validator_string(type[self.validator]),
                reputator=get_reputator_string(type[self.reputator]),
                elector=get_elector_string(type[self.elector]),
                trusted=list(self.trusted_nodes),
                represented=rep,
            )
            await cm.send_message(node_addr, m)
        async with self._lock:
            self.trusted_nodes.add(node_addr)

    async def update_represented(self, rep):
        async with self._lock:
            self.represented_nodes.update(rep)
