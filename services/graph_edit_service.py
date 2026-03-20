"""
Graph Edit Service — orchestrates edit sessions, LLM conversation, mutation application,
and auto-checkpointing.

Edit session lifecycle:
  start_session  → creates SQLite session row, calls LLM for opening question
  send_message   → appends to history, calls LLM for next proposal
  apply_mutations → auto-checkpoints, runs Cypher mutations, re-links, re-visualizes
  reject_mutations → logs rejection, LLM generates follow-up
  get_history    → returns full conversation from SQLite
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from database.neo4j_client import Neo4jClient
from database.sqlite_client import SQLiteClient
from models.schemas import (
    ApplyMutationsRequest,
    ApplyMutationsResponse,
    EditSessionMessage,
    EditSessionResponse,
    GraphMutation,
    GraphMutationProposal,
)
from services.checkpoint_service import CheckpointService
from services.llm_edit_agent import LLMEditAgent

logger = logging.getLogger(__name__)


class GraphEditService:
    def __init__(self, neo4j: Neo4jClient, sqlite: SQLiteClient, output_dir: str = "./outputs"):
        self.neo4j = neo4j
        self.sqlite = sqlite
        self.output_dir = output_dir
        self.agent = LLMEditAgent(neo4j, sqlite)
        self.checkpoint_svc = CheckpointService(neo4j, sqlite, output_dir)

    # ── Session management ────────────────────────────────────────────────────

    async def start_session(
        self, entity_type: str, entity_id: str, recruiter_id: str | None = None
    ) -> EditSessionResponse:
        """
        Open a new edit session. For job sessions, verifies recruiter ownership.
        Inserts a row into edit_sessions, then gets the opening LLM question.
        """
        if entity_type == "job" and recruiter_id:
            rows = await self.neo4j.run_query(
                "MATCH (j:Job {id: $job_id}) RETURN j.recruiter_id AS rid",
                {"job_id": entity_id},
            )
            if not rows:
                raise ValueError(f"Job '{entity_id}' not found")
            if rows[0]["rid"] and rows[0]["rid"] != recruiter_id:
                raise PermissionError(f"Recruiter '{recruiter_id}' does not own job '{entity_id}'")

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self.sqlite.execute(
            """
            INSERT INTO edit_sessions
                (session_id, entity_type, entity_id, recruiter_id, started_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, entity_type, entity_id, recruiter_id, now, now),
        )

        proposal = await self.agent.get_opening_question(session_id, entity_type, entity_id)
        graph_summary = await self.agent._get_graph_summary(entity_type, entity_id)

        logger.info(f"Edit session started: {session_id} for {entity_type}:{entity_id}")
        return EditSessionResponse(
            session_id=session_id,
            opening_question=proposal.follow_up_question,
            graph_summary=graph_summary,
        )

    async def send_message(
        self, session_id: str, message: str
    ) -> GraphMutationProposal:
        """Append user message to history, call LLM, return next proposal."""
        session = await self._get_session(session_id)
        await self._touch_session(session_id)
        proposal = await self.agent.get_next_question(
            session_id, session["entity_type"], session["entity_id"], message
        )
        return proposal

    async def apply_mutations(
        self, session_id: str, mutations: GraphMutation
    ) -> ApplyMutationsResponse:
        """
        Auto-checkpoint, apply Cypher mutations, re-link matches, recompute weights,
        re-generate visualization. Returns counts of changes made.
        """
        session = await self._get_session(session_id)
        entity_type = session["entity_type"]
        entity_id = session["entity_id"]

        # Auto-checkpoint before any change
        checkpoint = await self.checkpoint_svc.create_checkpoint(
            entity_type,
            entity_id,
            label=f"auto_before_{session_id[:8]}",
            session_id=session_id,
        )

        nodes_added = nodes_updated = nodes_removed = edges_added = 0

        for node_spec in mutations.add_nodes:
            await self._add_node(entity_type, entity_id, node_spec)
            nodes_added += 1

        for node_spec in mutations.update_nodes:
            await self._update_node(entity_type, entity_id, node_spec)
            nodes_updated += 1

        for name in mutations.remove_nodes:
            await self._remove_node(entity_type, entity_id, name)
            nodes_removed += 1

        for edge_spec in mutations.add_edges:
            await self._add_edge(entity_type, entity_id, edge_spec)
            edges_added += 1

        # Re-link MATCHES edges and recompute weights
        from services.llm_ingestion import LLMIngestionService
        from services.weights import recompute_weights
        from services.visualization import VisualizationService

        ingestor = LLMIngestionService(self.neo4j)
        viz = VisualizationService(self.neo4j, self.output_dir)

        if entity_type == "user":
            await ingestor.link_skill_matches(entity_id)
            await ingestor.link_domain_matches(entity_id)
            await recompute_weights(entity_id, self.neo4j)
            await viz.generate_user_graph(entity_id)
        else:
            await ingestor.link_job_skill_matches(entity_id)
            await ingestor.link_job_domain_matches(entity_id)
            await viz.generate_job_graph(entity_id)

        await self._touch_session(session_id)
        logger.info(
            f"Mutations applied for {entity_type}:{entity_id} — "
            f"+{nodes_added} nodes, ~{nodes_updated} updated, -{nodes_removed} removed, "
            f"+{edges_added} edges. Checkpoint: {checkpoint.version_id}"
        )
        return ApplyMutationsResponse(
            auto_checkpoint_version_id=checkpoint.version_id,
            nodes_added=nodes_added,
            nodes_updated=nodes_updated,
            nodes_removed=nodes_removed,
            edges_added=edges_added,
        )

    async def reject_mutations(self, session_id: str) -> GraphMutationProposal:
        """Log rejection and ask LLM for a follow-up question."""
        session = await self._get_session(session_id)
        now = datetime.now(timezone.utc).isoformat()
        await self.sqlite.execute(
            """
            INSERT INTO session_messages (session_id, role, content, proposal_json, created_at)
            VALUES (?, 'system', 'mutations_rejected', NULL, ?)
            """,
            (session_id, now),
        )
        # Ask LLM to continue the interview despite rejection
        proposal = await self.agent.get_next_question(
            session_id,
            session["entity_type"],
            session["entity_id"],
            "I'd like to skip those changes and talk about something else.",
        )
        await self._touch_session(session_id)
        return proposal

    async def get_history(self, session_id: str) -> list[EditSessionMessage]:
        """Return full conversation history for a session."""
        rows = await self.sqlite.fetchall(
            """
            SELECT role, content, proposal_json
            FROM session_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        )
        result = []
        for row in rows:
            from models.schemas import GraphMutationProposal
            proposal = None
            if row["proposal_json"]:
                try:
                    proposal = GraphMutationProposal.model_validate_json(row["proposal_json"])
                except Exception:
                    pass
            result.append(
                EditSessionMessage(role=row["role"], content=row["content"], proposal=proposal)
            )
        return result

    # ── Mutation helpers ──────────────────────────────────────────────────────

    async def _add_node(self, entity_type: str, entity_id: str, spec: dict) -> None:
        label = spec.get("label", "Skill")
        name = spec.get("name", "")
        id_key = "user_id" if entity_type == "user" else "job_id"

        if label == "Skill" and entity_type == "user":
            family = spec.get("family", "Other")
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (cat:SkillCategory {name: 'Skills', user_id: $entity_id})
                MERGE (u)-[:HAS_SKILL_CATEGORY]->(cat)
                MERGE (fam:SkillFamily {name: $family, user_id: $entity_id})
                SET fam.source = 'user_edit'
                MERGE (cat)-[:HAS_SKILL_FAMILY]->(fam)
                MERGE (s:Skill {name: $name, user_id: $entity_id})
                SET s.years             = $years,
                    s.level             = $level,
                    s.evidence_strength = $evidence_strength,
                    s.source            = 'user_edit'
                MERGE (fam)-[:HAS_SKILL]->(s)
                """,
                {
                    "entity_id": entity_id,
                    "family": family,
                    "name": name,
                    "years": spec.get("years"),
                    "level": spec.get("level"),
                    "evidence_strength": spec.get("evidence_strength"),
                },
            )
        elif label == "Domain" and entity_type == "user":
            family = spec.get("family", "Other")
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (cat:DomainCategory {name: 'Domains', user_id: $entity_id})
                MERGE (u)-[:HAS_DOMAIN_CATEGORY]->(cat)
                MERGE (fam:DomainFamily {name: $family, user_id: $entity_id})
                SET fam.source = 'user_edit'
                MERGE (cat)-[:HAS_DOMAIN_FAMILY]->(fam)
                MERGE (d:Domain {name: $name, user_id: $entity_id})
                SET d.years_experience = $years, d.depth = $depth, d.source = 'user_edit'
                MERGE (fam)-[:HAS_DOMAIN]->(d)
                """,
                {
                    "entity_id": entity_id,
                    "family": family,
                    "name": name,
                    "years": spec.get("years_experience"),
                    "depth": spec.get("depth"),
                },
            )
        elif label == "Project" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (cat:ProjectCategory {name: 'Projects', user_id: $entity_id})
                MERGE (u)-[:HAS_PROJECT_CATEGORY]->(cat)
                MERGE (p:Project {name: $name, user_id: $entity_id})
                SET p.description          = $description,
                    p.contribution_type    = $contribution_type,
                    p.has_measurable_impact = $has_measurable_impact,
                    p.source               = 'user_edit'
                MERGE (cat)-[:HAS_PROJECT]->(p)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "description": spec.get("description", ""),
                    "contribution_type": spec.get("contribution_type"),
                    "has_measurable_impact": spec.get("has_measurable_impact", False),
                },
            )
        elif label == "Anecdote" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (a:Anecdote {name: $name, user_id: $entity_id})
                SET a.situation        = $situation,
                    a.task             = $task,
                    a.action           = $action,
                    a.result           = $result,
                    a.lesson_learned   = $lesson_learned,
                    a.emotion_valence  = $emotion_valence,
                    a.confidence_signal = $confidence_signal,
                    a.spontaneous      = $spontaneous,
                    a.source           = 'conversation'
                MERGE (u)-[:HAS_ANECDOTE]->(a)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "situation": spec.get("situation"),
                    "task": spec.get("task"),
                    "action": spec.get("action"),
                    "result": spec.get("result"),
                    "lesson_learned": spec.get("lesson_learned"),
                    "emotion_valence": spec.get("emotion_valence"),
                    "confidence_signal": spec.get("confidence_signal"),
                    "spontaneous": spec.get("spontaneous", False),
                },
            )
        elif label == "Motivation" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (m:Motivation {name: $name, user_id: $entity_id})
                SET m.category = $category,
                    m.strength = $strength,
                    m.evidence = $evidence,
                    m.source   = 'conversation'
                MERGE (u)-[:MOTIVATED_BY]->(m)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "category": spec.get("category"),
                    "strength": spec.get("strength"),
                    "evidence": spec.get("evidence"),
                },
            )
        elif label == "Value" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (v:Value {name: $name, user_id: $entity_id})
                SET v.priority_rank = $priority_rank,
                    v.evidence      = $evidence,
                    v.source        = 'conversation'
                MERGE (u)-[:HOLDS_VALUE]->(v)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "priority_rank": spec.get("priority_rank"),
                    "evidence": spec.get("evidence"),
                },
            )
        elif label == "Goal" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (g:Goal {name: $name, user_id: $entity_id})
                SET g.type            = $type,
                    g.description     = $description,
                    g.timeframe_years = $timeframe_years,
                    g.clarity_level   = $clarity_level,
                    g.source          = 'conversation'
                MERGE (u)-[:ASPIRES_TO]->(g)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "type": spec.get("type"),
                    "description": spec.get("description"),
                    "timeframe_years": spec.get("timeframe_years"),
                    "clarity_level": spec.get("clarity_level"),
                },
            )
        elif label == "CultureIdentity" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (c:CultureIdentity {name: $name, user_id: $entity_id})
                SET c.team_size_preference = $team_size_preference,
                    c.leadership_style     = $leadership_style,
                    c.conflict_style       = $conflict_style,
                    c.feedback_preference  = $feedback_preference,
                    c.energy_sources       = $energy_sources,
                    c.energy_drains        = $energy_drains,
                    c.pace_preference      = $pace_preference,
                    c.source               = 'conversation'
                MERGE (u)-[:HAS_CULTURE_IDENTITY]->(c)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "team_size_preference": spec.get("team_size_preference"),
                    "leadership_style": spec.get("leadership_style"),
                    "conflict_style": spec.get("conflict_style"),
                    "feedback_preference": spec.get("feedback_preference"),
                    "energy_sources": json.dumps(spec.get("energy_sources", [])),
                    "energy_drains": json.dumps(spec.get("energy_drains", [])),
                    "pace_preference": spec.get("pace_preference"),
                },
            )
        elif label == "BehavioralInsight" and entity_type == "user":
            await self.neo4j.run_write(
                """
                MATCH (u:User {id: $entity_id})
                MERGE (b:BehavioralInsight {name: $name, user_id: $entity_id})
                SET b.insight_type      = $insight_type,
                    b.trigger           = $trigger,
                    b.response_pattern  = $response_pattern,
                    b.implication       = $implication,
                    b.source            = 'conversation'
                MERGE (u)-[:HAS_BEHAVIORAL_INSIGHT]->(b)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "insight_type": spec.get("insight_type"),
                    "trigger": spec.get("trigger"),
                    "response_pattern": spec.get("response_pattern"),
                    "implication": spec.get("implication"),
                },
            )
        # ── Job-specific deep profile nodes ───────────────────────────────────

        elif label == "JobSkillRequirement" and entity_type == "job":
            family = spec.get("family", "Other")
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (req_cat:JobSkillRequirements {job_id: $entity_id})
                MERGE (j)-[:HAS_SKILL_REQUIREMENTS]->(req_cat)
                MERGE (fam:JobSkillFamily {name: $family, job_id: $entity_id})
                MERGE (req_cat)-[:HAS_SKILL_FAMILY_REQ]->(fam)
                MERGE (r:JobSkillRequirement {name: $name, job_id: $entity_id})
                SET r.importance = $importance,
                    r.min_years  = $min_years,
                    r.required   = $required,
                    r.source     = 'recruiter_edit'
                MERGE (fam)-[:REQUIRES_SKILL]->(r)
                """,
                {
                    "entity_id": entity_id,
                    "family": family,
                    "name": name,
                    "importance": spec.get("importance", "must_have"),
                    "min_years": spec.get("min_years"),
                    "required": spec.get("required", True),
                },
            )
        elif label == "JobDomainRequirement" and entity_type == "job":
            family = spec.get("family", "Other")
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (req_cat:JobDomainRequirements {job_id: $entity_id})
                MERGE (j)-[:HAS_DOMAIN_REQUIREMENTS]->(req_cat)
                MERGE (fam:JobDomainFamily {name: $family, job_id: $entity_id})
                MERGE (req_cat)-[:HAS_DOMAIN_FAMILY_REQ]->(fam)
                MERGE (d:JobDomainRequirement {name: $name, job_id: $entity_id})
                SET d.min_years = $min_years,
                    d.source    = 'recruiter_edit'
                MERGE (fam)-[:REQUIRES_DOMAIN]->(d)
                """,
                {
                    "entity_id": entity_id,
                    "family": family,
                    "name": name,
                    "min_years": spec.get("min_years"),
                },
            )
        elif label == "WorkStyle" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (cc:JobCultureRequirements {job_id: $entity_id})
                MERGE (j)-[:HAS_CULTURE_REQUIREMENTS]->(cc)
                MERGE (w:WorkStyle {style: $style, job_id: $entity_id})
                SET w.source = 'recruiter_edit'
                MERGE (cc)-[:HAS_WORK_STYLE]->(w)
                """,
                {"entity_id": entity_id, "style": name},
            )
        elif label == "TeamComposition" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (t:TeamComposition {name: $name, job_id: $entity_id})
                SET t.team_size         = $team_size,
                    t.team_makeup       = $team_makeup,
                    t.reporting_to      = $reporting_to,
                    t.hiring_for_gap    = $hiring_for_gap,
                    t.existing_strengths = $existing_strengths,
                    t.source            = 'conversation'
                MERGE (j)-[:HAS_TEAM_COMPOSITION]->(t)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "team_size": spec.get("team_size"),
                    "team_makeup": spec.get("team_makeup"),
                    "reporting_to": spec.get("reporting_to"),
                    "hiring_for_gap": spec.get("hiring_for_gap"),
                    "existing_strengths": spec.get("existing_strengths"),
                },
            )
        elif label == "RoleContext" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (r:RoleContext {name: $name, job_id: $entity_id})
                SET r.first_30_days      = $first_30_days,
                    r.first_90_days      = $first_90_days,
                    r.owns_what          = $owns_what,
                    r.reports_to         = $reports_to,
                    r.growth_trajectory  = $growth_trajectory,
                    r.why_role_open      = $why_role_open,
                    r.source             = 'conversation'
                MERGE (j)-[:HAS_ROLE_CONTEXT]->(r)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "first_30_days": spec.get("first_30_days"),
                    "first_90_days": spec.get("first_90_days"),
                    "owns_what": spec.get("owns_what"),
                    "reports_to": spec.get("reports_to"),
                    "growth_trajectory": spec.get("growth_trajectory"),
                    "why_role_open": spec.get("why_role_open"),
                },
            )
        elif label == "HiringGoal" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (h:HiringGoal {name: $name, job_id: $entity_id})
                SET h.urgency             = $urgency,
                    h.timeline            = $timeline,
                    h.gap_being_filled    = $gap_being_filled,
                    h.ideal_background    = $ideal_background,
                    h.dealbreaker_absence = $dealbreaker_absence,
                    h.source              = 'conversation'
                MERGE (j)-[:DRIVEN_BY]->(h)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "urgency": spec.get("urgency"),
                    "timeline": spec.get("timeline"),
                    "gap_being_filled": spec.get("gap_being_filled"),
                    "ideal_background": spec.get("ideal_background"),
                    "dealbreaker_absence": spec.get("dealbreaker_absence"),
                },
            )
        elif label == "SoftSkillRequirement" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (s:SoftSkillRequirement {name: $name, job_id: $entity_id})
                SET s.quality            = $quality,
                    s.expectation        = $expectation,
                    s.evidence_indicator = $evidence_indicator,
                    s.dealbreaker        = $dealbreaker,
                    s.source             = 'conversation'
                MERGE (j)-[:REQUIRES_QUALITY]->(s)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "quality": spec.get("quality"),
                    "expectation": spec.get("expectation"),
                    "evidence_indicator": spec.get("evidence_indicator"),
                    "dealbreaker": spec.get("dealbreaker", False),
                },
            )
        elif label == "TeamCultureIdentity" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (c:TeamCultureIdentity {name: $name, job_id: $entity_id})
                SET c.decision_making      = $decision_making,
                    c.communication_style  = $communication_style,
                    c.feedback_culture     = $feedback_culture,
                    c.pace                 = $pace,
                    c.work_life            = $work_life,
                    c.management_style     = $management_style,
                    c.team_values          = $team_values,
                    c.anti_patterns        = $anti_patterns,
                    c.source               = 'conversation'
                MERGE (j)-[:HAS_TEAM_CULTURE]->(c)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "decision_making": spec.get("decision_making"),
                    "communication_style": spec.get("communication_style"),
                    "feedback_culture": spec.get("feedback_culture"),
                    "pace": spec.get("pace"),
                    "work_life": spec.get("work_life"),
                    "management_style": spec.get("management_style"),
                    "team_values": json.dumps(spec.get("team_values", [])),
                    "anti_patterns": json.dumps(spec.get("anti_patterns", [])),
                },
            )
        elif label == "SuccessMetric" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (m:SuccessMetric {name: $name, job_id: $entity_id})
                SET m.at_30_days       = $at_30_days,
                    m.at_90_days       = $at_90_days,
                    m.at_1_year        = $at_1_year,
                    m.key_deliverables = $key_deliverables,
                    m.how_measured     = $how_measured,
                    m.source           = 'conversation'
                MERGE (j)-[:DEFINES_SUCCESS_BY]->(m)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "at_30_days": spec.get("at_30_days"),
                    "at_90_days": spec.get("at_90_days"),
                    "at_1_year": spec.get("at_1_year"),
                    "key_deliverables": json.dumps(spec.get("key_deliverables", [])),
                    "how_measured": spec.get("how_measured"),
                },
            )
        elif label == "InterviewSignal" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (s:InterviewSignal {name: $name, job_id: $entity_id})
                SET s.signal_type        = $signal_type,
                    s.what_to_watch_for  = $what_to_watch_for,
                    s.why_it_matters     = $why_it_matters,
                    s.source             = 'conversation'
                MERGE (j)-[:SCREENS_FOR]->(s)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "signal_type": spec.get("signal_type"),
                    "what_to_watch_for": spec.get("what_to_watch_for"),
                    "why_it_matters": spec.get("why_it_matters"),
                },
            )
        elif label == "BehavioralInsight" and entity_type == "job":
            await self.neo4j.run_write(
                """
                MATCH (j:Job {id: $entity_id})
                MERGE (b:BehavioralInsight {name: $name, job_id: $entity_id})
                SET b.insight_type     = $insight_type,
                    b.trigger          = $trigger,
                    b.response_pattern = $response_pattern,
                    b.implication      = $implication,
                    b.source           = 'conversation'
                MERGE (j)-[:HAS_BEHAVIORAL_INSIGHT]->(b)
                """,
                {
                    "entity_id": entity_id,
                    "name": name,
                    "insight_type": spec.get("insight_type"),
                    "trigger": spec.get("trigger"),
                    "response_pattern": spec.get("response_pattern"),
                    "implication": spec.get("implication"),
                },
            )
        else:
            # Generic node: MERGE by name + entity_id, set all provided props
            props = {k: v for k, v in spec.items() if k not in ("label",) and v is not None}
            props["source"] = "user_edit"
            props[id_key] = entity_id
            await self.neo4j.run_write(
                f"MERGE (n:{label} {{name: $name, {id_key}: $entity_id}}) SET n += $props",
                {"name": name, "entity_id": entity_id, "props": props},
            )

    async def _update_node(self, entity_type: str, entity_id: str, spec: dict) -> None:
        label = spec.get("label")
        name = spec.get("name")
        props = {k: v for k, v in spec.items() if k not in ("label", "name") and v is not None}
        props["source"] = "user_edit"
        id_key = "user_id" if entity_type == "user" else "job_id"
        label_str = f":{label}" if label else ""
        await self.neo4j.run_write(
            f"MATCH (n{label_str} {{name: $name, {id_key}: $entity_id}}) SET n += $props",
            {"name": name, "entity_id": entity_id, "props": props},
        )

    async def _remove_node(self, entity_type: str, entity_id: str, name: str) -> None:
        id_key = "user_id" if entity_type == "user" else "job_id"
        if ":" in name:
            label, node_name = name.split(":", 1)
            await self.neo4j.run_write(
                f"MATCH (n:{label} {{name: $name, {id_key}: $entity_id}}) DETACH DELETE n",
                {"name": node_name, "entity_id": entity_id},
            )
        else:
            await self.neo4j.run_write(
                f"MATCH (n {{name: $name, {id_key}: $entity_id}}) DETACH DELETE n",
                {"name": name, "entity_id": entity_id},
            )

    async def _add_edge(self, entity_type: str, entity_id: str, edge_spec: dict) -> None:
        """Parse 'Type:name' refs, MERGE the edge, and write any 5W+H properties onto it."""
        def parse_ref(ref: str) -> tuple[str | None, str]:
            if ":" in ref:
                label, name = ref.split(":", 1)
                return label, name
            return None, ref

        from_label, from_name = parse_ref(edge_spec.get("from", ""))
        to_label, to_name = parse_ref(edge_spec.get("to", ""))
        rel_type = edge_spec.get("rel", "RELATES_TO")
        id_key = "user_id" if entity_type == "user" else "job_id"

        from_filter = f":{from_label}" if from_label else ""
        to_filter = f":{to_label}" if to_label else ""

        # Collect 5W+H edge properties (everything except structural keys)
        edge_props = {
            k: v for k, v in edge_spec.items()
            if k not in ("from", "to", "rel") and v is not None
        }

        if edge_props:
            await self.neo4j.run_write(
                f"""
                MATCH (a{from_filter} {{name: $from_name, {id_key}: $entity_id}})
                MATCH (b{to_filter} {{name: $to_name, {id_key}: $entity_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                SET r += $props
                """,
                {"from_name": from_name, "to_name": to_name, "entity_id": entity_id, "props": edge_props},
            )
        else:
            await self.neo4j.run_write(
                f"""
                MATCH (a{from_filter} {{name: $from_name, {id_key}: $entity_id}})
                MATCH (b{to_filter} {{name: $to_name, {id_key}: $entity_id}})
                MERGE (a)-[:{rel_type}]->(b)
                """,
                {"from_name": from_name, "to_name": to_name, "entity_id": entity_id},
            )

    async def _get_session(self, session_id: str) -> dict:
        row = await self.sqlite.fetchone(
            "SELECT * FROM edit_sessions WHERE session_id = ?", (session_id,)
        )
        if not row:
            raise ValueError(f"Edit session '{session_id}' not found")
        return row

    async def _touch_session(self, session_id: str) -> None:
        await self.sqlite.execute(
            "UPDATE edit_sessions SET last_active = ? WHERE session_id = ?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )
