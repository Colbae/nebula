import asyncio

from nebula.core.SDFL.Electors.elector import Elector
from nebula.core.SDFL.Reputators.reputator import Reputator
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import ElectionEvent, TrustNodeAddedEvent, ReputationEvent, RepresantativesUpdateEvent, \
    PromotionEvent
from nebula.core.network.communications import CommunicationsManager


class TrustBehavior:
    def __init__(
        self,
        represented_nodes,
        trusted_nodes,
        ip,
        port,
        elector: Elector,
        reputator: Reputator,
    ):
        self.represented_nodes = set(represented_nodes)
        self.trusted_nodes = set(trusted_nodes)
        self.ip = ip
        self.port = port
        self.elector = elector
        self.reputator = reputator
        self._lock = asyncio.Lock()
        self.reputations_updated_amount = 0
        self.round = -1
        self.trust_info_amount = 0

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def subscribe_to_events(self):
        em: EventManager = EventManager.get_instance()
        # Initiate election callback
        await em.subscribe_node_event(ElectionEvent, self._elect_leader)
        # Initiate reputation callback
        await em.subscribe_node_event(ReputationEvent, self._update_reputation)
        # Initiate adding trust node callback
        await em.subscribe(("trustworthy", "add"), self._add_trust_node_callback)

        await self.elector.subscribe_to_events()
        await self.reputator.subscribe_to_events()

    ## ELECTION CALLBACKS ##
    async def _elect_leader(self, ee: ElectionEvent):
        r, e = await ee.get_event_data()
        await self.elector.elect(r, e, self.represented_nodes)

    ## REPUTATION CALLBACKS ##
    async def _update_reputation(self, re: ReputationEvent):
        # self.represented_nodes can be edited from promotions,
        # create copy to iterate over
        prev_round = self.round
        self.round = await re.get_event_data()
        trustworthy = []
        for r_node in list(self.represented_nodes):
            if r_node == self.addr:
                continue
            # Update Rep for prev round
            await self.reputator.update_reputation(r_node, prev_round)
            if await self.reputator.is_trustworthy(r_node):
                trustworthy.append(r_node)
                await self._add_trust_node(r_node)

        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("trustworthy", "add", node_addr=trustworthy)
        for t_node in self.trusted_nodes:
            if t_node == self.addr:
                continue
            await cm.send_message(t_node, m)

        await self._reputation_updated()

    async def _reputation_updated(self):
        async with self._lock:
            self.reputations_updated_amount += 1
        if len(self.trusted_nodes) == self.reputations_updated_amount:
            # reset msg to 0 for next round
            self.reputations_updated_amount = 0
            em: EventManager = EventManager.get_instance()
            # initiate election once trust nodes have been properly updated
            await em.publish_node_event(ElectionEvent(self.round))

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
        await EventManager.get_instance().publish_node_event(RepresantativesUpdateEvent(self.represented_nodes))
        return removed_nodes

    async def _add_trust_node(self, node_addr):
        rep = await self._adjust_represented(node_addr)
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(
            "info",
            "trust_info",
            trusted=list(self.trusted_nodes),
            represented=rep,
        )
        await cm.send_message(node_addr, m)

        async with self._lock:
            self.trusted_nodes.add(node_addr)
        em: EventManager = EventManager.get_instance()
        await em.publish_node_event(TrustNodeAddedEvent(node_addr))

    ## MSG CALLBACKS ##
    async def _add_trust_node_callback(self, source, message):
        if source not in self.trusted_nodes:
            return
        new_nodes = message.node_addr
        for n in new_nodes:
            await self._add_trust_node(n)
        await self._reputation_updated()

    ## PROMOTION ##
    async def update_represented(self, source, message, round_num):
        async with self._lock:
            self.trust_info_amount += 1
            self.trusted_nodes.update(message.trusted)
            self.represented_nodes.update(message.represented)

        # wait until all trustworthy nodes have updated the new node
        # len(self.trusted_nodes) - 1, since trusted_nodes include this node
        if len(self.trusted_nodes) - 1 == self.trust_info_amount:
            # send msg to other trust nodes to confirm it being ready
            cm: CommunicationsManager = CommunicationsManager.get_instance()
            m = cm.create_message("trustworthy", "add", node_addr=[])
            for t_node in self.trusted_nodes:
                if t_node == self.addr:
                    continue
                await cm.send_message(t_node, m)

            await EventManager.get_instance().publish_node_event(
                PromotionEvent(self.represented_nodes, self.trusted_nodes))

            # start election
            em: EventManager = EventManager.get_instance()
            await em.publish_node_event(ElectionEvent(round_num))
