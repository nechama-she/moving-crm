from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_config
from routes import auth, leads, system, sms, companies, users, smartmoving, followups, outreach, assignment
from routes.meta import messenger, instagram

cfg = get_config()

app = FastAPI(title="Moving CRM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cfg["CORS_ORIGINS"].split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(companies.router)
app.include_router(users.router)
app.include_router(messenger.router)
app.include_router(instagram.router)
app.include_router(sms.router)
app.include_router(smartmoving.router)
app.include_router(followups.router)
app.include_router(outreach.router)
app.include_router(assignment.router)
app.include_router(system.router)
