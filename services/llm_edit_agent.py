"""
LLM Edit Agent — First Principles interview loop for graph editing.

Uses Groq (llama-3.3-70b-versatile) with JSON mode to produce structured
GraphMutationProposal responses. Every turn:
  1. Load full conversation history from SQLite session_messages
  2. Build Groq messages array (system + history + new user message)
  3. Call Groq with response_format={"type": "json_object"}
  4. Parse response as GraphMutationProposal
  5. Persist both user message and assistant proposal to session_messages
  6. Return the proposal
"""

import asyncio
import json
import logging
import os

from groq import AsyncGroq

from database.neo4j_client import Neo4jClient
from database.sqlite_client import SQLiteClient
from models.schemas import GraphMutation, GraphMutationProposal

logger = logging.getLogger(__name__)

_PROPOSAL_SCHEMA = json.dumps(GraphMutationProposal.model_json_schema(), indent=2)


class LLMEditAgent:
    def __init__(self, neo4j: Neo4jClient, sqlite: SQLiteClient):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        self._model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._client = AsyncGroq(api_key=api_key)
        self.neo4j = neo4j
        self.sqlite = sqlite

    async def get_opening_question(
        self, session_id: str, entity_type: str, entity_id: str
    ) -> GraphMutationProposal:
        """
        Generate the opening interview question for a new edit session.
        Loads graph summary from Neo4j, builds context, calls Groq, persists to SQLite.
        """
        graph_summary = await self._get_graph_summary(entity_type, entity_id)
        system_msg = self._build_system_prompt(graph_summary)
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
        Loads full history from SQLite, appends the new user message, calls Groq.
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
            requirements = await self.neo4j.run_query(
                """
                MATCH (j:Job {id: $id})-[:HAS_SKILL_REQUIREMENTS]->(:JobSkillRequirements)
                      -[:HAS_SKILL_FAMILY_REQ]->(:JobSkillFamily)
                      -[:REQUIRES_SKILL]->(r:JobSkillRequirement)
                RETURN r.name AS name, r.importance AS importance, r.min_years AS min_years
                """,
                {"id": entity_id},
            )
            return {
                "entity_type": "job",
                "entity_id": entity_id,
                "requirements": requirements,
            }

    def _build_system_prompt(self, graph_summary: dict) -> str:
        """Build the digital twin interview system prompt."""
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
            "domain|project|experience), label, change_type (add|update|infer|flag), detail\n"
            "  digital_twin_progress: optional, e.g. 'Technical depth: 72% | Human depth: 31%'\n"
            "  Estimate human depth based on: anecdotes (30%), motivations/values (25%), "
            "goals (20%), culture identity (15%), behavioral insights (10%)"
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
        """Call Groq with exponential backoff (3 attempts)."""
        for attempt in range(3):
            try:
                resp = await self._client.chat.completions.create(
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
                logger.warning(f"Groq error (attempt {attempt + 1}/3): {e}. Retrying in {wait}s")
                await asyncio.sleep(wait)
