import subscriptions.metrics.churn.metric as _churn  # noqa: F401

# Import concrete metrics so @register decorators execute.
import subscriptions.metrics.mrr.metric as _mrr  # noqa: F401
import subscriptions.metrics.retention.metric as _retention  # noqa: F401
from subscriptions.metrics.base import Metric, QuerySpec
from subscriptions.metrics.registry import discover_metrics, register, resolve_dependencies

__all__ = [
    "Metric",
    "QuerySpec",
    "discover_metrics",
    "register",
    "resolve_dependencies",
]
