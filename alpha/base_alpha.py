# alpha/base_alpha.py
"""Abstract base class for all alpha signal generators."""
from __future__ import annotations
from abc import ABC, abstractmethod
from alpha.signal import AlphaSignal


class BaseAlpha(ABC):
    """
    All alpha strategies implement this interface.
    Each strategy produces AlphaSignal objects with a consistent schema.
    """
    name: str = "base"

    @abstractmethod
    def to_alpha_signal(self, *args, **kwargs) -> AlphaSignal | None:
        """
        Convert strategy-specific input to a unified AlphaSignal.
        Returns None if the input does not produce a tradeable signal.
        """
        ...
