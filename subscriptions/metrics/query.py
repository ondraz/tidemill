"""Cubes and query fragment algebra.

This module implements the hybrid approach: semantic models declare what's
queryable (joins, measures, dimensions), and immutable QueryFragment objects
compose via ``+`` to build queries declaratively.  ``compile()`` turns a
composed fragment into a SQLAlchemy ``Select`` statement.

See docs/architecture/cubes.md for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, bindparam, func, literal_column, select, text
from sqlalchemy import table as sa_table

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnClause, ColumnElement, Label

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
    column: str
    op: str
    value: Any
    param_name: str


@dataclass(frozen=True)
class TimeGrainExpr:
    column: str
    granularity: str


# ── QueryFragment ────────────────────────────────────────────────────────


_OP_SUFFIX = {
    "=": "eq",
    "!=": "ne",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "in": "in",
    "between": "btwn",
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

    def __add__(self, other: QueryFragment) -> QueryFragment:
        if not isinstance(other, QueryFragment):
            return NotImplemented
        return QueryFragment(
            source=self.source or other.source,
            alias=self.alias or other.alias,
            measures=self.measures + other.measures,
            dimensions=self.dimensions + other.dimensions,
            filters=self.filters + other.filters,
            joins=self.joins | other.joins,
            time_grain=self.time_grain or other.time_grain,
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
        if self.joins and model is None:
            raise ValueError("Fragment references joins but no Cube was provided")

        source = self.source
        if source is None:
            msg = "Fragment has no source table"
            raise ValueError(msg)
        alias = self.alias or "t"
        stmt: Select[Any] = select().select_from(sa_table(source).alias(alias))
        params: dict[str, Any] = {}

        # 1. Resolve and add joins in dependency order
        if model and self.joins:
            stmt = _apply_joins(stmt, self.joins, model)

        # 2. Time grain (before dimensions so period comes first in SELECT)
        if self.time_grain:
            tg = self.time_grain
            trunc: Label[Any] = func.date_trunc(
                literal_column(f"'{tg.granularity}'"),
                literal_column(tg.column),
            ).label("period")
            stmt = stmt.add_columns(trunc).group_by(trunc)

        # 3. Dimensions — SELECT + GROUP BY
        for d in self.dimensions:
            col_expr: ColumnClause[Any] = literal_column(d.column)
            stmt = stmt.add_columns(col_expr.label(d.label))
            stmt = stmt.group_by(col_expr)

        # 4. Measures — aggregate expressions
        for m in self.measures:
            stmt = stmt.add_columns(_agg_expr(m))

        # 5. Filters — WHERE clauses with bind params
        for f in self.filters:
            clause, f_params = _filter_clause(f)
            stmt = stmt.where(clause)
            params.update(f_params)

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


def _filter_clause(f: FilterExpr) -> tuple[ColumnElement[Any], dict[str, Any]]:
    """Build a WHERE clause element and bind params from a FilterExpr."""
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
            clause = col < bindparam(f.param_name)
            params[f.param_name] = f.value
        case "<=":
            clause = col <= bindparam(f.param_name)
            params[f.param_name] = f.value
        case "in":
            clause = col.in_(bindparam(f.param_name, expanding=True))
            params[f.param_name] = list(f.value)
        case "between":
            sp, ep = f"{f.param_name}_start", f"{f.param_name}_end"
            clause = col.between(bindparam(sp), bindparam(ep))
            params[sp] = f.value[0]
            params[ep] = f.value[1]
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
