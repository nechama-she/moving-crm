import sys
from pathlib import Path

from sqlalchemy.orm import configure_mappers


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import models  # noqa: E402


def test_foreman_relationship_is_on_lead_job():
    """Catch relationships accidentally declared on the wrong ORM model."""
    configure_mappers()

    assert hasattr(models.LeadJob, "foreman")
    assert not hasattr(models.PricingPlan, "foreman")
