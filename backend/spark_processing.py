"""Staff-only diagnostics for the shared report-completion workflow."""
import json
import re
from datetime import datetime, timezone

STEPS = [('download', 'Read completed report'), ('extract', 'Extract inventory and volume'),
         ('inventory', 'Save job inventory'), ('pricing', 'Calculate move price'),
         ('publish', 'Save and publish estimate')]


def error_detail(exc):
    # Database wrappers can include SQL parameters; retain the underlying error only.
    original = getattr(exc, 'orig', exc)
    message = str(getattr(original, 'detail', original))
    message = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', message)
    message = re.sub(r'(?i)(bearer\s+)[^\s]+', r'\1[redacted]', message)
    message = re.sub(r'(?i)((?:password|token|secret|api[_-]?key)[\"\']?\s*[:=]\s*[\"\']?)[^\s,\"\']+', r'\1[redacted]', message)
    return f'{type(original).__name__}: {message}'[:3000]


class SparkProcessingLog:
    def __init__(self, report_id):
        self.data = {'report_id': report_id, 'started_at': self.now(), 'status': 'running',
                     'steps': [{'id': key, 'label': label, 'status': 'pending'} for key, label in STEPS]}
        self.current = 'download'

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def mark(self, key, status, message='', error=''):
        if status == 'running':
            self.current = key
        step = next(row for row in self.data['steps'] if row['id'] == key)
        step.update(status=status, message=message, at=self.now())
        if error:
            step['error'] = error

    def fail(self, exc):
        self.mark(self.current, 'error', 'Failed - click to view error', error_detail(exc))
        for step in self.data['steps']:
            if step['status'] == 'pending':
                step['status'] = 'skipped'
            elif step['status'] == 'success' and step['id'] in ('inventory', 'pricing', 'publish'):
                step.update(status='rolled_back', message='Rolled back after failure; changes were not saved')
        self.data.update(status='error', finished_at=self.now())

    def finish(self):
        self.data.update(status='error' if any(row['status'] == 'error' for row in self.data['steps']) else 'success', finished_at=self.now())

    def attach(self, details):
        from spark_history import remember_report
        details['spark_processing'] = self.data
        remember_report(details)

    def persist(self, db, lead_id):
        from models import LeadLiveSwitch
        saved = db.get(LeadLiveSwitch, lead_id)
        if saved:
            details = json.loads(saved.details or '{}')
            if details.get('last_spark_id') != self.data['report_id']:
                return
            self.attach(details)
            saved.details = json.dumps(details)
            db.commit()
