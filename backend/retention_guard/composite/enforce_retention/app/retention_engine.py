"""The retention engine: connects live to an external business's database,
reflects its schema, whitelists columns against what's been classified, and
runs the parameterized dry-run SELECT / enforce UPDATE-DELETE.

Deliberately framework-free (no Flask/requests here, no calls to other
services) so it can be unit tested directly against a real
sqlite:///:memory: engine — SQLAlchemy Core behaves identically against
SQLite for reflection/query-building purposes, so this is genuine executed-
query coverage, not mocked assertions. See
testing/composite/enforce_retention/test_retention_engine.py. All I/O with
other retention_guard services (fetching a decrypted DSN, classified
columns, forwarding auth) is handled by routes.py and passed in here as
plain data.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, MetaData, Table, select, update, delete
from sqlalchemy.exc import NoSuchTableError

DEFAULT_BATCH_LIMIT = 500


class ClassificationError(Exception):
    """Raised when a table doesn't exist on the live source, or a classified
    column no longer matches the live schema, or a required role is missing.
    Always a hard scan failure — never silently skipped or partially applied
    (see plan's connector design note: whitelist checks fail closed)."""


class ReflectedSource:
    """One connect+reflect+whitelist pass against an external source's one
    table, for one policy's run. Table/column identifiers are never string-
    built into SQL — `Table(..., autoload_with=engine)` and dict-style
    `table.c[name]` lookups are the actual whitelist mechanism: only columns
    that are simultaneously (a) present in the classified_columns this was
    constructed with AND (b) present in live reflection ever end up
    referenced by a generated query."""

    def __init__(self, connection_string, table_name, classified_columns):
        self.engine = create_engine(connection_string)
        try:
            self.table = Table(table_name, MetaData(), autoload_with=self.engine)
        except NoSuchTableError as exc:
            raise ClassificationError(f"table {table_name!r} does not exist on this data source") from exc

        self.subject_col = None
        self.activity_col = None
        self.pii_cols = []
        for cc in classified_columns:
            try:
                col = self.table.c[cc["column_name"]]
            except KeyError as exc:
                raise ClassificationError(
                    f"classified column {cc['column_name']!r} no longer exists on table {table_name!r} "
                    "— it may have been renamed or dropped on the source since it was classified"
                ) from exc
            role = cc["column_role"]
            if role == "subject_id":
                self.subject_col = col
            elif role == "activity_timestamp":
                self.activity_col = col
            elif role == "pii":
                self.pii_cols.append(col)

        if self.subject_col is None or self.activity_col is None:
            raise ClassificationError(
                f"table {table_name!r} needs exactly one subject_id and one activity_timestamp "
                "classified column before it can be scanned"
            )

    def build_find_matches_stmt(self, inactive_days, batch_limit=DEFAULT_BATCH_LIMIT):
        """Split out from find_matches() so tests can inspect the compiled
        statement directly (bound params, referenced columns) without needing
        a live connection — see
        testing/composite/enforce_retention/test_retention_engine.py."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)
        return select(self.subject_col).where(self.activity_col < cutoff).limit(batch_limit)

    def find_matches(self, inactive_days, batch_limit=DEFAULT_BATCH_LIMIT):
        """Dry-run: subject values whose activity_timestamp is older than the
        cutoff. Read-only. The cutoff is a plain Python value compared
        against a Column — SQLAlchemy Core compiles that as a bound
        parameter, never as inlined SQL text, same as every value here."""
        stmt = self.build_find_matches_stmt(inactive_days, batch_limit)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [str(row[0]) for row in rows]

    def anonymise(self, subject_id_values):
        """Nulls every classified pii column for exactly the given subject
        ids. Deliberately does not re-evaluate activity_col < cutoff — see
        plan: enforcement acts on the operator-approved snapshot, not a
        re-query, so "approved N" and "applied N" are always the same set."""
        if not self.pii_cols or not subject_id_values:
            return 0
        stmt = update(self.table).where(self.subject_col.in_(subject_id_values)).values(
            {col: None for col in self.pii_cols}
        )
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
        return result.rowcount

    def delete_rows(self, subject_id_values):
        """Deletes exactly the given subject ids' rows — same approved-
        snapshot-only rule as anonymise()."""
        if not subject_id_values:
            return 0
        stmt = delete(self.table).where(self.subject_col.in_(subject_id_values))
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
        return result.rowcount
