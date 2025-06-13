import logging

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import ElectionEvent, ReputationEvent, ValidationEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.noderole import AggregatorNode
from nebula.core.SDFL.elector import Elector, create_elector, get_elector_string
from nebula.core.SDFL.reputator import Reputator, create_reputator, get_reputator_string
from nebula.core.SDFL.validator import Validator, create_validator, get_validator_string
from nebula.core.training.lightning import Lightning


class TrustNode:
    def __init__(
        self,
        represented_nodes,
        trusted_nodes,
        elector: Elector,
        validator: Validator,
        reputator: Reputator,
    ):
        self.represented_nodes = set(represented_nodes)
        self.trusted_nodes = set(trusted_nodes)
        self.elector = elector
        self.validator = validator
        self.reputator = reputator
        self._leader = None

        self._initiate_callbacks()

    def _initiate_callbacks(self):
        em: EventManager = EventManager.get_instance()
        # Initiate election callback
        em.subscribe_node_event(ElectionEvent, self._elect_leader)
        # Initiate reputation callback
        em.subscribe_node_event(ReputationEvent, self._update_reputation)
        # Initiate validation callback
        em.subscribe_node_event(ValidationEvent, self._validate_model)
        # Initiate adding trust node callback
        em.subscribe(("addTrustworthy", ""), self._add_trust_node)

    @property
    def leader(self):
        return self._leader

    def _elect_leader(self, ee: ElectionEvent):
        cm: CommunicationsManager = CommunicationsManager.get_instance()

        self._leader = self.elector.elect()
        m = cm.create_message("leader", "", leader=self.leader)
        for n in self.represented_nodes:
            cm.send_message(n, m)
        return self.leader

    def _update_reputation(self, re: ReputationEvent):
        self.reputator.update_reputation(re)
        if self.reputator.is_trustworthy(re):
            cm: CommunicationsManager = CommunicationsManager.get_instance()
            m = cm.create_message("addTrustworthy", "", node_addr=re)
            for n in self.trusted_nodes:
                cm.send_message(n, m)
            self.trusted_nodes.add(re)

    def _validate_model(self, ve: ValidationEvent):
        if not self.validator.validate(ve):
            logging.info("Validation failed")

    def _send_msg_to_trusted(self, message_type: str, action: str = "", *args, **kwargs):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type, action, args, kwargs)
        for n in self.trusted_nodes:
            cm.send_message(n, m)

    def _update_represented(self, new_rep):
        cm: CommunicationsManager = CommunicationsManager.get_instance()

        # TODO: decide what rep nodes are to be changed
        r = self.represented_nodes[:1]

        for n in r:
            m = cm.create_message("representative", "", node_addr=new_rep)
            cm.send_message(n, m)
        return r

    def _add_trust_node(self, source, message):
        if source not in self.trusted_nodes:
            return

        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(
            "trustInfo",
            "",
            validator=get_validator_string(type[self.validator]),
            reputator=get_reputator_string(type[self.reputator]),
            elector=get_elector_string(type[self.elector]),
            trusted=list(self.trusted_nodes),
            represened=self._update_represented(message.node_addr),
        )
        cm.send_message(source, m)
        self.trusted_nodes.add(message.node_addr)


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

    def initialize_callbacks(self):
        em: EventManager = EventManager.get_instance()
        # subscribe to promotion events
        em.subscribe(("trustInfo", ""), self._promote_node)
        # subscribe to representative updates
        em.subscribe(("representative", ""), self._update_representative)

    def _update_representative(self, source, message):
        if source == self.representative and self.trust_node is None:
            self.representative = message.node_addr

    def _promote_node(self, source, message):
        if not self._trust_node:
            r = create_reputator(message.reputator)
            e = create_elector(message.elector)
            v = create_validator(message.validator)
            self._trust_node = TrustNode(
                represented_nodes=message.represented,
                trusted_nodes=message.trusted,
                elector=e,
                validator=v,
                reputator=r,
            )
            self.representative = None
        else:
            self._trust_node.represented_nodes.update(message.represented)
