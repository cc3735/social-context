"""
interactions.py — Interaction history (meeting log) for enrolled contacts.

Every meeting is logged here. The ContextService reads the last 3-5 interactions
when generating the glasses whisper script, so quality of these logs directly
affects the quality of what gets whispered in your ear.

Sources: manual entry, PLAUD transcript sync, vault_sync (ThoughtVault), glasses-detected.
"""

import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.logger import get_logger

router = APIRouter(prefix="/api/v1/contacts", tags=["interactions"])
logger = get_logger(__name__)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class InteractionCreate(BaseModel):
    owner_user_id: str = "demo-owner-001"
    occurred_at: str                    # ISO 8601
    venue: str                          # "DevWorld Conference, San Francisco"
    summary: str                        # What was discussed
    topics: list[str] = []              # ["MCP servers", "Claude API"]
    sentiment: str = "neutral"          # "positive" | "neutral" | "negative"
    duration_minutes: Optional[int] = None
    source: str = "manual"             # "manual" | "glasses_detected" | "plaud_transcript" | "vault_sync"
    transcript_segment: Optional[str] = None


class InteractionResponse(BaseModel):
    id: str
    contact_id: str
    occurred_at: str
    venue: str
    summary: str
    topics: list[str]
    sentiment: str
    duration_minutes: Optional[int]
    source: str
    created_at: str


# ─── In-memory store ─────────────────────────────────────────────────────────

_interactions: dict[str, list[dict]] = {
    "demo-contact-001": [
        {
            "id": "demo-interaction-001",
            "contact_id": "demo-contact-001",
            "owner_user_id": "demo-owner-001",
            "occurred_at": "2026-02-15T14:00:00Z",
            "venue": "DevWorld Conference, San Francisco",
            "summary": "Discussed MCP server architecture and Claude's tool use capabilities",
            "topics": ["MCP servers", "tool use", "Claude API"],
            "sentiment": "positive",
            "duration_minutes": 25,
            "source": "manual",
            "transcript_segment": None,
            "created_at": "2026-02-15T18:00:00Z",
        },
        {
            "id": "demo-interaction-002",
            "contact_id": "demo-contact-001",
            "owner_user_id": "demo-owner-001",
            "occurred_at": "2026-03-01T10:00:00Z",
            "venue": "Virtual (Zoom)",
            "summary": "Follow-up call about the MCP documentation and integration patterns",
            "topics": ["MCP documentation", "integration", "meta-glasses-sdk"],
            "sentiment": "positive",
            "duration_minutes": 45,
            "source": "plaud_transcript",
            "transcript_segment": "He mentioned the meta-glasses-sdk integration was exactly what he needed.",
            "created_at": "2026-03-01T12:00:00Z",
        }
    ]
}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/{contact_id}/interactions", response_model=list[InteractionResponse])
async def list_interactions(contact_id: str, limit: int = 10):
    """List interaction history for a contact, newest first."""
    interactions = _interactions.get(contact_id, [])
    # Sort newest first
    sorted_interactions = sorted(interactions, key=lambda x: x["occurred_at"], reverse=True)
    return [_to_response(i) for i in sorted_interactions[:limit]]


@router.post("/{contact_id}/interactions", response_model=InteractionResponse, status_code=201)
async def create_interaction(contact_id: str, req: InteractionCreate):
    """Log a new meeting with a contact."""
    interaction_id = str(uuid.uuid4())
    interaction = {
        "id": interaction_id,
        "contact_id": contact_id,
        "owner_user_id": req.owner_user_id,
        "occurred_at": req.occurred_at,
        "venue": req.venue,
        "summary": req.summary,
        "topics": req.topics,
        "sentiment": req.sentiment,
        "duration_minutes": req.duration_minutes,
        "source": req.source,
        "transcript_segment": req.transcript_segment,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    if contact_id not in _interactions:
        _interactions[contact_id] = []
    _interactions[contact_id].append(interaction)

    logger.info(
        "interaction_logged",
        contact_id=contact_id,
        venue=req.venue,
        source=req.source,
    )
    return _to_response(interaction)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _to_response(i: dict) -> InteractionResponse:
    return InteractionResponse(
        id=i["id"],
        contact_id=i["contact_id"],
        occurred_at=i["occurred_at"],
        venue=i["venue"],
        summary=i["summary"],
        topics=i.get("topics", []),
        sentiment=i.get("sentiment", "neutral"),
        duration_minutes=i.get("duration_minutes"),
        source=i.get("source", "manual"),
        created_at=i.get("created_at", ""),
    )
