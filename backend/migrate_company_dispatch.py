"""Backfill contract/dispatch ownership using the configured company mappings."""

from sqlalchemy import text


def backfill_company_dispatch(connection):
    """Run inside the deployment transaction; safe to repeat on later deploys."""
    # Fix jobs before leads so jobs inheriting their lead's company retain the
    # original dispatch company. Explicit dispatch assignments take precedence.
    jobs = connection.execute(text("""
        UPDATE lead_jobs AS job
        SET company_id = contract.id,
            dispatch_company_id = COALESCE(job.dispatch_company_id, dispatch.id),
            updated_at = CURRENT_TIMESTAMP
        FROM leads AS lead, companies AS dispatch, companies AS contract
        WHERE job.lead_id = lead.id
          AND COALESCE(job.company_id, lead.company_id) = dispatch.id
          AND dispatch.dispatches_for_company_id = contract.id
          AND contract.dispatches_for_company_id IS NULL
          AND dispatch.id <> contract.id
    """))
    leads = connection.execute(text("""
        UPDATE leads AS lead
        SET company_id = contract.id,
            updated_at = CURRENT_TIMESTAMP
        FROM companies AS dispatch, companies AS contract
        WHERE lead.company_id = dispatch.id
          AND dispatch.dispatches_for_company_id = contract.id
          AND contract.dispatches_for_company_id IS NULL
          AND dispatch.id <> contract.id
    """))
    return jobs.rowcount, leads.rowcount
