import os
from dotenv import load_dotenv

load_dotenv()


def get_config() -> dict:
    return {
        "DATABASE_URL": os.environ["DATABASE_URL"],
        "JWT_SECRET": os.getenv("JWT_SECRET", "dev-secret-change-in-prod"),
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "http://localhost:5174"),
    }
