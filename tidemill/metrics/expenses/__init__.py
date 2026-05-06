"""Expenses metric — aggregates bill + expense (purchase) lines.

Queries the platform-neutral expense schema so any ``ExpenseConnector``
(QuickBooks, Xero, FreshBooks, Wave, Sage) feeds the same numbers.
"""

from tidemill.metrics.expenses.metric import ExpensesMetric

__all__ = ["ExpensesMetric"]
