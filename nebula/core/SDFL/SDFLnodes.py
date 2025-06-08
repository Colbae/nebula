from nebula.config.config import Config
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

    @property
    def leader(self):
        return self._leader

    def elect_leader(self):
        self._leader = self.elector.elect()
        for n in self.represented_nodes:
            self.__notify_node(n)
        return self.leader

    def update_reputation(self, node):
        self.reputator.update_reputation(self, node)
        if self.reputator.is_trustworthy(node):
            self.add_trustworthy_node(node)

    def add_trustworthy_node(self, new_node):
        for n in self.trusted_nodes:
            self.__notify_peers(n, new_node)
        self.trusted_nodes.append(new_node)

    def send_model(self, addr):
        pass

    def __notify_peers(self, peer, new_node):
        pass

    def __notify_node(self, node):
        pass


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

    def send_model(self, addr):
        pass

    def __validate_addr(self, addr):
        pass
