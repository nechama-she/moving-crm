from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_config
from routes import leads, conversations, system, sms

cfg = get_config()

app = FastAPI(title="Moving CRM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cfg["CORS_ORIGINS"].split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router)
app.include_router(conversations.router)
app.include_router(sms.router)
app.include_router(system.router)
