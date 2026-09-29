import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from models import Base, LeadAttachment
from report_files import move_files, remove_report_file, preview_report_file


def test_removed_customer_file_remains_available_to_staff_only():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        access = SimpleNamespace(lead_id='lead', job_id='job')
        db.add_all([LeadAttachment(id=id,lead_id=lead,file_name='photo.png',
                                  content_type='image/png',file_blob=b'image',file_size=5)
                    for id,lead in [('photo','lead'),('foreign','other')]])
        db.commit()
        remove_report_file(access,'photo',db)
        assert move_files(access,db)==[]
        assert [row.id for row in move_files(access,db,all_lead=True,include_removed=True)]==['photo']
        with pytest.raises(HTTPException):
            preview_report_file(access,'photo',db)
        assert preview_report_file(access,'photo',db,all_lead=True,include_removed=True)['url'].startswith('data:image/png')
        with pytest.raises(HTTPException):
            preview_report_file(access,'foreign',db,all_lead=True,include_removed=True)
        assert db.get(LeadAttachment,'photo').file_blob==b'image'
    engine.dispose()
