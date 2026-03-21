"""
LiteLLM-based structured extraction service.

Uses LiteLLM's acompletion with JSON mode to enforce structured output.
The full Pydantic JSON schema is embedded in the system prompt and
response_format={"type": "json_object"} is used to guarantee valid JSON.

Model is configured via LLM_MODEL env var in LiteLLM format "provider/model".
Default: groq/llama-3.3-70b-versatile
"""

import asyncio
import json
import logging
import os

from litellm import acompletion

from models.schemas import UserProfileExtraction, JobPostingExtraction
from models.taxonomies import SKILL_TAXONOMY, DOMAIN_TAXONOMY

logger = logging.getLogger(__name__)

# Pre-compute JSON schemas once at module load — included in every system prompt
# so the model knows exactly what structure to return.
_USER_SCHEMA = json.dumps(UserProfileExtraction.model_json_schema(), indent=2)
_JOB_SCHEMA = json.dumps(JobPostingExtraction.model_json_schema(), indent=2)


def _build_skill_taxonomy_hint() -> str:
    return "\n".join(
        f"  - {family}: {', '.join(skills[:6])}..."
        for family, skills in SKILL_TAXONOMY.items()
    )


def _build_domain_taxonomy_hint() -> str:
    return "\n".join(
        f"  - {family}: {', '.join(domains[:4])}..."
        for family, domains in DOMAIN_TAXONOMY.items()
    )


