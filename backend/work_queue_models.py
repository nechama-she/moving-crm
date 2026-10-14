"""Durable read model. Source customer records remain authoritative."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Numeric, String, Text
from models import Base


class QueueActivity(Base):
    __tablename__ = "work_queue_activity"
    source = Column(String(20), primary_key=True)
    source_key = Column(String(64), primary_key=True)
    client = Column(String(255), nullable=False, index=True)
    message_id = Column(String(255), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    event_time = Column(Numeric(24, 6), nullable=False, default=0)
    sequence = Column(Numeric(80, 0), nullable=False, default=0)
    deleted = Column(Boolean, nullable=False, default=False)
    payload = Column(Text, nullable=False)
    __table_args__ = (
        Index("ix_work_queue_activity_client_time", "client", "occurred_at"),
        Index("ix_work_queue_activity_source_time", "source", "deleted", "occurred_at"),
    )


class QueueLead(Base):
    __tablename__ = "work_queue_leads"
    lead_id = Column(String(36), primary_key=True)
    rep = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    first_category = Column(String(20), nullable=False, default="")
    first_payload = Column(Text, nullable=False, default="{}")
    followup = Column(Boolean, nullable=False, default=False)
    overdue = Column(Boolean, nullable=False, default=False)
    followup_payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False)
    crm_created_at = Column(DateTime(timezone=True), nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    next_due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    __table_args__ = (
        Index("ix_work_queue_first_filters", "first_category", "rep", "company"),
        Index("ix_work_queue_followup_filters", "followup", "overdue", "rep", "company"),
    )


class QueueDirty(Base):
    __tablename__ = "work_queue_dirty"
    lead_id = Column(String(36), primary_key=True)
    revision = Column(BigInteger, nullable=False, default=1, server_default="1")


class QueueCheckpoint(Base):
    __tablename__ = "work_queue_checkpoints"
    key = Column(String(40), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
