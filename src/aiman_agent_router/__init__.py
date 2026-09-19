"""AIMAN Agent Router."""

from .models import TaskEnvelope, RoutingDecision, ExecutionPlan
from .registry import CapabilityRegistry, load_default_registry
from .router import AgentRouter

__all__ = [
    "TaskEnvelope",
    "RoutingDecision",
    "ExecutionPlan",
    "CapabilityRegistry",
    "load_default_registry",
    "AgentRouter",
]

__version__ = "0.1.0"
