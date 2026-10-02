"""Strict helpers for turning parsed TOML tables into typed values.

Plan notes "02 - Technical Architecture" (data loading: fail fast, name the file and key) and
decision D-009 (no pydantic; unknown keys are errors, which catches typos like ``kgb``).
"""

from collections.abc import Iterable, Mapping
from typing import Any


class DataError(ValueError):
    """A data file is malformed. The message names the file and the offending key."""


class TableReader:
    """Reads keys from one TOML table and reports mistakes with the file and table name.

    Create it with every key the table may contain; unknown keys raise immediately.
    """

    def __init__(
        self,
        table: object,
        *,
        source: str,
        where: str,
        allowed: Iterable[str],
    ) -> None:
        self.source = source
        self.where = where
        if not isinstance(table, Mapping):
            raise self.error("must be a table")
        self.table: Mapping[str, Any] = table
        allowed_keys = set(allowed)
        unknown = sorted(key for key in self.table if key not in allowed_keys)
        if unknown:
            raise self.error(
                f"unknown key(s) {', '.join(map(repr, unknown))}; "
                f"allowed: {', '.join(sorted(allowed_keys))}"
            )

    def error(self, message: str, key: str | None = None) -> DataError:
        """Build a :class:`DataError` naming the file, the table and optionally the key."""
        location = self.where if key is None else f"{self.where}{'.' if self.where else ''}{key}"
        prefix = f"{self.source}: {location}: " if location else f"{self.source}: "
        return DataError(prefix + message)

    def has(self, key: str) -> bool:
        """Return whether the table defines ``key``."""
        return key in self.table

    def raw(self, key: str) -> Any:
        """Return a required value without type checking."""
        if key not in self.table:
            raise self.error("missing required key", key)
        return self.table[key]

    def string(self, key: str) -> str:
        """Return a required non-empty string."""
        value = self.raw(key)
        if not isinstance(value, str) or not value:
            raise self.error(f"must be a non-empty string, got {value!r}", key)
        return value

    def optional_string(self, key: str) -> str | None:
        """Return a non-empty string, or ``None`` if the key is absent."""
        return self.string(key) if self.has(key) else None

    def number(self, key: str, default: float | None = None) -> float:
        """Return a number (int or float, never bool) as a float."""
        if key not in self.table and default is not None:
            return default
        value = self.raw(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise self.error(f"must be a number, got {value!r}", key)
        return float(value)

    def integer(self, key: str) -> int:
        """Return a required whole number."""
        value = self.number(key)
        if not value.is_integer():
            raise self.error(f"must be a whole number, got {value!r}", key)
        return int(value)

    def subtable(self, key: str, allowed: Iterable[str]) -> "TableReader":
        """Return a reader for a required sub-table, with its own set of allowed keys."""
        where = f"{self.where}.{key}" if self.where else key
        return TableReader(self.raw(key), source=self.source, where=where, allowed=allowed)

    def boolean(self, key: str, default: bool) -> bool:
        """Return a boolean, or ``default`` if the key is absent."""
        if key not in self.table:
            return default
        value = self.table[key]
        if not isinstance(value, bool):
            raise self.error(f"must be true or false, got {value!r}", key)
        return value

    def numbers(self, key: str, count: int) -> tuple[float, ...]:
        """Return a required array of exactly ``count`` numbers."""
        value = self.raw(key)
        if (
            not isinstance(value, list)
            or len(value) != count
            or any(isinstance(item, bool) or not isinstance(item, int | float) for item in value)
        ):
            raise self.error(f"must be an array of {count} numbers, got {value!r}", key)
        return tuple(float(item) for item in value)

    def integers(self, key: str, count: int) -> tuple[int, ...]:
        """Return a required array of exactly ``count`` whole numbers."""
        values = self.numbers(key, count)
        if any(not item.is_integer() for item in values):
            raise self.error(f"must be whole numbers, got {list(values)!r}", key)
        return tuple(int(item) for item in values)

    def tables(self, key: str) -> list[Any]:
        """Return an optional array of tables (``[[key]]``), empty if absent."""
        if key not in self.table:
            return []
        value = self.table[key]
        if not isinstance(value, list):
            raise self.error("must be an array of tables", key)
        return value
