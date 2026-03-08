"""
main.py — Social Context Assistant FastAPI application.

WHY THIS EXISTS:
Human memory is unreliable at scale. In professional life, you meet dozens
of people per month. Each conversation builds context. But 3 months later
at a conference — you remember the face but not what they work on or what
you promised to follow up on.

The glasses see who you're looking at. Your vault knows everything you've
captured about them. The glasses whisper the context before you speak.
You walk into every conversation knowing everything.

PRIVACY ARCHITECTURE:
  ZERO face biometric data ever leaves the device.
  All face recognition runs on-device via MediaPipe (React Native/WASM).
  This server receives only: person_id (UUID) + confidence score.
  The face embedding that identified them never touches our servers.
  This design is GDPR/CCPA compliant by construction.

ENROLLMENT:
  Bilateral and explicit. Both people must agree:
  Person B shows a QR code → Person A scans it → face embedding stored ONLY
  on Person A's device (Android Keystore). Server stores: name, company,
  notes, interaction history — no biometric data.

DEPLOYED: social.thoughtvault.ai → Azure VM → port 8004
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import glasses, contacts, interactions, enrollment, follow_ups
from services.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("social_context_startup")
    yield
    logger.info("social_context_shutdown")


app = FastAPI(
    title="Social Context API",
    description="On-device face recognition + server-side relationship context for smart glasses.",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(glasses.router)       # /api/v1/glasses/*
app.include_router(contacts.router)      # /api/v1/contacts/*
app.include_router(interactions.router)  # /api/v1/contacts/{id}/interactions
app.include_router(enrollment.router)    # /api/v1/enrollment/*
app.include_router(follow_ups.router)    # /api/v1/follow-ups/*


@app.get("/health")
def health():
    return {"status": "ok", "service": "social-context"}
