"""
Pure graph-based matching engine.

All scoring is done through Cypher set-intersection queries — no vectors,
no embeddings. Every score component is directly traceable to explicit
graph edges, making the system fully scrutable.

Base scoring dimensions (sum to 100%):
  - Skills  (65%): weighted intersection via MATCHES edges, with seniority factor
  - Domain  (35%): set intersection of user domains ∩ job domain requirements

Bonus signals (0-1, not weighted into total_score):
  - culture_bonus:    work-style preference match ratio
  - preference_bonus: remote_work + company_size match ratio

Skill importance weights:
  - must_have:    1.0
  - nice_to_have: 0.5
  - default:      0.8

Seniority factor per matched skill:
  - user.years >= req.min_years OR either is null → 1.0 (full credit)
  - user.years < req.min_years → user.years / req.min_years (partial credit)

Name normalization: toLower(trim(...)) applied in all Cypher comparisons.
"""

import logging
from database.neo4j_client import Neo4jClient
from models.schemas import MatchResult, BatchMatchResponse, CandidateResult, BatchCandidateResponse
from models.taxonomies import MatchWeight, SkillImportanceWeight, normalize_work_style

logger = logging.getLogger(__name__)


class MatchingEngine:
    def __init__(self, client: Neo4jClient):
        self.client = client

    # ──────────────────────────────────────────────────────────────────────────
    # BATCH MATCHING
    # ──────────────────────────────────────────────────────────────────────────

    async def rank_all_jobs_for_user(self, user_id: str) -> BatchMatchResponse:
        """
        Score ALL jobs in the database for a given user.
        Returns results sorted by total_score descending.
        """
        jobs = await self.client.run_query(
            "MATCH (j:Job) RETURN j.id AS job_id"
        )

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
        """
        Score ALL users in the database against a given job.
        Returns results sorted by total_score descending (reverse-match).
        """
        users = await self.client.run_query(
            "MATCH (u:User) RETURN u.id AS id"
        )

        results: list[CandidateResult] = []
        for user_record in users:
            match = await self._score_user_job_pair(user_record["id"], job_id)
            if match is not None:
                results.append(CandidateResult(
                    user_id=user_record["id"],
                    total_score=match.total_score,
                    skill_score=match.skill_score,
                    domain_score=match.domain_score,
                    culture_bonus=match.culture_bonus,
                    preference_bonus=match.preference_bonus,
                    matched_skills=match.matched_skills,
                    missing_skills=match.missing_skills,
                    matched_domains=match.matched_domains,
                    missing_domains=match.missing_domains,
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
        """
        Compute match score for a single user-job pair.
        Base score = Skills (65%) + Domain (35%).
        Bonus signals = culture_bonus + preference_bonus (shown separately).
        Returns None if either user or job is not found.
        """
        job_info = await self.client.run_query(
            "MATCH (j:Job {id: $job_id}) RETURN j.title AS title, j.company AS company",
            {"job_id": job_id},
        )
        if not job_info:
            logger.warning(f"Job not found: {job_id}")
            return None

        user_check = await self.client.run_query(
            "MATCH (u:User {id: $user_id}) RETURN u.id AS id",
            {"user_id": user_id},
        )
        if not user_check:
            logger.warning(f"User not found: {user_id}")
            return None

        skill_data   = await self._compute_skill_score(user_id, job_id)
        domain_data  = await self._compute_domain_score(user_id, job_id)
        culture_data = await self._compute_culture_bonus(user_id, job_id)
        pref_data    = await self._compute_preference_bonus(user_id, job_id)

        skill_score       = skill_data.get("score", 0.0) or 0.0
        domain_score      = domain_data.get("score", 0.0) or 0.0
        culture_bonus     = culture_data.get("bonus", 0.0) or 0.0
        preference_bonus  = pref_data.get("bonus", 0.0) or 0.0

        total_score = round(
            skill_score  * MatchWeight.SKILLS +
            domain_score * MatchWeight.DOMAIN,
            4,
        )

        return MatchResult(
            job_id=job_id,
            job_title=job_info[0]["title"] or "Unknown",
            company=job_info[0]["company"],
            total_score=total_score,
            skill_score=round(skill_score, 4),
            domain_score=round(domain_score, 4),
            culture_bonus=round(culture_bonus, 4),
            preference_bonus=round(preference_bonus, 4),
            matched_skills=skill_data.get("matched", []),
            missing_skills=skill_data.get("missing", []),
            matched_domains=domain_data.get("matched", []),
            missing_domains=domain_data.get("missing", []),
            explanation=self._build_explanation(
                skill_score, domain_score, culture_bonus, preference_bonus
            ),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # BASE SCORE COMPONENTS
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_skill_score(self, user_id: str, job_id: str) -> dict:
        """
        Weighted skill match via MATCHES edges with seniority factor.

        For each matched skill pair (Skill → MATCHES → JobSkillRequirement):
          contribution = importance_weight * seniority_factor
          seniority_factor = min(user.years / req.min_years, 1.0) if both known, else 1.0

        score = sum(contributions) / sum(all job requirement weights)

        Returns: {score, matched: [names], missing: [names]}
        """
        # Query 1: matched skills via MATCHES edges
        matched_records = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(req:JobSkillRequirement)
                  <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                  <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                  <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            WITH req, s,
                 CASE req.importance
                   WHEN 'must_have'    THEN $w_must
                   WHEN 'nice_to_have' THEN $w_nice
                   ELSE $w_default
                 END AS imp_weight,
                 CASE
                   WHEN req.min_years IS NULL OR s.years IS NULL THEN 1.0
                   WHEN s.years >= req.min_years               THEN 1.0
                   ELSE s.years / toFloat(req.min_years)
                 END AS seniority_factor
            RETURN
                collect(toLower(trim(req.name))) AS matched_names,
                reduce(acc = 0.0, x IN collect(imp_weight * seniority_factor) | acc + x)
                    AS matched_weight
            """,
            {
                "user_id": user_id,
                "job_id": job_id,
                "w_must": SkillImportanceWeight.MUST_HAVE,
                "w_nice": SkillImportanceWeight.NICE_TO_HAVE,
                "w_default": SkillImportanceWeight.DEFAULT,
            },
        )

        # Query 2: all job requirements (for total weight and missing list)
        all_records = await self.client.run_query(
            """
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_SKILL_REQUIREMENTS]->
                  (:JobSkillRequirements)-[:HAS_SKILL_FAMILY_REQ]->
                  (:JobSkillFamily)-[:REQUIRES_SKILL]->(req:JobSkillRequirement)
            RETURN
                collect(toLower(trim(req.name))) AS all_names,
                reduce(acc = 0.0, x IN collect(
                    CASE req.importance
                      WHEN 'must_have'    THEN $w_must
                      WHEN 'nice_to_have' THEN $w_nice
                      ELSE $w_default
                    END
                ) | acc + x) AS total_weight
            """,
            {
                "job_id": job_id,
                "w_must": SkillImportanceWeight.MUST_HAVE,
                "w_nice": SkillImportanceWeight.NICE_TO_HAVE,
                "w_default": SkillImportanceWeight.DEFAULT,
            },
        )

        matched_names  = matched_records[0]["matched_names"] if matched_records else []
        matched_weight = matched_records[0]["matched_weight"] if matched_records else 0.0
        all_names      = all_records[0]["all_names"] if all_records else []
        total_weight   = all_records[0]["total_weight"] if all_records else 0.0

        matched_set  = set(matched_names)
        missing      = [n for n in all_names if n not in matched_set]
        score        = (matched_weight / total_weight) if total_weight > 0 else 0.0

        return {"score": score, "matched": matched_names, "missing": missing}

    async def _compute_domain_score(self, user_id: str, job_id: str) -> dict:
        """
        Domain set intersection score.

        Returns: {score, matched: [domain_names], missing: [domain_names]}
        """
        records = await self.client.run_query(
            """
            // Collect user domains (direct + inferred from projects)
            OPTIONAL MATCH (u:User {id: $user_id})-[:HAS_DOMAIN_CATEGORY]->
                  (:DomainCategory)-[:HAS_DOMAIN_FAMILY]->
                  (:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
            WITH collect(toLower(trim(d.name))) AS user_domains

            OPTIONAL MATCH (u2:User {id: $user_id})-[:HAS_PROJECT_CATEGORY]->
                  (:ProjectCategory)-[:HAS_PROJECT]->(p:Project)-[:IN_DOMAIN]->(pd:Domain)
            WITH user_domains, collect(toLower(trim(pd.name))) AS project_domains
            WITH user_domains + project_domains AS all_user_domains

            // Collect job domain requirements
            OPTIONAL MATCH (j:Job {id: $job_id})-[:HAS_DOMAIN_REQUIREMENTS]->
                  (:JobDomainRequirements)-[:HAS_DOMAIN_FAMILY_REQ]->
                  (:JobDomainFamily)-[:REQUIRES_DOMAIN]->(dr:JobDomainRequirement)
            WITH all_user_domains, collect(toLower(trim(dr.name))) AS job_domains

            WITH all_user_domains, job_domains,
                 [d IN job_domains WHERE d IN all_user_domains]     AS matched_domains,
                 [d IN job_domains WHERE NOT d IN all_user_domains] AS missing_domains

            RETURN
                CASE WHEN size(job_domains) > 0
                     THEN toFloat(size(matched_domains)) / toFloat(size(job_domains))
                     ELSE 0.0
                END AS score,
                matched_domains AS matched,
                missing_domains AS missing
            """,
            {"user_id": user_id, "job_id": job_id},
        )
        return records[0] if records else {"score": 0.0, "matched": [], "missing": []}

    # ──────────────────────────────────────────────────────────────────────────
    # BONUS SIGNALS (not weighted into total_score)
    # ──────────────────────────────────────────────────────────────────────────

    async def _compute_culture_bonus(self, user_id: str, job_id: str) -> dict:
        """
        Culture fit bonus: ratio of job work styles that match user work_style preferences.

        Uses synonym normalization (WORK_STYLE_SYNONYMS) so that e.g. "remote"
        matches "remote-first", "high-autonomy" matches "autonomous", etc.

        Returns: {bonus} — 0.0 if job has no work styles or user has none
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
        Preference fit bonus: ratio of checkable user preferences that the job satisfies.
        Checks: remote_work vs j.remote_policy (with synonym normalization),
                company_size vs j.company_size (exact canonical match).

        Returns: {bonus} — 0.0 if user has no checkable preferences
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
                # Normalize both sides so "remote-first" == "remote" etc.
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

        Traverses: User → skill/domain hierarchy → Skill/Domain
                   → MATCHES → JobSkillRequirement/JobDomainRequirement
                   → job hierarchy → Job

        Every path represents a concrete match reason traceable in the graph.
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
            names = record.get("node_names", [])
            rels  = record.get("rel_types", [])
            path_str = " → ".join(
                part for pair in zip(names, rels + [""]) for part in pair if part
            )
            paths.append({
                "path": path_str,
                "length": record.get("path_length"),
            })
        return paths

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    def _build_explanation(
        self,
        skill_score: float,
        domain_score: float,
        culture_bonus: float,
        preference_bonus: float,
    ) -> str:
        parts = []

        if skill_score >= 0.8:
            parts.append("Strong skill alignment")
        elif skill_score >= 0.5:
            parts.append("Moderate skill overlap")
        elif skill_score > 0:
            parts.append("Limited skill match")
        else:
            parts.append("No skill overlap found")

        if domain_score >= 0.7:
            parts.append("domain expertise aligns well")
        elif domain_score >= 0.4:
            parts.append("partial domain match")

        if culture_bonus >= 0.7:
            parts.append("strong culture fit")
        elif culture_bonus > 0:
            parts.append("partial culture fit")

        if preference_bonus == 1.0:
            parts.append("preferences fully satisfied")
        elif preference_bonus > 0:
            parts.append("partial preference match")

        return "; ".join(parts) if parts else "Insufficient overlap for match"
