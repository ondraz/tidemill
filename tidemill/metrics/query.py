"""Cubes and query fragment algebra.

This module implements the hybrid approach: semantic models declare what's
queryable (joins, measures, dimensions), and immutable QueryFragment objects
compose via ``+`` to build queries declaratively.  ``compile()`` turns a
composed fragment into a SQLAlchemy ``Select`` statement.

See docs/architecture/cubes.md for the full design rationale.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import sqlparse
from sqlalchemy import (
    Select,
    String,
    and_,
    bindparam,
    func,
    literal_column,
    or_,
    select,
    text,
    true,
    values,
)
from sqlalchemy import (
    column as sa_column,
)
from sqlalchemy import table as sa_table

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnClause, ColumnElement, Label

logger = logging.getLogger(__name__)


def _day_start(v: Any) -> Any:
    """Coerce a naked ``date`` to its 00:00:00 ``datetime``.

    Tidemill's public convention is that date ranges are closed-closed:
    ``[start, end]`` includes every timestamp from ``start T00:00:00.000``
    through ``end T23:59:59.999999``. When callers pass a ``date`` for a
    timestamp column, we pin it to the start of that day.
    """
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime.combine(v, time.min)
    return v


def _day_end(v: Any) -> Any:
    """Coerce a naked ``date`` to its 23:59:59.999999 ``datetime``.

    Mirrors :func:`_day_start` for the closing boundary so BETWEEN is
    truly inclusive of the last calendar day.
    """
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime.combine(v, time.max)
    return v


# ── ANSI helpers for SQL log coloring ──────────────────────────────────────

_GREY = "\033[90m"
_RESET = "\033[0m"


@lru_cache(maxsize=1)
def _use_colors() -> bool:
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


# ── Definition types (used inside Cube declarations) ────────────


@dataclass(frozen=True)
class JoinDef:
    table: str
    alias: str
    on: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class MeasureDef:
    agg: str
    column: str
    label: str


@dataclass(frozen=True)
class DimDef:
    column: str
    join: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class TimeDimDef:
    column: str
    label: str | None = None


# ── Constructors (the public DSL for model declarations) ─────────────────


def Join(
    table: str,
    *,
    alias: str,
    on: str,
    depends_on: list[str] | None = None,
) -> JoinDef:
    return JoinDef(
        table=table,
        alias=alias,
        on=on,
        depends_on=tuple(depends_on) if depends_on else (),
    )


def Sum(column: str, *, label: str | None = None) -> MeasureDef:
    return MeasureDef("sum", column, label or column.rsplit(".", 1)[-1])


def CountDistinct(column: str, *, label: str | None = None) -> MeasureDef:
    return MeasureDef("count_distinct", column, label or column.rsplit(".", 1)[-1])


def Count(column: str = "*", *, label: str | None = None) -> MeasureDef:
    return MeasureDef("count", column, label or "count")


def Avg(column: str, *, label: str | None = None) -> MeasureDef:
    return MeasureDef("avg", column, label or column.rsplit(".", 1)[-1])


def Dim(column: str, *, join: str | None = None, label: str | None = None) -> DimDef:
    return DimDef(
        column=column,
        join=join,
        label=label or column.rsplit(".", 1)[-1],
    )


def TimeDim(column: str, *, label: str | None = None) -> TimeDimDef:
    return TimeDimDef(column=column, label=label or column.rsplit(".", 1)[-1])


# ── Fragment expression types (internal, carried by QueryFragment) ───────


@dataclass(frozen=True)
class MeasureExpr:
    agg: str
    column: str
    label: str


@dataclass(frozen=True)
class DimExpr:
    column: str
    label: str


@dataclass(frozen=True)
class FilterExpr:
    """A single WHERE clause element, or a compound of clauses.

    When ``kind == "simple"`` (default), ``column``/``op``/``value``/
    ``param_name`` describe one predicate.  When ``kind`` is ``"and"`` or
    ``"or"``, ``children`` is a non-empty tuple of sub-filters and the
    scalar fields are unused.  This keeps the compilation path uniform —
    see :func:`_filter_clause`.
    """

    column: str
    op: str
    value: Any
    param_name: str
    kind: str = "simple"
    children: tuple[FilterExpr, ...] = ()


@dataclass(frozen=True)
class TimeGrainExpr:
    column: str
    granularity: str


@dataclass(frozen=True)
class DynamicJoinExpr:
    """A join produced at query-compose time (not declared on the Cube).

    The primary use is attribute-table joins produced by :meth:`Cube.attribute`.
    Each filter against an attribute key declares a LEFT JOIN to
    ``customer_attribute`` aliased by attribute key; the LEFT JOIN is essential
    so ``is_empty``-style predicates see NULL for customers that have no row
    for the key (rather than being filtered out by the join itself).

    ``depends_on`` lists *static* join names (from the Cube's ``Joins`` class)
    that must be present for the ``on`` clause to resolve — for example an
    attribute join typically depends on the ``customer`` join because it
    joins to ``c.id``.
    """

    alias: str
    table: str
    on: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompareBranch:
    """One segment in a compare-mode query.

    ``filter_fragment`` carries the filters (and any dynamic_joins introduced
    by attribute conditions) for this branch.  Its measures/dimensions are
    ignored — only filters contribute to the compound compare predicate.
    """

    segment_id: str
    filter_fragment: QueryFragment


# ── QueryFragment ────────────────────────────────────────────────────────


_OP_SUFFIX = {
    "=": "eq",
    "!=": "ne",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "in": "in",
    "not in": "nin",
    "between": "btwn",
    "contains": "ct",
    "not_contains": "nct",
    "starts_with": "sw",
    "ends_with": "ew",
    "is_empty": "null",
    "is_not_empty": "nnull",
}


@dataclass(frozen=True)
class QueryFragment:
    """Immutable query fragment.  Fragments compose via ``+`` (commutative monoid)."""

    source: str | None = None
    alias: str | None = None
    measures: tuple[MeasureExpr, ...] = ()
    dimensions: tuple[DimExpr, ...] = ()
    filters: tuple[FilterExpr, ...] = ()
    joins: frozenset[str] = frozenset()
    time_grain: TimeGrainExpr | None = None
    # Joins produced at compose time (e.g. attribute EAV joins).  Deduped by
    # alias across composition so two filters on the same attribute key share
    # one join.
    dynamic_joins: tuple[DynamicJoinExpr, ...] = ()
    # Compare-mode branches.  When non-empty, compile() emits a CROSS JOIN on
    # a VALUES set of segment IDs and a compound OR predicate that tags each
    # row with the segments it satisfies.
    compare: tuple[CompareBranch, ...] = ()

    def __add__(self, other: QueryFragment) -> QueryFragment:
        if not isinstance(other, QueryFragment):
            return NotImplemented
        # Merge dynamic_joins by alias — two filters on the same attribute key
        # share one EAV join rather than joining twice.
        merged_dynamic: dict[str, DynamicJoinExpr] = {}
        for dj in self.dynamic_joins + other.dynamic_joins:
            merged_dynamic.setdefault(dj.alias, dj)
        return QueryFragment(
            source=self.source or other.source,
            alias=self.alias or other.alias,
            measures=self.measures + other.measures,
            dimensions=self.dimensions + other.dimensions,
            filters=self.filters + other.filters,
            joins=self.joins | other.joins,
            time_grain=self.time_grain or other.time_grain,
            dynamic_joins=tuple(merged_dynamic.values()),
            # Compare mode is set by exactly one fragment in a composition —
            # if both sides set it, later wins (caller's responsibility).
            compare=self.compare or other.compare,
        )

    # ── Compilation ──────────────────────────────────────────────────

    def compile(
        self,
        model: type[Cube] | None = None,
    ) -> tuple[Select[Any], dict[str, Any]]:
        """Compile into a SQLAlchemy ``Select`` and a bind-params dict.

        *model* is required when the fragment references joins.  It provides
        the join definitions needed to resolve table references.
        """
        # Static joins may come from compare branches too — union them in so
        # _apply_joins sees every name we need.
        needed_static: frozenset[str] = self.joins
        for branch in self.compare:
            needed_static = needed_static | branch.filter_fragment.joins

        if needed_static and model is None:
            raise ValueError("Fragment references joins but no Cube was provided")

        source = self.source
        if source is None:
            msg = "Fragment has no source table"
            raise ValueError(msg)
        alias = self.alias or "t"
        stmt: Select[Any] = select().select_from(sa_table(source).alias(alias))
        params: dict[str, Any] = {}

        # Dynamic joins (attribute EAV joins) — union across self + compare
        # branches, deduped by alias.  Dynamic joins always LEFT JOIN so
        # IS NULL / is_empty semantics remain correct for customers without
        # a row for a given attribute key.
        merged_dynamic: dict[str, DynamicJoinExpr] = {}
        for dj in self.dynamic_joins:
            merged_dynamic.setdefault(dj.alias, dj)
        for branch in self.compare:
            for dj in branch.filter_fragment.dynamic_joins:
                merged_dynamic.setdefault(dj.alias, dj)

        # Dynamic joins may depend on static joins (e.g. customer) — include
        # them in the static resolution set so they're added transitively.
        for dj in merged_dynamic.values():
            needed_static = needed_static | frozenset(dj.depends_on)

        # 1. Resolve and add static joins in dependency order
        if model and needed_static:
            stmt = _apply_joins(stmt, needed_static, model)

        # 2. Dynamic joins (LEFT JOIN customer_attribute ca_X ON ...)
        if merged_dynamic:
            stmt = _apply_dynamic_joins(stmt, merged_dynamic.values())

        # 3. Compare mode: CROSS JOIN a VALUES list of segment IDs and
        #    prepend seg.segment_id to the GROUP BY / SELECT.
        seg_col: Any = None
        if self.compare:
            seg_tbl = values(
                sa_column("segment_id", String),
                name="seg",
            ).data([(b.segment_id,) for b in self.compare])
            # CROSS JOIN is expressed as an inner join on true()
            stmt = stmt.join(seg_tbl, true())
            seg_col = seg_tbl.c.segment_id
            stmt = stmt.add_columns(seg_col.label("segment_id")).group_by(seg_col)

        # 4. Time grain (before dimensions so period comes first in SELECT).
        # ORDER BY period ASC so callers always receive series rows in
        # chronological order — every series-producing endpoint inherits this.
        if self.time_grain:
            tg = self.time_grain
            trunc: Label[Any] = func.date_trunc(
                literal_column(f"'{tg.granularity}'"),
                literal_column(tg.column),
            ).label("period")
            stmt = stmt.add_columns(trunc).group_by(trunc).order_by(trunc)

        # 5. Dimensions — SELECT + GROUP BY
        for d in self.dimensions:
            col_expr: ColumnClause[Any] = literal_column(d.column)
            stmt = stmt.add_columns(col_expr.label(d.label))
            stmt = stmt.group_by(col_expr)

        # 6. Measures — aggregate expressions
        for m in self.measures:
            stmt = stmt.add_columns(_agg_expr(m))

        # 7. Filters — WHERE clauses with bind params (non-compare filters
        #    AND together; compare predicate is a compound OR-of-ANDs).
        for f in self.filters:
            clause, f_params = _filter_clause(f)
            stmt = stmt.where(clause)
            params.update(f_params)

        # 8. Compare predicate: OR across branches, each branch tagged with
        #    seg.segment_id = <branch_id> AND the branch's filters.
        if self.compare and seg_col is not None:
            branch_preds = []
            for branch in self.compare:
                leg_clauses: list[Any] = [seg_col == branch.segment_id]
                for f in branch.filter_fragment.filters:
                    clause, f_params = _filter_clause(f)
                    leg_clauses.append(clause)
                    params.update(f_params)
                branch_preds.append(and_(*leg_clauses))
            stmt = stmt.where(or_(*branch_preds))

        if logger.isEnabledFor(logging.DEBUG):
            log_sql(stmt, params)

        return stmt, params

    def to_sql(
        self,
        model: type[Cube] | None = None,
    ) -> str:
        """Compile and return the SQL string (PostgreSQL dialect) for inspection."""
        stmt, params = self.compile(model)
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        sql = str(compiled)
        # Substitute params for readability
        for key, value in params.items():
            placeholder = f"%({key})s"
            if isinstance(value, str):
                sql = sql.replace(placeholder, f"'{value}'")
            elif isinstance(value, (list, tuple)):
                formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in value)
                sql = sql.replace(placeholder, formatted)
            else:
                sql = sql.replace(placeholder, str(value))
        return sql


def _caller_label(depth: int = 3) -> str:
    """Best-effort label from the call stack: ``ClassName.method_name``."""
    try:
        frame = sys._getframe(depth)
        self_obj = frame.f_locals.get("self")
        cls_name = type(self_obj).__name__ if self_obj else ""
        method = frame.f_code.co_name
        return f"{cls_name}.{method}" if cls_name else method
    except AttributeError, ValueError:
        return ""


def log_sql(
    stmt: Select[Any] | str,
    params: dict[str, Any] | None = None,
    *,
    label: str | None = None,
) -> None:
    """Log a prettified SQL statement at DEBUG level.

    Accepts a SQLAlchemy ``Select`` (compiled via the PostgreSQL dialect) or a
    raw SQL string.  Bind parameters are substituted inline for readability.

    *label* is shown as the query context (e.g. ``MrrMetric._current_mrr``).
    When omitted the caller is auto-detected from the stack.
    """
    if isinstance(stmt, str):
        raw = stmt
    else:
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        raw = str(compiled)

    if params:
        for key, value in params.items():
            placeholder = f"%({key})s"
            if isinstance(value, str):
                raw = raw.replace(placeholder, f"'{value}'")
            elif isinstance(value, (list, tuple)):
                formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in value)
                raw = raw.replace(placeholder, formatted)
            else:
                raw = raw.replace(placeholder, str(value))

    tag = label or _caller_label()
    # Collapse to a single line so the log record stays on one line — makes
    # trace/span correlation in Loki reliable (each stdout line is a separate
    # Loki entry). Structured fields (`sql`, `sql_label`) are attached via
    # `extra` for future structured-logging consumers.
    single_line = " ".join(sqlparse.format(raw, keyword_case="upper").split())
    display = f"{_GREY}{single_line}{_RESET}" if _use_colors() else single_line
    logger.debug(
        "[%s] SQL: %s",
        tag,
        display,
        extra={"sql": single_line, "sql_label": tag},
    )


def _apply_joins(
    stmt: Select[Any],
    needed: frozenset[str],
    model: type[Cube],
) -> Select[Any]:
    """Resolve joins in dependency order and add them to the statement."""
    added: set[str] = set()

    def add(name: str) -> None:
        if name in added:
            return
        jdef = model._joins[name]
        for dep in jdef.depends_on:
            add(dep)
        target = sa_table(jdef.table).alias(jdef.alias)
        nonlocal stmt
        stmt = stmt.join(target, text(jdef.on))
        added.add(name)

    for name in sorted(needed):
        add(name)
    return stmt


def _apply_dynamic_joins(
    stmt: Select[Any],
    dynamic_joins: Any,
) -> Select[Any]:
    """Apply each ``DynamicJoinExpr`` as a LEFT JOIN.

    LEFT JOIN is required so that ``is_empty`` / ``IS NULL`` predicates can
    distinguish "no row for this attribute key" from "row exists with NULL
    value": the dynamic alias's columns are NULL in the former case, which
    is the semantically correct answer for an absent attribute.
    """
    for dj in sorted(dynamic_joins, key=lambda d: d.alias):
        target = sa_table(dj.table).alias(dj.alias)
        stmt = stmt.outerjoin(target, text(dj.on))
    return stmt


def _agg_expr(m: MeasureExpr) -> Label[Any]:
    """Build a SQLAlchemy aggregate expression from a MeasureExpr."""
    col: ColumnElement[Any] = literal_column("*") if m.column == "*" else literal_column(m.column)

    match m.agg:
        case "sum":
            return func.sum(col).label(m.label)
        case "count_distinct":
            return func.count(func.distinct(col)).label(m.label)
        case "count":
            return func.count(col).label(m.label)
        case "avg":
            return func.avg(col).label(m.label)
        case other:
            raise ValueError(f"Unknown aggregation: {other}")


def _rename_params(f: FilterExpr, suffix: str) -> FilterExpr:
    """Return a copy of *f* with every bind-param name suffixed.

    Recurses into compound filters so nested AND/OR structures stay
    self-consistent after the rename.  Used by :meth:`Cube.or_group` to
    avoid collisions between legs that filter on the same column.
    """
    if f.kind in ("and", "or"):
        return FilterExpr(
            column="",
            op="=",
            value=None,
            param_name="",
            kind=f.kind,
            children=tuple(_rename_params(c, suffix) for c in f.children),
        )
    if not f.param_name:
        return f
    return FilterExpr(
        column=f.column,
        op=f.op,
        value=f.value,
        param_name=f"{f.param_name}_{suffix}",
        kind=f.kind,
        children=f.children,
    )


_LIKE_ESCAPE_CHARS = ("\\", "%", "_")


def _escape_like(value: Any) -> str:
    r"""Escape LIKE/ILIKE wildcards in a user-supplied string.

    Uses ``\\`` as the escape char (matched with ``ESCAPE '\\'`` in clauses).
    """
    s = str(value)
    for ch in _LIKE_ESCAPE_CHARS:
        s = s.replace(ch, f"\\{ch}")
    return s


def _filter_clause(f: FilterExpr) -> tuple[ColumnElement[Any], dict[str, Any]]:
    """Build a WHERE clause element and bind params from a FilterExpr.

    Supports simple predicates (``f.kind == "simple"``) and compound kinds
    (``"and"``, ``"or"``) that recurse over ``f.children``.  All variants
    produce bind-param-safe SQLAlchemy ``ColumnElement`` objects — no raw
    ``text()`` SQL beyond what static Cube join declarations already use.
    """
    # Compound filters — recursively build clauses and combine.
    if f.kind in ("and", "or"):
        clauses: list[ColumnElement[Any]] = []
        all_params: dict[str, Any] = {}
        for child in f.children:
            c, p = _filter_clause(child)
            clauses.append(c)
            all_params.update(p)
        combinator = and_ if f.kind == "and" else or_
        return combinator(*clauses), all_params

    col: ColumnClause[Any] = literal_column(f.column)
    params: dict[str, Any] = {}

    match f.op:
        case "=":
            clause = col == bindparam(f.param_name)
            params[f.param_name] = f.value
        case "!=":
            clause = col != bindparam(f.param_name)
            params[f.param_name] = f.value
        case ">":
            clause = col > bindparam(f.param_name)
            params[f.param_name] = f.value
        case ">=":
            clause = col >= bindparam(f.param_name)
            params[f.param_name] = f.value
        case "<":
            # Half-open upper bound — keep the raw value (a ``date`` at 00:00
            # semantically means "before this day", which is what callers want).
            clause = col < bindparam(f.param_name)
            params[f.param_name] = f.value
        case "<=":
            # Inclusive upper bound — pin a ``date`` to end-of-day.
            clause = col <= bindparam(f.param_name)
            params[f.param_name] = _day_end(f.value)
        case "in":
            clause = col.in_(bindparam(f.param_name, expanding=True))
            params[f.param_name] = list(f.value)
        case "not in":
            clause = ~col.in_(bindparam(f.param_name, expanding=True))
            params[f.param_name] = list(f.value)
        case "between":
            # Closed-closed: ``[start, end]`` inclusive on both ends.
            # Dates are coerced to day bounds so the last calendar day is
            # fully covered.
            sp, ep = f"{f.param_name}_start", f"{f.param_name}_end"
            clause = col.between(bindparam(sp), bindparam(ep))
            params[sp] = _day_start(f.value[0])
            params[ep] = _day_end(f.value[1])
        case "contains":
            clause = col.ilike(bindparam(f.param_name), escape="\\")
            params[f.param_name] = f"%{_escape_like(f.value)}%"
        case "not_contains":
            clause = ~col.ilike(bindparam(f.param_name), escape="\\")
            params[f.param_name] = f"%{_escape_like(f.value)}%"
        case "starts_with":
            clause = col.ilike(bindparam(f.param_name), escape="\\")
            params[f.param_name] = f"{_escape_like(f.value)}%"
        case "ends_with":
            clause = col.ilike(bindparam(f.param_name), escape="\\")
            params[f.param_name] = f"%{_escape_like(f.value)}"
        case "is_empty":
            clause = col.is_(None)
        case "is_not_empty":
            clause = col.is_not(None)
        case other:
            raise ValueError(f"Unknown filter operator: {other}")

    return clause, params


# ── Cube ────────────────────────────────────────────────────────


class _MeasuresAccessor:
    """Wraps a model's Measures class so attribute access returns QueryFragments."""

    def __init__(self, model_cls: type[Cube]) -> None:
        self._model = model_cls

    def __getattr__(self, name: str) -> QueryFragment:
        if name.startswith("_"):
            raise AttributeError(name)
        measures = self._model._measures
        if name not in measures:
            available = sorted(measures)
            raise AttributeError(
                f"No measure '{name}' in {self._model.__name__}. Available: {available}"
            )
        m = measures[name]
        return QueryFragment(
            source=self._model.__source__,
            alias=self._model.__alias__,
            measures=(MeasureExpr(m.agg, m.column, m.label),),
        )

    def __repr__(self) -> str:
        return f"<MeasuresAccessor({sorted(self._model._measures)})>"


class _CubeMeta(type):
    """Metaclass that collects Joins/Measures/Dimensions/TimeDimensions."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> _CubeMeta:
        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Cube":
            return cls

        # Collect join definitions
        joins_cls = namespace.get("Joins")
        joins: dict[str, JoinDef] = {}
        if joins_cls:
            for k, v in vars(joins_cls).items():
                if isinstance(v, JoinDef):
                    joins[k] = v
        cls._joins = joins  # type: ignore[attr-defined]

        # Collect measure definitions
        measures_cls = namespace.get("Measures")
        measures: dict[str, MeasureDef] = {}
        if measures_cls:
            for k, v in vars(measures_cls).items():
                if isinstance(v, MeasureDef):
                    measures[k] = v
        cls._measures = measures  # type: ignore[attr-defined]

        # Collect dimension definitions
        dims_cls = namespace.get("Dimensions")
        dimensions: dict[str, DimDef] = {}
        if dims_cls:
            for k, v in vars(dims_cls).items():
                if isinstance(v, DimDef):
                    dimensions[k] = v
        cls._dimensions = dimensions  # type: ignore[attr-defined]

        # Collect time dimension definitions
        time_cls = namespace.get("TimeDimensions")
        time_dimensions: dict[str, TimeDimDef] = {}
        if time_cls:
            for k, v in vars(time_cls).items():
                if isinstance(v, TimeDimDef):
                    time_dimensions[k] = v
        cls._time_dimensions = time_dimensions  # type: ignore[attr-defined]

        # Wrap measures for fragment-returning access
        cls.measures = _MeasuresAccessor(cls)  # type: ignore[attr-defined,arg-type]

        return cls


_ATTRIBUTE_VALUE_COLUMNS = {
    "string": "value_string",
    "number": "value_number",
    "boolean": "value_bool",
    "timestamp": "value_timestamp",
}


def _safe_key(key: str) -> str:
    """Sanitize an attribute key for use in a SQL alias / param name.

    Replaces anything outside ``[a-zA-Z0-9_]`` with ``_`` — segment keys are
    user-defined (CSV columns, Stripe metadata) so they can contain spaces,
    hyphens, dots.
    """
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in key)


class Cube(metaclass=_CubeMeta):
    """Base class for semantic model declarations.

    Subclass this and declare nested ``Joins``, ``Measures``, ``Dimensions``,
    and ``TimeDimensions`` classes.  The metaclass collects them and provides
    factory methods that return :class:`QueryFragment` instances.
    """

    __source__: str
    __alias__: str

    # These are populated by the metaclass on concrete subclasses.
    _joins: dict[str, JoinDef]
    _measures: dict[str, MeasureDef]
    _dimensions: dict[str, DimDef]
    _time_dimensions: dict[str, TimeDimDef]
    measures: _MeasuresAccessor

    # ── Factory methods ──────────────────────────────────────────────

    @classmethod
    def dimension(cls, name: str) -> QueryFragment:
        """Return a fragment that adds a GROUP BY dimension."""
        if name not in cls._dimensions:
            raise ValueError(
                f"Unknown dimension '{name}' in {cls.__name__}. "
                f"Available: {sorted(cls._dimensions)}"
            )
        d = cls._dimensions[name]
        joins = cls._resolve_join_deps(d.join) if d.join else frozenset()
        label = d.label or d.column.rsplit(".", 1)[-1]
        return QueryFragment(
            source=cls.__source__,
            alias=cls.__alias__,
            dimensions=(DimExpr(d.column, label),),
            joins=joins,
        )

    @classmethod
    def filter(cls, name: str, op: str, value: Any) -> QueryFragment:
        """Return a fragment that adds a WHERE clause on a named dimension."""
        if name in cls._dimensions:
            d = cls._dimensions[name]
            joins = cls._resolve_join_deps(d.join) if d.join else frozenset()
            param = name
            return QueryFragment(
                source=cls.__source__,
                alias=cls.__alias__,
                filters=(FilterExpr(d.column, op, value, param),),
                joins=joins,
            )
        if name in cls._time_dimensions:
            td = cls._time_dimensions[name]
            param = name
            return QueryFragment(
                source=cls.__source__,
                alias=cls.__alias__,
                filters=(FilterExpr(td.column, op, value, param),),
            )
        raise ValueError(
            f"Cannot filter on unknown dimension '{name}' in {cls.__name__}. "
            f"Available: {sorted(set(cls._dimensions) | set(cls._time_dimensions))}"
        )

    @classmethod
    def where(cls, column: str, op: str, value: Any) -> QueryFragment:
        """Return a fragment with a raw WHERE clause (not a named dimension)."""
        suffix = _OP_SUFFIX.get(op, op)
        param = f"{column.replace('.', '_')}_{suffix}"
        return QueryFragment(
            source=cls.__source__,
            alias=cls.__alias__,
            filters=(FilterExpr(column, op, value, param),),
        )

    @classmethod
    def attribute(
        cls,
        key: str,
        op: str,
        value: Any,
        *,
        attr_type: str = "string",
    ) -> QueryFragment:
        """Return a fragment that filters on a customer attribute (EAV).

        Adds a LEFT JOIN to ``customer_attribute`` aliased ``ca_<key>`` and a
        WHERE clause against the typed value column (``value_string``,
        ``value_number``, ``value_bool``, ``value_timestamp``).

        The join is recorded as a :class:`DynamicJoinExpr` with
        ``depends_on=("customer",)`` so the transitive customer join is
        pulled in automatically.  The alias is deterministic — two filters
        on the same key share one EAV join.

        Args:
            key: the attribute key (from ``attribute_definition.key``).
            op: comparison operator (see :func:`_filter_clause` for the full
                set — ``=``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``,
                ``not in``, ``between``, ``contains``, ``not_contains``,
                ``starts_with``, ``ends_with``, ``is_empty``,
                ``is_not_empty``).
            value: the comparison value (ignored for ``is_empty`` /
                ``is_not_empty``).
            attr_type: one of ``"string"``, ``"number"``, ``"boolean"``,
                ``"timestamp"``.  Determines which typed column the filter
                targets.  Callers that know the declared type (usually from
                ``attribute_definition``) should pass it; the default is
                ``"string"``.
        """
        if attr_type not in _ATTRIBUTE_VALUE_COLUMNS:
            raise ValueError(
                f"Unknown attribute type {attr_type!r}; expected one of "
                f"{sorted(_ATTRIBUTE_VALUE_COLUMNS)}"
            )
        value_col = _ATTRIBUTE_VALUE_COLUMNS[attr_type]
        safe = _safe_key(key)
        alias = f"ca_{safe}"
        # Embed the attribute key as an ANSI SQL string literal (single quotes
        # with embedded quotes doubled).  ON clauses in tidemill's Cube algebra
        # are passed to ``text()`` rather than a parameterized expression, so
        # we escape here — the key itself is a trusted identifier (ingested
        # via Stripe/API/CSV), not user input at query time.
        escaped_key = key.replace("'", "''")
        on = (
            f"{alias}.customer_id = c.id AND "
            f"{alias}.source_id = c.source_id AND "
            f"{alias}.key = '{escaped_key}'"
        )
        join = DynamicJoinExpr(
            alias=alias,
            table="customer_attribute",
            on=on,
            depends_on=("customer",),
        )
        param = f"attr_{safe}_{_OP_SUFFIX.get(op, 'op')}"
        return QueryFragment(
            source=cls.__source__,
            alias=cls.__alias__,
            filters=(FilterExpr(f"{alias}.{value_col}", op, value, param),),
            dynamic_joins=(join,),
        )

    @classmethod
    def or_group(cls, fragments: list[QueryFragment]) -> QueryFragment:
        """Combine fragments with OR — each fragment becomes one OR leg.

        Within a leg, the source fragment's filters are AND'd together
        (that's the default fragment-composition semantics); legs are
        combined with OR.  Static joins and dynamic joins from all legs are
        merged into the returned fragment so the join graph is complete.

        Param names in each leg's filters are suffixed with ``_orN`` to
        avoid bind-param collisions when two legs filter on the same
        column.
        """
        if not fragments:
            return QueryFragment()
        all_joins: frozenset[str] = frozenset()
        merged_dyn: dict[str, DynamicJoinExpr] = {}
        legs: list[FilterExpr] = []
        source = None
        alias = None

        for i, fr in enumerate(fragments):
            source = source or fr.source
            alias = alias or fr.alias
            all_joins = all_joins | fr.joins
            for dj in fr.dynamic_joins:
                merged_dyn.setdefault(dj.alias, dj)
            renamed = tuple(_rename_params(f, f"or{i}") for f in fr.filters)
            if len(renamed) == 0:
                continue
            if len(renamed) == 1:
                legs.append(renamed[0])
            else:
                # Multiple filters in one leg → AND them together.
                legs.append(FilterExpr("", "=", None, "", kind="and", children=renamed))

        if not legs:
            return QueryFragment(
                source=source or cls.__source__,
                alias=alias or cls.__alias__,
                joins=all_joins,
                dynamic_joins=tuple(merged_dyn.values()),
            )

        compound = FilterExpr("", "=", None, "", kind="or", children=tuple(legs))
        return QueryFragment(
            source=source or cls.__source__,
            alias=alias or cls.__alias__,
            filters=(compound,),
            joins=all_joins,
            dynamic_joins=tuple(merged_dyn.values()),
        )

    @classmethod
    def time_grain(cls, name: str, granularity: str) -> QueryFragment:
        """Return a fragment that adds DATE_TRUNC grouping."""
        if name not in cls._time_dimensions:
            raise ValueError(
                f"Unknown time dimension '{name}' in {cls.__name__}. "
                f"Available: {sorted(cls._time_dimensions)}"
            )
        td = cls._time_dimensions[name]
        return QueryFragment(
            source=cls.__source__,
            alias=cls.__alias__,
            time_grain=TimeGrainExpr(td.column, granularity),
        )

    @classmethod
    def apply_spec(cls, spec: Any) -> QueryFragment:
        """Translate a :class:`QuerySpec` into a composed fragment.

        Validates dimension/filter names against this model.
        """
        if spec is None:
            return QueryFragment()

        result = QueryFragment()

        for dim_name in spec.dimensions or []:
            result = result + cls.dimension(dim_name)

        for field_name, value in (spec.filters or {}).items():
            if isinstance(value, dict):
                op = next(iter(value))
                result = result + cls.filter(field_name, op, value[op])
            else:
                result = result + cls.filter(field_name, "=", value)

        if spec.granularity:
            time_dims = sorted(cls._time_dimensions)
            if time_dims:
                result = result + cls.time_grain(time_dims[0], spec.granularity)

        return result

    # ── Introspection ────────────────────────────────────────────────

    @classmethod
    def available_dimensions(cls) -> list[str]:
        return sorted(cls._dimensions)

    @classmethod
    def available_measures(cls) -> list[str]:
        return sorted(cls._measures)

    @classmethod
    def available_time_dimensions(cls) -> list[str]:
        return sorted(cls._time_dimensions)

    # ── Internal ─────────────────────────────────────────────────────

    @classmethod
    def _resolve_join_deps(cls, join_name: str) -> frozenset[str]:
        result: set[str] = {join_name}
        jdef = cls._joins.get(join_name)
        if jdef:
            for dep in jdef.depends_on:
                result |= cls._resolve_join_deps(dep)
        return frozenset(result)
