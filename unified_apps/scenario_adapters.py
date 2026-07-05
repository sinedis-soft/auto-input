"""Compatibility facade for integrated scenario adapters.

The implementation is split into focused modules under
``scenario_adapters_parts`` so each adapter can be read and maintained separately,
while existing imports from ``scenario_adapters`` continue to work.
"""

from __future__ import annotations

if __package__:
    from .scenario_adapters_parts import (
        ASKO_INSURED_LEGAL_FIELDS,
        AskoIntegratedAdapter,
        BaseScenarioAdapter,
        DataCallback,
        LogCallback,
        StateCallback,
        WartaIntegratedAdapter,
        build_adapter,
    )
else:
    from scenario_adapters_parts import (
        ASKO_INSURED_LEGAL_FIELDS,
        AskoIntegratedAdapter,
        BaseScenarioAdapter,
        DataCallback,
        LogCallback,
        StateCallback,
        WartaIntegratedAdapter,
        build_adapter,
    )

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
