from abc import ABC, abstractmethod

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import ElectionEvent, LeaderElectedEvent


class InvalidElectorError(ValueError):
    def __init__(self, e_type: str):
        super().__init__(f"Invalid reputator type: '{e_type}'")


async def publish_election_event(leader, source, round_num):
    em: EventManager = EventManager.get_instance()
    le = LeaderElectedEvent(leader, source, round_num)
    await em.publish_node_event(le)


class Elector(ABC):
    """
    Abstract base class for electing a leader from a set of trustworthy nodes.

    The `Elector` class is responsible for electing a leader among nodes that are
    considered trustworthy. Subclasses should implement the logic for determining the leader.

    The leader's address is expected to be consistent across all trustworthy nodes.
    This consistency ensures that all trustworthy nodes agree on whom the leader is.
    """

    @abstractmethod
    async def elect(self, ee: ElectionEvent, rep: set[str]):
        """
        Elects a leader for the aggregation.
        Args:
            ee: ElectionEvent object
            rep: list of represented nodes
        Returns: Address of the leader.
        """
        pass

    @abstractmethod
    async def subscribe_to_events(self):
        """
        Subscribes to relevant events
        """
        pass


def create_elector(config: Config, trusted=None):
    from nebula.core.SDFL.Electors.RoundRobinElector import RoundRobinElector

    e_type = config.participant["sdfl_args"]["elector"]
    match e_type:
        case "RoundRobinElector":
            return RoundRobinElector(config, trusted)
    raise InvalidElectorError(e_type)


def get_elector_string(rep: type[Elector]) -> str:
    return rep.__name__
