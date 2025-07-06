import asyncio

from nebula.config.config import Config
from nebula.core.SDFL.Electors.elector import create_elector, publish_election_event
from nebula.core.SDFL.Reputators.reputator import create_reputator
from nebula.core.SDFL.TrustBehavior import TrustBehavior
from nebula.core.engine import Engine
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import UpdateReceivedEvent, ModelPropagationEvent, LeaderElectedEvent, \
    NewRepresentativeEvent, ElectionEvent
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
        self._leader_queues = {}

        # Dictionary from (round_num, election_num) => asyncio.Queue to wait for the leader update and retrieve it
        self._leader_queues: dict[tuple[int, int], asyncio.Queue] = {}

        # Dictionary from (round_num, election_num) => leader to prevent race conditions
        self._leader: dict[tuple[int, int], str] = {}

    @property
    def trust_behavior(self):
        return self._trust_behavior

    @property
    def addr(self):
        return f"{self._engine.ip}:{self._engine.port}"

    async def _get_leader(self, r_num, e_num) -> str:
        """
        Safe leader retrieval, retrievs leader of current round.
        Avoids potential KeyErrors from dict retrieval.
        Waits for the leader to be updated.
        """
        key = (r_num, e_num)

        # Check if leader already present, if not start a waiting queue
        async with self._lock:
            if key in self._leader:
                return self._leader[key]

            if key not in self._leader_queues:
                self._leader_queues[key] = asyncio.Queue()
            queue = self._leader_queues[key]

        leader = await queue.get()
        return leader

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
            await EventManager.get_instance().publish_node_event(NewRepresentativeEvent(self._representative))

    async def _promote_node(self, source, message):
        if not self._trust_behavior:
            r = create_reputator(self._config)
            e = create_elector(self._config, message.trusted)
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
                reputator=r,
            )
            self._representative = None
            await self._trust_behavior.subscribe_to_events()
        await self._trust_behavior.update_represented(source, message, self._engine.round)

    async def _update_leader(self, lee: LeaderElectedEvent):
        leader, source, r_num, e_num = await lee.get_event_data()
        if source != self._representative and (
            self.trust_behavior is not None and source not in self._trust_behavior.trusted_nodes):
            return

        key = (r_num, e_num)
        async with self._lock:
            self._leader[key] = leader
            queue = self._leader_queues.pop(key, None)
            if queue is not None:
                await queue.put(leader)

    async def _election_event(self, source, message):
        await publish_election_event(message.leader_addr, source, message.round, message.election_num)

    async def redo_aggregation(self, aggregation_num):
        em: EventManager = EventManager.get_instance()
        # initiate election once trust nodes have been properly updated
        await em.publish_node_event(ElectionEvent(self._engine.round, aggregation_num))
        nodes = await self.select_nodes_to_wait(aggregation_num)

        await self._engine.aggregator.update_federation_nodes(nodes)
        await self.after_learning_cycle(aggregation_num)
        return await self._engine.aggregator.get_aggregation()

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

        await self.after_learning_cycle()

        await self._engine._waiting_model_updates()

    async def after_learning_cycle(self, election_num=0):
        # If this node is leader act as aggregator

        leader = await self._get_leader(self._engine.round, election_num)

        if leader == self.addr:
            self_update_event = UpdateReceivedEvent(
                self._engine.trainer.get_model_parameters(), self._engine.trainer.get_model_weight(), self._engine.addr,
                self._engine.round
            )
            await EventManager.get_instance().publish_node_event(self_update_event)
        mpe = ModelPropagationEvent(
            await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False), "stable")
        await EventManager.get_instance().publish_node_event(mpe)

    async def select_nodes_to_wait(self, election_num=0):
        # only wait for leader update
        leader = await self._get_leader(self._engine.round, election_num)
        if self.addr == leader:
            return await self._engine.cm.get_addrs_current_connections(only_direct=True, myself=False)
        return {leader}

    async def resolve_missing_updates(self):
        return {}
