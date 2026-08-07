"""Unit tests for the retention engine's connector/query-builder — the
highest-value target in the whole feature (see the plan). Runs against a
real sqlite file-backed engine, not mocks: SQLAlchemy Core reflection and
query building behave identically against SQLite, so this is genuine
executed-query coverage for the whitelist logic that matters most —
never referencing an unclassified column, never inlining a value into SQL
text, failing closed on a stale/missing classification, and only ever
mutating an operator-approved row set."""
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, MetaData, Table, Column, String, DateTime, insert, select

from backend.retention_guard.composite.enforce_retention.app.retention_engine import (
    ReflectedSource,
    ClassificationError,
)

# "internal_notes" is deliberately left unclassified — several tests assert
# it's never read, referenced, or mutated by anything the engine builds.
CLASSIFIED_COLUMNS = [
    {"column_name": "id", "column_role": "subject_id"},
    {"column_name": "last_login_at", "column_role": "activity_timestamp"},
    {"column_name": "email", "column_role": "pii"},
    {"column_name": "phone", "column_role": "pii"},
]


def _seed_customers(db_path, rows):
    """Creates and seeds a `customers` table in a file-backed sqlite DB, then
    disposes its own engine — ReflectedSource opens a fresh connection to the
    same file, exactly like it would open a fresh connection to a real
    external Postgres source it doesn't otherwise share a process with."""
    engine = create_engine(f"sqlite:///{db_path}")
    metadata = MetaData()
    customers = Table(
        "customers", metadata,
        Column("id", String, primary_key=True),
        Column("email", String),
        Column("phone", String),
        Column("last_login_at", DateTime),
        Column("internal_notes", String),
    )
    metadata.create_all(engine)
    if rows:
        with engine.begin() as conn:
            conn.execute(insert(customers), rows)
    engine.dispose()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "fakecorp.db"


@pytest.fixture
def connection_string(db_path):
    return f"sqlite:///{db_path}"


NOW = datetime.now(timezone.utc)
INACTIVE_ROW = {"id": "cust-1", "email": "a@x.com", "phone": "555-1", "last_login_at": NOW - timedelta(days=200), "internal_notes": "vip"}
ACTIVE_ROW = {"id": "cust-2", "email": "b@x.com", "phone": "555-2", "last_login_at": NOW - timedelta(days=5), "internal_notes": None}


# ── Reflection / whitelist failure modes ────────────────────────────────

def test_missing_table_raises_before_any_query(db_path, connection_string):
    _seed_customers(db_path, [])
    with pytest.raises(ClassificationError, match="does not exist"):
        ReflectedSource(connection_string, "nonexistent_table", CLASSIFIED_COLUMNS)


def test_stale_classified_column_raises(db_path, connection_string):
    _seed_customers(db_path, [])
    stale_columns = CLASSIFIED_COLUMNS + [{"column_name": "ssn", "column_role": "pii"}]
    with pytest.raises(ClassificationError, match="ssn"):
        ReflectedSource(connection_string, "customers", stale_columns)


def test_missing_required_role_raises(db_path, connection_string):
    _seed_customers(db_path, [])
    incomplete = [c for c in CLASSIFIED_COLUMNS if c["column_role"] != "activity_timestamp"]
    with pytest.raises(ClassificationError, match="subject_id and one activity_timestamp"):
        ReflectedSource(connection_string, "customers", incomplete)


# ── Dry-run query building ───────────────────────────────────────────────

def test_find_matches_returns_only_inactive_subjects(db_path, connection_string):
    _seed_customers(db_path, [INACTIVE_ROW, ACTIVE_ROW])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    matches = source.find_matches(inactive_days=180)

    assert matches == ["cust-1"]


def test_find_matches_stmt_never_references_unclassified_or_pii_columns(db_path, connection_string):
    _seed_customers(db_path, [])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    stmt = source.build_find_matches_stmt(inactive_days=30)
    sql_text = str(stmt.compile(compile_kwargs={"literal_binds": False}))

    # Only the subject_id (selected) and activity_timestamp (filtered on)
    # columns are ever referenced — email/phone (classified pii, but
    # irrelevant to a dry-run SELECT) and internal_notes (never classified
    # at all) never appear in the generated query.
    assert "email" not in sql_text
    assert "phone" not in sql_text
    assert "internal_notes" not in sql_text
    assert "id" in sql_text
    assert "last_login_at" in sql_text


def test_find_matches_stmt_binds_cutoff_as_a_param_not_inlined_text(db_path, connection_string):
    _seed_customers(db_path, [])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    stmt = source.build_find_matches_stmt(inactive_days=30)
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    sql_text = str(compiled)

    cutoff_values = [v for v in compiled.params.values() if isinstance(v, datetime)]
    assert len(cutoff_values) == 1
    cutoff = cutoff_values[0]
    expected = datetime.now(timezone.utc) - timedelta(days=30)
    assert abs((cutoff.replace(tzinfo=timezone.utc) - expected).total_seconds()) < 5
    # The bound value never appears inlined in the SQL text itself.
    assert cutoff.isoformat()[:10] not in sql_text


# ── Enforcement acts only on the approved snapshot ──────────────────────

def test_anonymise_nulls_only_pii_columns_for_approved_subjects(db_path, connection_string):
    _seed_customers(db_path, [INACTIVE_ROW, ACTIVE_ROW])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    rowcount = source.anonymise(["cust-1"])

    assert rowcount == 1
    with source.engine.connect() as conn:
        cust1 = conn.execute(select(source.table).where(source.table.c.id == "cust-1")).one()
        cust2 = conn.execute(select(source.table).where(source.table.c.id == "cust-2")).one()
    assert cust1.email is None and cust1.phone is None
    # Untouched: the subject_id itself, and everything about the row that
    # wasn't classified as pii — including a column that was never
    # classified at all.
    assert cust1.id == "cust-1"
    assert cust1.internal_notes == "vip"
    # A subject not in the approved set is completely unaffected — this is
    # the "approved set == applied set" guarantee, not a re-query of the
    # original inactive_days condition.
    assert cust2.email == "b@x.com" and cust2.phone == "555-2"


def test_anonymise_with_empty_subject_list_is_a_no_op(db_path, connection_string):
    _seed_customers(db_path, [INACTIVE_ROW])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    rowcount = source.anonymise([])

    assert rowcount == 0
    with source.engine.connect() as conn:
        cust1 = conn.execute(select(source.table).where(source.table.c.id == "cust-1")).one()
    assert cust1.email == "a@x.com"


def test_delete_rows_removes_only_approved_subjects(db_path, connection_string):
    _seed_customers(db_path, [INACTIVE_ROW, ACTIVE_ROW])
    source = ReflectedSource(connection_string, "customers", CLASSIFIED_COLUMNS)

    rowcount = source.delete_rows(["cust-1"])

    assert rowcount == 1
    with source.engine.connect() as conn:
        remaining = conn.execute(select(source.table.c.id)).all()
    assert [r.id for r in remaining] == ["cust-2"]
