"""
context_service.py — Aggregate relationship context for a recognized person.

WHY THIS EXISTS:
When the glasses recognize someone, we have ~855ms from tap to first audio.
This service assembles every relevant piece of context about that person
from multiple sources and formats it into a 2-3 sentence natural whisper
that GPT-4o generates.

CONTEXT SOURCES (in order of priority):
1. contacts table — name, company, title, relationship strength
2. interactions — last 3 meetings: venue, topics, sentiment
3. follow_ups — what do you owe this person? ("Send the MCP docs")
4. ThoughtVault vault — any vault entries mentioning them by name
5. Last seen — when and where you last encountered them

GPT-4o WHISPER SCRIPT EXAMPLES:
  "That's Sarah Kim from Sequoia. You met at the AI Summit in June.
   She backed two fintech startups. You were going to send her your pitch deck."

  "Marcus Chen, Anthropic research. Deep in tool use and MCP. You met twice —
   DevWorld in March, then virtually in August. Strong technical contact."

  "You haven't met this person yet — they're not in your network."

PERFORMANCE:
  Context aggregation: ~50ms (DB lookups with indexes)
  GPT-4o script generation: ~300ms (short prompt, gpt-4o-mini)
  ElevenLabs TTS: ~350ms
  Total: ~700ms (under the 855ms target)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from services.logger import get_logger

logger = get_logger(__name__)


@dataclass
class InteractionSummary:
    venue: str
    occurred_at: str
    topics: list[str]
    sentiment: str


@dataclass
class FollowUp:
    description: str
    due_date: Optional[str]
    status: str


@dataclass
class PersonContext:
    person_id: str
    display_name: str
    company: Optional[str]
    title: Optional[str]
    relationship_strength: int         # 1-5
    last_seen_at: Optional[str]
    recent_interactions: list[InteractionSummary]
    pending_follow_ups: list[FollowUp]
    vault_mentions: list[str]          # Relevant ThoughtVault excerpts
    tags: list[str]
    known: bool = True                 # False = person_id not found in contacts


class ContextService:
    """Aggregates multi-source context and generates GPT-4o whisper scripts."""

    def __init__(self):
        self._openai_client = None

    async def get_full_context(self, person_id: str, owner_id: str) -> PersonContext:
        """
        Pull context for a recognized person from all sources in parallel.
        """
        # Run DB queries in parallel
        contact_task = asyncio.create_task(self._fetch_contact(person_id, owner_id))
        interactions_task = asyncio.create_task(self._fetch_recent_interactions(person_id, owner_id))
        follow_ups_task = asyncio.create_task(self._fetch_pending_follow_ups(person_id, owner_id))
        vault_task = asyncio.create_task(self._fetch_vault_mentions(person_id, owner_id))

        contact, interactions, follow_ups, vault = await asyncio.gather(
            contact_task, interactions_task, follow_ups_task, vault_task
        )

        if contact is None:
            return PersonContext(
                person_id=person_id,
                display_name="Unknown",
                company=None,
                title=None,
                relationship_strength=0,
                last_seen_at=None,
                recent_interactions=[],
                pending_follow_ups=[],
                vault_mentions=[],
                tags=[],
                known=False,
            )

        return PersonContext(
            person_id=person_id,
            display_name=contact["display_name"],
            company=contact.get("company"),
            title=contact.get("title"),
            relationship_strength=contact.get("relationship_strength", 1),
            last_seen_at=contact.get("last_seen_at"),
            recent_interactions=interactions,
            pending_follow_ups=follow_ups,
            vault_mentions=vault,
            tags=contact.get("tags", []),
            known=True,
        )

    async def generate_whisper_script(self, context: PersonContext) -> str:
        """
        GPT-4o generates a 2-3 sentence natural whisper script.
        Tone: casual, confident, like a personal assistant whispering context.
        """
        if not context.known:
            return "This person isn't in your network yet."

        client = self._get_openai_client()
        if client is None:
            # Fallback: template-based script
            return self._template_script(context)

        # Build context summary for GPT-4o
        context_lines = [
            f"Name: {context.display_name}",
            f"Company: {context.company or 'Unknown'}",
            f"Title: {context.title or 'Unknown'}",
            f"Relationship strength: {context.relationship_strength}/5",
        ]

        if context.recent_interactions:
            last = context.recent_interactions[0]
            context_lines.append(f"Last meeting: {last.venue}, {last.occurred_at}. Topics: {', '.join(last.topics[:3])}")
            if len(context.recent_interactions) > 1:
                context_lines.append(f"Total meetings: {len(context.recent_interactions)}")

        if context.pending_follow_ups:
            follow_up = context.pending_follow_ups[0]
            context_lines.append(f"Pending follow-up: {follow_up.description}")

        if context.vault_mentions:
            context_lines.append(f"Vault reference: {context.vault_mentions[0][:100]}")

        context_block = "\n".join(context_lines)

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a personal assistant whispering context about someone "
                                "the user is about to talk to. Speak in 2-3 sentences, casual, "
                                "confident, like a briefing whisper. Lead with the most important info. "
                                "No bullet points. No filler phrases like 'I should mention'."
                            )
                        },
                        {
                            "role": "user",
                            "content": f"Generate a whisper script for:\n{context_block}"
                        }
                    ],
                    max_tokens=100,
                    temperature=0.6,
                )
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("whisper_script_generation_failed", error=str(e))
            return self._template_script(context)

    def _template_script(self, context: PersonContext) -> str:
        """Fallback template when GPT-4o is unavailable."""
        script = f"That's {context.display_name}"
        if context.company:
            script += f" from {context.company}"
        script += "."

        if context.recent_interactions:
            last = context.recent_interactions[0]
            script += f" You met at {last.venue}."

        if context.pending_follow_ups:
            script += f" You were going to: {context.pending_follow_ups[0].description}."

        return script

    # ─── Data Fetchers (TODO: replace with real DB queries) ──────────────────

    async def _fetch_contact(self, person_id: str, owner_id: str) -> Optional[dict]:
        """Fetch contact record from DB. Returns None if not found."""
        # TODO: DB query
        # Demo data for testing:
        if person_id == "demo-person-001":
            return {
                "display_name": "Marcus Chen",
                "company": "Anthropic",
                "title": "Research Engineer",
                "relationship_strength": 3,
                "last_seen_at": "2026-02-15",
                "tags": ["technical", "ai", "mcp"],
            }
        return None

    async def _fetch_recent_interactions(self, person_id: str, owner_id: str) -> list[InteractionSummary]:
        """Fetch last 3 interactions from DB."""
        # TODO: DB query
        return []

    async def _fetch_pending_follow_ups(self, person_id: str, owner_id: str) -> list[FollowUp]:
        """Fetch pending follow-ups for this contact."""
        # TODO: DB query
        return []

    async def _fetch_vault_mentions(self, person_id: str, owner_id: str) -> list[str]:
        """Pull relevant ThoughtVault entries mentioning this person."""
        try:
            # TODO: call ThoughtVault RAG API with person display_name as query
            # vault_response = await thoughtvault_client.query(display_name)
            # return [entry["excerpt"] for entry in vault_response.get("results", [])]
            return []
        except Exception as e:
            logger.warning("vault_mention_fetch_failed", error=str(e))
            return []

    def _get_openai_client(self):
        if self._openai_client is not None:
            return self._openai_client
        try:
            import openai
            import os
            key = os.getenv("OPENAI_API_KEY")
            if key:
                self._openai_client = openai.OpenAI(api_key=key)
        except ImportError:
            pass
        return self._openai_client
