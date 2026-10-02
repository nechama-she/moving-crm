import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from migrate_company_dispatch import backfill_company_dispatch


@pytest.mark.parametrize(
    "lead_company,job_company,dispatch,expected_lead,expected_job,expected_dispatch",
    [
        ("rapid", "rapid", None, "gorilla", "gorilla", "rapid"),
        ("gorilla", "rapid", None, "gorilla", "gorilla", "rapid"),
        ("rapid", None, None, "gorilla", "gorilla", "rapid"),
        ("rapid", "rapid", "other", "gorilla", "gorilla", "other"),
        ("rapid", "rapid", "rapid", "gorilla", "gorilla", "rapid"),
        ("rapid", "other", None, "gorilla", "other", None),
        ("gorilla", "gorilla", "rapid", "gorilla", "gorilla", "rapid"),
        ("other", None, None, "other", None, None),
        (None, None, None, None, None, None),
        ("self", "self", None, "self", "self", None),
        ("chain", "chain", None, "chain", "chain", None),
        ("orphan", "orphan", None, "orphan", "orphan", None),
    ],
)
def test_backfill_and_repeat(
    lead_company, job_company, dispatch, expected_lead, expected_job, expected_dispatch
):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id TEXT PRIMARY KEY, dispatches_for_company_id TEXT)"))
        connection.execute(text("CREATE TABLE leads (id TEXT PRIMARY KEY, company_id TEXT, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE lead_jobs (id TEXT PRIMARY KEY, lead_id TEXT, company_id TEXT, dispatch_company_id TEXT, updated_at TIMESTAMP)"))
        connection.execute(text("""
            INSERT INTO companies VALUES ('gorilla', NULL), ('rapid', 'gorilla'),
                ('other', NULL), ('self', 'self'), ('chain', 'rapid'), ('orphan', 'missing')
        """))
        connection.execute(text("INSERT INTO leads VALUES ('lead', :company, NULL)"), {"company": lead_company})
        connection.execute(text("INSERT INTO lead_jobs VALUES ('job', 'lead', :company, :dispatch, NULL)"),
                           {"company": job_company, "dispatch": dispatch})

        jobs, leads = backfill_company_dispatch(connection)
        assert jobs == int(job_company == "rapid" or (job_company is None and lead_company == "rapid"))
        assert leads == int(lead_company == "rapid")
        assert connection.execute(text("SELECT company_id FROM leads")).scalar() == expected_lead
        assert tuple(connection.execute(text("SELECT company_id, dispatch_company_id FROM lead_jobs")).one()) == (expected_job, expected_dispatch)
        assert backfill_company_dispatch(connection) == (0, 0)
    engine.dispose()


def test_backfill_mixed_jobs_and_lead_without_jobs():
    """Resolve inherited companies before changing their shared lead owner."""
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id TEXT PRIMARY KEY, dispatches_for_company_id TEXT)"))
        connection.execute(text("CREATE TABLE leads (id TEXT PRIMARY KEY, company_id TEXT, updated_at TIMESTAMP)"))
        connection.execute(text("CREATE TABLE lead_jobs (id TEXT PRIMARY KEY, lead_id TEXT, company_id TEXT, dispatch_company_id TEXT, updated_at TIMESTAMP)"))
        connection.execute(text("INSERT INTO companies VALUES ('gorilla', NULL), ('rapid', 'gorilla'), ('other', NULL)"))
        connection.execute(text("INSERT INTO leads VALUES ('lead', 'rapid', NULL), ('no-jobs', 'rapid', NULL)"))
        connection.execute(text("""
            INSERT INTO lead_jobs VALUES
                ('inherited', 'lead', NULL, NULL, NULL),
                ('explicit', 'lead', 'rapid', NULL, NULL),
                ('manual', 'lead', NULL, 'other', NULL),
                ('unrelated', 'lead', 'other', NULL, NULL)
        """))

        assert backfill_company_dispatch(connection) == (3, 2)
        assert connection.execute(text("SELECT company_id FROM leads ORDER BY id")).scalars().all() == ["gorilla", "gorilla"]
        assert [tuple(row) for row in connection.execute(text(
            "SELECT id, company_id, dispatch_company_id FROM lead_jobs ORDER BY id"
        ))] == [
            ("explicit", "gorilla", "rapid"),
            ("inherited", "gorilla", "rapid"),
            ("manual", "gorilla", "other"),
            ("unrelated", "other", None),
        ]
        assert backfill_company_dispatch(connection) == (0, 0)
    engine.dispose()
