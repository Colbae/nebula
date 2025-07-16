import asyncio
import math

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
        round_num=-1,
        initial_round=-1,
    ):
        self.represented_nodes = set(represented_nodes)
        self.trusted_nodes = set(trusted_nodes)
        self.ip = ip
        self.port = port
        self.elector = elector
        self.reputator = reputator
        self._lock = asyncio.Lock()
        self.reputations_updated_amount = 0
        self.round = round_num
        self.trust_info_amount = 0
        self.rep_allocations = {}
        self.new_trustnodes = []
        self.elections_for_round = set()
        self.initial_round = initial_round

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

    async def _start_election(self):
        async with self._lock:
            if self.round in self.elections_for_round:
                return
            self.elections_for_round.add(self.round)
        em: EventManager = EventManager.get_instance()
        await em.publish_node_event(ElectionEvent(self.round))

    ## REPUTATION CALLBACKS ##
    async def _update_reputation(self, re: ReputationEvent):
        self.round, prev_round = await re.get_event_data()
        trustworthy = []

        if self.round < self.initial_round:
            return

        for r_node in list(self.represented_nodes):
            if r_node == self.addr:
                continue
            # Update Rep for prev round
            await self.reputator.update_reputation(r_node, prev_round)
            if await self.reputator.is_trustworthy(r_node):
                trustworthy.append(r_node)
        async with self._lock:
            self.new_trustnodes.extend(trustworthy)
            self.rep_allocations[self.addr] = self.represented_nodes

        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("trustworthy", "add", node_addr=trustworthy, rep_addr=self.represented_nodes)
        for t_node in self.trusted_nodes:
            if t_node == self.addr:
                continue
            await cm.send_message(t_node, m)

        await self._reputation_updated()

    async def _reputation_updated(self):
        async with self._lock:
            self.reputations_updated_amount += 1
        if len(self.trusted_nodes) == self.reputations_updated_amount:
            # Add the new trustnodes
            new_allocation = await self._adjust_represented(self.new_trustnodes)
            await self._add_trust_nodes(new_allocation)

            # reset updates
            async with self._lock:
                self.reputations_updated_amount = 0
                self.new_trustnodes = []

            # Start the election process
            # initiate election once trust nodes have been properly updated
            await self._start_election()

    async def _adjust_represented(self, new_reps):
        if len(new_reps) == 0:
            return {}

        cm: CommunicationsManager = CommunicationsManager.get_instance()
        total_reps = 0
        trust_node_order = list(self.trusted_nodes)
        trust_node_order.sort()
        new_reps.sort()
        new_trust_nodes = list(self.trusted_nodes)
        new_trust_nodes.extend(new_reps)
        max_amount = 0

        for node in self.rep_allocations:
            total_reps += len(self.rep_allocations[node])
            max_amount = max(max_amount, len(self.rep_allocations[node]))

        # always keep max amount possible

        amount_to_keep = math.ceil(total_reps / len(new_trust_nodes))

        trust_node_amount_giving = {}
        for node in trust_node_order:
            amount_to_remove = len(self.rep_allocations[node]) - amount_to_keep
            trust_node_amount_giving[node] = amount_to_remove

        min_per_new = (total_reps - len(trust_node_order) * amount_to_keep) // len(new_reps)

        amount_per_new = {}
        allocation_amount = {}
        given = 0
        for n in trust_node_order:
            amount_to_give = trust_node_amount_giving[n]
            for new in new_reps:
                current_amount = amount_per_new.get(new, 0)
                if current_amount < min_per_new and n == self.addr:
                    giving = min(min_per_new - current_amount, amount_to_give)
                    amount_per_new[new] = giving + current_amount
                    amount_to_give -= giving
                    given += giving
                    allocation_amount[new] = giving
                elif current_amount < min_per_new:
                    giving = min(min_per_new - current_amount, amount_to_give)
                    amount_per_new[new] = giving + current_amount
                    amount_to_give -= giving

                if amount_to_give == 0:
                    break

        allocations = {}
        reps = list(self.represented_nodes)
        reps.remove(self.addr)
        for n in new_reps:
            if n in self.represented_nodes:
                allocations[n] = allocations.get(n, [])
                allocations[n].append(n)
                reps.remove(n)
        for n in new_reps:
            amount = allocation_amount.get(n, 0)
            if amount > 0:
                allocations[n] = allocations.get(n, [])
                if len(reps) < amount:
                    allocations[n].extend(reps)
                    break

                allocations[n].extend(reps[:amount])
                reps = reps[amount:]

        async with self._lock:
            for n in new_reps:
                reps = allocations.get(n, [])
                for r in reps:
                    m = cm.create_message("representative", "update", node_addr=n)
                    await cm.send_message(r, m)
                    if r in self.represented_nodes:
                        self.represented_nodes.remove(r)

        await EventManager.get_instance().publish_node_event(RepresantativesUpdateEvent(self.represented_nodes))
        return allocations

    async def _add_trust_nodes(self, rep_alloc):
        async with self._lock:
            for n in self.new_trustnodes:
                self.trusted_nodes.add(n)

        cur = await self.elector.get_current()

        for n in self.new_trustnodes:
            cm: CommunicationsManager = CommunicationsManager.get_instance()
            m = cm.create_message(
                "info",
                "trust_info",
                trusted=list(self.trusted_nodes),
                represented=rep_alloc.get(n, []),
                current=cur,
                round_num=self.round
            )
            await cm.send_message(n, m)

        em: EventManager = EventManager.get_instance()
        await em.publish_node_event(TrustNodeAddedEvent(set(self.trusted_nodes)))

    ## MSG CALLBACKS ##
    async def _add_trust_node_callback(self, source, message):
        if source not in self.trusted_nodes:
            return

        async with self._lock:
            self.new_trustnodes.extend(message.node_addr)
            self.rep_allocations[source] = message.rep_addr

        await self._reputation_updated()

    ## PROMOTION ##
    async def update_represented(self, source, message):
        async with self._lock:
            self.trust_info_amount += 1
            self.trusted_nodes.update(message.trusted)
            self.represented_nodes.update(message.represented)

        # wait until all trustworthy nodes have updated the new node
        # len(self.trusted_nodes) - 1, since trusted_nodes include this node
        if len(self.trusted_nodes) - 1 == self.trust_info_amount:
            await EventManager.get_instance().publish_node_event(
                PromotionEvent(self.represented_nodes, self.trusted_nodes, message.round_num))
            # start election
            await self._start_election()
