import tidemill.metrics.trials.tables as _tables  # noqa: F401  # register metric tables
from tidemill.metrics.trials.cubes import TrialEventCube
from tidemill.metrics.trials.metric import TrialsMetric

__all__ = ["TrialEventCube", "TrialsMetric"]
