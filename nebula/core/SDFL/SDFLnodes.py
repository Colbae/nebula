import asyncio
import logging

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import RoundEndEvent, RoundStartEvent, ValidationEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.noderole import AggregatorNode
from nebula.core.SDFL.elector import Elector, create_elector, get_elector_string, publish_election_event
from nebula.core.SDFL.reputator import Reputator, create_reputator, get_reputator_string
from nebula.core.SDFL.validator import Validator, create_validator, get_validator_string
from nebula.core.training.lightning import Lightning


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
        self._leader = await self.elector.elect(re)
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

    async def _update_represented(self, new_rep):
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
        rep = await self._update_represented(node_addr)
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


class FollowerNode(AggregatorNode):
    def __init__(
        self,
        model,
        datamodule,
        representative,
        trust_node=None,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        self.leader = None
        self._lock = asyncio.Lock()
        self.representative = representative
        self._trust_node = trust_node
        super().__init__(
            model,
            datamodule,
            config,
            trainer,
            security,
        )

    @property
    def trust_node(self):
        return self._trust_node

    async def start_communications(self):
        await super().start_communications()

        em: EventManager = EventManager.get_instance()
        # subscribe to promotion events
        await em.subscribe(("info", "trust_info"), self._promote_node)
        # subscribe to representative updates
        await em.subscribe(("representative", "update"), self._update_representative)
        # subscribe to leader update
        await em.subscribe(("leader", "elect"), self._update_leader)
        # trust node callbacks
        if self.trust_node is not None:
            await self._trust_node.start_communications()

    async def _update_representative(self, source, message):
        if source == self.representative and self.trust_node is None:
            self.representative = message.node_addr

    async def _promote_node(self, source, message):
        if not self._trust_node:
            r = create_reputator(self.config)
            e = create_elector(self.config, message.represented, message.trusted)
            v = create_validator(self.config)
            trusted = [f"{self.ip}:{self.port}"]
            rep = [f"{self.ip}:{self.port}"]
            trusted.extend(message.trusted)
            rep.extend(message.represented)

            self._trust_node = TrustNode(
                represented_nodes=rep,
                trusted_nodes=trusted,
                ip=self.ip,
                port=self.port,
                elector=e,
                validator=v,
                reputator=r,
            )
            self.representative = None
            await self._trust_node.start_communications()
        else:
            await self._trust_node.update_represented(message.represented)

    async def _update_leader(self, source, message):
        async with self._lock:
            self.leader = message.leader_addr
            await publish_election_event(self.leader, message.round)
