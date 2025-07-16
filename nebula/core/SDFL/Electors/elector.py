from abc import ABC, abstractmethod

from nebula.config.config import Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import LeaderElectedEvent


class InvalidElectorError(ValueError):
    def __init__(self, e_type: str):
        super().__init__(f"Invalid reputator type: '{e_type}'")


async def publish_election_event(leader, source, round_num, election_num):
    em: EventManager = EventManager.get_instance()
    le = LeaderElectedEvent(leader, source, round_num, election_num)
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
    async def elect(self, round_num: int, election_num: int, rep: set[str]):
        """
        Elects a leader for the aggregation.
        Args:
            round_num: Number of current round
            election_num: Number of current election
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

    @abstractmethod
    async def get_current(self):
        pass


def create_elector(config: Config, trusted=None, current=0):
    from nebula.core.SDFL.Electors.RoundRobinElector import RoundRobinElector

    e_type: str = config.participant["sdfl_args"]["elector"]
    e_type = e_type.lower()
    match e_type:
        case "roundrobinelector":
            return RoundRobinElector(config, trusted, current)
    raise InvalidElectorError(e_type)


def get_elector_string(rep: type[Elector]) -> str:
    return rep.__name__