class LLMExtractionService:
    """
    Wraps LiteLLM for structured JSON extraction.

    Uses acompletion with response_format={"type": "json_object"} and a
    system prompt that includes the full Pydantic JSON schema. The response
    is parsed with model_validate_json() for strict Pydantic validation.

    The schema is passed in the system message so the model treats it as a
    hard constraint rather than a soft suggestion.
    """

    def __init__(self):
        self._model_name = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
        self._skill_hint = _build_skill_taxonomy_hint()
        self._domain_hint = _build_domain_taxonomy_hint()
        logger.info(f"LLM extraction service initialized with model: {self._model_name}")

    @staticmethod
    def _unwrap_json(raw: str) -> str:
        """Unwrap JSON array → object (some models return [{...}] instead of {...})."""
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return json.dumps(parsed[0])
        except (json.JSONDecodeError, IndexError):
            pass
        return raw

    async def _call_with_retry(self, **kwargs) -> str:
        """Call LLM with exponential backoff (3 attempts: immediate, 1s, 2s)."""
        for attempt in range(3):
            try:
                resp = await acompletion(**kwargs)
                return self._unwrap_json(resp.choices[0].message.content)
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(f"LLM API error (attempt {attempt + 1}/3): {e}. Retrying in {wait}s")
                await asyncio.sleep(wait)

    async def extract_user_profile(self, profile_text: str) -> UserProfileExtraction:
        """
        Extract structured user profile from raw resume/profile text.

        Returns a validated UserProfileExtraction with skills, projects,
        domains, experiences, preferences, and problem-solving patterns.
        """
        system_msg = (
            "You are a senior engineering manager and technical recruiter conducting a rigorous, "
            "evidence-based analysis of a candidate profile. Your job is NOT to be flattering — "
            "it is to extract structured data AND produce a brutally honest assessment of what "
            "this person can actually do versus what they merely claim.\n\n"
            "EXTRACTION RULES:\n"
            "1. For each skill, assess evidence_strength honestly: did they just list it, or do "
            "   they have concrete project evidence? 'expert' level requires multiple production projects.\n"
            "2. For each project, extract HOW each skill was specifically used (not just that it was used). "
            "   Capture contribution_type honestly — 'sole_engineer' only if they clearly built it alone.\n"
            "3. For each experience, extract concrete accomplishments with metrics where present. "
            "   If the profile is vague, reflect that vagueness — do NOT invent specifics.\n"
            "4. For the critical assessment: think like a skeptical EM reading this resume before "
            "   a hiring committee. What would concern you? What is well-evidenced? "
            "   What level is this person REALLY at (not what their title says)?\n"
            "5. Flag inflated skills: if someone claims 'expert' in 15 technologies, that's a red flag.\n"
            "6. overall_signal 'misleading' if claims are materially unsupported by evidence.\n\n"
            "INTERPRETATION FLAGS — THIS IS CRITICAL:\n"
            "For EVERY field where you made an inference (rather than reading it directly), "
            "create an interpretation_flag. A flag must be created when:\n"
            "  - Years of experience was calculated/inferred (not stated explicitly)\n"
            "  - Skill level was inferred from job titles or context (not stated)\n"
            "  - Contribution type is ambiguous ('we built', 'our team' without clarity on their role)\n"
            "  - Domain depth was guessed from industry rather than described\n"
            "  - Any claim seems inconsistent with other evidence\n"
            "  - Accomplishments were vague and you had to guess the impact\n"
            "The clarification_question must quote the actual resume text and ask a specific, "
            "answerable question. Use suggested_options for multiple-choice fields "
            "(e.g. skill levels, contribution types, depths).\n\n"
            "SCHEMA CONSTRAINTS:\n"
            "- skill.family must be one of: Programming Languages, Web Frameworks, "
            "Databases, Cloud & DevOps, ML & AI, Data Engineering, Mobile Development, "
            "Testing & QA, Analytics & Visualization, Other\n"
            "- domain.family must be one of: FinTech, Healthcare, E-commerce, SaaS, "
            "Enterprise, Gaming, Education, Other\n"
            "- Return an empty list [] for any section with no data — never omit keys.\n"
            "- Return ONLY valid JSON matching this exact schema:\n\n"
            f"{_USER_SCHEMA}"
        )

        user_msg = (
            "Analyze this professional profile. Extract all structured data, produce a critical "
            "assessment through the lens of a skeptical engineering manager, AND generate "
            "interpretation_flags for every uncertain inference.\n\n"
            "For each project, describe HOW each skill was used — not just that it was used. "
            "For each skill, honestly assess evidence_strength. "
            "In the assessment, be direct about red flags, inflated claims, and genuine strengths.\n\n"
            "Remember: every inference you make (not directly stated) needs an interpretation_flag "
            "so the user can verify or correct it.\n\n"
            "Skill family reference:\n"
            f"{self._skill_hint}\n\n"
            "Domain family reference:\n"
            f"{self._domain_hint}\n\n"
            f"PROFILE TEXT:\n{profile_text}"
        )

        raw_json = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        extracted = UserProfileExtraction.model_validate_json(raw_json)
        logger.info(
            f"Extracted: {len(extracted.skills)} skills, "
            f"{len(extracted.projects)} projects, "
            f"{len(extracted.domains)} domains"
        )
        return extracted

    async def generate_match_explanation(
        self,
        user_id: str,
        job_title: str,
        company: str | None,
        total_score: float,
        skill_score: float,
        domain_score: float,
        culture_bonus: float,
        preference_bonus: float,
        matched_skills: list[str],
        missing_skills: list[str],
        matched_domains: list[str],
        missing_domains: list[str],
        paths: list[str],
        perspective: str = "recruiter",
        rich_context: dict | None = None,
    ) -> dict:
        """
        Generate a structured, evidence-based explanation of a user-job match.

        Uses rich_context (skill evidence, 5W+H usage, critical assessment, domain depth)
        to produce a detailed, actionable analysis — not just name-matching.

        Returns a dict with:
          verdict, headline, why_they_fit, critical_gaps, nice_to_have_gaps,
          seniority_fit, honest_take, recommendation, interview_focus
        """
        import json as _j

        company_str = company or "Unknown Company"
        ctx = rich_context or {}

        # ── Format matched skills with evidence context ──────────────────────────
        skill_lines = []
        for s in ctx.get("matched_skills_rich", []):
            name     = s.get("skill", "?")
            level    = s.get("level") or "unknown level"
            years    = s.get("years")
            ev       = s.get("evidence_strength") or "unknown evidence"
            imp      = s.get("importance") or "default"
            min_yr   = s.get("min_years")
            contexts = [c for c in (s.get("usage_contexts") or []) if c]
            whats    = [w for w in (s.get("usage_what") or []) if w]
            outcomes = [o for o in (s.get("outcomes") or []) if o]

            years_str = f"{years}yr" if years else "yrs unknown"
            min_str   = f" (job needs {min_yr}yr min)" if min_yr else ""
            ev_label  = {
                "multiple_productions": "★★★★ production-proven",
                "project_backed":       "★★★ project-evidenced",
                "mentioned_once":       "★★ mentioned briefly",
                "claimed_only":         "★ claimed only",
            }.get(ev, ev)

            how_parts = []
            if whats:
                how_parts.append(f"used to: {'; '.join(whats[:2])}")
            if contexts:
                how_parts.append(f"context: {'; '.join(contexts[:2])}")
            if outcomes:
                how_parts.append(f"outcome: {'; '.join(outcomes[:1])}")

            how_str = " — " + " | ".join(how_parts) if how_parts else ""
            skill_lines.append(
                f"  • {name} [{imp}]: {level}, {years_str}{min_str}, {ev_label}{how_str}"
            )

        # Fall back to flat list if rich context not available
        if not skill_lines and matched_skills:
            skill_lines = [f"  • {s}" for s in matched_skills]

        # ── Format gaps ──────────────────────────────────────────────────────────
        must_gap_lines = []
        for g in ctx.get("missing_must_have", []):
            sk = g.get("skill", "?")
            my = g.get("min_years")
            must_gap_lines.append(f"  • {sk} (must_have{f', {my}yr min' if my else ''})")
        if not must_gap_lines:
            must_gap_lines = [f"  • {s}" for s in missing_skills if s]

        nice_gaps = ctx.get("missing_nice", [m for m in missing_skills if m not in
                             [g.get("skill", "") for g in ctx.get("missing_must_have", [])]])
        nice_gap_str = ", ".join(nice_gaps[:6]) if nice_gaps else "None"

        # ── Format assessment ────────────────────────────────────────────────────
        assessment = ctx.get("assessment", {})
        seniority    = assessment.get("seniority_assessment") or "unknown"
        signal       = assessment.get("overall_signal") or "unknown"
        identity     = assessment.get("candidate_identity") or ""
        honest_summ  = assessment.get("honest_summary") or ""
        red_flags    = assessment.get("red_flags") or []
        inflated     = assessment.get("inflated_skills") or []
        genuine      = assessment.get("genuine_strengths") or []
        five_wh      = assessment.get("five_w_h_summary") or {}

        red_flag_str   = "\n".join(f"  ⚠ {f}" for f in red_flags[:4]) if red_flags else "  None noted"
        genuine_str    = "\n".join(f"  ✓ {g}" for g in genuine[:4]) if genuine else "  (none noted)"
        inflated_str   = "\n".join(f"  ! {i}" for i in inflated[:3]) if inflated else "  None"

        # ── Format domains ───────────────────────────────────────────────────────
        domain_lines = []
        for d in ctx.get("matched_domains_rich", []):
            dn   = d.get("domain", "?")
            dep  = d.get("depth") or "unknown"
            dyrs = d.get("years")
            domain_lines.append(f"  • {dn}: {dep} depth" + (f", {dyrs}yr" if dyrs else ""))
        if not domain_lines and matched_domains:
            domain_lines = [f"  • {d}" for d in matched_domains]

        job_meta  = ctx.get("job_meta", {})
        exp_min   = job_meta.get("exp_min")
        co_size   = job_meta.get("company_size") or "unknown"
        remote    = job_meta.get("remote_policy") or "unknown"

        five_wh_str = ""
        if isinstance(five_wh, dict) and five_wh:
            five_wh_str = "\nCandidate 5W+H:\n" + "\n".join(
                f"  {k.upper()}: {v}" for k, v in five_wh.items() if v
            )

        # ── Perspective instruction ──────────────────────────────────────────────
        if perspective == "seeker":
            person_instr = (
                "Write in SECOND PERSON (you/your). "
                "Tone: honest and constructive — help them understand their fit and what to prepare. "
                "E.g. 'Your Python expertise is well-evidenced... however, Kubernetes is a critical gap you'll need to address.'"
            )
            output_guidance = (
                "For 'why_they_fit': use 'Your [skill] experience...' phrasing.\n"
                "For 'honest_take': frame concerns as areas to prepare, not disqualifiers.\n"
                "For 'recommendation': advise them on whether to apply and what to prepare."
            )
        else:
            person_instr = (
                f"Write in THIRD PERSON about candidate '{user_id}'. "
                "Tone: professional recruiter/hiring manager lens — direct, honest, evidence-based. "
                f"E.g. '{user_id} demonstrates production-proven Python skills...'"
            )
            output_guidance = (
                "For 'why_they_fit': reference the candidate by name or 'the candidate'.\n"
                "For 'honest_take': be direct about risks and genuine strengths.\n"
                "For 'recommendation': advise the hiring team on next steps."
            )

        system_msg = (
            "You are a senior engineering manager generating a detailed, evidence-based job match analysis. "
            "You have access to the candidate's actual graph data: how skills were used, at what scale, "
            "with what evidence quality — not just which skill names match. "
            "Your analysis must go beyond surface-level name matching to assess genuine fit.\n\n"
            "Return ONLY valid JSON matching this exact schema:\n"
            "{\n"
            '  "verdict": "Strong match" | "Good match" | "Moderate match" | "Weak match" | "Not recommended",\n'
            '  "headline": "1 sentence: who this person is and why they do/do not fit this specific role",\n'
            '  "why_they_fit": ["skill or domain with specific evidence and context — not just names"],\n'
            '  "critical_gaps": ["must-have gaps with explanation of impact on this role"],\n'
            '  "nice_to_have_gaps": ["lower priority gaps"],\n'
            '  "seniority_fit": "1-2 sentences: assessed level vs what the role needs",\n'
            '  "honest_take": "2-3 sentences: evidence-backed assessment of genuine strengths and concerns",\n'
            '  "recommendation": "Hire | Proceed to technical screen | Conditional consider | Pass — with 1 sentence rationale",\n'
            '  "interview_focus": ["specific technical areas to probe if proceeding"]\n'
            "}"
        )

        user_msg = (
            f"Candidate: {user_id}\n"
            f"Role: {job_title} at {company_str}\n"
            f"Company size: {co_size} | Remote: {remote}"
            + (f" | Min experience: {exp_min}yr" if exp_min else "")
            + "\n\n"
            f"Match scores: Overall {round(total_score * 100)}% "
            f"(Skills 65%→{round(skill_score * 100)}%, Domain 35%→{round(domain_score * 100)}%) "
            f"| Culture bonus: {round(culture_bonus * 100)}% | Preference bonus: {round(preference_bonus * 100)}%\n\n"
            "═══ MATCHED SKILLS (with evidence quality + how actually used) ═══\n"
            + ("\n".join(skill_lines) or "  None")
            + "\n\n"
            "═══ CRITICAL GAPS (must-have skills not in profile) ═══\n"
            + ("\n".join(must_gap_lines) or "  None — all must-haves covered")
            + "\n\n"
            f"Nice-to-have gaps: {nice_gap_str}\n\n"
            "═══ MATCHED DOMAINS ═══\n"
            + ("\n".join(domain_lines) or "  None")
            + "\n\n"
            "═══ CANDIDATE ASSESSMENT (from critical analysis) ═══\n"
            f"Profile signal: {signal} | Seniority: {seniority}\n"
            + (f"Identity: {identity}\n" if identity else "")
            + (f"Honest summary: {honest_summ}\n" if honest_summ else "")
            + f"\nGenuine evidenced strengths:\n{genuine_str}\n"
            + f"\nRed flags / concerns:\n{red_flag_str}\n"
            + f"\nInflated skill claims:\n{inflated_str}\n"
            + five_wh_str
            + "\n\n"
            f"{person_instr}\n"
            f"{output_guidance}\n\n"
            "Generate the structured match explanation. Be specific — use actual skill names, "
            "evidence levels, and context from the data above. Do NOT be generic."
        )

        raw = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        try:
            return _j.loads(raw)
        except Exception:
            # Fallback: wrap raw text so callers always get a dict
            return {
                "verdict": "Unknown",
                "headline": raw[:200] if raw else "Explanation unavailable",
                "why_they_fit": [],
                "critical_gaps": [],
                "nice_to_have_gaps": [],
                "seniority_fit": "",
                "honest_take": raw if raw else "",
                "recommendation": "",
                "interview_focus": [],
            }

    async def extract_job_posting(self, job_text: str) -> JobPostingExtraction:
        """
        Extract structured job requirements from raw job posting text.

        Returns a validated JobPostingExtraction with skill requirements,
        domain requirements, work styles, and company metadata.
        """
        system_msg = (
            "You are an expert HR data extractor. Extract structured job requirements "
            "and return ONLY valid JSON matching this exact schema:\n\n"
            f"{_JOB_SCHEMA}\n\n"
            "Constraints:\n"
            "- skill.family must be one of: Programming Languages, Web Frameworks, "
            "Databases, Cloud & DevOps, ML & AI, Data Engineering, Mobile Development, "
            "Testing & QA, Analytics & Visualization, Other\n"
            "- domain.family must be one of: FinTech, Healthcare, E-commerce, SaaS, "
            "Enterprise, Gaming, Education, Other\n"
            "- remote_policy must be one of: 'remote', 'hybrid', 'onsite'\n"
            "- company_size must be one of: 'startup', 'mid-size', 'enterprise'\n"
            "- importance must be one of: 'must_have' (required/mandatory skills) or 'optional' (nice-to-have/bonus skills)\n"
            "- Return an empty list [] for any section with no data — never omit keys."
        )

        user_msg = (
            "Extract all job requirements from the following job posting.\n\n"
            "Skill family reference:\n"
            f"{self._skill_hint}\n\n"
            "Domain family reference:\n"
            f"{self._domain_hint}\n\n"
            f"JOB POSTING:\n{job_text}"
        )

        raw_json = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        extracted = JobPostingExtraction.model_validate_json(raw_json)
        logger.info(
            f"Extracted job: {extracted.title} at {extracted.company} — "
            f"{len(extracted.skill_requirements)} skill requirements"
        )
        return extracted

    async def describe_user_from_graph(self, user_id: str, neo4j_client) -> dict:
        """
        Query the user's complete graph — technical AND human portrait nodes — and
        generate a rich natural-language description alongside a computed completeness score.

        Returns a dict with:
          - LLM-generated profile (identity, career_arc, strengths, assessment, etc.)
          - completeness: DigitalTwinCompleteness (computed, not LLM-generated)
        """
        import json as _j

        # ── Technical nodes ───────────────────────────────────────────────────
        skills = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
            OPTIONAL MATCH (p:Project {user_id: $id})-[r:DEMONSTRATES_SKILL]->(s)
            OPTIONAL MATCH (s)-[:GROUNDED_IN]->(anec:Anecdote)
            RETURN s.name AS name, s.years AS years, s.level AS level,
                   s.evidence_strength AS evidence_strength,
                   count(DISTINCT p) AS project_count,
                   collect(DISTINCT r.context)[0..2] AS contexts,
                   count(DISTINCT anec) AS anecdote_count
            ORDER BY project_count DESC, years DESC
            """,
            {"id": user_id},
        )
        domains = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
                  -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
            RETURN d.name AS name, d.years_experience AS years, d.depth AS depth
            ORDER BY years DESC
            """,
            {"id": user_id},
        )
        projects = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_PROJECT_CATEGORY]->(:ProjectCategory)
                  -[:HAS_PROJECT]->(p:Project)
            RETURN p.name AS name, p.description AS description,
                   p.contribution_type AS contribution_type,
                   p.has_measurable_impact AS has_measurable_impact
            """,
            {"id": user_id},
        )
        experiences = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_EXPERIENCE_CATEGORY]->(:ExperienceCategory)
                  -[:HAS_EXPERIENCE]->(e:Experience)
            RETURN e.title AS title, e.company AS company,
                   e.duration_years AS duration_years,
                   e.description AS description,
                   e.accomplishments AS accomplishments,
                   e.contribution_type AS contribution_type
            ORDER BY e.duration_years DESC
            """,
            {"id": user_id},
        )
        assessment = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_ASSESSMENT]->(a:CriticalAssessment)
            RETURN a.overall_signal AS overall_signal,
                   a.seniority_assessment AS seniority_assessment,
                   a.depth_vs_breadth AS depth_vs_breadth,
                   a.candidate_identity AS candidate_identity,
                   a.honest_summary AS honest_summary,
                   a.genuine_strengths AS genuine_strengths,
                   a.red_flags AS red_flags,
                   a.five_w_h_summary AS five_w_h_summary,
                   a.interview_focus_areas AS interview_focus_areas
            """,
            {"id": user_id},
        )
        patterns = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_PATTERN_CATEGORY]->
                  (:PatternCategory)-[:HAS_PATTERN]->(p:ProblemSolvingPattern)
            RETURN p.pattern AS pattern, p.evidence AS evidence
            """,
            {"id": user_id},
        )

        # ── Human portrait nodes ──────────────────────────────────────────────
        anecdotes = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_ANECDOTE]->(a:Anecdote)
            RETURN a.name AS name, a.situation AS situation, a.action AS action,
                   a.result AS result, a.lesson_learned AS lesson_learned,
                   a.confidence_signal AS confidence_signal,
                   a.spontaneous AS spontaneous
            """,
            {"id": user_id},
        )
        motivations = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:MOTIVATED_BY]->(m:Motivation)
            RETURN m.category AS category, m.strength AS strength, m.evidence AS evidence
            ORDER BY m.strength DESC
            """,
            {"id": user_id},
        )
        values = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HOLDS_VALUE]->(v:Value)
            RETURN v.name AS name, v.priority_rank AS priority_rank, v.evidence AS evidence
            ORDER BY v.priority_rank
            """,
            {"id": user_id},
        )
        goals = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:ASPIRES_TO]->(g:Goal)
            RETURN g.type AS type, g.description AS description,
                   g.timeframe_years AS timeframe_years, g.clarity_level AS clarity_level
            """,
            {"id": user_id},
        )
        culture_identity = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_CULTURE_IDENTITY]->(c:CultureIdentity)
            RETURN c.team_size_preference AS team_size_preference,
                   c.leadership_style AS leadership_style,
                   c.feedback_preference AS feedback_preference,
                   c.pace_preference AS pace_preference,
                   c.conflict_style AS conflict_style,
                   c.energy_sources AS energy_sources,
                   c.energy_drains AS energy_drains
            """,
            {"id": user_id},
        )
        behavioral_insights = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_BEHAVIORAL_INSIGHT]->(b:BehavioralInsight)
            RETURN b.insight_type AS insight_type, b.trigger AS trigger,
                   b.implication AS implication
            """,
            {"id": user_id},
        )

        # ── Profile verification status ───────────────────────────────────────
        verification = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})
            RETURN u.id AS id
            """,
            {"id": user_id},
        )

        # ── Compute completeness (deterministic, not LLM) ─────────────────────
        completeness = self._compute_digital_twin_completeness(
            skills=skills,
            projects=projects,
            experiences=experiences,
            has_assessment=bool(assessment),
            patterns=patterns,
            anecdotes=[a for a in anecdotes if a.get("name")],
            motivations=[m for m in motivations if m.get("category")],
            values=[v for v in values if v.get("name")],
            goals=[g for g in goals if g.get("description")],
            culture_identity=culture_identity[0] if culture_identity and culture_identity[0].get("pace_preference") else None,
            behavioral_insights=[b for b in behavioral_insights if b.get("insight_type")],
        )

        # ── Build full graph data for LLM ─────────────────────────────────────
        graph_data = {
            "skills": skills,
            "domains": domains,
            "projects": projects,
            "experiences": experiences,
            "assessment": assessment[0] if assessment else {},
            "patterns": [p for p in patterns if p.get("pattern")],
            # Human portrait — included only if data exists
            "anecdotes": [a for a in anecdotes if a.get("name")],
            "motivations": [m for m in motivations if m.get("category")],
            "values": [v for v in values if v.get("name")],
            "goals": [g for g in goals if g.get("description")],
            "culture_identity": culture_identity[0] if culture_identity and culture_identity[0].get("pace_preference") else None,
            "behavioral_insights": [b for b in behavioral_insights if b.get("insight_type")],
        }

        system_msg = (
            "You are a senior engineering manager writing an honest, insightful professional profile "
            "of a candidate based on their complete knowledge graph — both technical skills and "
            "the human portrait captured through the deep interview.\n\n"
            "This profile is shown to the candidate themselves so they understand how they are perceived "
            "by recruiters. Be specific, evidence-based, and honest — not flattering.\n\n"
            "If motivations, values, goals, or culture identity data exist in the graph, incorporate them. "
            "These reveal WHO this person is beyond their resume.\n"
            "If anecdotes exist, reference the stories — they are stronger evidence than skill claims.\n"
            "If behavioral insights exist, note them honestly.\n\n"
            "Return a JSON object with these exact keys:\n"
            "{\n"
            "  \"identity\": \"1-sentence professional identity statement\",\n"
            "  \"career_arc\": \"2-3 sentences describing their career progression and trajectory\",\n"
            "  \"who_they_are\": \"2-3 sentences on what drives them, how they work, and what they care about — "
            "based on motivations/values/culture data if available, otherwise omit or note as unknown\",\n"
            "  \"core_strengths\": [\"strength 1 with evidence — cite anecdotes where available\"],\n"
            "  \"domain_expertise\": \"paragraph about domain depth and industry context\",\n"
            "  \"technical_profile\": \"paragraph about technical skills, depth vs breadth, evidence quality\",\n"
            "  \"honest_assessment\": \"paragraph: what they can genuinely do, what level they are at, "
            "what they have not yet demonstrated\",\n"
            "  \"gaps_and_concerns\": [\"specific gap or concern with evidence — be direct\"],\n"
            "  \"best_suited_for\": \"what kind of role, team, company size, culture, and problem type "
            "this person is best matched with — use culture identity data if present\",\n"
            "  \"interview_ready_summary\": \"what a recruiter needs to know before interviewing in 2-3 sentences\"\n"
            "}\n"
            "Return ONLY valid JSON."
        )

        user_msg = (
            f"Generate a professional profile for user: {user_id}\n\n"
            f"COMPLETE GRAPH DATA:\n{json.dumps(graph_data, indent=2, default=str)}"
        )

        raw = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        try:
            description = _j.loads(raw)
        except Exception:
            description = {"identity": raw, "error": "parse_failed"}

        description["completeness"] = completeness.model_dump()
        return description

    def _compute_digital_twin_completeness(
        self,
        skills: list,
        projects: list,
        experiences: list,
        has_assessment: bool,
        patterns: list,
        anecdotes: list,
        motivations: list,
        values: list,
        goals: list,
        culture_identity: dict | None,
        behavioral_insights: list,
    ):
        """
        Compute the DigitalTwinCompleteness score — deterministic, no LLM.

        Technical depth scoring (contributes 50% of overall):
          Skills evidence quality:  40% of tech score
          Projects with impact:     30% of tech score
          Experiences + accmplshmt: 20% of tech score
          Skills with anecdotes:    10% of tech score

        Human depth scoring (contributes 50% of overall):
          Anecdotes (cap at 5):     30% of human score
          Motivation identified:    20% of human score
          Values identified:        15% of human score
          Goal set:                 15% of human score
          Culture identity built:   15% of human score
          Behavioral insights:       5% of human score
        """
        from models.schemas import (
            DigitalTwinCompleteness, TechnicalDepthBreakdown, HumanDepthBreakdown
        )

        # ── Technical depth ────────────────────────────────────────────────────
        total_skills  = len(skills)
        claimed_only  = sum(1 for s in skills if s.get("evidence_strength") == "claimed_only")
        evidenced     = sum(1 for s in skills if s.get("evidence_strength") in
                           ("mentioned_once", "project_backed", "multiple_productions"))
        with_anecdotes = sum(1 for s in skills if (s.get("anecdote_count") or 0) > 0)

        total_projects = len(projects)
        with_impact    = sum(1 for p in projects if p.get("has_measurable_impact"))

        total_exp    = len(experiences)
        with_accomp  = sum(
            1 for e in experiences
            if e.get("accomplishments") and len(e["accomplishments"]) > 0
        )

        # Sub-scores (0.0–1.0)
        skill_evidence_score = (evidenced / total_skills) if total_skills else 0.0
        project_impact_score = (with_impact / total_projects) if total_projects else 0.0
        exp_accomp_score     = (with_accomp / total_exp) if total_exp else 0.0
        anecdote_skill_score = (with_anecdotes / total_skills) if total_skills else 0.0

        tech_raw = (
            skill_evidence_score * 0.40 +
            project_impact_score * 0.30 +
            exp_accomp_score     * 0.20 +
            anecdote_skill_score * 0.10
        )
        # Assessment bonus: cap the raw score at 0.95 without it, full 1.0 with it
        if not has_assessment:
            tech_raw = min(tech_raw, 0.90)
        tech_pct = round(tech_raw * 100)

        # ── Human depth ────────────────────────────────────────────────────────
        anecdote_target  = 5
        anecdote_count   = len(anecdotes)
        anecdote_score   = min(anecdote_count / anecdote_target, 1.0)
        has_motivation   = len(motivations) > 0
        has_values       = len(values) > 0
        has_goal         = len(goals) > 0
        has_culture      = culture_identity is not None
        has_behavior     = len(behavioral_insights) > 0

        human_raw = (
            anecdote_score       * 0.30 +
            (1.0 if has_motivation else 0.0) * 0.20 +
            (1.0 if has_values    else 0.0) * 0.15 +
            (1.0 if has_goal      else 0.0) * 0.15 +
            (1.0 if has_culture   else 0.0) * 0.15 +
            (1.0 if has_behavior  else 0.0) * 0.05
        )
        human_pct = round(human_raw * 100)

        overall_pct = round((tech_pct + human_pct) / 2)

        # ── Matching capability flags ──────────────────────────────────────────
        evidence_weighted_active = evidenced > 0
        soft_skill_active        = len([p for p in patterns if p.get("pattern")]) > 0
        culture_active           = has_culture

        # ── Profile verification (check critical flags in SQLite via approximation) ─
        # We don't have SQLite here — will be enriched by the route if needed.
        # Approximate: assume verified if assessment exists and evidenced > claimed.
        profile_verified = has_assessment and evidenced >= claimed_only

        # ── Missing dimensions (actionable, honest) ────────────────────────────
        missing: list[str] = []

        if claimed_only > 0:
            missing.append(
                f"{claimed_only} skill(s) have only 'claimed' evidence — "
                f"their matching weight is reduced to 30%. "
                f"Add projects or anecdotes to strengthen them."
            )
        if with_anecdotes == 0 and total_skills > 0:
            missing.append(
                "No anecdotes captured yet. Recruiters can't see the stories behind your skills. "
                "Start the deep profile interview."
            )
        elif with_anecdotes < total_skills and total_skills > 0:
            missing.append(
                f"{total_skills - with_anecdotes} skill(s) have no backing story. "
                f"The more stories we have, the more accurately we can describe your experience."
            )
        if not has_motivation:
            missing.append(
                "Motivation not identified. We can't match you to companies whose mission aligns "
                "with what drives you."
            )
        if not has_values:
            missing.append(
                "Core values not captured. Role culture matching will miss alignment signals."
            )
        if not has_goal:
            missing.append(
                "No career goal set. We can't prioritise growth-oriented or leadership roles for you."
            )
        if not has_culture:
            missing.append(
                "Culture identity incomplete — culture fit scoring is disabled for your matches. "
                "This is 15% of your total match score."
            )
        if not has_assessment:
            missing.append(
                "Critical assessment not generated. Re-ingest your profile to produce it."
            )
        if total_projects == 0:
            missing.append("No projects in your profile — skill evidence cannot be project-backed.")
        elif with_impact == 0:
            missing.append(
                "None of your projects have measurable impact. "
                "Add metrics (users, latency, revenue) to strengthen your evidence."
            )

        # ── Next action ────────────────────────────────────────────────────────
        if human_pct < 20:
            next_action = (
                "Start the deep profile interview — your human portrait is nearly empty. "
                "Culture fit scoring and motivation matching are currently disabled for you."
            )
        elif not has_motivation:
            next_action = (
                "Continue the profile interview to capture what drives you. "
                "This enables motivation-based matching."
            )
        elif not has_goal:
            next_action = (
                "Tell us your 5-year goal. This unlocks role trajectory matching."
            )
        elif not has_culture:
            next_action = (
                "Complete the culture identity section of your interview. "
                "This activates culture fit scoring (15% of your match score)."
            )
        elif claimed_only > 0:
            next_action = (
                f"Add stories or projects for {claimed_only} skill(s) sitting at 'claimed only'. "
                f"Each one currently scores at 30% weight in matching."
            )
        elif with_anecdotes < total_skills:
            next_action = (
                f"Add anecdotes for {total_skills - with_anecdotes} more skill(s). "
                f"Recruiters see the story — not just the skill name."
            )
        else:
            next_action = (
                "Your profile is strong. Keep it updated as you ship new work."
            )

        return DigitalTwinCompleteness(
            overall_pct=overall_pct,
            technical_depth=TechnicalDepthBreakdown(
                score_pct=tech_pct,
                skills_total=total_skills,
                skills_evidenced=evidenced,
                skills_with_anecdotes=with_anecdotes,
                skills_claimed_only=claimed_only,
                projects_total=total_projects,
                projects_with_impact=with_impact,
                experiences_total=total_exp,
                experiences_with_accomplishments=with_accomp,
                has_critical_assessment=has_assessment,
            ),
            human_depth=HumanDepthBreakdown(
                score_pct=human_pct,
                anecdotes_count=anecdote_count,
                anecdotes_target=anecdote_target,
                motivations_identified=has_motivation,
                values_identified=has_values,
                goal_set=has_goal,
                culture_identity_built=has_culture,
                behavioral_insights_count=len(behavioral_insights),
                culture_matching_enabled=has_culture,
            ),
            evidence_weighted_scoring_active=evidence_weighted_active,
            soft_skill_scoring_active=soft_skill_active,
            culture_fit_scoring_active=culture_active,
            profile_verified=profile_verified,
            missing_dimensions=missing,
            next_action=next_action,
        )

    async def compute_completeness(self, user_id: str, neo4j_client) -> "DigitalTwinCompleteness":
        """
        Compute digital twin completeness without calling the LLM.

        Runs only the graph queries needed for the deterministic scoring model.
        Much faster than describe_user_from_graph() — suitable for dashboard polling
        and profile progress UIs that don't need the full LLM-generated description.
        """
        skills = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
            OPTIONAL MATCH (s)-[:GROUNDED_IN]->(anec:Anecdote)
            RETURN s.evidence_strength AS evidence_strength,
                   count(DISTINCT anec) AS anecdote_count
            """,
            {"id": user_id},
        )
        projects = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_PROJECT_CATEGORY]->(:ProjectCategory)
                  -[:HAS_PROJECT]->(p:Project)
            RETURN p.has_measurable_impact AS has_measurable_impact
            """,
            {"id": user_id},
        )
        experiences = await neo4j_client.run_query(
            """
            MATCH (u:User {id: $id})-[:HAS_EXPERIENCE_CATEGORY]->(:ExperienceCategory)
                  -[:HAS_EXPERIENCE]->(e:Experience)
            RETURN e.accomplishments AS accomplishments
            """,
            {"id": user_id},
        )
        has_assessment_rows = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:HAS_ASSESSMENT]->(a:CriticalAssessment) RETURN a.overall_signal AS sig",
            {"id": user_id},
        )
        has_assessment = bool(has_assessment_rows and has_assessment_rows[0].get("sig"))

        patterns = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_PATTERN_CATEGORY]->
                  (:PatternCategory)-[:HAS_PATTERN]->(p:ProblemSolvingPattern)
            RETURN p.pattern AS pattern
            """,
            {"id": user_id},
        )
        anecdotes = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:HAS_ANECDOTE]->(a:Anecdote) RETURN a.name AS name",
            {"id": user_id},
        )
        motivations = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:MOTIVATED_BY]->(m:Motivation) RETURN m.category AS category",
            {"id": user_id},
        )
        values = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:HOLDS_VALUE]->(v:Value) RETURN v.name AS name",
            {"id": user_id},
        )
        goals = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:ASPIRES_TO]->(g:Goal) RETURN g.description AS description",
            {"id": user_id},
        )
        culture_identity = await neo4j_client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $id})-[:HAS_CULTURE_IDENTITY]->(c:CultureIdentity)
            RETURN c.pace_preference AS pace_preference
            """,
            {"id": user_id},
        )
        behavioral_insights = await neo4j_client.run_query(
            "OPTIONAL MATCH (u:User {id: $id})-[:HAS_BEHAVIORAL_INSIGHT]->(b:BehavioralInsight) RETURN b.insight_type AS insight_type",
            {"id": user_id},
        )

        return self._compute_digital_twin_completeness(
            skills=skills,
            projects=projects,
            experiences=experiences,
            has_assessment=has_assessment,
            patterns=patterns,
            anecdotes=[a for a in anecdotes if a.get("name")],
            motivations=[m for m in motivations if m.get("category")],
            values=[v for v in values if v.get("name")],
            goals=[g for g in goals if g.get("description")],
            culture_identity=culture_identity[0] if culture_identity and culture_identity[0].get("pace_preference") else None,
            behavioral_insights=[b for b in behavioral_insights if b.get("insight_type")],
        )
