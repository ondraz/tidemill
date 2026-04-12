"""Authentication, dashboard, and chart table definitions.

These tables extend the shared ``metadata`` from :mod:`tidemill.models` so that
``metadata.create_all`` picks them up automatically at startup.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from tidemill.models import metadata

# ── Authentication ──────────────────────────────────────────────────────
# Clerk manages users externally.  We store a local row keyed by Clerk user
# ID so that dashboards, charts, and API keys can reference an owner.

app_user = Table(
    "app_user",
    metadata,
    Column("id", Text, primary_key=True),  # Clerk user_id (e.g. "user_2x...")
    Column("email", Text),
    Column("name", Text),
    Column("avatar_url", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True)),
)

api_key = Table(
    "api_key",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("key_hash", Text, nullable=False, unique=True),
    Column("key_prefix", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

# ── Dashboards & Charts ────────────────────────────────────────────────

dashboard = Table(
    "dashboard",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

dashboard_section = Table(
    "dashboard_section",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "dashboard_id",
        Text,
        ForeignKey("dashboard.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", Text, nullable=False),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

saved_chart = Table(
    "saved_chart",
    metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("config", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

dashboard_chart = Table(
    "dashboard_chart",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "dashboard_id",
        Text,
        ForeignKey("dashboard.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "section_id",
        Text,
        ForeignKey("dashboard_section.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "saved_chart_id",
        Text,
        ForeignKey("saved_chart.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("position", Integer, nullable=False, server_default="0"),
    UniqueConstraint("dashboard_id", "saved_chart_id", name="uq_dashboard_chart"),
)
