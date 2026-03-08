"""
glasses_session_service.py — In-memory glasses session management for Social Context.

Tracks active sessions: device fingerprint → session token → owner_user_id.
Records recognition stats for post-session audit.
"""

from datetime import datetime, timezone
from typing import Optional
from services.logger import get_logger

logger = get_logger(__name__)

# session_id → session dict
_sessions: dict[str, dict] = {}


class GlassesSessionService:
    """In-memory session store. Replace with DB-backed sessions in production."""

    def create_session(
        self,
        session_id: str,
        session_token: str,
        device_fingerprint: str,
        owner_user_id: str,
    ) -> dict:
        session = {
            "session_id": session_id,
            "session_token": session_token,
            "device_fingerprint": device_fingerprint,
            "owner_user_id": owner_user_id,
            "started_at": datetime.now(timezone.utc),
            "ended_at": None,
            "recognitions_attempted": 0,
            "recognitions_successful": 0,
        }
        _sessions[session_id] = session
        return session

    def is_valid(self, session_id: str) -> bool:
        session = _sessions.get(session_id)
        if not session:
            return False
        return session.get("ended_at") is None

    def get_session(self, session_id: str) -> Optional[dict]:
        return _sessions.get(session_id)

    def record_recognition(self, session_id: str, served_context: bool) -> None:
        session = _sessions.get(session_id)
        if not session:
            return
        session["recognitions_attempted"] += 1
        if served_context:
            session["recognitions_successful"] += 1

    def end_session(self, session_id: str) -> dict:
        session = _sessions.get(session_id)
        if not session:
            return {}
        session["ended_at"] = datetime.now(timezone.utc)
        return {
            "recognitions_attempted": session["recognitions_attempted"],
            "recognitions_successful": session["recognitions_successful"],
        }

    def get_active_sessions(self) -> list[dict]:
        return [s for s in _sessions.values() if s.get("ended_at") is None]
