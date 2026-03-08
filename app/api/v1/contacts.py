"""
contacts.py — Contact management endpoints for Social Context Assistant.

Contacts are the people you've enrolled for recognition.
They're linked by person_id (UUID), not by face data (which stays on-device).
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from services.logger import get_logger

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])
logger = get_logger(__name__)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    person_id: str
    owner_user_id: str
    display_name: str
    company: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []


class ContactUpdate(BaseModel):
    display_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    relationship_strength: Optional[int] = None


class ContactResponse(BaseModel):
    id: str
    person_id: str
    display_name: str
    company: Optional[str]
    title: Optional[str]
    email: Optional[str]
    tags: list[str]
    relationship_strength: int
    enrolled_at: str
    last_seen_at: Optional[str]


# ─── In-memory store (TODO: replace with Supabase DB queries) ─────────────────

_contacts: dict[str, dict] = {
    "demo-contact-001": {
        "id": "demo-contact-001",
        "person_id": "demo-person-001",
        "owner_user_id": "demo-owner-001",
        "display_name": "Marcus Chen",
        "company": "Anthropic",
        "title": "Research Engineer",
        "email": "marcus@anthropic.com",
        "linkedin_url": None,
        "notes": "Deep in tool use and MCP servers. Great contact for AI infra.",
        "tags": ["technical", "ai", "mcp"],
        "relationship_strength": 3,
        "enrolled_at": "2026-01-15T10:00:00Z",
        "last_seen_at": "2026-02-15T14:00:00Z",
    }
}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[ContactResponse])
async def list_contacts(owner_user_id: str = "demo-owner-001"):
    """List all enrolled contacts for this owner."""
    contacts = [
        c for c in _contacts.values()
        if c.get("owner_user_id") == owner_user_id
    ]
    return [_to_response(c) for c in contacts]


@router.post("", response_model=ContactResponse, status_code=201)
async def create_contact(req: ContactCreate):
    """Create a contact record manually (not via QR enrollment)."""
    import uuid
    contact_id = str(uuid.uuid4())
    contact = {
        "id": contact_id,
        "person_id": req.person_id,
        "owner_user_id": req.owner_user_id,
        "display_name": req.display_name,
        "company": req.company,
        "title": req.title,
        "email": req.email,
        "linkedin_url": req.linkedin_url,
        "notes": req.notes,
        "tags": req.tags,
        "relationship_strength": 1,
        "enrolled_at": datetime.utcnow().isoformat() + "Z",
        "last_seen_at": None,
    }
    _contacts[contact_id] = contact
    logger.info("contact_created", contact_id=contact_id, display_name=req.display_name)
    return _to_response(contact)


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(contact_id: str):
    """Get a contact by ID."""
    contact = _contacts.get(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return _to_response(contact)


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(contact_id: str, req: ContactUpdate):
    """Update a contact's details."""
    contact = _contacts.get(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    if req.display_name is not None:
        contact["display_name"] = req.display_name
    if req.company is not None:
        contact["company"] = req.company
    if req.title is not None:
        contact["title"] = req.title
    if req.email is not None:
        contact["email"] = req.email
    if req.notes is not None:
        contact["notes"] = req.notes
    if req.tags is not None:
        contact["tags"] = req.tags
    if req.relationship_strength is not None:
        contact["relationship_strength"] = max(1, min(5, req.relationship_strength))

    return _to_response(contact)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: str):
    """
    Delete contact record from server.
    NOTE: caller must also delete face embedding from Android Keystore on-device.
    """
    if contact_id not in _contacts:
        raise HTTPException(status_code=404, detail="Contact not found")
    del _contacts[contact_id]
    logger.info("contact_deleted", contact_id=contact_id)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _to_response(c: dict) -> ContactResponse:
    return ContactResponse(
        id=c["id"],
        person_id=c["person_id"],
        display_name=c["display_name"],
        company=c.get("company"),
        title=c.get("title"),
        email=c.get("email"),
        tags=c.get("tags", []),
        relationship_strength=c.get("relationship_strength", 1),
        enrolled_at=c.get("enrolled_at", ""),
        last_seen_at=c.get("last_seen_at"),
    )
