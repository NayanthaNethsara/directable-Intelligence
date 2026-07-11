from abc import ABC, abstractmethod

from ..schema import ControllerRequest


class Brain(ABC):
    name: str = "base"

    @abstractmethod
    def decide(self, req: ControllerRequest) -> str:
        """Return the decision as a RAW JSON STRING."""
        ...
