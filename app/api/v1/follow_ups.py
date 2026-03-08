"""
follow_ups.py — Pending follow-up items for enrolled contacts.

Follow-ups are what you owe someone or what you promised to do.
They're surfaced in the glasses whisper script when you recognize the person.
Example: "You were going to send him your MCP server documentation."

Status flow: pending → completed | snoozed
"""

import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.logger import get_logger

router = APIRouter(tags=["follow_ups"])
logger = get_logger(__name__)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class FollowUpCreate(BaseModel):
    owner_user_id: str = "demo-owner-001"
    description: str                        # "Send MCP server documentation"
    due_date: Optional[str] = None          # ISO 8601 date
    source_interaction_id: Optional[str] = None


class FollowUpUpdate(BaseModel):
    status: str                             # "completed" | "snoozed" | "pending"
    description: Optional[str] = None
    due_date: Optional[str] = None


class FollowUpResponse(BaseModel):
    id: str
    contact_id: str
    description: str
    due_date: Optional[str]
    status: str
    source_interaction_id: Optional[str]
    completed_at: Optional[str]
    created_at: str


# ─── In-memory store ─────────────────────────────────────────────────────────

_follow_ups: dict[str, list[dict]] = {
    "demo-contact-001": [
        {
            "id": "demo-followup-001",
            "contact_id": "demo-contact-001",
            "owner_user_id": "demo-owner-001",
            "description": "Send MCP server documentation and meta-glasses-sdk integration guide",
            "due_date": "2026-03-15",
            "status": "pending",
            "source_interaction_id": "demo-interaction-002",
            "completed_at": None,
            "created_at": "2026-03-01T12:00:00Z",
        }
    ]
}

# All follow-ups across all contacts (for the global list)
_all_follow_ups: dict[str, dict] = {
    "demo-followup-001": _follow_ups["demo-contact-001"][0]
}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/api/v1/follow-ups", response_model=list[FollowUpResponse])
async def list_all_follow_ups(owner_user_id: str = "demo-owner-001", status: str = "pending"):
    """List all pending follow-ups across all contacts."""
    follow_ups = [
        f for f in _all_follow_ups.values()
        if f.get("owner_user_id") == owner_user_id and f.get("status") == status
    ]
    return [_to_response(f) for f in follow_ups]


@router.get("/api/v1/contacts/{contact_id}/follow-ups", response_model=list[FollowUpResponse])
async def list_contact_follow_ups(contact_id: str, status: Optional[str] = None):
    """List follow-ups for a specific contact."""
    follow_ups = _follow_ups.get(contact_id, [])
    if status:
        follow_ups = [f for f in follow_ups if f.get("status") == status]
    return [_to_response(f) for f in follow_ups]


@router.post("/api/v1/contacts/{contact_id}/follow-ups", response_model=FollowUpResponse, status_code=201)
async def create_follow_up(contact_id: str, req: FollowUpCreate):
    """Add a follow-up item for a contact."""
    follow_up_id = str(uuid.uuid4())
    follow_up = {
        "id": follow_up_id,
        "contact_id": contact_id,
        "owner_user_id": req.owner_user_id,
        "description": req.description,
        "due_date": req.due_date,
        "status": "pending",
        "source_interaction_id": req.source_interaction_id,
        "completed_at": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    if contact_id not in _follow_ups:
        _follow_ups[contact_id] = []
    _follow_ups[contact_id].append(follow_up)
    _all_follow_ups[follow_up_id] = follow_up

    logger.info("follow_up_created", contact_id=contact_id, description=req.description)
    return _to_response(follow_up)


@router.put("/api/v1/follow-ups/{follow_up_id}", response_model=FollowUpResponse)
async def update_follow_up(follow_up_id: str, req: FollowUpUpdate):
    """Complete or snooze a follow-up."""
    follow_up = _all_follow_ups.get(follow_up_id)
    if not follow_up:
        raise HTTPException(status_code=404, detail="Follow-up not found")

    follow_up["status"] = req.status
    if req.description:
        follow_up["description"] = req.description
    if req.due_date:
        follow_up["due_date"] = req.due_date
    if req.status == "completed":
        follow_up["completed_at"] = datetime.utcnow().isoformat() + "Z"

    logger.info("follow_up_updated", follow_up_id=follow_up_id, status=req.status)
    return _to_response(follow_up)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _to_response(f: dict) -> FollowUpResponse:
    return FollowUpResponse(
        id=f["id"],
        contact_id=f["contact_id"],
        description=f["description"],
        due_date=f.get("due_date"),
        status=f.get("status", "pending"),
        source_interaction_id=f.get("source_interaction_id"),
        completed_at=f.get("completed_at"),
        created_at=f.get("created_at", ""),
    )
