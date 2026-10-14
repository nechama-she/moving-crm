"""Export and preview configuration transfers; never read or write client tables.

Uses libpq PGHOST/PGDATABASE/PGUSER/PGPASSWORD variables. No database URL or
password is accepted as a command-line argument. Preview performs SELECT only.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from models import Base


TABLES = ('companies', 'inventory_room_types', 'inventory_catalog_items',
          'pricing_plans', 'pricing_rules', 'pricing_rates', 'pricing_services',
          'local_pricing_routes')
COMPANY_FIELDS = {'id', 'name', 'color', 'logo', 'customer_questions', 'phone',
                  'office_address', 'dot_number', 'sender_email', 'timezone',
                  'is_default_company', 'dispatches_for_company_id',
                  'facebook_page_id', 'aircall_number_id', 'aircall_name',
                  'samrtmoving_branch_id', 'granot_api_id', 'granot_mover_ref'}


def table(name):
    if name not in (*TABLES, 'app_settings'):
        raise ValueError('Table not permitted')
    return Base.metadata.tables[name]


def fields(name):
    if name == 'companies':
        return COMPANY_FIELDS
    return set(table(name).columns.keys()) - {'created_at', 'updated_at', 'updated_by'}


def setting_allowed(key):
    return key.startswith('local_pricing:')


def export_settings(connection):
    data = {}
    for name in TABLES:
        columns = [table(name).c[key] for key in sorted(fields(name))]
        data[name] = [dict(row) for row in connection.execute(select(*columns)).mappings()]
    settings = table('app_settings')
    # Filter before retrieving values: client/job records never enter the bundle.
    query = select(settings.c.key, settings.c.value).where(
        settings.c.key.startswith('local_pricing:'))
    data['app_settings'] = [dict(row) for row in connection.execute(query).mappings()]
    keys = connection.execute(select(settings.c.key)).scalars()
    excluded = {}
    for key in keys:
        if not setting_allowed(key):
            prefix = key.split(':', 1)[0]
            excluded[prefix] = excluded.get(prefix, 0) + 1
    return {'format': 1, 'tables': data, 'excluded_setting_types': excluded}


def normalize(value):
    return ' '.join(value.strip().casefold().split())


def company_mapping(source, target):
    mapping = {}
    seen = set()
    for row in source:
        name = normalize(row['name'])
        if name in seen:
            raise ValueError('Duplicate source company name: ' + row['name'])
        seen.add(name)
        matches = [other for other in target if normalize(other['name']) == name]
        if len(matches) != 1:
            raise ValueError('Company needs exactly one production match: ' + row['name'])
        mapping[row['id']] = matches[0]['id']
    return mapping


def validate(bundle):
    if bundle.get('format') != 1 or set(bundle.get('tables', {})) != set((*TABLES, 'app_settings')):
        raise ValueError('Unexpected bundle format or tables')
    for name, rows in bundle['tables'].items():
        allowed = {'key', 'value'} if name == 'app_settings' else fields(name)
        seen = set()
        for row in rows:
            if set(row) - allowed:
                raise ValueError('Unexpected fields in ' + name)
            identity = row.get('key') if name == 'app_settings' else row.get('id', row.get('company_id'))
            if not identity or identity in seen:
                raise ValueError('Missing or duplicate identity in ' + name)
            seen.add(identity)
            if name == 'app_settings' and not setting_allowed(row['key']):
                raise ValueError('Unapproved application setting')


def preview(connection, bundle):
    validate(bundle)
    source = bundle['tables']
    companies = table('companies')
    target = [dict(row) for row in connection.execute(select(companies.c.id, companies.c.name)).mappings()]
    mapping = company_mapping(source['companies'], target)
    plans = table('pricing_plans')
    existing = list(connection.execute(select(plans.c.id, plans.c.company_id, plans.c.name)).mappings())
    plan_mapping = {}
    source_plan_names = set()
    for row in source['pricing_plans']:
        company_id = mapping.get(row['company_id'])
        if not company_id:
            raise ValueError('Pricing book has no matched company: ' + row['name'])
        identity = (company_id, normalize(row['name']))
        if identity in source_plan_names:
            raise ValueError('Duplicate source pricing book: ' + row['name'])
        source_plan_names.add(identity)
        matches = [p for p in existing if p['company_id'] == company_id and normalize(p['name']) == normalize(row['name'])]
        if len(matches) > 1:
            raise ValueError('Ambiguous production pricing book: ' + row['name'])
        plan_mapping[row['id']] = matches[0]['id'] if matches else None
    return {'mode': 'READ ONLY - nothing applied', 'company_id_mapping': mapping,
            'pricing_plan_id_mapping': plan_mapping,
            'source_row_counts': {name: len(rows) for name, rows in source.items()},
            'excluded_setting_types': bundle.get('excluded_setting_types', {}),
            'preserved': ['clients', 'jobs', 'reports', 'uploads', 'users', 'production company IDs and creation timestamps', 'credentials outside the companies table'],
            'requires_review': ['User-specific settings are excluded and reported separately.',
                                'Existing pricing rows for matching books will be replaced; production-only books are retained.']}


def apply_settings(connection, bundle):
    """Caller owns transaction. Never commit here; any error rolls back all changes."""
    report = preview(connection, bundle)
    source = bundle['tables']
    companies = report['company_id_mapping']
    plans = {key: value or str(uuid4()) for key, value in report['pricing_plan_id_mapping'].items()}

    def upsert(name, values, keys):
        target = table(name)
        condition = [target.c[key] == values[key] for key in keys]
        if connection.execute(select(target).where(*condition)).first():
            connection.execute(target.update().where(*condition).values(**values))
        else:
            connection.execute(target.insert().values(**values))

    # Clear the single-default constraint before assigning the source default.
    if sum(bool(row.get('is_default_company')) for row in source['companies']) > 1:
        raise ValueError('Multiple source default companies')
    if any(row.get('is_default_company') for row in source['companies']):
        connection.execute(table('companies').update().values(is_default_company=False))
    # Permit page IDs to move between matched companies without a transient
    # uniqueness conflict. All changes remain inside the caller's transaction.
    page_owners = [companies[row['id']] for row in source['companies'] if 'facebook_page_id' in row]
    if page_owners:
        connection.execute(table('companies').update().where(
            table('companies').c.id.in_(page_owners)).values(facebook_page_id=None))
    for row in source['companies']:
        values = {**row, 'id': companies[row['id']]}
        if values.get('dispatches_for_company_id'):
            values['dispatches_for_company_id'] = companies[values['dispatches_for_company_id']]
        upsert('companies', values, ['id'])
    for name in ('inventory_room_types', 'inventory_catalog_items'):
        for row in source[name]:
            row = dict(row)
            existing = connection.execute(select(table(name)).where(table(name).c.id == row['id'])).mappings().first()
            # Catalog names are editable settings; the stable ID identifies
            # the item across environments even after a rename. Preserve that
            # ID so existing inventory and pricing references remain valid.
            if name == 'inventory_room_types' and existing and normalize(existing['name']) != normalize(row['name']):
                raise ValueError('Catalog ID collision: ' + row['id'])
            if not existing and name == 'inventory_room_types':
                matches = [item for item in connection.execute(select(table(name))).mappings()
                           if normalize(item['name']) == normalize(row['name'])]
                if len(matches) > 1:
                    raise ValueError('Ambiguous room type: ' + row['name'])
                if matches:
                    row['id'] = matches[0]['id']
            upsert(name, row, ['id'])
    for row in source['pricing_plans']:
        values = {**row, 'id': plans[row['id']], 'company_id': companies[row['company_id']]}
        existing = connection.execute(select(table('pricing_plans')).where(table('pricing_plans').c.id == values['id'])).mappings().first()
        # source_key is unique and belongs to the target book's identity.
        values['source_key'] = existing['source_key'] if existing else 'settings-transfer:' + values['id']
        upsert('pricing_plans', values, ['id'])
    for name in ('pricing_rules', 'pricing_rates', 'pricing_services'):
        target = table(name)
        connection.execute(target.delete().where(target.c.plan_id.in_(list(plans.values()))))
        for row in source[name]:
            connection.execute(target.insert().values(**{**row, 'id': str(uuid4()), 'plan_id': plans[row['plan_id']]}))
    target = table('local_pricing_routes')
    connection.execute(target.delete().where(target.c.company_id.in_(list(companies.values()))))
    for row in source['local_pricing_routes']:
        values = {**row, 'id': str(uuid4()), 'company_id': companies[row['company_id']]}
        connection.execute(target.insert().values(**values))
    for row in source['app_settings']:
        values = dict(row)
        if values['key'].startswith('local_pricing:'):
            values['key'] = 'local_pricing:' + plans[values['key'].split(':', 1)[1]]
        upsert('app_settings', values, ['key'])
    return {**report, 'mode': 'APPLIED', 'pricing_plan_id_mapping': plans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['export', 'preview', 'apply'])
    parser.add_argument('file', type=Path)
    parser.add_argument('--confirm-database', help='Required for apply; must equal current_database()')
    args = parser.parse_args()
    engine = create_engine('postgresql+psycopg2://', connect_args={'sslmode': 'require', 'connect_timeout': 10})
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' + (', READ ONLY' if args.mode != 'apply' else ''))
        if args.mode == 'export':
            bundle = export_settings(connection)
            with args.file.open('x', encoding='utf-8') as output:
                json.dump(bundle, output, indent=2, default=lambda value: str(value) if isinstance(value, Decimal) else value)
            print(json.dumps({'exported': {name: len(rows) for name, rows in bundle['tables'].items()}}))
        elif args.mode == 'preview':
            print(json.dumps(preview(connection, json.loads(args.file.read_text(encoding='utf-8'))), indent=2))
        else:
            if not args.confirm_database or connection.exec_driver_sql('SELECT current_database()').scalar() != args.confirm_database:
                raise ValueError('Explicit matching database confirmation required')
            connection.exec_driver_sql('SET LOCAL lock_timeout = \'10s\'')
            connection.exec_driver_sql('LOCK TABLE ' + ', '.join((*TABLES, 'app_settings')) + ' IN SHARE ROW EXCLUSIVE MODE')
            result = apply_settings(connection, json.loads(args.file.read_text(encoding='utf-8')))
            connection.commit()
            print(json.dumps(result, indent=2))
    engine.dispose()


if __name__ == '__main__':
    main()
