import logging

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import ElectionEvent, ReputationEvent, ValidationEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.noderole import AggregatorNode
from nebula.core.SDFL.elector import Elector
from nebula.core.SDFL.reputator import Reputator
from nebula.core.SDFL.validator import Validator
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
        self.represented_nodes = represented_nodes
        self.trusted_nodes = trusted_nodes
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
            self._add_trustworthy_node(re)

    def _add_trustworthy_node(self, new_node):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message("addTrustworthy", "", node_addr=new_node)
        for n in self.trusted_nodes:
            cm.send_message(n, m)
        self.trusted_nodes.append(new_node)

    def _validate_model(self, ve: ValidationEvent):
        if not self.validator.validate(ve):
            logging.info("Validation failed")

    def _send_msg_to_trusted(self, message_type: str, action: str = "", *args, **kwargs):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type, action, args, kwargs)
        for n in self.trusted_nodes:
            cm.send_message(n, m)


class FollowerNode(AggregatorNode):
    def __init__(
        self,
        model,
        datamodule,
        representative,
        config=Config,
        trainer=Lightning,
        security=False,
    ):
        self.representative = representative
        self._trust_node = None
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

    def promote_node(self, trust_node: TrustNode):
        self._trust_node = trust_node
