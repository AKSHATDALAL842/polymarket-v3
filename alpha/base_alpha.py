from __future__ import annotations
from abc import ABC, abstractmethod
from alpha.signal import AlphaSignal


class BaseAlpha(ABC):
    name: str = "base"

    @abstractmethod
    def to_alpha_signal(self, *args, **kwargs) -> AlphaSignal | None:
        ...
