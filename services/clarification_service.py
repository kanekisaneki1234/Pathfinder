"""
Clarification Service — manages the extraction_flags lifecycle.

After a resume is ingested the LLM flags every uncertain interpretation.
This service:
  1. Stores flags in SQLite (extraction_flags table)
  2. Returns them as ordered clarification questions for the user
  3. Resolves each flag: confirmed (LLM was right) or corrected (user patches it)
  4. Applies corrections directly to Neo4j so the graph becomes the user's exact digital twin
  5. Marks the flag status and tracks what fraction of the graph is verified

Field path format: 'Type:Name:property'
  Skill:Python:level              → Skill node named Python, set .level
  Skill:Python:years              → Skill node named Python, set .years
  Project:PaymentAPI:contribution_type → Project node
  Domain:FinTech:depth            → Domain node
  Experience:Senior Eng at X:description → Experience node
  Assessment:overall_signal       → CriticalAssessment node
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from litellm import acompletion

from database.neo4j_client import Neo4jClient
from database.sqlite_client import SQLiteClient
from models.schemas import (
    ClarificationQuestion,
    ClarificationsResponse,
    InterpretationFlag,
    ResolveFlagResponse,
)
from services.weights import recompute_weights
from pydantic import BaseModel as _BaseModel
from typing import Literal as _Literal

class _InterpretResult(_BaseModel):
    interpreted_value: str
    is_complete: bool
    needs_clarification: str | None = None
    explanation: str
    confidence: _Literal["high", "medium", "low"]

logger = logging.getLogger(__name__)

# Properties that require recomputing weights when corrected
_WEIGHT_AFFECTING = {"level", "years", "years_experience", "depth", "evidence_strength"}

# Ordered impact levels for sorting
_IMPACT_ORDER = {"critical": 0, "important": 1, "minor": 2}


class ClarificationService:
    def __init__(self, neo4j: Neo4jClient, sqlite: SQLiteClient):
        self.neo4j = neo4j
        self.sqlite = sqlite

    # ── Storing flags ─────────────────────────────────────────────────────────

    async def store_flags(self, user_id: str, flags: list[InterpretationFlag]) -> int:
        """
        Persist all interpretation flags from an extraction run.
        Clears existing pending flags for this user first (re-ingest scenario).
        Returns the number of flags stored.
        """
        # Remove any previously pending flags (not yet resolved) for this user
        await self.sqlite.execute(
            "DELETE FROM extraction_flags WHERE user_id = ? AND status = 'pending'",
            (user_id,),
        )

        now = datetime.now(timezone.utc).isoformat()
        for flag in flags:
            await self.sqlite.execute(
                """
                INSERT INTO extraction_flags
                    (flag_id, user_id, field, raw_text, interpreted_as,
                     confidence, ambiguity_reason, clarification_question,
                     resolution_impact, suggested_options, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    flag.field,
                    flag.raw_text,
                    flag.interpreted_as,
                    flag.confidence,
                    flag.ambiguity_reason,
                    flag.clarification_question,
                    flag.resolution_impact,
                    json.dumps(flag.suggested_options) if flag.suggested_options else None,
                    now,
                ),
            )
        logger.info(f"Stored {len(flags)} extraction flags for user {user_id}")
        return len(flags)

    # ── Querying flags ────────────────────────────────────────────────────────

    async def get_clarifications(self, user_id: str) -> ClarificationsResponse:
        """Return all flags for a user, sorted by impact (critical first)."""
        rows = await self.sqlite.fetchall(
            "SELECT * FROM extraction_flags WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        )

        questions = sorted(
            [self._row_to_question(r) for r in rows],
            key=lambda q: (_IMPACT_ORDER.get(q.resolution_impact, 9), q.flag_id),
        )

        pending = [q for q in questions if q.status == "pending"]
        resolved = [q for q in questions if q.status != "pending"]
        critical_pending = [q for q in pending if q.resolution_impact == "critical"]

        return ClarificationsResponse(
            user_id=user_id,
            total_flags=len(questions),
            pending=len(pending),
            resolved=len(resolved),
            questions=questions,
            graph_verified=len(critical_pending) == 0 and len(questions) > 0,
        )

    # ── Resolving flags ───────────────────────────────────────────────────────

    async def resolve_flag(
        self,
        user_id: str,
        flag_id: str,
        is_correct: bool,
        user_answer: str,
        correction: str | None = None,
    ) -> ResolveFlagResponse:
        """
        Mark a flag as resolved.
        If is_correct=False and correction is provided, patch the Neo4j node.
        """
        row = await self.sqlite.fetchone(
            "SELECT * FROM extraction_flags WHERE flag_id = ? AND user_id = ?",
            (flag_id, user_id),
        )
        if not row:
            raise ValueError(f"Flag '{flag_id}' not found for user '{user_id}'")

        status = "confirmed" if is_correct else "corrected"
        now = datetime.now(timezone.utc).isoformat()
        graph_updated = False
        updated_field = updated_value = None

        if not is_correct and correction:
            graph_updated = await self._apply_correction(user_id, row["field"], correction)
            updated_field = row["field"]
            updated_value = correction

        await self.sqlite.execute(
            """
            UPDATE extraction_flags
            SET status = ?, user_answer = ?, correction_applied = ?, resolved_at = ?
            WHERE flag_id = ?
            """,
            (status, user_answer, correction if not is_correct else None, now, flag_id),
        )

        # Count remaining critical flags
        remaining_rows = await self.sqlite.fetchall(
            "SELECT 1 FROM extraction_flags WHERE user_id = ? AND status = 'pending' AND resolution_impact = 'critical'",
            (user_id,),
        )

        logger.info(
            f"Flag {flag_id} resolved as '{status}' for user {user_id}. "
            f"Graph updated: {graph_updated}"
        )
        return ResolveFlagResponse(
            flag_id=flag_id,
            status=status,
            graph_updated=graph_updated,
            updated_field=updated_field,
            updated_value=updated_value,
            remaining_critical=len(remaining_rows),
        )

    async def skip_flag(self, user_id: str, flag_id: str) -> None:
        """Mark a flag as skipped (user chose not to answer)."""
        await self.sqlite.execute(
            "UPDATE extraction_flags SET status = 'skipped', resolved_at = ? WHERE flag_id = ? AND user_id = ?",
            (datetime.now(timezone.utc).isoformat(), flag_id, user_id),
        )

    async def interpret_answer(
        self,
        user_id: str,
        flag_id: str,
        user_answer: str,
    ) -> dict:
        """
        Takes the user's natural language answer for a flag, calls LLM to interpret it
        into a structured value. Returns the interpretation WITHOUT saving to graph yet.

        The caller should show the interpretation to the user for confirmation.
        Only call resolve_flag() once the user confirms the interpretation is correct.

        Returns dict with keys:
          interpreted_value: str  — the concrete value to store (e.g. "intermediate", "3.5")
          is_complete: bool       — False if answer is still too vague to save
          needs_clarification: str|None — follow-up question if is_complete=False
          explanation: str        — "I understood this to mean..."
          confidence: str         — high/medium/low
        """
        row = await self.sqlite.fetchone(
            "SELECT * FROM extraction_flags WHERE flag_id = ? AND user_id = ?",
            (flag_id, user_id),
        )
        if not row:
            raise ValueError(f"Flag '{flag_id}' not found")

        model = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")

        import json as _json
        schema = _json.dumps(_InterpretResult.model_json_schema(), indent=2)

        system_msg = (
            "You are a precise data interpreter helping build a professional knowledge graph. "
            "A user has answered a clarification question in natural language. "
            "Your job is to:\n"
            "1. Interpret the answer into a concrete, storable value for the specific field\n"
            "2. Assess whether the answer is specific enough to save (is_complete)\n"
            "3. If too vague, generate a targeted follow-up question\n"
            "4. Write a clear explanation of what you understood\n\n"
            "RULES:\n"
            "- 'is_complete=false' if the answer is vague, contradictory, or still ambiguous\n"
            "- For enum fields (level, depth, contribution_type), the interpreted_value must be one of the valid options\n"
            "- For numeric fields (years), extract the number or flag as incomplete if unclear\n"
            "- Be strict: 'I think about 3-4 years' is incomplete — ask them to commit to a number\n"
            "- 'I mostly did it myself' is incomplete — ask if they were the sole engineer or had team members\n"
            f"\nReturn ONLY valid JSON matching: {schema}"
        )

        user_msg = (
            f"FIELD BEING CLARIFIED: {row['field']}\n"
            f"ORIGINAL RESUME TEXT: \"{row['raw_text']}\"\n"
            f"PREVIOUS AI INTERPRETATION: {row['interpreted_as']}\n"
            f"CLARIFICATION QUESTION ASKED: {row['clarification_question']}\n\n"
            f"USER'S ANSWER: {user_answer}\n\n"
            "Interpret this answer. If it's still vague, set is_complete=false and provide "
            "a specific follow-up question that will get a concrete answer."
        )

        resp = await acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw = resp.choices[0].message.content
        result = _InterpretResult.model_validate_json(raw)
        return result.model_dump()

    # ── Graph patch ───────────────────────────────────────────────────────────

    async def _apply_correction(self, user_id: str, field: str, correction: str) -> bool:
        """
        Parse the field path and apply the correction to the appropriate Neo4j node.
        Returns True if a graph update was executed.

        Field format: 'Type:Name:property'
        Examples:
          Skill:Python:level              → set Skill.level
          Project:PaymentAPI:contribution_type → set Project.contribution_type
          Domain:FinTech:depth            → set Domain.depth
          Experience:Senior Eng:accomplishments → set Experience.accomplishments (as JSON)
        """
        parts = field.split(":", 2)
        if len(parts) < 3:
            logger.warning(f"Cannot parse field path '{field}' — expected Type:Name:property")
            return False

        node_type, node_name, prop = parts[0], parts[1], parts[2]
        needs_reweight = prop in _WEIGHT_AFFECTING

        # Coerce value to correct Python type before writing
        value = self._coerce_value(prop, correction)

        # Special case: accomplishments stored as JSON array
        if prop == "accomplishments" and isinstance(value, str):
            # If user provides comma-separated list, wrap it
            value = json.dumps([s.strip() for s in correction.split("|") if s.strip()])

        await self.neo4j.run_write(
            f"MATCH (n:{node_type} {{name: $name, user_id: $user_id}}) SET n.{prop} = $value, n.verified = true",
            {"name": node_name, "user_id": user_id, "value": value},
        )

        if needs_reweight:
            await recompute_weights(user_id, self.neo4j)

        return True

    def _coerce_value(self, prop: str, raw: str):
        """Coerce the correction string to the right Python type for Neo4j."""
        float_props = {"years", "years_experience", "duration_years"}
        bool_props = {"has_measurable_impact"}
        if prop in float_props:
            try:
                return float(raw)
            except ValueError:
                return raw
        if prop in bool_props:
            return raw.lower() in ("true", "yes", "1")
        return raw

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_question(row: dict) -> ClarificationQuestion:
        opts = None
        if row.get("suggested_options"):
            try:
                opts = json.loads(row["suggested_options"])
            except Exception:
                pass
        return ClarificationQuestion(
            flag_id=row["flag_id"],
            field=row["field"],
            raw_text=row["raw_text"],
            interpreted_as=row["interpreted_as"],
            confidence=row["confidence"],
            ambiguity_reason=row["ambiguity_reason"],
            clarification_question=row["clarification_question"],
            resolution_impact=row["resolution_impact"],
            suggested_options=opts,
            status=row["status"],
        )
