import asyncio

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.noderole import AggregatorNode
from nebula.core.SDFL.Electors.elector import create_elector, publish_election_event
from nebula.core.SDFL.Reputators.reputator import create_reputator
from nebula.core.SDFL.TrustNode import TrustNode
from nebula.core.SDFL.Validators.validator import create_validator
from nebula.core.training.lightning import Lightning


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
            e = create_elector(self.config, message.trusted)
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
