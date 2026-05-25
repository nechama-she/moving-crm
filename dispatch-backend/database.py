from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import get_config

cfg = get_config()
engine = create_engine(cfg["DATABASE_URL"], pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
