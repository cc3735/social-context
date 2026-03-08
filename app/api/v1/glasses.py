"""
glasses.py — Primary glasses endpoints for Social Context Assistant.

Glasses tap → on-device MediaPipe recognition → person_id returned to companion app
→ companion calls POST /recognize → we fetch context → GPT-4o-mini whisper script
→ ElevenLabs TTS → companion plays through glasses speakers.

Privacy guarantee: face embeddings NEVER reach this server.
Only person_id (UUID) is transmitted after on-device match.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.context_service import ContextService
from services.tts_service import SocialTTSService
from services.glasses_session_service import GlassesSessionService
from services.logger import get_logger

router = APIRouter(prefix="/api/v1/glasses", tags=["glasses"])
logger = get_logger(__name__)

context_service = ContextService()
tts_service = SocialTTSService()
session_service = GlassesSessionService()

# Connected WebSocket sessions: session_id → WebSocket
_active_ws: dict[str, WebSocket] = {}


# ─── Request / Response Models ────────────────────────────────────────────────

class SessionStartRequest(BaseModel):
    device_fingerprint: str
    owner_user_id: str = "demo-owner-001"


class SessionStartResponse(BaseModel):
    session_id: str
    session_token: str
    contact_count: int
    greeting_tts_base64: Optional[str] = None


class RecognitionRequest(BaseModel):
    session_id: str
    person_id: str              # From on-device MediaPipe match — NOT a face embedding
    confidence: float           # Cosine similarity from on-device comparison (0-1)
    trigger_type: str = "double_tap"  # "double_tap" | "voice_command"


class RecognitionResponse(BaseModel):
    matched: bool
    person_id: str
    display_name: Optional[str] = None
    tts_script: Optional[str] = None
    tts_audio_base64: Optional[str] = None
    context: Optional[dict] = None


class SessionEndResponse(BaseModel):
    recognitions_today: int
    context_served_count: int
    session_duration_seconds: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/session/start", response_model=SessionStartResponse)
async def start_session(req: SessionStartRequest):
    """
    Register glasses device and open a Social Context session.
    Returns session token for WebSocket auth and approximate contact count.
    """
    session_id = str(uuid.uuid4())
    session_token = str(uuid.uuid4())

    session_service.create_session(
        session_id=session_id,
        session_token=session_token,
        device_fingerprint=req.device_fingerprint,
        owner_user_id=req.owner_user_id,
    )

    # TODO: count contacts from DB for this owner
    contact_count = 0

    logger.info(
        "glasses_session_started",
        session_id=session_id,
        device=req.device_fingerprint,
    )

    return SessionStartResponse(
        session_id=session_id,
        session_token=session_token,
        contact_count=contact_count,
    )


@router.post("/recognize", response_model=RecognitionResponse)
async def recognize(req: RecognitionRequest):
    """
    Core recognition endpoint. Called after on-device MediaPipe match.

    The companion app:
    1. Captures a frame (tap-triggered)
    2. Runs MediaPipe face embedding (on-device)
    3. Compares embedding to enrolled embeddings in Android Keystore
    4. If match found → sends person_id + confidence here (NOT the embedding)
    5. We fetch full context → generate whisper script → return TTS audio

    Privacy: only person_id crosses the network. Face biometric stays on device.

    Gate: confidence < 0.75 → refuse to generate context (prevent false positives)
    """
    if not session_service.is_valid(req.session_id):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Confidence gate — don't serve context for uncertain matches
    if req.confidence < 0.75:
        logger.info(
            "recognition_confidence_too_low",
            confidence=req.confidence,
            person_id=req.person_id,
        )
        tts_script = "Recognition confidence too low. Try again directly facing the person."
        tts_audio = await tts_service.synthesize(tts_script, urgency="low")
        return RecognitionResponse(
            matched=False,
            person_id=req.person_id,
            tts_script=tts_script,
            tts_audio_base64=tts_audio,
        )

    session = session_service.get_session(req.session_id)
    owner_id = session["owner_user_id"]

    # Fetch full context from all sources in parallel
    context = await context_service.get_full_context(req.person_id, owner_id)

    # Generate whisper script
    tts_script = await context_service.generate_whisper_script(context)

    # Synthesize TTS
    tts_audio = await tts_service.synthesize(tts_script, urgency="low")

    # Update session stats
    session_service.record_recognition(req.session_id, served_context=context.known)

    logger.info(
        "recognition_served",
        person_id=req.person_id,
        known=context.known,
        confidence=req.confidence,
    )

    context_dict = None
    if context.known:
        context_dict = {
            "display_name": context.display_name,
            "company": context.company,
            "title": context.title,
            "relationship_strength": context.relationship_strength,
            "last_seen_at": context.last_seen_at,
            "pending_follow_ups": len(context.pending_follow_ups),
            "tags": context.tags,
        }

    return RecognitionResponse(
        matched=context.known,
        person_id=req.person_id,
        display_name=context.display_name if context.known else None,
        tts_script=tts_script,
        tts_audio_base64=tts_audio,
        context=context_dict,
    )


@router.websocket("/session/{session_id}/stream")
async def glasses_stream(websocket: WebSocket, session_id: str):
    """
    Bidirectional WebSocket stream for Social Context glasses session.

    Client → Server:
      { "type": "recognition_request", "person_id": "...", "confidence": 0.92 }
      { "type": "voice_command", "command": "add_note|log_meeting|follow_up", "person_id": "..." }
      { "type": "ping" }

    Server → Client:
      { "type": "context_response", "tts_script": "...", "tts_audio_base64": "...", "contact": {...} }
      { "type": "command_ack", "action": "...", "tts_script": "..." }
      { "type": "error", "message": "..." }
      { "type": "pong" }
    """
    if not session_service.is_valid(session_id):
        await websocket.close(code=4001, reason="Invalid session")
        return

    await websocket.accept()
    _active_ws[session_id] = websocket
    session = session_service.get_session(session_id)
    owner_id = session["owner_user_id"]

    logger.info("glasses_ws_connected", session_id=session_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "recognition_request":
                person_id = data.get("person_id")
                confidence = float(data.get("confidence", 0))

                if confidence < 0.75:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Recognition confidence below threshold",
                        "tts_script": "Confidence too low — try again.",
                    })
                    continue

                context = await context_service.get_full_context(person_id, owner_id)
                tts_script = await context_service.generate_whisper_script(context)
                tts_audio = await tts_service.synthesize(tts_script, urgency="low")
                session_service.record_recognition(session_id, served_context=context.known)

                await websocket.send_json({
                    "type": "context_response",
                    "person_id": person_id,
                    "matched": context.known,
                    "display_name": context.display_name if context.known else None,
                    "tts_script": tts_script,
                    "tts_audio_base64": tts_audio,
                    "contact": {
                        "company": context.company,
                        "title": context.title,
                        "relationship_strength": context.relationship_strength,
                        "pending_follow_ups": len(context.pending_follow_ups),
                    } if context.known else None,
                })

            elif msg_type == "voice_command":
                command = data.get("command")
                person_id = data.get("person_id")

                ack_script = _handle_voice_command(command, person_id)
                tts_audio = await tts_service.synthesize(ack_script, urgency="low")

                await websocket.send_json({
                    "type": "command_ack",
                    "action": command,
                    "tts_script": ack_script,
                    "tts_audio_base64": tts_audio,
                })

    except WebSocketDisconnect:
        logger.info("glasses_ws_disconnected", session_id=session_id)
    finally:
        _active_ws.pop(session_id, None)


@router.post("/session/{session_id}/end", response_model=SessionEndResponse)
async def end_session(session_id: str):
    """End a glasses session and return stats."""
    if not session_service.is_valid(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    session = session_service.get_session(session_id)
    started_at = session.get("started_at", datetime.now(timezone.utc))
    duration = int((datetime.now(timezone.utc) - started_at).total_seconds())

    stats = session_service.end_session(session_id)

    logger.info(
        "glasses_session_ended",
        session_id=session_id,
        duration_seconds=duration,
        recognitions=stats.get("recognitions_attempted", 0),
    )

    return SessionEndResponse(
        recognitions_today=stats.get("recognitions_attempted", 0),
        context_served_count=stats.get("recognitions_successful", 0),
        session_duration_seconds=duration,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _handle_voice_command(command: str, person_id: Optional[str]) -> str:
    """Map voice commands to confirmation scripts."""
    if command == "add_note":
        return "Ready for your note. Speak now."
    elif command == "log_meeting":
        return "Logging meeting. Where did you meet and what did you discuss?"
    elif command == "follow_up":
        return "What follow-up do you want to add?"
    elif command == "who_is_this":
        return "Scanning — look directly at the person."
    else:
        return f"Command received: {command}."
