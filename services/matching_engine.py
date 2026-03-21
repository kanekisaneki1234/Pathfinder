"""
Pure graph-based matching engine.

All scoring is done through Cypher set-intersection queries — no vectors,
no embeddings. Every score component is directly traceable to explicit
graph edges, making the system fully scrutable.

Four-axis scoring model:
  Skills      (45% when all data present): evidence-weighted intersection via MATCHES edges
  Domain      (20% when all data present): depth-weighted intersection
  Soft Skills (20% when job has SoftSkillRequirements + user has patterns): quality alignment
  Culture Fit (15% when both sides have digital twin culture data): identity match

When dimensions lack data they are excluded and remaining weights rescale:
  No soft, no culture → Skills 65% + Domain 35%  (backwards compatible)
  Has culture, no soft → Skills 55% + Domain 25% + Culture 20%
  Has soft, no culture → Skills 55% + Domain 25% + Soft 20%
  All four present     → Skills 45% + Domain 20% + Soft 20% + Culture 15%

Skill scoring details:
  contribution = importance_weight × seniority_factor × evidence_weight
  evidence weights: claimed_only=0.30, mentioned_once=0.50,
                    project_backed=0.80, multiple_productions=1.00

Domain scoring details:
  contribution = depth_weight × (1 / total_domains)
  depth weights: shallow=0.40, moderate=0.70, deep=1.00

Name normalization: toLower(trim(...)) applied in all Cypher comparisons.
"""

import logging
from database.neo4j_client import Neo4jClient
from models.schemas import MatchResult, BatchMatchResponse, CandidateResult, BatchCandidateResponse
from models.taxonomies import (
    MatchWeight,
    SkillImportanceWeight,
    EvidenceWeight,
    DomainDepthWeight,
    SOFT_SKILL_TO_PATTERN,
    BEHAVIORAL_RISK_TYPES,
    CULTURE_FIELD_MAP,
    normalize_work_style,
)

logger = logging.getLogger(__name__)


