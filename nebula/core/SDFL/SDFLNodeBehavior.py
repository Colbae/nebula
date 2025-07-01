import asyncio

from nebula.config.config import Config
from nebula.core.SDFL.Electors.elector import create_elector, publish_election_event
from nebula.core.SDFL.Reputators.reputator import create_reputator
from nebula.core.SDFL.TrustBehavior import TrustBehavior
from nebula.core.SDFL.Validators.validator import create_validator
from nebula.core.engine import Engine
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent, ModelPropagationEvent, LeaderElectedEvent
from nebula.core.noderole import RoleBehavior, factory_node_role


class SDFLNodeBehavior(RoleBehavior):
    def __init__(self,
                 engine: Engine,
                 config: Config,
                 representative,
                 trust_behavior=None,
                 ):
        super().__init__()
        self._engine = engine
        self._config = config
        self._role = factory_node_role("trainer_aggregator")
        self._lock = asyncio.Lock()
        self._representative = representative
        self._trust_behavior: TrustBehavior = trust_behavior

        # Dictionary from round => leader to prevent race conditions
        self._leader = {}

    @property
    def trust_behavior(self):
        return self._trust_behavior

    @property
    def addr(self):
        return f"{self._engine.ip}:{self._engine.port}"

    async def _get_leader(self, r):
        """
        Safe leader retrieval, retrievs leader of current round.
        Avoids potential KeyErrors from dict retrieval.
        Waits for the leader to be updated.
        """
        while True:
            leader = self._leader.get(r, None)
            if leader is not None:
                return leader
            await asyncio.sleep(0.5)

    async def subscribe_to_events(self):
        em: EventManager = EventManager.get_instance()
        # subscribe to promotion events
        await em.subscribe(("info", "trust_info"), self._promote_node)
        # subscribe to representative updates
        await em.subscribe(("representative", "update"), self._update_representative)
        # subscribe to leader update
        await em.subscribe(("leader", "elect"), self._election_event)
        await em.subscribe_node_event(LeaderElectedEvent, self._update_leader)

        # trust node callbacks
        if self.trust_behavior is not None:
            await self._trust_behavior.subscribe_to_events()

    async def _update_representative(self, source, message):
        if source == self._representative and self.trust_behavior is None:
            self._representative = message.node_addr

    async def _promote_node(self, source, message):
        if not self._trust_behavior:
            r = create_reputator(self._config)
            e = create_elector(self._config, message.trusted)
            v = create_validator(self._config)
            trusted = [self.addr]
            rep = [self.addr]
            trusted.extend(message.trusted)
            rep.extend(message.represented)

            self._trust_behavior = TrustBehavior(
                represented_nodes=rep,
                trusted_nodes=trusted,
                ip=self._engine.ip,
                port=self._engine.port,
                elector=e,
                validator=v,
                reputator=r,
            )
            self._representative = None
            await self._trust_behavior.subscribe_to_events()
        await self._trust_behavior.update_represented(source, message, self._engine.round)

    async def _update_leader(self, lee: LeaderElectedEvent):
        leader, source, r = await lee.get_event_data()
        # Leader msg must come from rep or from trustworthy peerstarting training..
        if source != self._representative and (
            self.trust_behavior is not None and source not in self._trust_behavior.trusted_nodes):
            print(f"source {source}, trusted {self._representative}")
            return
        async with self._lock:
            self._leader[r] = leader

    async def _election_event(self, source, message):
        await publish_election_event(message.leader_addr, source, message.round)

    ## ABC-METHOD IMPLEMENTATIONS ##

    def get_role(self):
        return self._role

    def get_role_name(self, effective=False):
        return self._role.value

    async def extended_learning_cycle(self):
        await self._engine.trainer.test()
        await self._engine.trainning_in_progress_lock.acquire_async()
        await self._engine.trainer.train()
        await self._engine.trainning_in_progress_lock.release_async()

        # If this node is leader act as aggregator
        if await self._get_leader(self._engine.round) == self.addr:
            self_update_event = UpdateReceivedEvent(
                self._engine.trainer.get_model_parameters(), self._engine.trainer.get_model_weight(), self._engine.addr,
                self._engine.round
            )
            await EventManager.get_instance().publish_node_event(self_update_event)

        mpe = ModelPropagationEvent(
            await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)
        await self._engine._waiting_model_updates()

    async def select_nodes_to_wait(self):
        # only wait for leader update
        leader = await self._get_leader(self._engine.round)
        if self.addr == leader:
            return await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return {leader}

    async def resolve_missing_updates(self):
        return {}
