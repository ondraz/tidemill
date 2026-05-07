"""QuickBooks Online connector — expense data source.

Tidemill's first expense-side connector. Maps QBO Vendor/Account/Bill/Purchase/
BillPayment entities into the platform-neutral expense schema. Designed to be
the reference implementation that Xero, FreshBooks, Wave, and Sage connectors
follow — each only needs to subclass ``ExpenseConnector`` and provide the four
normalize/extract methods plus its own auth flow.
"""

from tidemill.connectors.quickbooks.connector import QuickBooksConnector

__all__ = ["QuickBooksConnector"]