class MatchingEngine:
    def __init__(self, client: Neo4jClient):
        self.client = client

    # ──────────────────────────────────────────────────────────────────────────
    # BATCH MATCHING
    # ──────────────────────────────────────────────────────────────────────────

    async def rank_all_jobs_for_user(self, user_id: str) -> BatchMatchResponse:
        jobs = await self.client.run_query("MATCH (j:Job) RETURN j.id AS job_id")
        results: list[MatchResult] = []
        for job_record in jobs:
            result = await self._score_user_job_pair(user_id, job_record["job_id"])
            if result is not None:
                results.append(result)
        results.sort(key=lambda r: r.total_score, reverse=True)
        return BatchMatchResponse(
            user_id=user_id,
            results=results,
            total_jobs_ranked=len(results),
        )

    async def rank_all_users_for_job(self, job_id: str) -> BatchCandidateResponse:
        users = await self.client.run_query("MATCH (u:User) RETURN u.id AS id")
        results: list[CandidateResult] = []
        for user_record in users:
            match = await self._score_user_job_pair(user_record["id"], job_id)
            if match is not None:
                results.append(CandidateResult(
                    user_id=user_record["id"],
                    total_score=match.total_score,
                    skill_score=match.skill_score,
                    optional_skill_score=match.optional_skill_score,
                    domain_score=match.domain_score,
                    soft_skill_score=match.soft_skill_score,
                    culture_fit_score=match.culture_fit_score,
                    culture_bonus=match.culture_bonus,
                    preference_bonus=match.preference_bonus,
                    matched_skills=match.matched_skills,
                    missing_skills=match.missing_skills,
                    matched_domains=match.matched_domains,
                    missing_domains=match.missing_domains,
                    behavioral_risk_flags=match.behavioral_risk_flags,
                    explanation=match.explanation,
                ))
        results.sort(key=lambda r: r.total_score, reverse=True)
        return BatchCandidateResponse(
            job_id=job_id,
            results=results,
            total_users_ranked=len(results),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # SINGLE PAIR SCORING
    # ──────────────────────────────────────────────────────────────────────────

    async def _score_user_job_pair(
        self, user_id: str, job_id: str
    ) -> MatchResult | None:
        job_info = await self.client.run_query(
            "MATCH (j:Job {id: $job_id}) RETURN j.title AS title, j.company AS company",
            {"job_id": job_id},
        )
        if not job_info:
            return None
        user_check = await self.client.run_query(
            "MATCH (u:User {id: $user_id}) RETURN u.id AS id",
            {"user_id": user_id},
        )
        if not user_check:
            return None

        skill_data        = await self._compute_skill_score(user_id, job_id)
        domain_data       = await self._compute_domain_score(user_id, job_id)
        soft_data         = await self._compute_soft_skill_score(user_id, job_id)
        culture_fit_data  = await self._compute_culture_fit_score(user_id, job_id)
        culture_bonus_data = await self._compute_culture_bonus(user_id, job_id)
        pref_data         = await self._compute_preference_bonus(user_id, job_id)

        mandatory_score   = skill_data.get("mandatory_score", 0.0) or 0.0
        optional_score    = skill_data.get("optional_score", 0.0) or 0.0
        domain_score      = domain_data.get("score", 0.0) or 0.0
        soft_skill_score  = soft_data.get("score")   # None = no data
        culture_fit_score = culture_fit_data.get("score")  # None = no data
        culture_bonus     = culture_bonus_data.get("bonus", 0.0) or 0.0
        preference_bonus  = pref_data.get("bonus", 0.0) or 0.0

        total_score = self._compute_total_score(
            mandatory_score, optional_score, domain_score, soft_skill_score, culture_fit_score
        )

        return MatchResult(
            job_id=job_id,
            job_title=job_info[0]["title"] or "Unknown",
            company=job_info[0]["company"],
            total_score=round(total_score, 4),
            skill_score=round(mandatory_score, 4),
            optional_skill_score=round(optional_score, 4),
            domain_score=round(domain_score, 4),
            soft_skill_score=round(soft_skill_score, 4) if soft_skill_score is not None else 0.0,
            culture_fit_score=round(culture_fit_score, 4) if culture_fit_score is not None else 0.0,
            culture_bonus=round(culture_bonus, 4),
            preference_bonus=round(preference_bonus, 4),
            matched_skills=skill_data.get("matched", []),
            missing_skills=skill_data.get("missing", []),
            matched_domains=domain_data.get("matched", []),
            missing_domains=domain_data.get("missing", []),
            behavioral_risk_flags=soft_data.get("risk_flags", []),
            explanation=self._build_explanation(
                mandatory_score, domain_score, soft_skill_score,
                culture_fit_score, culture_bonus, preference_bonus
            ),
        )

    def _compute_total_score(
        self,
        skill_score: float,
        optional_skill_score: float,
        domain_score: float,
        soft_skill_score: float | None,
        culture_fit_score: float | None,
    ) -> float:
        """
        Dynamically weight the score based on which dimensions have data.
        Skills are split into mandatory (55%) and optional (10%) axes.
        This prevents penalising users who haven't completed the deep interview
        while rewarding those who have by incorporating richer signals.
        """
        has_soft    = soft_skill_score is not None
        has_culture = culture_fit_score is not None

        if has_soft and has_culture:
            return (
                skill_score          * MatchWeight.MANDATORY_FULL +
                optional_skill_score * MatchWeight.OPTIONAL_FULL +
                domain_score         * MatchWeight.DOMAIN_FULL +
                soft_skill_score     * MatchWeight.SOFT_SKILLS +
                culture_fit_score    * MatchWeight.CULTURE_FIT
            )
        elif has_culture:
            return (
                skill_score          * MatchWeight.MANDATORY_CULTURE +
                optional_skill_score * MatchWeight.OPTIONAL_CULTURE +
                domain_score         * MatchWeight.DOMAIN_CULTURE +
                culture_fit_score    * MatchWeight.CULTURE_ONLY
            )
        elif has_soft:
            return (
                skill_score          * MatchWeight.MANDATORY_SOFT +
                optional_skill_score * MatchWeight.OPTIONAL_SOFT +
                domain_score         * MatchWeight.DOMAIN_SOFT +
                soft_skill_score     * MatchWeight.SOFT_ONLY
            )
        else:
            return (
                skill_score          * MatchWeight.SKILLS_MANDATORY +
                optional_skill_score * MatchWeight.SKILLS_OPTIONAL +
                domain_score         * MatchWeight.DOMAIN
            )

    # ──────────────────────────────────────────────────────────────────────────
    # DIMENSION 1: EVIDENCE-WEIGHTED SKILL SCORE
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_skill_score(self, user_id: str, job_id: str) -> dict:
        """
        Evidence-weighted skill match split into mandatory (must_have) and optional axes.

        contribution = importance_weight × seniority_factor × evidence_weight
        evidence_weight: claimed_only=0.30, mentioned_once=0.50,
                         project_backed=0.80, multiple_productions=1.00

        mandatory_score = matched_must_have_weight / total_must_have_weight
        optional_score  = matched_optional_weight  / total_optional_weight

        Backward compat: existing nodes with importance='nice_to_have' fall through
        to $w_default and are counted in the optional pool.
        """
        evidence_params = {
            "e_multi":   EvidenceWeight.MULTIPLE_PRODUCTIONS,
            "e_proj":    EvidenceWeight.PROJECT_BACKED,
            "e_once":    EvidenceWeight.MENTIONED_ONCE,
            "e_claim":   EvidenceWeight.CLAIMED_ONLY,
            "e_unknown": EvidenceWeight.UNKNOWN,
        }

        # ── Mandatory skills (must_have only) ──────────────────────────────────
        mandatory_matched = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(req:JobSkillRequirement)
                  <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                  <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                  <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            WHERE req.importance = 'must_have'
            WITH req, s,
                 CASE
                   WHEN req.min_years IS NULL OR s.years IS NULL THEN 1.0
                   WHEN s.years >= req.min_years               THEN 1.0
                   ELSE s.years / toFloat(req.min_years)
                 END AS seniority_factor,
                 CASE coalesce(s.evidence_strength, 'unknown')
                   WHEN 'multiple_productions' THEN $e_multi
                   WHEN 'project_backed'       THEN $e_proj
                   WHEN 'mentioned_once'       THEN $e_once
                   WHEN 'claimed_only'         THEN $e_claim
                   ELSE $e_unknown
                 END AS evidence_weight
            RETURN
                collect(toLower(trim(req.name))) AS matched_names,
                reduce(acc = 0.0,
                       x IN collect($w_must * seniority_factor * evidence_weight) |
                       acc + x) AS matched_weight
            """,
            {"user_id": user_id, "job_id": job_id,
             "w_must": SkillImportanceWeight.MUST_HAVE, **evidence_params},
        )

        mandatory_all = await self.client.run_query(
            """
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_SKILL_REQUIREMENTS]->
                  (:JobSkillRequirements)-[:HAS_SKILL_FAMILY_REQ]->
                  (:JobSkillFamily)-[:REQUIRES_SKILL]->(req:JobSkillRequirement)
            WHERE req.importance = 'must_have'
            RETURN
                collect(toLower(trim(req.name))) AS all_names,
                reduce(acc = 0.0, x IN collect($w_must) | acc + x) AS total_weight
            """,
            {"job_id": job_id, "w_must": SkillImportanceWeight.MUST_HAVE},
        )

        # ── Optional skills (optional / nice_to_have / unknown importance) ─────
        optional_matched = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(req:JobSkillRequirement)
                  <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                  <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                  <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            WHERE req.importance <> 'must_have'
            WITH req, s,
                 CASE
                   WHEN req.min_years IS NULL OR s.years IS NULL THEN 1.0
                   WHEN s.years >= req.min_years               THEN 1.0
                   ELSE s.years / toFloat(req.min_years)
                 END AS seniority_factor,
                 CASE coalesce(s.evidence_strength, 'unknown')
                   WHEN 'multiple_productions' THEN $e_multi
                   WHEN 'project_backed'       THEN $e_proj
                   WHEN 'mentioned_once'       THEN $e_once
                   WHEN 'claimed_only'         THEN $e_claim
                   ELSE $e_unknown
                 END AS evidence_weight
            RETURN
                collect(toLower(trim(req.name))) AS matched_names,
                reduce(acc = 0.0,
                       x IN collect($w_optional * seniority_factor * evidence_weight) |
                       acc + x) AS matched_weight
            """,
            {"user_id": user_id, "job_id": job_id,
             "w_optional": SkillImportanceWeight.OPTIONAL, **evidence_params},
        )

        optional_all = await self.client.run_query(
            """
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_SKILL_REQUIREMENTS]->
                  (:JobSkillRequirements)-[:HAS_SKILL_FAMILY_REQ]->
                  (:JobSkillFamily)-[:REQUIRES_SKILL]->(req:JobSkillRequirement)
            WHERE req.importance <> 'must_have'
            RETURN
                collect(toLower(trim(req.name))) AS all_names,
                reduce(acc = 0.0, x IN collect($w_optional) | acc + x) AS total_weight
            """,
            {"job_id": job_id, "w_optional": SkillImportanceWeight.OPTIONAL},
        )

        # ── Aggregate ──────────────────────────────────────────────────────────
        m_matched_names  = mandatory_matched[0]["matched_names"] if mandatory_matched else []
        m_matched_weight = mandatory_matched[0]["matched_weight"] if mandatory_matched else 0.0
        m_all_names      = mandatory_all[0]["all_names"] if mandatory_all else []
        m_total_weight   = mandatory_all[0]["total_weight"] if mandatory_all else 0.0

        o_matched_names  = optional_matched[0]["matched_names"] if optional_matched else []
        o_matched_weight = optional_matched[0]["matched_weight"] if optional_matched else 0.0
        o_all_names      = optional_all[0]["all_names"] if optional_all else []
        o_total_weight   = optional_all[0]["total_weight"] if optional_all else 0.0

        mandatory_set     = set(m_matched_names)
        optional_set      = set(o_matched_names)
        missing_mandatory = [n for n in m_all_names if n not in mandatory_set]
        missing_optional  = [n for n in o_all_names if n not in optional_set]

        mandatory_score = (m_matched_weight / m_total_weight) if m_total_weight > 0 else 0.0
        optional_score  = (o_matched_weight / o_total_weight) if o_total_weight > 0 else 0.0

        return {
            "mandatory_score":  mandatory_score,
            "optional_score":   optional_score,
            "matched":          m_matched_names,
            "missing":          missing_mandatory,
            "optional_matched": o_matched_names,
            "optional_missing": missing_optional,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # DIMENSION 2: DEPTH-WEIGHTED DOMAIN SCORE
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_domain_score(self, user_id: str, job_id: str) -> dict:
        """
        Domain score with depth weighting.

        Each matched domain contributes: depth_weight / total_domains
        depth weights: deep=1.00, moderate=0.70, shallow=0.40

        Shallow domain experience is no longer equivalent to deep expertise.
        """
        records = await self.client.run_query(
            """
            // Collect job domain requirements (the denominator)
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_DOMAIN_REQUIREMENTS]->
                  (:JobDomainRequirements)-[:HAS_DOMAIN_FAMILY_REQ]->
                  (:JobDomainFamily)-[:REQUIRES_DOMAIN]->(dr:JobDomainRequirement)
            WITH collect({name: toLower(trim(dr.name))}) AS job_domains_raw

            // Collect user domains (direct)
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_DOMAIN_CATEGORY]->
                  (:DomainCategory)-[:HAS_DOMAIN_FAMILY]->
                  (:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
            WITH job_domains_raw,
                 collect({name: toLower(trim(d.name)), depth: coalesce(d.depth, 'unknown')}) AS direct_domains

            // Collect user domains inferred from projects
            OPTIONAL MATCH (u2:User {id: $user_id})-[:HAS_PROJECT_CATEGORY]->
                  (:ProjectCategory)-[:HAS_PROJECT]->(p:Project)-[:IN_DOMAIN]->(pd:Domain)
            WITH job_domains_raw, direct_domains,
                 collect({name: toLower(trim(pd.name)), depth: coalesce(pd.depth, 'unknown')}) AS project_domains
            WITH job_domains_raw, direct_domains + project_domains AS all_user_domains

            RETURN job_domains_raw, all_user_domains
            """,
            {"user_id": user_id, "job_id": job_id},
        )

        if not records:
            return {"score": 0.0, "matched": [], "missing": []}

        row             = records[0]
        job_domains_raw = row.get("job_domains_raw") or []
        user_domains    = row.get("all_user_domains") or []

        if not job_domains_raw:
            return {"score": 0.0, "matched": [], "missing": []}

        job_names = [d["name"] for d in job_domains_raw]
        # Build user domain lookup: name → best depth seen
        user_depth_map: dict[str, str] = {}
        for ud in user_domains:
            name  = ud.get("name", "")
            depth = ud.get("depth", "unknown")
            # Keep the best depth if the same domain appears multiple times
            existing = user_depth_map.get(name, "unknown")
            priority = {"deep": 3, "moderate": 2, "shallow": 1, "unknown": 0}
            if priority.get(depth, 0) > priority.get(existing, 0):
                user_depth_map[name] = depth

        matched = []
        missing = []
        total_depth_weight = 0.0
        for jname in job_names:
            if jname in user_depth_map:
                matched.append(jname)
                total_depth_weight += DomainDepthWeight.get(user_depth_map[jname])
            else:
                missing.append(jname)

        # Score = sum(depth_weights of matched) / (total_domains × max_depth_weight)
        # Max possible = each domain matched at full depth = len(job_names) × 1.0
        score = total_depth_weight / len(job_names) if job_names else 0.0

        return {"score": score, "matched": matched, "missing": missing}

    # ──────────────────────────────────────────────────────────────────────────
    # DIMENSION 3: SOFT SKILL ALIGNMENT SCORE
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_soft_skill_score(self, user_id: str, job_id: str) -> dict:
        """
        Soft skill score based on SoftSkillRequirement nodes (job side) vs
        ProblemSolvingPattern + Experience.contribution_type + BehavioralInsight (user side).

        Returns None score when job has no SoftSkillRequirements or user has no
        behavioral data — allowing graceful weight redistribution.

        Also returns behavioral_risk_flags: risk signals from BehavioralInsight nodes
        that conflict with dealbreaker soft skills.
        """
        # Query job soft skill requirements
        soft_reqs = await self.client.run_query(
            """
            OPTIONAL MATCH (j:Job {id: $job_id})-[:REQUIRES_QUALITY]->(s:SoftSkillRequirement)
            RETURN s.name AS name, s.quality AS quality,
                   coalesce(s.dealbreaker, false) AS dealbreaker
            """,
            {"job_id": job_id},
        )
        soft_reqs = [r for r in soft_reqs if r.get("quality")]
        if not soft_reqs:
            return {"score": None, "risk_flags": []}

        # Query user patterns and behavioral insights
        user_patterns = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_PATTERN_CATEGORY]->
                  (:PatternCategory)-[:HAS_PATTERN]->(p:ProblemSolvingPattern)
            RETURN toLower(trim(p.pattern)) AS pattern
            """,
            {"user_id": user_id},
        )
        user_pattern_set = {r["pattern"] for r in user_patterns if r.get("pattern")}

        # Also pull ownership signals from experience contribution_type
        exp_contributions = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_EXPERIENCE_CATEGORY]->
                  (:ExperienceCategory)-[:HAS_EXPERIENCE]->(e:Experience)
            RETURN coalesce(e.contribution_type, 'unclear') AS contribution_type
            """,
            {"user_id": user_id},
        )
        has_leadership = any(
            r["contribution_type"] in ("sole_engineer", "tech_lead")
            for r in exp_contributions
        )
        if has_leadership:
            # Ownership is evidenced by leading/sole work
            user_pattern_set.add("_has_ownership_evidence")

        # Pull behavioral insights for risk flag detection
        behavior_rows = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_BEHAVIORAL_INSIGHT]->(b:BehavioralInsight)
            RETURN b.insight_type AS insight_type, b.trigger AS trigger, b.implication AS implication
            """,
            {"user_id": user_id},
        )
        risk_behavior = [
            r for r in behavior_rows
            if r.get("insight_type") in BEHAVIORAL_RISK_TYPES
        ]

        if not user_pattern_set and not has_leadership:
            # No behavioral data at all — cannot score
            return {"score": None, "risk_flags": []}

        total = len(soft_reqs)
        matched_weight = 0.0
        risk_flags: list[str] = []

        for req in soft_reqs:
            quality      = (req.get("quality") or "").lower()
            dealbreaker  = req.get("dealbreaker", False)
            patterns_needed = [p.lower() for p in SOFT_SKILL_TO_PATTERN.get(quality, [])]

            # Ownership quality: also accept _has_ownership_evidence signal
            if quality == "ownership" and "_has_ownership_evidence" in user_pattern_set:
                patterns_needed = patterns_needed + ["_has_ownership_evidence"]

            has_evidence = any(p in user_pattern_set for p in patterns_needed)

            # Check if any risk behavior conflicts with this requirement
            if not has_evidence and risk_behavior and dealbreaker:
                risk_flags.append(
                    f"Behavioral signal conflicts with '{quality}' requirement "
                    f"(dealbreaker): {risk_behavior[0].get('implication', 'push-back pattern observed')}"
                )
                matched_weight += 0.0  # no credit for dealbreaker with risk signal
            elif has_evidence:
                matched_weight += 1.0
            else:
                matched_weight += 0.5  # neutral — no data either way

        score = matched_weight / total if total > 0 else None

        return {"score": score, "risk_flags": risk_flags}

    # ──────────────────────────────────────────────────────────────────────────
    # DIMENSION 4: CULTURE FIT SCORE (digital twin alignment)
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_culture_fit_score(self, user_id: str, job_id: str) -> dict:
        """
        Culture fit score based on CultureIdentity (user) vs TeamCultureIdentity (job).

        Returns None score when either side lacks digital twin culture data,
        allowing graceful weight redistribution to technical dimensions.

        Matching axes:
          1. pace_preference vs TeamCultureIdentity.pace
          2. feedback_preference vs TeamCultureIdentity.feedback_culture
          3. leadership_style vs TeamCultureIdentity.management_style
          4. energy_drains NOT overlapping with TeamCultureIdentity.anti_patterns
          5. team_size_preference vs TeamComposition.team_size (when available)
        """
        import json as _j

        user_culture = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_CULTURE_IDENTITY]->(c:CultureIdentity)
            RETURN c.team_size_preference AS team_size_preference,
                   c.leadership_style     AS leadership_style,
                   c.feedback_preference  AS feedback_preference,
                   c.pace_preference      AS pace_preference,
                   c.energy_drains        AS energy_drains
            """,
            {"user_id": user_id},
        )
        job_culture = await self.client.run_query(
            """
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_TEAM_CULTURE]->(tc:TeamCultureIdentity)
            RETURN tc.management_style    AS management_style,
                   tc.feedback_culture   AS feedback_culture,
                   tc.pace               AS pace,
                   tc.anti_patterns      AS anti_patterns,
                   tc.decision_making    AS decision_making
            """,
            {"job_id": job_id},
        )

        if not user_culture or not user_culture[0].get("pace_preference"):
            return {"score": None}
        if not job_culture or not job_culture[0].get("pace"):
            return {"score": None}

        uc = user_culture[0]
        jc = job_culture[0]

        checks = 0
        hits   = 0.0

        # 1. Pace
        user_pace = (uc.get("pace_preference") or "").lower()
        job_pace  = (jc.get("pace") or "").lower()
        if user_pace and job_pace:
            checks += 1
            compatible = CULTURE_FIELD_MAP["pace"].get(user_pace, [])
            hits += 1.0 if job_pace in compatible else 0.0

        # 2. Feedback
        user_fb = (uc.get("feedback_preference") or "").lower()
        job_fb  = (jc.get("feedback_culture") or "").lower()
        if user_fb and job_fb:
            checks += 1
            compatible = CULTURE_FIELD_MAP["feedback"].get(user_fb, [])
            hits += 1.0 if job_fb in compatible else 0.0

        # 3. Leadership style vs management style
        user_lead = (uc.get("leadership_style") or "").lower()
        job_mgmt  = (jc.get("management_style") or "").lower()
        if user_lead and job_mgmt:
            checks += 1
            compatible = CULTURE_FIELD_MAP["management"].get(user_lead, [])
            hits += 1.0 if job_mgmt in compatible else 0.0

        # 4. Energy drains vs anti-patterns (overlap = bad = lower score)
        raw_drains       = uc.get("energy_drains") or "[]"
        raw_anti         = jc.get("anti_patterns") or "[]"
        try:
            drains   = _j.loads(raw_drains) if isinstance(raw_drains, str) else raw_drains
            anti     = _j.loads(raw_anti)   if isinstance(raw_anti, str)   else raw_anti
        except Exception:
            drains, anti = [], []

        if drains and anti:
            drains_norm = {d.lower().strip() for d in drains}
            anti_norm   = {a.lower().strip() for a in anti}
            overlap     = drains_norm & anti_norm
            checks += 1
            # No overlap = full hit (user's drains don't match job's anti-patterns)
            hits += 1.0 if not overlap else max(0.0, 1.0 - len(overlap) / max(len(drains_norm), 1))

        score = (hits / checks) if checks > 0 else None
        return {"score": score}

    # ──────────────────────────────────────────────────────────────────────────
    # LEGACY BONUS SIGNALS (kept for backwards compat, not in total_score)
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_culture_bonus(self, user_id: str, job_id: str) -> dict:
        """
        Legacy culture bonus: ratio of job WorkStyle nodes that match user Preference(work_style).
        Uses synonym normalization. Kept as supplementary signal alongside culture_fit_score.
        """
        records = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_PREFERENCE_CATEGORY]->
                  (:PreferenceCategory)-[:HAS_PREFERENCE]->(p:Preference)
            WHERE p.type = 'work_style'
            WITH collect(toLower(trim(p.value))) AS user_styles

            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_CULTURE_REQUIREMENTS]->
                  (:JobCultureRequirements)-[:HAS_WORK_STYLE]->(ws:WorkStyle)
            RETURN user_styles, collect(toLower(trim(ws.style))) AS job_styles
            """,
            {"user_id": user_id, "job_id": job_id},
        )
        if not records:
            return {"bonus": 0.0}
        user_raw = records[0]["user_styles"] or []
        job_raw  = records[0]["job_styles"]  or []
        if not job_raw:
            return {"bonus": 0.0}
        user_canonical = {normalize_work_style(s) for s in user_raw}
        matched = sum(1 for js in job_raw if normalize_work_style(js) in user_canonical)
        return {"bonus": round(matched / len(job_raw), 3)}

    async def _compute_preference_bonus(self, user_id: str, job_id: str) -> dict:
        """
        Preference bonus: remote_work + company_size match ratio.
        """
        records = await self.client.run_query(
            """
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_PREFERENCE_CATEGORY]->
                  (:PreferenceCategory)-[:HAS_PREFERENCE]->(p:Preference)
            WHERE p.type IN ['remote_work', 'company_size']
            WITH collect({type: p.type, value: toLower(trim(p.value))}) AS user_prefs

            MATCH (j:Job {id: $job_id})
            RETURN user_prefs,
                   toLower(trim(j.remote_policy)) AS remote_policy,
                   toLower(trim(j.company_size))  AS company_size
            """,
            {"user_id": user_id, "job_id": job_id},
        )
        if not records or not records[0]["user_prefs"]:
            return {"bonus": 0.0}
        row   = records[0]
        prefs = row["user_prefs"]
        matched = 0
        for pref in prefs:
            if pref["type"] == "remote_work":
                if normalize_work_style(pref["value"]) == normalize_work_style(row["remote_policy"] or ""):
                    matched += 1
            elif pref["type"] == "company_size":
                if pref["value"] == (row["company_size"] or ""):
                    matched += 1
        return {"bonus": round(matched / len(prefs), 3)}

    # ──────────────────────────────────────────────────────────────────────────
    # GRAPH PATH TRACING (Scrutability)
    # ──────────────────────────────────────────────────────────────────────────

    async def trace_match_paths(
        self, user_id: str, job_id: str, limit: int = 10
    ) -> list[dict]:
        """
        Find explicit graph paths connecting a user to a job via MATCHES edges.
        Every path represents a concrete, auditable match reason.
        """
        records = await self.client.run_query(
            """
            MATCH path = (u:User {id: $user_id})
                         -[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                         -[:HAS_SKILL_FAMILY]->(:SkillFamily)
                         -[:HAS_SKILL]->(s:Skill)
                         -[:MATCHES]->(r:JobSkillRequirement)
                         <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                         <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                         <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            RETURN
                [node IN nodes(path) | coalesce(node.name, node.id, node.title, '')] AS node_names,
                [rel  IN relationships(path) | type(rel)] AS rel_types,
                length(path) AS path_length
            ORDER BY path_length
            LIMIT $limit

            UNION

            MATCH path = (u:User {id: $user_id})
                         -[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
                         -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)
                         -[:HAS_DOMAIN]->(d:Domain)
                         -[:MATCHES]->(dr:JobDomainRequirement)
                         <-[:REQUIRES_DOMAIN]-(:JobDomainFamily)
                         <-[:HAS_DOMAIN_FAMILY_REQ]-(:JobDomainRequirements)
                         <-[:HAS_DOMAIN_REQUIREMENTS]-(j:Job {id: $job_id})
            RETURN
                [node IN nodes(path) | coalesce(node.name, node.id, node.title, '')] AS node_names,
                [rel  IN relationships(path) | type(rel)] AS rel_types,
                length(path) AS path_length
            ORDER BY path_length
            LIMIT $limit
            """,
            {"user_id": user_id, "job_id": job_id, "limit": limit},
        )
        paths = []
        for record in records:
            names    = record.get("node_names", [])
            rels     = record.get("rel_types", [])
            path_str = " → ".join(
                part for pair in zip(names, rels + [""]) for part in pair if part
            )
            paths.append({"path": path_str, "length": record.get("path_length")})
        return paths

    # ──────────────────────────────────────────────────────────────────────────
    # RICH CONTEXT FOR LLM EXPLANATION
    # ──────────────────────────────────────────────────────────────────────────

    async def gather_match_context(self, user_id: str, job_id: str) -> dict:
        """
        Pull full contextual data for a user-job pair to power a detailed LLM explanation.

        Now includes the complete digital twin portrait on both sides:
          User: skills+evidence, domains+depth, assessment, motivation, goals,
                culture identity, behavioral insights, anecdotes
          Job:  skill reqs, domain reqs, soft skill reqs, team culture,
                role context, hiring goals, success metrics, interview signals
        """
        import json as _j

        # ── User side ──────────────────────────────────────────────────────────

        matched_rich = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(req:JobSkillRequirement)
                  <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                  <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                  <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            OPTIONAL MATCH (p:Project {user_id: $user_id})-[demo:DEMONSTRATES_SKILL]->(s)
            OPTIONAL MATCH (s)-[:GROUNDED_IN]->(anec:Anecdote)
            RETURN s.name              AS skill,
                   s.level             AS level,
                   s.years             AS years,
                   s.evidence_strength AS evidence_strength,
                   req.importance      AS importance,
                   req.min_years       AS min_years,
                   collect(DISTINCT demo.context)[0..3] AS usage_contexts,
                   collect(DISTINCT demo.what)[0..2]    AS usage_what,
                   collect(DISTINCT demo.outcome)[0..2] AS outcomes,
                   collect(DISTINCT anec.situation)[0..1] AS anecdote_situations,
                   collect(DISTINCT anec.result)[0..1]    AS anecdote_results
            ORDER BY CASE req.importance WHEN 'must_have' THEN 0 ELSE 1 END, s.years DESC
            """,
            {"user_id": user_id, "job_id": job_id},
        )

        all_reqs = await self.client.run_query(
            """
            MATCH (j:Job {id: $job_id})-[:HAS_SKILL_REQUIREMENTS]->(:JobSkillRequirements)
                  -[:HAS_SKILL_FAMILY_REQ]->(:JobSkillFamily)-[:REQUIRES_SKILL]->(req:JobSkillRequirement)
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(req)
            RETURN req.name AS skill, req.importance AS importance,
                   req.min_years AS min_years, s IS NOT NULL AS matched
            """,
            {"user_id": user_id, "job_id": job_id},
        )
        missing_must = [
            {"skill": r["skill"], "min_years": r["min_years"]}
            for r in all_reqs
            if not r["matched"] and r["importance"] == "must_have"
        ]
        missing_nice = [r["skill"] for r in all_reqs if not r["matched"] and r["importance"] != "must_have"]

        assessment_rows = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_ASSESSMENT]->(a:CriticalAssessment)
            RETURN a.overall_signal AS overall_signal, a.seniority_assessment AS seniority_assessment,
                   a.depth_vs_breadth AS depth_vs_breadth, a.candidate_identity AS candidate_identity,
                   a.honest_summary AS honest_summary, a.genuine_strengths AS genuine_strengths,
                   a.red_flags AS red_flags, a.inflated_skills AS inflated_skills,
                   a.five_w_h_summary AS five_w_h_summary
            """,
            {"user_id": user_id},
        )
        assessment = {}
        if assessment_rows:
            raw = dict(assessment_rows[0])
            for key in ("genuine_strengths", "red_flags", "inflated_skills"):
                val = raw.get(key)
                if isinstance(val, str):
                    try:
                        raw[key] = _j.loads(val)
                    except Exception:
                        raw[key] = [val] if val else []
            if isinstance(raw.get("five_w_h_summary"), str):
                try:
                    raw["five_w_h_summary"] = _j.loads(raw["five_w_h_summary"])
                except Exception:
                    pass
            assessment = raw

        # User digital twin — human portrait
        motivations = await self.client.run_query(
            "OPTIONAL MATCH (u:User {id: $user_id})-[:MOTIVATED_BY]->(m:Motivation) "
            "RETURN m.category AS category, m.strength AS strength, m.evidence AS evidence "
            "ORDER BY m.strength DESC LIMIT 3",
            {"user_id": user_id},
        )
        values = await self.client.run_query(
            "OPTIONAL MATCH (u:User {id: $user_id})-[:HOLDS_VALUE]->(v:Value) "
            "RETURN v.name AS name, v.priority_rank AS priority_rank, v.evidence AS evidence "
            "ORDER BY v.priority_rank LIMIT 5",
            {"user_id": user_id},
        )
        goals = await self.client.run_query(
            "OPTIONAL MATCH (u:User {id: $user_id})-[:ASPIRES_TO]->(g:Goal) "
            "RETURN g.type AS type, g.description AS description, "
            "g.timeframe_years AS timeframe_years, g.clarity_level AS clarity_level",
            {"user_id": user_id},
        )
        user_culture = await self.client.run_query(
            "OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_CULTURE_IDENTITY]->(c:CultureIdentity) "
            "RETURN c.team_size_preference AS team_size_preference, "
            "c.leadership_style AS leadership_style, c.feedback_preference AS feedback_preference, "
            "c.pace_preference AS pace_preference, c.energy_sources AS energy_sources, "
            "c.energy_drains AS energy_drains, c.conflict_style AS conflict_style",
            {"user_id": user_id},
        )
        behavioral_insights = await self.client.run_query(
            "OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_BEHAVIORAL_INSIGHT]->(b:BehavioralInsight) "
            "RETURN b.insight_type AS insight_type, b.trigger AS trigger, b.implication AS implication",
            {"user_id": user_id},
        )
        domains_rich = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
                  -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
                  -[:MATCHES]->(dr:JobDomainRequirement)
                  <-[:REQUIRES_DOMAIN]-(:JobDomainFamily)
                  <-[:HAS_DOMAIN_FAMILY_REQ]-(:JobDomainRequirements)
                  <-[:HAS_DOMAIN_REQUIREMENTS]-(j:Job {id: $job_id})
            RETURN d.name AS domain, d.depth AS depth, d.years_experience AS years
            ORDER BY d.years_experience DESC
            """,
            {"user_id": user_id, "job_id": job_id},
        )

        # ── Job side ───────────────────────────────────────────────────────────

        job_meta_rows = await self.client.run_query(
            "MATCH (j:Job {id: $job_id}) RETURN j.experience_years_min AS exp_min, "
            "j.company_size AS company_size, j.remote_policy AS remote_policy, "
            "j.title AS title, j.company AS company",
            {"job_id": job_id},
        )
        job_meta = dict(job_meta_rows[0]) if job_meta_rows else {}

        soft_skill_reqs = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:REQUIRES_QUALITY]->(s:SoftSkillRequirement) "
            "RETURN s.name AS name, s.quality AS quality, s.expectation AS expectation, "
            "s.evidence_indicator AS evidence_indicator, s.dealbreaker AS dealbreaker",
            {"job_id": job_id},
        )
        job_team_culture = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_TEAM_CULTURE]->(tc:TeamCultureIdentity) "
            "RETURN tc.decision_making AS decision_making, tc.communication_style AS communication_style, "
            "tc.feedback_culture AS feedback_culture, tc.pace AS pace, tc.work_life AS work_life, "
            "tc.management_style AS management_style, tc.team_values AS team_values, "
            "tc.anti_patterns AS anti_patterns",
            {"job_id": job_id},
        )
        role_context = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_ROLE_CONTEXT]->(r:RoleContext) "
            "RETURN r.owns_what AS owns_what, r.first_90_days AS first_90_days, "
            "r.growth_trajectory AS growth_trajectory, r.why_role_open AS why_role_open",
            {"job_id": job_id},
        )
        hiring_goals = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:DRIVEN_BY]->(h:HiringGoal) "
            "RETURN h.gap_being_filled AS gap_being_filled, h.urgency AS urgency, "
            "h.dealbreaker_absence AS dealbreaker_absence, h.ideal_background AS ideal_background",
            {"job_id": job_id},
        )
        success_metrics = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:DEFINES_SUCCESS_BY]->(m:SuccessMetric) "
            "RETURN m.at_90_days AS at_90_days, m.at_1_year AS at_1_year, "
            "m.key_deliverables AS key_deliverables",
            {"job_id": job_id},
        )
        team_composition = await self.client.run_query(
            "OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_TEAM_COMPOSITION]->(t:TeamComposition) "
            "RETURN t.team_size AS team_size, t.team_makeup AS team_makeup, "
            "t.hiring_for_gap AS hiring_for_gap",
            {"job_id": job_id},
        )

        return {
            # User technical
            "matched_skills_rich":   [dict(r) for r in matched_rich],
            "missing_must_have":     missing_must,
            "missing_nice":          missing_nice,
            "matched_domains_rich":  [dict(r) for r in domains_rich],
            # User assessment
            "assessment":            assessment,
            # User human portrait
            "motivations":           [dict(r) for r in motivations if r.get("category")],
            "values":                [dict(r) for r in values if r.get("name")],
            "goals":                 [dict(r) for r in goals if r.get("description")],
            "user_culture":          dict(user_culture[0]) if user_culture and user_culture[0].get("pace_preference") else {},
            "behavioral_insights":   [dict(r) for r in behavioral_insights if r.get("insight_type")],
            # Job context
            "job_meta":              job_meta,
            "soft_skill_reqs":       [dict(r) for r in soft_skill_reqs if r.get("quality")],
            "job_team_culture":      dict(job_team_culture[0]) if job_team_culture and job_team_culture[0].get("pace") else {},
            "role_context":          dict(role_context[0]) if role_context and role_context[0].get("owns_what") else {},
            "hiring_goals":          dict(hiring_goals[0]) if hiring_goals and hiring_goals[0].get("gap_being_filled") else {},
            "success_metrics":       dict(success_metrics[0]) if success_metrics and success_metrics[0].get("at_90_days") else {},
            "team_composition":      dict(team_composition[0]) if team_composition and team_composition[0].get("team_size") else {},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    def _build_explanation(
        self,
        skill_score: float,
        domain_score: float,
        soft_skill_score: float | None,
        culture_fit_score: float | None,
        culture_bonus: float,
        preference_bonus: float,
    ) -> str:
        parts = []

        if skill_score >= 0.8:
            parts.append("Strong evidence-weighted skill alignment")
        elif skill_score >= 0.5:
            parts.append("Moderate skill overlap")
        elif skill_score > 0:
            parts.append("Limited skill match (check evidence depth)")
        else:
            parts.append("No skill overlap found")

        if domain_score >= 0.7:
            parts.append("deep domain expertise aligns")
        elif domain_score >= 0.4:
            parts.append("partial domain match")

        if soft_skill_score is not None:
            if soft_skill_score >= 0.8:
                parts.append("strong soft skill alignment")
            elif soft_skill_score >= 0.5:
                parts.append("partial soft skill match")
            else:
                parts.append("soft skill gaps detected")

        if culture_fit_score is not None:
            if culture_fit_score >= 0.8:
                parts.append("strong culture fit")
            elif culture_fit_score >= 0.5:
                parts.append("partial culture alignment")
            else:
                parts.append("culture mismatch signals")
        elif culture_bonus >= 0.7:
            parts.append("work style alignment")

        if preference_bonus == 1.0:
            parts.append("preferences fully satisfied")
        elif preference_bonus > 0:
            parts.append("partial preference match")

        return "; ".join(parts) if parts else "Insufficient overlap for match"
