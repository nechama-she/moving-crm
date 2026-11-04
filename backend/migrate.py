"""Pending schema changes for the existing production database.

Install timed follow-up tasks and first-contact tracking.
"""
import logging

from sqlalchemy import text

from database import engine

logger = logging.getLogger("migrate")


def migrate() -> None:
    with engine.begin() as connection:
        from models import InventoryCatalogSet, EstimateSignature, CompanyDocument
        CompanyDocument.__table__.create(connection, checkfirst=True)
        from company_documents import seed_documents
        seed_documents(connection)
        EstimateSignature.__table__.create(connection, checkfirst=True)
        connection.execute(text('ALTER TABLE estimate_signatures ADD COLUMN IF NOT EXISTS report_id TEXT'))
        InventoryCatalogSet.__table__.create(connection, checkfirst=True)
        from pickup_areas import migrate_pickup_regions
        logger.info("Copied %s pricing pickup area rows", migrate_pickup_regions(connection))
        # Every table under a pricing plan is deleted with the plan by the database.
        for child in ('pricing_rates', 'pricing_rules', 'pricing_services'):
            for (name,) in connection.execute(text("""
                SELECT conname FROM pg_constraint
                WHERE conrelid = CAST(:child AS regclass) AND confrelid = 'pricing_plans'::regclass
                  AND contype = 'f' AND confdeltype <> 'c'
            """), {'child': child}).all():
                connection.execute(text(f'ALTER TABLE {child} DROP CONSTRAINT "{name}", ADD CONSTRAINT "{name}" '
                                        'FOREIGN KEY (plan_id) REFERENCES pricing_plans(id) ON DELETE CASCADE'))
        # One rate per destination and size column; this index also serves lookups by plan.
        if not connection.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'uq_pricing_rates_plan_destination_band'")).first():
            # Pricing already uses the first row by sort order; the extra copies are never read.
            removed = connection.execute(text("""
                DELETE FROM pricing_rates WHERE id IN (
                    SELECT id FROM (
                        SELECT id, row_number() OVER (
                            PARTITION BY plan_id, destination, band_label ORDER BY sort_order, id) AS position
                        FROM pricing_rates) ranked
                    WHERE position > 1)
            """)).rowcount
            logger.info("Removed %s duplicate pricing rate rows", removed)
            connection.execute(text('ALTER TABLE pricing_rates ADD CONSTRAINT uq_pricing_rates_plan_destination_band '
                                    'UNIQUE (plan_id, destination, band_label)'))
        connection.execute(text('DROP INDEX IF EXISTS ix_pricing_rates_plan_id'))
        # Origin destination & administration Fee moves from an "All Jobs" service row to the plan.
        if not connection.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'pricing_plans' AND column_name = 'admin_fee'""")).first():
            connection.execute(text('ALTER TABLE pricing_plans ADD COLUMN admin_fee NUMERIC(12, 2)'))
            moved = 0
            for plan_id, in connection.execute(text('SELECT id FROM pricing_plans')).all():
                rows = connection.execute(text("""
                    SELECT id, rate_text FROM pricing_services
                    WHERE plan_id = :plan_id AND lower(name) LIKE '%all jobs%'"""), {'plan_id': plan_id}).all()
                amount = rows[0].rate_text.strip().lstrip('$').strip() if len(rows) == 1 else ''
                # Only a single plain amount is moved; anything else stays a service and keeps working.
                if amount.replace('.', '', 1).isdigit():
                    connection.execute(text('UPDATE pricing_plans SET admin_fee = :amount WHERE id = :plan_id'),
                                       {'amount': amount, 'plan_id': plan_id})
                    connection.execute(text('DELETE FROM pricing_services WHERE id = :id'), {'id': rows[0].id})
                    moved += 1
            logger.info("Moved the administration fee to %s pricing plans", moved)
        # Plans whose fee existed only as "DESTINATION & ORIGIN (All Jobs) $N" in a rule's text.
        if connection.execute(text("""
            INSERT INTO app_settings(key, value) VALUES ('migration:admin-fee-from-rules-v1', 'copied')
            ON CONFLICT (key) DO NOTHING RETURNING key
        """)).scalar():
            import re
            from_rules = 0
            for plan_id, description in connection.execute(text("""
                    SELECT p.id, r.description FROM pricing_plans p JOIN pricing_rules r ON r.plan_id = p.id
                    WHERE p.admin_fee IS NULL ORDER BY p.id, r.sort_order""")).all():
                match = re.search(r"destination\s*&\s*origin\s*\(all jobs\)\s*\$?\s*(\d+(?:\.\d+)?)", description, re.IGNORECASE)
                if match and connection.execute(text(
                        'UPDATE pricing_plans SET admin_fee = :amount WHERE id = :id AND admin_fee IS NULL'),
                        {'amount': match.group(1), 'id': plan_id}).rowcount:
                    from_rules += 1
            logger.info("Copied the administration fee from rule text for %s pricing plans", from_rules)
        from extra_stops import migrate_stops_cards
        logger.info("Moved additional stop pricing for %s pricing plans", migrate_stops_cards(connection))
        from elevator_pricing import migrate_elevator_cards
        logger.info("Moved elevator pricing for %s pricing plans", migrate_elevator_cards(connection))
        from long_carry_pricing import migrate_long_carry_cards
        logger.info("Moved long carry pricing for %s pricing plans", migrate_long_carry_cards(connection))
        from stairs_pricing import migrate_stairs_cards
        logger.info("Moved stairs pricing for %s pricing plans", migrate_stairs_cards(connection))
        from storage_pricing import migrate_storage_cards
        logger.info("Moved storage pricing for %s pricing plans", migrate_storage_cards(connection))
        from shuttle import migrate_shuttle_cards
        logger.info("Moved delivery shuttle pricing for %s pricing plans", migrate_shuttle_cards(connection))
        from delivery_fees import migrate_fee_cards
        logger.info("Moved %s origin and destination fee cards", migrate_fee_cards(connection))
        from bulky_items import migrate_bulky_items
        logger.info("Moved %s bulky item rates", migrate_bulky_items(connection))
        from long_distance_packing import migrate_packing_cards
        logger.info("Moved packing rates and materials for %s pricing plans", migrate_packing_cards(connection))
        # Jobs priced while the old "All Jobs" rule line was charged next to the new fee: zero that
        # line, as a recalculation would, and take it out of the job, published and lead totals.
        if connection.execute(text("""
            INSERT INTO app_settings(key, value) VALUES ('migration:admin-fee-duplicate-charges-v1', 'cleared')
            ON CONFLICT (key) DO NOTHING RETURNING key
        """)).scalar():
            import json
            duplicates = connection.execute(text("""
                SELECT c.id, c.job_id, j.lead_id, c.total_cost, c.discount_amount
                FROM lead_job_charges c JOIN lead_jobs j ON j.id = c.job_id
                WHERE c.name = 'DESTINATION & ORIGIN (All Jobs)' AND (c.total_cost <> 0 OR c.discount_amount <> 0)
                  AND EXISTS (SELECT 1 FROM lead_job_charges fee
                              WHERE fee.job_id = c.job_id AND fee.name = 'Origin destination & administration Fee')
            """)).all()
            for charge_id, job_id, lead_id, total, discount in duplicates:
                connection.execute(text(
                    'UPDATE lead_job_charges SET subtotal = 0, discount_amount = 0, total_cost = 0 WHERE id = :id'),
                    {'id': charge_id})
                connection.execute(text('UPDATE lead_jobs SET price = price - :total WHERE id = :id AND price IS NOT NULL'),
                                   {'total': total, 'id': job_id})
                connection.execute(text(
                    'UPDATE public_move_access SET published_price = published_price - :total '
                    'WHERE job_id = :id AND published_price IS NOT NULL'), {'total': total, 'id': job_id})
                raw = connection.execute(text('SELECT estimated_total FROM leads WHERE id = :id'), {'id': lead_id}).scalar()
                summary = json.loads(raw) if raw else None
                if isinstance(summary, dict):
                    summary['subtotal'] = float(summary.get('subtotal', 0)) - float(total + discount)
                    summary['finalTotal'] = float(summary.get('finalTotal', 0)) - float(total)
                    connection.execute(text('UPDATE leads SET estimated_total = :value WHERE id = :id'),
                                       {'value': json.dumps(summary), 'id': lead_id})
            logger.info("Removed %s duplicate administration fee charges", len(duplicates))
            # Every other job keeps its amount; the line takes the new name.
            renamed = connection.execute(text("""
                UPDATE lead_job_charges SET name = 'Origin destination & administration Fee'
                WHERE name = 'DESTINATION & ORIGIN (All Jobs)' AND NOT EXISTS (
                    SELECT 1 FROM lead_job_charges fee
                    WHERE fee.job_id = lead_job_charges.job_id AND fee.name = 'Origin destination & administration Fee')
            """)).rowcount
            logger.info("Renamed %s administration fee charges", renamed)
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS set_id VARCHAR(36)'))
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS set_name VARCHAR(200)'))
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS mover_pack_count INTEGER'))
        connection.execute(text('ALTER TABLE inventory_edit_items ADD COLUMN IF NOT EXISTS manual BOOLEAN'))
        connection.execute(text('ALTER TABLE lead_job_charges ADD COLUMN IF NOT EXISTS source VARCHAR(20)'))
        from models import LeadContact
        LeadContact.__table__.create(connection, checkfirst=True)
        from models import LeadPayment
        from sqlalchemy import inspect as inspect_schema
        payments_table_existed = inspect_schema(connection).has_table('lead_payments')
        LeadPayment.__table__.create(connection, checkfirst=True)
        connection.execute(text('ALTER TABLE lead_payments ADD COLUMN IF NOT EXISTS paid_at DATE'))
        connection.execute(text('ALTER TABLE lead_payments ADD COLUMN IF NOT EXISTS method VARCHAR(30)'))
        for column, kind in (('crew_size', 'INTEGER'), ('trucks', 'INTEGER'), ('start_time', 'VARCHAR(20)'),
                             ('estimated_hours', 'NUMERIC(5, 2)'), ('travel_hours', 'NUMERIC(5, 2)')):
            connection.execute(text(f'ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS {column} {kind}'))
        connection.execute(text('ALTER TABLE companies ADD COLUMN IF NOT EXISTS valuation_per_lb NUMERIC(6, 2)'))
        for column, kind in (('third_party_payout_to', 'VARCHAR(255)'), ('third_party_payout_amount', 'NUMERIC(12, 2)'),
                             ('third_party_payout_paid', 'BOOLEAN'), ('third_party_payout_paid_at', 'VARCHAR(40)')):
            connection.execute(text(f'ALTER TABLE leads ADD COLUMN IF NOT EXISTS {column} {kind}'))
        # Where payments were first made with a payout each, those payouts become the lead's one payout,
        # and the old columns stop being required; they are left in place until they are dropped.
        if connection.execute(text("""SELECT 1 FROM information_schema.columns
                                      WHERE table_name = 'lead_payments' AND column_name = 'third_party_commission_amount'""")).first():
            connection.execute(text("""
                UPDATE leads SET third_party_payout_to = payout.recipient, third_party_payout_amount = payout.amount,
                                 third_party_payout_paid = payout.paid, third_party_payout_paid_at = payout.paid_at
                FROM (SELECT lead_id, MAX(NULLIF(third_party_commission_to, '')) AS recipient,
                             SUM(third_party_commission_amount) AS amount, BOOL_AND(third_party_commission_paid) AS paid,
                             MAX(third_party_commission_paid_at) AS paid_at
                      FROM lead_payments WHERE third_party_commission_amount > 0 GROUP BY lead_id) AS payout
                WHERE leads.id = payout.lead_id AND leads.third_party_payout_amount IS NULL"""))
            for column in ('third_party_commission_to', 'third_party_commission_amount',
                           'third_party_commission_paid', 'third_party_commission_paid_at'):
                connection.execute(text(f'ALTER TABLE lead_payments ALTER COLUMN {column} DROP NOT NULL'))
        # Payments were a JSON list on the lead, all synced from SmartMoving. They move to their own rows once,
        # when the table is created; the old list is left as it was until it is dropped.
        if not payments_table_existed and connection.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'leads' AND column_name = 'payments'")).first():
            import json
            import uuid
            def number(value, default=0):
                try:
                    return float(value) if value is not None else default
                except (TypeError, ValueError):
                    return default
            for lead_id, raw in connection.execute(text("SELECT id, payments FROM leads WHERE payments IS NOT NULL AND payments <> ''")).all():
                try:
                    items = json.loads(raw)
                except ValueError:
                    items = []
                rows = [dict(id=str(uuid.uuid4()), lead_id=lead_id, source='smartmoving', sort_order=index,
                             amount=number(item.get('amount')), taken_by_user=str(item.get('takenByUser') or '').strip(),
                             rep_paid=bool(item.get('repPaid')), rep_paid_at=str(item.get('repPaidAt') or '').strip(),
                             rep_commission_percent=number(item.get('repCommissionPercent'), None),
                             rep_commission_amount=number(item.get('repCommissionAmount'), None))
                        for index, item in enumerate(items if isinstance(items, list) else []) if isinstance(item, dict)]
                if rows:
                    connection.execute(LeadPayment.__table__.insert(), rows)
                # The payouts that were on single payments become the lead's one payout.
                payouts = [item for item in (items if isinstance(items, list) else [])
                           if isinstance(item, dict) and number(item.get('thirdPartyCommissionAmount')) > 0]
                if payouts:
                    connection.execute(text("""UPDATE leads SET third_party_payout_to = :to, third_party_payout_amount = :amount,
                                               third_party_payout_paid = :paid, third_party_payout_paid_at = :paid_at WHERE id = :id"""), {
                        'id': lead_id,
                        'to': next((str(item.get('thirdPartyCommissionTo')).strip() for item in payouts if item.get('thirdPartyCommissionTo')), ''),
                        'amount': sum(number(item.get('thirdPartyCommissionAmount')) for item in payouts),
                        'paid': all(item.get('thirdPartyCommissionPaid') for item in payouts),
                        'paid_at': max(str(item.get('thirdPartyCommissionPaidAt') or '') for item in payouts)})
        # The list lives in the inventory tables; the old JSON draft copy is no longer read or written.
        connection.execute(text("""UPDATE lead_liveswitch SET details = (details::jsonb - 'inventory_draft')::text
                                   WHERE details LIKE '%"inventory_draft"%'"""))
        for column, kind in (('pricing_plan_id', 'VARCHAR(36)'), ('pricing_move_type', 'VARCHAR(50)'), ('pricing_match_key', 'VARCHAR(64)'),
                             ('minimum_cuft', 'INTEGER'),
                             ('estimate_approved_id', 'VARCHAR(36)'), ('estimate_approved_at', 'TIMESTAMP')):
            connection.execute(text(f'ALTER TABLE lead_jobs ADD COLUMN IF NOT EXISTS {column} {kind}'))
        from followup_tasks import install as install_followup_tasks
        install_followup_tasks(connection)
        from smartmoving_task_migration import install as install_smartmoving_tasks
        install_smartmoving_tasks(connection)
        from first_contact_state import install as install_first_contact
        install_first_contact(connection)
        # Clear the incorrectly backfilled queue once. The marker and delete
        # share this transaction, so a failed deployment transaction can retry.
        clear_first_contact = connection.execute(text("""
            INSERT INTO app_settings(key, value)
            VALUES ('cleanup:first-contact-backfill-v1', 'cleared')
            ON CONFLICT (key) DO NOTHING RETURNING key
        """)).scalar()
        if clear_first_contact:
            cleared = connection.execute(text("DELETE FROM first_contact_states")).rowcount
            logger.info("Cleared %s first-contact state rows", cleared)
        # Reps whose follow-ups live in the CRM: SmartMoving no longer changes their leads'
        # priority or tasks. Eli Jones is first; the marker keeps later edits to the flag.
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS crm_managed_followups BOOLEAN NOT NULL DEFAULT FALSE"))
        enable_eli = connection.execute(text("""
            INSERT INTO app_settings(key, value)
            VALUES ('migration:crm-managed-followups:eli-jones', 'enabled')
            ON CONFLICT (key) DO NOTHING RETURNING key
        """)).scalar()
        if enable_eli:
            enabled = connection.execute(text(
                "UPDATE users SET crm_managed_followups = TRUE WHERE lower(trim(name)) = 'eli jones'"
            )).rowcount
            logger.info("Enabled CRM-managed follow-ups for %s user(s) named Eli Jones", enabled)
    logger.info("Follow-up task and first-contact state setup complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
