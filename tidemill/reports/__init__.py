"""Analytical reports for Tidemill subscription data.

Three function types per submodule:

- **Data** (``waterfall``, ``breakdown``, ...) --- fetch and return
  DataFrames/dicts.  Only convert cents to dollars.  No printing or
  formatting.
- **Style** (``style_waterfall``, ...) --- take a DataFrame/dict and
  return a ``pd.io.formats.style.Styler`` for rich Jupyter display.
- **Plot** (``plot_waterfall``, ...) --- take a DataFrame/dict and return
  a ``plotly.graph_objects.Figure``.

Quick start::

    from tidemill.reports import setup, mrr
    from tidemill.reports.client import TidemillClient

    setup()
    tm = TidemillClient()

    df = mrr.waterfall(tm, "2025-09-01", "2026-04-30")  # data
    mrr.style_waterfall(df)                               # styled table
    mrr.plot_waterfall(df)                                # plotly chart
"""

from tidemill.reports import churn, ltv, mrr, retention, trials
from tidemill.reports._style import setup
from tidemill.reports.client import TidemillClient

__all__ = ["setup", "TidemillClient", "mrr", "churn", "retention", "ltv", "trials"]
