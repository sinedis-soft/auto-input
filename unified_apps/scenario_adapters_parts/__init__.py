"""Logical modules for unified scenario adapters."""

from .asko import ASKO_INSURED_LEGAL_FIELDS, AskoIntegratedAdapter
from .base import BaseScenarioAdapter, DataCallback, LogCallback, StateCallback
from .factory import build_adapter
from .warta import WartaIntegratedAdapter

__all__ = [
    "ASKO_INSURED_LEGAL_FIELDS",
    "AskoIntegratedAdapter",
    "BaseScenarioAdapter",
    "DataCallback",
    "LogCallback",
    "StateCallback",
    "WartaIntegratedAdapter",
    "build_adapter",
]
