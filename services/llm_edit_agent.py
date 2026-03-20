"""
LLM Edit Agent — First Principles interview loop for graph editing.

Uses LiteLLM with JSON mode to produce structured GraphMutationProposal
responses. Every turn:
  1. Load full conversation history from SQLite session_messages
  2. Build messages array (system + history + new user message)
  3. Call LLM with response_format={"type": "json_object"}
  4. Parse response as GraphMutationProposal
  5. Persist both user message and assistant proposal to session_messages
  6. Return the proposal
"""

import asyncio
import json
import logging
import os

from litellm import acompletion

from database.neo4j_client import Neo4jClient
from database.sqlite_client import SQLiteClient
from models.schemas import GraphMutation, GraphMutationProposal

logger = logging.getLogger(__name__)

_PROPOSAL_SCHEMA = json.dumps(GraphMutationProposal.model_json_schema(), indent=2)


class LLMEditAgent:
    def __init__(self, neo4j: Neo4jClient, sqlite: SQLiteClient):
        self._model = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
        self.neo4j = neo4j
        self.sqlite = sqlite

    async def get_opening_question(
        self, session_id: str, entity_type: str, entity_id: str
    ) -> GraphMutationProposal:
        """
        Generate the opening interview question for a new edit session.
        Loads graph summary from Neo4j, builds context, calls LLM, persists to SQLite.
        """
        graph_summary = await self._get_graph_summary(entity_type, entity_id)
        system_msg = self._build_system_prompt(graph_summary)
        if entity_type == "job":
            opening_user_msg = (
                "I want this job posting to actually reflect what we're looking for — "
                "not just a list of skills, but the real picture of the role, the team, "
                "and the kind of person who will thrive here. Ask me what you need to know."
            )
        else:
            opening_user_msg = (
                "I'm ready. I want this profile to be a true reflection of who I am — "
                "not just a list of technologies, but the real picture of how I work, what drives me, "
                "and where I'm headed. Ask me what you need to know."
            )

        raw_json = await self._call_with_retry(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": opening_user_msg},
            ]
        )
        proposal = GraphMutationProposal.model_validate_json(raw_json)

        # Persist the opening exchange
        await self._persist_message(session_id, "user", opening_user_msg, None)
        await self._persist_message(session_id, "assistant", proposal.follow_up_question, raw_json)
        return proposal

    async def get_next_question(
        self, session_id: str, entity_type: str, entity_id: str, user_message: str
    ) -> GraphMutationProposal:
        """
        Process a user reply and return the next proposal.
        Loads full history from SQLite, appends the new user message, calls LLM.
        """
        graph_summary = await self._get_graph_summary(entity_type, entity_id)
        system_msg = self._build_system_prompt(graph_summary)

        # Load conversation history
        history_rows = await self.sqlite.fetchall(
            "SELECT role, content FROM session_messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        messages = [{"role": "system", "content": system_msg}]
        for row in history_rows:
            if row["role"] in ("user", "assistant"):
                messages.append({"role": row["role"], "content": row["content"]})
        messages.append({"role": "user", "content": user_message})

        raw_json = await self._call_with_retry(messages=messages)
        proposal = GraphMutationProposal.model_validate_json(raw_json)

        # Persist
        await self._persist_message(session_id, "user", user_message, None)
        await self._persist_message(session_id, "assistant", proposal.follow_up_question, raw_json)
        return proposal

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_graph_summary(self, entity_type: str, entity_id: str) -> dict:
        """Fetch a rich 5W+H graph summary for the system prompt."""
        if entity_type == "user":
            skills = await self.neo4j.run_query(
                """
                MATCH (u:User {id: $id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                      -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                OPTIONAL MATCH (p:Project {user_id: $id})-[r:DEMONSTRATES_SKILL]->(s)
                RETURN s.name AS name,
                       coalesce(s.years, 0) AS years,
                       coalesce(s.level, 'unknown') AS level,
                       coalesce(s.evidence_strength, 'unknown') AS evidence_strength,
                       count(p) AS project_count,
                       collect(CASE WHEN r.context IS NOT NULL THEN r.context ELSE null END)[0..3] AS usage_contexts
                ORDER BY project_count ASC, years ASC
                """,
                {"id": entity_id},
            )
            domains = await self.neo4j.run_query(
                """
                MATCH (u:User {id: $id})-[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
                      -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
                RETURN d.name AS name,
                       coalesce(d.years_experience, 0) AS years,
                       coalesce(d.depth, 'unknown') AS depth
                ORDER BY years ASC
                """,
                {"id": entity_id},
            )
            projects = await self.neo4j.run_query(
                """
                MATCH (u:User {id: $id})-[:HAS_PROJECT_CATEGORY]->(:ProjectCategory)
                      -[:HAS_PROJECT]->(p:Project)
                OPTIONAL MATCH (p)-[r:DEMONSTRATES_SKILL]->(s:Skill)
                RETURN p.name AS name,
                       p.description AS description,
                       coalesce(p.contribution_type, 'unclear') AS contribution_type,
                       coalesce(p.has_measurable_impact, false) AS has_measurable_impact,
                       collect({skill: s.name, context: r.context, how: r.how, outcome: r.outcome}) AS skill_usages
                """,
                {"id": entity_id},
            )
            experiences = await self.neo4j.run_query(
                """
                MATCH (u:User {id: $id})-[:HAS_EXPERIENCE_CATEGORY]->(:ExperienceCategory)
                      -[:HAS_EXPERIENCE]->(e:Experience)
                RETURN e.title AS title,
                       e.company AS company,
                       coalesce(e.duration_years, 0) AS duration_years,
                       e.description AS description,
                       e.accomplishments AS accomplishments,
                       coalesce(e.contribution_type, 'unclear') AS contribution_type
                ORDER BY e.duration_years DESC
                """,
                {"id": entity_id},
            )
            assessment = await self.neo4j.run_query(
                """
                MATCH (u:User {id: $id})-[:HAS_ASSESSMENT]->(a:CriticalAssessment)
                RETURN a.overall_signal AS overall_signal,
                       a.seniority_assessment AS seniority_assessment,
                       a.candidate_identity AS candidate_identity,
                       a.honest_summary AS honest_summary,
                       a.red_flags AS red_flags,
                       a.inflated_skills AS inflated_skills,
                       a.interview_focus_areas AS interview_focus_areas
                """,
                {"id": entity_id},
            )
            return {
                "entity_type": "user",
                "entity_id": entity_id,
                "skills": skills,
                "domains": domains,
                "projects": projects,
                "experiences": experiences,
                "assessment": assessment[0] if assessment else None,
            }
        else:
            job_meta = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id}) RETURN j.title AS title, j.company AS company, "
                "j.remote_policy AS remote_policy, j.company_size AS company_size, "
                "j.experience_years_min AS experience_years_min",
                {"id": entity_id},
            )
            skill_reqs = await self.neo4j.run_query(
                """
                MATCH (j:Job {id: $id})-[:HAS_SKILL_REQUIREMENTS]->(:JobSkillRequirements)
                      -[:HAS_SKILL_FAMILY_REQ]->(:JobSkillFamily)
                      -[:REQUIRES_SKILL]->(r:JobSkillRequirement)
                RETURN r.name AS name, r.importance AS importance,
                       coalesce(r.min_years, 0) AS min_years
                ORDER BY r.importance DESC
                """,
                {"id": entity_id},
            )
            domain_reqs = await self.neo4j.run_query(
                """
                MATCH (j:Job {id: $id})-[:HAS_DOMAIN_REQUIREMENTS]->(:JobDomainRequirements)
                      -[:HAS_DOMAIN_FAMILY_REQ]->(:JobDomainFamily)
                      -[:REQUIRES_DOMAIN]->(d:JobDomainRequirement)
                RETURN d.name AS name, coalesce(d.min_years, 0) AS min_years
                """,
                {"id": entity_id},
            )
            work_styles = await self.neo4j.run_query(
                """
                MATCH (j:Job {id: $id})-[:HAS_CULTURE_REQUIREMENTS]->(:JobCultureRequirements)
                      -[:HAS_WORK_STYLE]->(w:WorkStyle)
                RETURN w.style AS style
                """,
                {"id": entity_id},
            )
            # Deep job profile nodes (populated via recruiter interview)
            team_composition = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:HAS_TEAM_COMPOSITION]->(t:TeamComposition) "
                "RETURN t.team_size AS team_size, t.team_makeup AS team_makeup, "
                "t.reporting_to AS reporting_to, t.hiring_for_gap AS hiring_for_gap, "
                "t.existing_strengths AS existing_strengths",
                {"id": entity_id},
            )
            role_context = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:HAS_ROLE_CONTEXT]->(r:RoleContext) "
                "RETURN r.first_30_days AS first_30_days, r.first_90_days AS first_90_days, "
                "r.owns_what AS owns_what, r.reports_to AS reports_to, "
                "r.growth_trajectory AS growth_trajectory, r.why_role_open AS why_role_open",
                {"id": entity_id},
            )
            hiring_goals = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:DRIVEN_BY]->(h:HiringGoal) "
                "RETURN h.urgency AS urgency, h.timeline AS timeline, "
                "h.gap_being_filled AS gap_being_filled, h.ideal_background AS ideal_background, "
                "h.dealbreaker_absence AS dealbreaker_absence",
                {"id": entity_id},
            )
            soft_skills = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:REQUIRES_QUALITY]->(s:SoftSkillRequirement) "
                "RETURN s.name AS name, s.quality AS quality, s.expectation AS expectation, "
                "s.evidence_indicator AS evidence_indicator, s.dealbreaker AS dealbreaker",
                {"id": entity_id},
            )
            team_culture = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:HAS_TEAM_CULTURE]->(c:TeamCultureIdentity) "
                "RETURN c.decision_making AS decision_making, "
                "c.communication_style AS communication_style, "
                "c.feedback_culture AS feedback_culture, c.pace AS pace, "
                "c.work_life AS work_life, c.management_style AS management_style, "
                "c.team_values AS team_values, c.anti_patterns AS anti_patterns",
                {"id": entity_id},
            )
            success_metrics = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:DEFINES_SUCCESS_BY]->(m:SuccessMetric) "
                "RETURN m.at_30_days AS at_30_days, m.at_90_days AS at_90_days, "
                "m.at_1_year AS at_1_year, m.key_deliverables AS key_deliverables, "
                "m.how_measured AS how_measured",
                {"id": entity_id},
            )
            interview_signals = await self.neo4j.run_query(
                "MATCH (j:Job {id: $id})-[:SCREENS_FOR]->(s:InterviewSignal) "
                "RETURN s.name AS name, s.signal_type AS signal_type, "
                "s.what_to_watch_for AS what_to_watch_for, s.why_it_matters AS why_it_matters",
                {"id": entity_id},
            )
            return {
                "entity_type": "job",
                "entity_id": entity_id,
                "meta": job_meta[0] if job_meta else {},
                "skill_requirements": skill_reqs,
                "domain_requirements": domain_reqs,
                "work_styles": [w["style"] for w in work_styles],
                "team_composition": team_composition[0] if team_composition else None,
                "role_context": role_context[0] if role_context else None,
                "hiring_goals": hiring_goals[0] if hiring_goals else None,
                "soft_skills": soft_skills,
                "team_culture": team_culture[0] if team_culture else None,
                "success_metrics": success_metrics[0] if success_metrics else None,
                "interview_signals": interview_signals,
            }

    def _build_system_prompt(self, graph_summary: dict) -> str:
        """Dispatch to the correct system prompt based on entity type."""
        if graph_summary.get("entity_type") == "job":
            return self._build_job_system_prompt(graph_summary)
        return self._build_user_system_prompt(graph_summary)

    def _build_user_system_prompt(self, graph_summary: dict) -> str:
        """Build the digital twin interview system prompt for candidate profiling."""
        assessment = graph_summary.get("assessment") or {}
        candidate_identity = assessment.get("candidate_identity", "")
        honest_summary = assessment.get("honest_summary", "")
        red_flags = assessment.get("red_flags", "[]")
        inflated_skills = assessment.get("inflated_skills", "[]")
        interview_focus_areas = assessment.get("interview_focus_areas", "[]")

        # Find weakest-evidenced skill to anchor first question
        skills = graph_summary.get("skills", [])
        weakest_note = ""
        probe_targets = []
        if skills:
            weakest = skills[0]
            evidence = weakest.get("evidence_strength", "unknown")
            weakest_note = (
                f"\nWEAKEST SKILL: '{weakest['name']}' "
                f"(claimed {weakest['years']} yrs / {weakest['level']}, "
                f"evidence_strength={evidence}, backed by {weakest.get('project_count', 0)} project(s))."
            )
            probe_targets = [
                s for s in skills
                if s.get("evidence_strength") in ("claimed_only", "mentioned_once", "unknown")
                or (s.get("level") in ("advanced", "expert") and s.get("project_count", 0) < 2)
            ]

        probe_list = "\n".join(
            f"  - {s['name']}: claimed {s['level']}/{s['years']}yrs but evidence_strength={s.get('evidence_strength','?')}"
            for s in probe_targets[:5]
        )

        return (
            "You are building a complete digital twin of a person — not just a skill list, but a living "
            "portrait of who they are: what drives them, how they think, what they have been through, "
            "and where they are going.\n\n"
            "You are a sincere, deeply curious interviewer. Your role is dual:\n"
            "  1. UNDERSTAND the person — their motivations, values, working style, aspirations, "
            "and the real stories behind their work\n"
            "  2. BUILD a knowledge graph (mutations) that reflects everything you learn\n\n"
            "This is NOT a resume validation exercise. It is a conversation.\n"
            "The recruiter who reads this profile will know not just WHAT this person has done, "
            "but WHO they are.\n\n"
            "EXISTING PROFILE CONTEXT:\n"
            f"CANDIDATE IDENTITY: {candidate_identity or '(not yet assessed)'}\n"
            f"HONEST SUMMARY: {honest_summary or '(not yet assessed)'}\n"
            f"RED FLAGS: {red_flags}\n"
            f"SKILLS NEEDING DEPTH: {inflated_skills}\n"
            f"PRIORITY AREAS TO EXPLORE: {interview_focus_areas}\n"
            f"{weakest_note}\n"
            + (f"\nSKILLS WITH LOW EVIDENCE VS CLAIMED LEVEL:\n{probe_list}\n" if probe_list else "")
            + "\n"
            "═══════════════════════════════════════════════════════\n"
            "INTERVIEW RULES — READ CAREFULLY\n"
            "═══════════════════════════════════════════════════════\n\n"
            "RULE 1 — THE WHY-LADDER: Never accept the first answer. Always go one level deeper.\n"
            "  When they add a skill, ask WHY before adding it.\n"
            "  'I use Kubernetes' → 'What brought Kubernetes into your world specifically?'\n"
            "  → 'What were you running before, and why wasn't that enough?'\n"
            "  → 'What did YOU personally configure, and what broke first?'\n"
            "  Keep asking why until you hit a genuine motivation or a concrete story.\n\n"
            "RULE 2 — COLLECT ANECDOTES: Every skill, every role, every decision has a story behind it.\n"
            "  When they tell you what they did, ask them to walk you through it.\n"
            "  You want the situation, their specific task, what they did, and what came out of it.\n"
            "  Capture this as an Anecdote node and link it to the relevant skill/project via GROUNDED_IN.\n"
            "  A story behind a skill is worth more to a recruiter than any claimed level.\n\n"
            "RULE 3 — INFER MOTIVATION FROM PATTERNS: Do not ask 'are you money-driven or passion-driven'.\n"
            "  Listen to what they choose to tell you. What are they proud of?\n"
            "  What made them leave jobs? What energizes vs drains them?\n"
            "  After 2-3 stories, you will know. Then create a Motivation node with your inference.\n\n"
            "RULE 4 — PUSH-BACK PROTOCOL: If they say 'just add it, don't ask why':\n"
            "  ADD the node first (so they feel heard), then gently redirect:\n"
            "  'Added. Is there a project on your profile where [skill] was central? I want that story.'\n"
            "  ALSO create a BehavioralInsight node recording the push-back — this is data.\n"
            "  The recruiter will see they avoided the question. That tells a story too.\n\n"
            "RULE 5 — ASPIRATION: At a natural point, ask about their future.\n"
            "  'Given everything you have told me — where are you actually trying to go?'\n"
            "  'Not the job title. What does success look like for you in 5 years?'\n"
            "  Capture this as a Goal node.\n\n"
            "RULE 6 — CULTURE IDENTITY: Look for patterns in how they describe teams and work environments.\n"
            "  'You mentioned doing this alone — do you prefer that? When do you need a team?'\n"
            "  'What kind of feedback helps you the most?'\n"
            "  'What would make you leave a well-paying job?'\n"
            "  Build a CultureIdentity node from these signals.\n\n"
            "RULE 7 — ONE QUESTION PER TURN: Always exactly one focused question. Never list multiple.\n"
            "  Let the answer lead you to the next question.\n\n"
            "RULE 8 — MINIMUM DEPTH: Stay on a topic for at least 3 exchanges before moving on.\n"
            "  Surface answers do not count. Only stop when you have a real story or clear signal.\n\n"
            "RULE 9 — DO NOT FLATTER: Never say 'great answer' or 'that is impressive'.\n"
            "  You are not validating them. You are understanding them.\n"
            "  Respond with curiosity and follow-up, not praise.\n\n"
            "RULE 10 — 5W+H FOR EVERY TECHNICAL CLAIM (the extraction skeleton):\n"
            "  WHO:   Were you the sole owner? Part of a team? What was your specific role?\n"
            "  WHAT:  What exactly did you build/design/ship? Be precise.\n"
            "  WHEN:  When? How long? What were the time and resource constraints?\n"
            "  WHERE: What company, scale, environment? How many users, what load?\n"
            "  WHY:   Why this approach? What problem did it solve? Why not the alternative?\n"
            "  HOW:   What specific pattern, technique, architecture did you use?\n"
            "  Use 5W+H as a checklist: if any dimension is missing, that is your next question.\n"
            "  Do not write a DEMONSTRATES_SKILL edge until you have at least WHAT, WHY, and HOW.\n\n"
            "RULE 11 — THE GRAPH IMPACT BANNER: Every turn, generate a graph_impact_banner.\n"
            "  Show the person exactly what their answer is updating in their digital twin.\n"
            "  Be specific: 'Your Kubernetes story upgraded evidence: mentioned_once → project_backed'\n"
            "  and 'New anecdote added — recruiters can now read the story behind this skill'.\n"
            "  If no mutations this turn, tell them what the follow-up answer will capture.\n\n"
            "RULE 12 — NEVER HALLUCINATE: If something is ambiguous, ask. Do not infer and guess.\n"
            "  A question is always better than a fabricated node.\n"
            "  If you are not certain about a value (years, level, ownership), leave it null "
            "and ask for it rather than assuming.\n\n"
            "═══════════════════════════════════════════════════════\n"
            "MENTAL MODELS FOR PROBING DEPTH\n"
            "═══════════════════════════════════════════════════════\n"
            "Apply these models to every answer before accepting it and moving on:\n\n"
            "FIRST PRINCIPLES — Strip away what they told you and ask: what is actually true here?\n"
            "  'You said you led the migration. What does lead mean in this context — "
            "did you make architectural decisions, or coordinate execution?'\n"
            "  Do not accept job titles or labels. Break them down to the actual actions.\n\n"
            "SECOND ORDER THINKING — Ask about the consequences of their decisions.\n"
            "  'That worked — what problems did it create downstream?'\n"
            "  'How did that architectural choice affect the team 6 months later?'\n"
            "  People who truly owned something know what broke because of their decisions.\n\n"
            "INVERSION — Ask what failure looks like to find what success really means.\n"
            "  'What would have gone wrong if you hadn't done this?'\n"
            "  'What almost made this fail?'\n"
            "  'What would make you never want to do this kind of work again?'\n"
            "  Inverting the question reveals values and judgment that direct questions hide.\n\n"
            "OCCAM'S RAZOR — When the story seems complex, look for the simpler truth.\n"
            "  If their explanation requires many qualifications, probe for the real answer.\n"
            "  'Set aside the team context for a moment. What did YOU specifically contribute?'\n"
            "  Complexity is sometimes a shield for vague ownership.\n\n"
            "CONTINUE PROBING UNTIL: The answer is specific enough to create mutations with "
            "confidence. If you cannot write a non-null, honest Anecdote or update evidence_strength "
            "based on the answer — you have not gone deep enough yet.\n\n"
            "CURRENT PROFILE STATE:\n"
            f"{json.dumps(graph_summary, indent=2)}\n\n"
            "═══════════════════════════════════════════════════════\n"
            "RESPONSE SCHEMA — return ONLY valid JSON\n"
            "═══════════════════════════════════════════════════════\n"
            f"{_PROPOSAL_SCHEMA}\n\n"
            "NODE FORMATS FOR add_nodes:\n"
            "  Skill:    {\"label\": \"Skill\", \"name\": \"...\", \"years\": 2, \"level\": \"intermediate\",\n"
            "             \"family\": \"Web Frameworks\", \"evidence_strength\": \"project_backed\"}\n"
            "  Domain:   {\"label\": \"Domain\", \"name\": \"...\", \"years_experience\": 2,\n"
            "             \"depth\": \"moderate\", \"family\": \"FinTech\"}\n"
            "  Project:  {\"label\": \"Project\", \"name\": \"...\", \"description\": \"...\",\n"
            "             \"contribution_type\": \"tech_lead\", \"has_measurable_impact\": true}\n"
            "  Anecdote: {\"label\": \"Anecdote\", \"name\": \"[short descriptive title e.g. K8s Migration at Stripe]\",\n"
            "             \"situation\": \"context and constraints\",\n"
            "             \"task\": \"what they were specifically responsible for\",\n"
            "             \"action\": \"what they actually did — be specific\",\n"
            "             \"result\": \"what came out of it, ideally measurable\",\n"
            "             \"lesson_learned\": \"what they took away from it\",\n"
            "             \"emotion_valence\": \"positive|negative|mixed\",\n"
            "             \"confidence_signal\": \"high|medium|low\",\n"
            "             \"spontaneous\": true}\n"
            "  Motivation: {\"label\": \"Motivation\", \"name\": \"[category_name]\",\n"
            "               \"category\": \"impact_driven|passion_driven|financial_security|"
            "wealth_accumulation|recognition_driven|stability_seeking|growth_seeking|autonomy_seeking\",\n"
            "               \"strength\": 0.8,\n"
            "               \"evidence\": \"brief quote or behavior that revealed this\"}\n"
            "  Value:    {\"label\": \"Value\", \"name\": \"[value name e.g. autonomy]\",\n"
            "             \"priority_rank\": 1,\n"
            "             \"evidence\": \"what they said or did that revealed this value\"}\n"
            "  Goal:     {\"label\": \"Goal\", \"name\": \"[short goal title]\",\n"
            "             \"type\": \"5_year|career_peak|immediate|life\",\n"
            "             \"description\": \"full description of the goal\",\n"
            "             \"timeframe_years\": 5,\n"
            "             \"clarity_level\": \"vague|directional|specific\"}\n"
            "  CultureIdentity: {\"label\": \"CultureIdentity\", \"name\": \"culture_profile\",\n"
            "                    \"team_size_preference\": \"solo|small_tight|large_structured\",\n"
            "                    \"leadership_style\": \"servant|directive|collaborative|invisible\",\n"
            "                    \"conflict_style\": \"direct|diplomatic|avoidant|analytical\",\n"
            "                    \"feedback_preference\": \"frequent_small|milestone_big|self_directed\",\n"
            "                    \"energy_sources\": [\"hard problems\", \"shipping\"],\n"
            "                    \"energy_drains\": [\"meetings\", \"politics\"],\n"
            "                    \"pace_preference\": \"sprint|steady|deliberate\"}\n"
            "  BehavioralInsight: {\"label\": \"BehavioralInsight\",\n"
            "                      \"name\": \"[short unique id e.g. push_back_k8s_mar2024]\",\n"
            "                      \"insight_type\": \"push_back|rehearsed_answer|deflection|"
            "spontaneous_depth|inconsistency|avoidance|openness\",\n"
            "                      \"trigger\": \"what question prompted this behavior\",\n"
            "                      \"response_pattern\": \"what they said or did\",\n"
            "                      \"implication\": \"what this signals about them as a person\"}\n\n"
            "EDGE FORMATS FOR add_edges:\n"
            "  DEMONSTRATES_SKILL — always include 5W+H:\n"
            "    {\"from\": \"Project:Name\", \"rel\": \"DEMONSTRATES_SKILL\", \"to\": \"Skill:Name\",\n"
            "     \"context\": \"one-sentence summary\",\n"
            "     \"what\": \"what was built\", \"how\": \"specific technique\",\n"
            "     \"why\": \"why this skill was used\", \"scale\": \"10k users/day\",\n"
            "     \"outcome\": \"reduced latency by 40%\"}\n"
            "  GROUNDED_IN — skill or project backed by a specific story:\n"
            "    {\"from\": \"Skill:Kubernetes\", \"rel\": \"GROUNDED_IN\", \"to\": \"Anecdote:Name\"}\n"
            "  REVEALS_TRAIT — anecdote that reveals a behavioral pattern:\n"
            "    {\"from\": \"Anecdote:Name\", \"rel\": \"REVEALS_TRAIT\", "
            "\"to\": \"ProblemSolvingPattern:pattern_name\"}\n\n"
            "update_nodes example (downgrading inflated skill after probing):\n"
            "  {\"label\": \"Skill\", \"name\": \"Kubernetes\", \"level\": \"intermediate\",\n"
            "   \"evidence_strength\": \"mentioned_once\"}\n"
            "remove_nodes: list of strings like \"Skill:GraphQL\" or just \"GraphQL\"\n\n"
            "GRAPH IMPACT BANNER FORMAT:\n"
            "  headline: '1-sentence summary of what this answer updated'\n"
            "  items: each item has icon (skill|anecdote|motivation|value|goal|culture|behavior|"
            "domain|project|experience), label, change_type (add|update|infer|flag|initiated), detail\n"
            "  Use 'initiated' only for the session-start banner when no graph changes have occurred yet.\n"
            "  digital_twin_progress: optional, e.g. 'Technical depth: 72% | Human depth: 31%'\n"
            "  Estimate human depth based on: anecdotes (30%), motivations/values (25%), "
            "goals (20%), culture identity (15%), behavioral insights (10%)"
        )

    def _build_job_system_prompt(self, graph_summary: dict) -> str:
        """Build the deep recruiter interview system prompt for job profile building."""
        meta = graph_summary.get("meta") or {}
        skill_reqs = graph_summary.get("skill_requirements", [])
        domain_reqs = graph_summary.get("domain_requirements", [])
        work_styles = graph_summary.get("work_styles", [])
        team_composition = graph_summary.get("team_composition")
        role_context = graph_summary.get("role_context")
        hiring_goals = graph_summary.get("hiring_goals")
        soft_skills = graph_summary.get("soft_skills", [])
        team_culture = graph_summary.get("team_culture")
        success_metrics = graph_summary.get("success_metrics")
        interview_signals = graph_summary.get("interview_signals", [])

        missing = []
        if not team_composition:
            missing.append("team composition (who is already on the team, what gap exists)")
        if not role_context:
            missing.append("role context (what this person will own, first 30/90 days)")
        if not hiring_goals:
            missing.append("hiring goal (why this role is open, urgency, dealbreakers)")
        if not soft_skills:
            missing.append("soft skill requirements (ownership, accountability, communication)")
        if not team_culture:
            missing.append("team culture (how the team actually works, management style)")
        if not success_metrics:
            missing.append("success definition (what does good look like at 30/90/180 days)")

        missing_note = (
            "\nPROFILE GAPS — these are critical missing sections to surface first:\n"
            + "\n".join(f"  - {m}" for m in missing)
            if missing else ""
        )

        return (
            "You are building a complete job profile — a digital twin of what this role actually is, "
            "not just a list of skill requirements.\n\n"
            "You are interviewing the RECRUITER, not the candidate. Your job is to understand:\n"
            "  1. WHY this role exists and what problem it solves for the team\n"
            "  2. WHO is already on the team and what gap this person fills\n"
            "  3. WHAT this person will truly own — not the job description, but the real expectations\n"
            "  4. HOW the team works — culture, decision-making, pace, management style\n"
            "  5. WHAT GOOD LOOKS LIKE — how success is measured at 30, 90, and 365 days\n"
            "  6. WHAT QUALITIES are actually non-negotiable (ownership, accountability, communication)\n\n"
            "Most job postings are vague checklists. This interview makes them honest.\n"
            "The candidate who reads this profile will know exactly what they are walking into.\n\n"
            "CURRENT JOB PROFILE:\n"
            f"Title: {meta.get('title', '(unknown)')}\n"
            f"Company: {meta.get('company', '(unknown)')}\n"
            f"Remote Policy: {meta.get('remote_policy', '(unknown)')}\n"
            f"Company Size: {meta.get('company_size', '(unknown)')}\n"
            f"Experience Min: {meta.get('experience_years_min', '(unknown)')} years\n"
            f"Skill Requirements ({len(skill_reqs)}): "
            f"{[s['name'] for s in skill_reqs[:8]]}\n"
            f"Domain Requirements: {[d['name'] for d in domain_reqs]}\n"
            f"Work Styles: {work_styles}\n"
            f"Soft Skills Captured: {[s['name'] for s in soft_skills]}\n"
            f"Team Composition: {team_composition or '(not yet captured)'}\n"
            f"Role Context: {role_context or '(not yet captured)'}\n"
            f"Hiring Goal: {hiring_goals or '(not yet captured)'}\n"
            f"Team Culture: {team_culture or '(not yet captured)'}\n"
            f"Success Metrics: {success_metrics or '(not yet captured)'}\n"
            f"Interview Signals: {interview_signals}\n"
            f"{missing_note}\n\n"
            "═══════════════════════════════════════════════════════\n"
            "INTERVIEW RULES FOR JOB PROFILING\n"
            "═══════════════════════════════════════════════════════\n\n"
            "RULE 1 — WHY-LADDER: Every requirement has a reason. Find it.\n"
            "  'We need Kubernetes experience' → 'Is someone building K8s or operating an existing setup?'\n"
            "  → 'What is running right now, and what breaks without this person?'\n"
            "  → 'Would you trade deep K8s knowledge for strong distributed systems instincts?'\n"
            "  Strip checkbox requirements down to actual problems the team needs solved.\n\n"
            "RULE 2 — THE TEAM FIRST: Before asking about skills, understand the team.\n"
            "  'Who will this person work with every day?'\n"
            "  'What does the team look like right now — seniority mix, strengths, gaps?'\n"
            "  'What does the person sitting next to this hire actually do?'\n"
            "  Capture this as a TeamComposition node.\n\n"
            "RULE 3 — OWNERSHIP CLARITY: Do not accept vague responsibility descriptions.\n"
            "  'Owns the backend' → 'What does own mean concretely — who reviews their PRs?'\n"
            "  → 'When something breaks at 2am, is it their pager?'\n"
            "  → 'Do they have authority to make architectural decisions without approval?'\n"
            "  The difference between 'owns' and 'contributes to' changes the entire hire.\n\n"
            "RULE 4 — SOFT SKILLS ARE BEHAVIORS: Do not accept abstract quality labels.\n"
            "  'Strong ownership' → 'Describe the last person on your team who had this.'\n"
            "  → 'What did they do that told you they had ownership?'\n"
            "  → 'What happened when someone DIDN'T have this quality?'\n"
            "  Capture each as a SoftSkillRequirement with evidence_indicator — not just a label.\n\n"
            "RULE 5 — WHAT GOOD LOOKS LIKE: Every role needs a definition of success.\n"
            "  'What does this person accomplish in their first 30 days?'\n"
            "  'What would you see at 90 days that tells you this was the right hire?'\n"
            "  'What would make you regret this hire 6 months from now?'\n"
            "  Capture this as a SuccessMetric node.\n\n"
            "RULE 6 — TEAM CULTURE (not company values): Dig into how the team actually works.\n"
            "  'How are technical decisions made on your team?'\n"
            "  'How often does your team meet, and for what?'\n"
            "  'How does your manager give feedback — and how often?'\n"
            "  'What kind of person has left your team, and why?'\n"
            "  Capture this as a TeamCultureIdentity node.\n\n"
            "RULE 7 — WHY IS THIS ROLE OPEN: Always establish this early.\n"
            "  Scaling? Replacement? New capability? Backfill?\n"
            "  'Is this a new role or did someone leave it?'\n"
            "  If replacement: 'What did the previous person struggle with?'\n"
            "  Capture this in HiringGoal.why_role_open.\n\n"
            "RULE 8 — INTERVIEW SIGNALS: Ask what the recruiter is watching for.\n"
            "  'What would make you reject someone who looks good on paper?'\n"
            "  'What green flags do you look for in the interview?'\n"
            "  Capture these as InterviewSignal nodes.\n\n"
            "RULE 9 — ONE QUESTION PER TURN. Let the answer lead you.\n\n"
            "RULE 10 — PUSH-BACK PROTOCOL: Same as candidate interviews.\n"
            "  If recruiter says 'just add communication skills' without context:\n"
            "  Add it, then redirect: 'Added. What does poor communication look like "
            "on your team — what actually goes wrong?'\n"
            "  Record a BehavioralInsight about the recruiter too.\n\n"
            "RULE 11 — NEVER HALLUCINATE: If you are not sure about team size, timeline, "
            "or any property — ask. Do not fill in a null with an assumption.\n\n"
            "═══════════════════════════════════════════════════════\n"
            "MENTAL MODELS FOR JOB PROBING\n"
            "═══════════════════════════════════════════════════════\n\n"
            "FIRST PRINCIPLES — Strip away the job description. What is the actual problem?\n"
            "  'If you couldn't hire anyone, what would break on your team in 3 months?'\n"
            "  That is the real requirement.\n\n"
            "SECOND ORDER THINKING — What will this hire cause downstream?\n"
            "  'How will the rest of the team change once this person joins?'\n"
            "  'Does hiring a senior here create a bottleneck for the juniors?'\n\n"
            "INVERSION — Ask what failure looks like.\n"
            "  'What made your last bad hire a bad hire?'\n"
            "  'What would make you fire this person in 6 months?'\n"
            "  'What would make them quit in 6 months?'\n"
            "  These questions surface the real culture and expectations better than any positive question.\n\n"
            "OCCAM'S RAZOR — Long requirement lists hide the real non-negotiables.\n"
            "  'You listed 12 requirements. If you could only keep 3, which ones?'\n"
            "  The answer tells you the actual job.\n\n"
            "5W+H — Apply this to every skill requirement:\n"
            "  WHO uses this skill — the hire or the whole team?\n"
            "  WHAT is it used for — building, maintaining, or designing?\n"
            "  WHEN — daily, occasionally, or just at the start?\n"
            "  WHERE — in which part of the stack/product?\n"
            "  WHY — what breaks if they don't have it?\n"
            "  HOW deeply — deep expert or practical working knowledge?\n\n"
            "═══════════════════════════════════════════════════════\n"
            "CURRENT FULL PROFILE STATE:\n"
            "═══════════════════════════════════════════════════════\n"
            f"{json.dumps(graph_summary, indent=2)}\n\n"
            "RESPONSE SCHEMA — return ONLY valid JSON:\n"
            f"{_PROPOSAL_SCHEMA}\n\n"
            "JOB NODE FORMATS FOR add_nodes:\n"
            "  JobSkillRequirement: {\"label\": \"JobSkillRequirement\", \"name\": \"...\",\n"
            "                        \"importance\": \"must_have|nice_to_have\",\n"
            "                        \"min_years\": 3, \"required\": true,\n"
            "                        \"family\": \"Cloud & DevOps\"}\n"
            "  JobDomainRequirement: {\"label\": \"JobDomainRequirement\", \"name\": \"...\",\n"
            "                         \"min_years\": 2, \"family\": \"FinTech\"}\n"
            "  WorkStyle:  {\"label\": \"WorkStyle\", \"name\": \"async-first\"}\n"
            "  TeamComposition: {\"label\": \"TeamComposition\", \"name\": \"current_team\",\n"
            "                    \"team_size\": 6,\n"
            "                    \"team_makeup\": \"2 senior backend, 1 EM, 1 data eng, 2 frontend\",\n"
            "                    \"reporting_to\": \"VP Engineering\",\n"
            "                    \"hiring_for_gap\": \"no one owns observability and infra\",\n"
            "                    \"existing_strengths\": \"strong on distributed systems\"}\n"
            "  RoleContext: {\"label\": \"RoleContext\", \"name\": \"role_context\",\n"
            "                \"first_30_days\": \"...\", \"first_90_days\": \"...\",\n"
            "                \"owns_what\": \"owns the entire payments service end-to-end\",\n"
            "                \"reports_to\": \"Engineering Manager\",\n"
            "                \"growth_trajectory\": \"IC path or management in 18 months\",\n"
            "                \"why_role_open\": \"scaling|replacement|new_capability|backfill\"}\n"
            "  HiringGoal: {\"label\": \"HiringGoal\", \"name\": \"primary_hiring_goal\",\n"
            "               \"urgency\": \"critical|growing|strategic\",\n"
            "               \"timeline\": \"need someone in 30 days\",\n"
            "               \"gap_being_filled\": \"we have no one who owns infra\",\n"
            "               \"ideal_background\": \"...\",\n"
            "               \"dealbreaker_absence\": \"must have production K8s experience\"}\n"
            "  SoftSkillRequirement: {\"label\": \"SoftSkillRequirement\",\n"
            "                         \"name\": \"ownership\",\n"
            "                         \"quality\": \"ownership|accountability|initiative|communication|"
            "mentorship|conflict_resolution|cross_functional|documentation|estimation\",\n"
            "                         \"expectation\": \"operates without hand-holding\",\n"
            "                         \"evidence_indicator\": \"proactively flags risks before asked\",\n"
            "                         \"dealbreaker\": true}\n"
            "  TeamCultureIdentity: {\"label\": \"TeamCultureIdentity\", \"name\": \"team_culture\",\n"
            "                        \"decision_making\": \"consensus|top_down|distributed|data_driven\",\n"
            "                        \"communication_style\": \"async_first|high_meeting|"
            "documentation_heavy|verbal\",\n"
            "                        \"feedback_culture\": \"blunt|diplomatic|frequent|sparse\",\n"
            "                        \"pace\": \"sprint|steady|deliberate\",\n"
            "                        \"work_life\": \"startup_hours|sustainable|flexible\",\n"
            "                        \"management_style\": \"hands_on|hands_off|coaching\",\n"
            "                        \"team_values\": [\"shipping fast\", \"code quality\"],\n"
            "                        \"anti_patterns\": [\"needs constant direction\", \"can't handle ambiguity\"]}\n"
            "  SuccessMetric: {\"label\": \"SuccessMetric\", \"name\": \"success_definition\",\n"
            "                  \"at_30_days\": \"...\", \"at_90_days\": \"...\", \"at_1_year\": \"...\",\n"
            "                  \"key_deliverables\": [\"...\"],\n"
            "                  \"how_measured\": \"...\"}\n"
            "  InterviewSignal: {\"label\": \"InterviewSignal\",\n"
            "                    \"name\": \"[short id e.g. green_flag_ownership]\",\n"
            "                    \"signal_type\": \"green_flag|red_flag\",\n"
            "                    \"what_to_watch_for\": \"...\",\n"
            "                    \"why_it_matters\": \"...\"}\n"
            "  BehavioralInsight: same format as user interview — record recruiter behavior too\n\n"
            "EDGE FORMAT: same as user interview for any cross-links\n\n"
            "GRAPH IMPACT BANNER FORMAT:\n"
            "  headline: '1-sentence summary of what this answer captured about the role'\n"
            "  items: icon (use 'skill' for skills, 'culture' for team culture, "
            "'behavior' for soft skills, 'goal' for role context/hiring goals)\n"
            "  digital_twin_progress: e.g. 'Role profile: 45% complete | Missing: team culture, success definition'"
        )

    async def _persist_message(
        self, session_id: str, role: str, content: str, proposal_json: str | None
    ) -> None:
        from datetime import datetime, timezone
        await self.sqlite.execute(
            """
            INSERT INTO session_messages (session_id, role, content, proposal_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, proposal_json, datetime.now(timezone.utc).isoformat()),
        )

    async def _call_with_retry(self, messages: list) -> str:
        """Call LLM with exponential backoff (3 attempts)."""
        for attempt in range(3):
            try:
                resp = await acompletion(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.7,
                )
                return resp.choices[0].message.content
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(f"LLM error (attempt {attempt + 1}/3): {e}. Retrying in {wait}s")
                await asyncio.sleep(wait)
