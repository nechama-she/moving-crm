import os
from dotenv import load_dotenv

load_dotenv()


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.environ["DB_HOST"]
    port = os.getenv("DB_PORT", "5432")
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def get_config() -> dict:
    return {
        "DATABASE_URL": _database_url(),
        "JWT_SECRET": os.getenv("JWT_SECRET", "dev-secret-change-in-prod"),
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:5174"),
    }
