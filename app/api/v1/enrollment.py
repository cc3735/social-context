"""
enrollment.py — QR-based bilateral enrollment flow.

HOW IT WORKS:
  1. Person B generates an enrollment token → QR code shown on their phone
  2. Person A scans the QR code with the companion app
  3. Companion app redeems the token → gets person_id back
  4. Companion app captures Person B's face → runs MediaPipe embedding (ON DEVICE)
  5. Embedding stored in Android Keystore (never leaves device)
  6. Server stores: person_id, display_name, company (NO FACE DATA)
  7. Person B gets notified: "You've been enrolled as a contact"

This flow ensures:
  - Consent: Person B explicitly generated the QR code to share
  - Privacy: Face biometric stored only in Android Keystore on Person A's device
  - Auditability: Person B can see who has enrolled them

Tokens expire after 15 minutes (ENROLLMENT_TOKEN_TTL_MINUTES).
One-time use only.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.logger import get_logger

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])
logger = get_logger(__name__)

ENROLLMENT_TOKEN_TTL_MINUTES = 15


# ─── Schemas ─────────────────────────────────────────────────────────────────

class GenerateTokenRequest(BaseModel):
    """The person who generates this token IS the subject to be enrolled."""
    person_id: str
    display_name: str
    company: Optional[str] = None
    title: Optional[str] = None


class GenerateTokenResponse(BaseModel):
    token: str
    qr_payload: str               # Compact string for QR code generation
    expires_at: str
    person_id: str


class RedeemTokenRequest(BaseModel):
    """
    Person A (the enroller) redeems the token.
    NOTE: face_embedding is NOT sent here — it stays on-device in Android Keystore.
    The companion app handles embedding storage AFTER getting back person_id.
    """
    token: str
    enroller_user_id: str = "demo-owner-001"


class RedeemTokenResponse(BaseModel):
    success: bool
    person_id: str
    display_name: str
    company: Optional[str]
    title: Optional[str]
    # Companion app uses person_id to:
    # 1. Store face embedding in Keystore keyed by person_id
    # 2. Create a contact record via POST /api/v1/contacts


# ─── In-memory token store ────────────────────────────────────────────────────

_tokens: dict[str, dict] = {}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/generate-token", response_model=GenerateTokenResponse)
async def generate_token(req: GenerateTokenRequest):
    """
    Generate a one-time enrollment QR token.
    Called by the SUBJECT (Person B) — the person who will be recognized.
    """
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ENROLLMENT_TOKEN_TTL_MINUTES)

    _tokens[token] = {
        "person_id": req.person_id,
        "display_name": req.display_name,
        "company": req.company,
        "title": req.title,
        "expires_at": expires_at,
        "used": False,
        "used_by": None,
        "created_at": datetime.now(timezone.utc),
    }

    # QR payload: compact JSON for QR encoding
    qr_payload = f"sc://enroll?token={token}&pid={req.person_id}&name={req.display_name}"

    logger.info(
        "enrollment_token_generated",
        person_id=req.person_id,
        display_name=req.display_name,
        expires_at=expires_at.isoformat(),
    )

    return GenerateTokenResponse(
        token=token,
        qr_payload=qr_payload,
        expires_at=expires_at.isoformat(),
        person_id=req.person_id,
    )


@router.post("/redeem", response_model=RedeemTokenResponse)
async def redeem_token(req: RedeemTokenRequest):
    """
    Redeem an enrollment token.
    Called by the ENROLLER (Person A) — the person who will do the recognizing.

    After this returns, the companion app must:
    1. Capture Person B's face with camera
    2. Run MediaPipe face embedding (on-device)
    3. Store embedding in Android Keystore keyed by person_id
    4. Call POST /api/v1/contacts to create server-side contact record
    """
    token_data = _tokens.get(req.token)

    if not token_data:
        raise HTTPException(status_code=404, detail="Invalid enrollment token")

    if token_data["used"]:
        raise HTTPException(status_code=409, detail="Enrollment token already used")

    now = datetime.now(timezone.utc)
    if now > token_data["expires_at"]:
        raise HTTPException(
            status_code=410,
            detail=f"Enrollment token expired at {token_data['expires_at'].isoformat()}"
        )

    # Mark as used
    token_data["used"] = True
    token_data["used_by"] = req.enroller_user_id
    token_data["used_at"] = now

    logger.info(
        "enrollment_token_redeemed",
        person_id=token_data["person_id"],
        enroller=req.enroller_user_id,
    )

    return RedeemTokenResponse(
        success=True,
        person_id=token_data["person_id"],
        display_name=token_data["display_name"],
        company=token_data.get("company"),
        title=token_data.get("title"),
    )


@router.get("/token-status/{token}")
async def get_token_status(token: str):
    """Check if a token is still valid (for QR display countdown timer)."""
    token_data = _tokens.get(token)
    if not token_data:
        return {"valid": False, "reason": "not_found"}

    if token_data["used"]:
        return {"valid": False, "reason": "used"}

    now = datetime.now(timezone.utc)
    if now > token_data["expires_at"]:
        return {"valid": False, "reason": "expired"}

    remaining_seconds = int((token_data["expires_at"] - now).total_seconds())
    return {
        "valid": True,
        "remaining_seconds": remaining_seconds,
        "person_id": token_data["person_id"],
    }
