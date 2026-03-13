"""
LLM ingestion service — writes the Gemini-extracted hierarchy into Neo4j.

Every node and relationship created here is tagged source='llm'. This provenance
tag is used later by the graph merger and visualization service to filter views.

Schema created (User side):
  User → SkillCategory → SkillFamily → Skill
  User → ProjectCategory → Project → (DEMONSTRATES_SKILL) → Skill
  User → DomainCategory → DomainFamily → Domain
  User → ExperienceCategory → Experience
  User → PreferenceCategory → Preference
  User → PatternCategory → ProblemSolvingPattern
"""

import logging
from database.neo4j_client import Neo4jClient
from models.schemas import UserProfileExtraction, JobPostingExtraction
from services.weights import recompute_weights

logger = logging.getLogger(__name__)


class LLMIngestionService:
    def __init__(self, client: Neo4jClient):
        self.client = client

    # ──────────────────────────────────────────────────────────────────────────
    # USER INGESTION
    # ──────────────────────────────────────────────────────────────────────────

    async def ingest_user_profile(
        self, user_id: str, extraction: UserProfileExtraction
    ) -> None:
        """Build the full user hierarchy in Neo4j from LLM extraction output."""
        await self._create_user_node(user_id)
        await self._ingest_skills(user_id, extraction.skills)
        await self._ingest_projects(user_id, extraction.projects)
        await self._ingest_domains(user_id, extraction.domains)
        await self._ingest_experiences(user_id, extraction.experiences)
        await self._ingest_preferences(user_id, extraction.preferences)
        await self._ingest_patterns(user_id, extraction.patterns)
        await recompute_weights(user_id, self.client)
        logger.info(f"LLM hierarchy written for user {user_id}")

    async def _create_user_node(self, user_id: str) -> None:
        await self.client.run_write(
            """
            MERGE (u:User {id: $user_id})
            SET u.updated_at = timestamp()
            """,
            {"user_id": user_id},
        )

    async def _ingest_skills(self, user_id: str, skills: list) -> None:
        for skill in skills:
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                OPTIONAL MATCH (:SkillFamily {user_id: $user_id})-[old_r:HAS_SKILL]->(:Skill {name: $name, user_id: $user_id})
                DELETE old_r
                WITH u
                MERGE (cat:SkillCategory {name: 'Skills', user_id: $user_id})
                MERGE (u)-[:HAS_SKILL_CATEGORY]->(cat)
                MERGE (fam:SkillFamily {name: $family, user_id: $user_id})
                SET fam.source = 'llm'
                MERGE (cat)-[:HAS_SKILL_FAMILY]->(fam)
                MERGE (s:Skill {name: $name, user_id: $user_id})
                SET s.years  = $years,
                    s.level  = $level,
                    s.source = 'llm'
                MERGE (fam)-[:HAS_SKILL]->(s)
                """,
                {
                    "user_id": user_id,
                    "family": skill.family or "Other",
                    "name": skill.name,
                    "years": skill.years,
                    "level": skill.level,
                },
            )

    async def _ingest_projects(self, user_id: str, projects: list) -> None:
        for project in projects:
            # Create project node
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                MERGE (cat:ProjectCategory {name: 'Projects', user_id: $user_id})
                MERGE (u)-[:HAS_PROJECT_CATEGORY]->(cat)
                MERGE (p:Project {name: $name, user_id: $user_id})
                SET p.description = $description,
                    p.domain      = $domain,
                    p.source      = 'llm'
                MERGE (cat)-[:HAS_PROJECT]->(p)
                """,
                {
                    "user_id": user_id,
                    "name": project.name,
                    "description": project.description,
                    "domain": project.domain,
                },
            )

            # Link project → skills (only if skill node exists)
            for skill_name in project.skills_demonstrated:
                await self.client.run_write(
                    """
                    MATCH (p:Project {name: $project_name, user_id: $user_id})
                    MATCH (s:Skill {name: $skill_name, user_id: $user_id})
                    MERGE (p)-[:DEMONSTRATES_SKILL]->(s)
                    """,
                    {
                        "user_id": user_id,
                        "project_name": project.name,
                        "skill_name": skill_name,
                    },
                )

            # Link project → domain if specified
            if project.domain:
                await self.client.run_write(
                    """
                    MATCH (p:Project {name: $project_name, user_id: $user_id})
                    MERGE (d:Domain {name: $domain, user_id: $user_id})
                    ON CREATE SET d.source = 'llm'
                    MERGE (p)-[:IN_DOMAIN]->(d)
                    """,
                    {
                        "user_id": user_id,
                        "project_name": project.name,
                        "domain": project.domain,
                    },
                )

    async def _ingest_domains(self, user_id: str, domains: list) -> None:
        for domain in domains:
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                MERGE (cat:DomainCategory {name: 'Domains', user_id: $user_id})
                MERGE (u)-[:HAS_DOMAIN_CATEGORY]->(cat)
                MERGE (fam:DomainFamily {name: $family, user_id: $user_id})
                SET fam.source = 'llm'
                MERGE (cat)-[:HAS_DOMAIN_FAMILY]->(fam)
                MERGE (d:Domain {name: $name, user_id: $user_id})
                SET d.years_experience = $years,
                    d.depth            = $depth,
                    d.source           = 'llm'
                MERGE (fam)-[:HAS_DOMAIN]->(d)
                """,
                {
                    "user_id": user_id,
                    "family": domain.family or "Other",
                    "name": domain.name,
                    "years": domain.years_experience,
                    "depth": domain.depth,
                },
            )

    async def _ingest_experiences(self, user_id: str, experiences: list) -> None:
        for exp in experiences:
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                MERGE (cat:ExperienceCategory {name: 'Experience', user_id: $user_id})
                MERGE (u)-[:HAS_EXPERIENCE_CATEGORY]->(cat)
                MERGE (e:Experience {title: $title, user_id: $user_id})
                SET e.company        = $company,
                    e.duration_years = $duration_years,
                    e.description    = $description,
                    e.source         = 'llm'
                MERGE (cat)-[:HAS_EXPERIENCE]->(e)
                """,
                {
                    "user_id": user_id,
                    "title": exp.title,
                    "company": exp.company,
                    "duration_years": exp.duration_years,
                    "description": exp.description,
                },
            )

    async def _ingest_preferences(self, user_id: str, preferences: list) -> None:
        for pref in preferences:
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                MERGE (cat:PreferenceCategory {name: 'Preferences', user_id: $user_id})
                MERGE (u)-[:HAS_PREFERENCE_CATEGORY]->(cat)
                MERGE (p:Preference {type: $type, user_id: $user_id})
                SET p.value  = $value,
                    p.source = 'llm'
                MERGE (cat)-[:HAS_PREFERENCE]->(p)
                """,
                {
                    "user_id": user_id,
                    "type": pref.type,
                    "value": pref.value,
                },
            )

    async def _ingest_patterns(self, user_id: str, patterns: list) -> None:
        for pattern in patterns:
            await self.client.run_write(
                """
                MATCH (u:User {id: $user_id})
                MERGE (cat:PatternCategory {name: 'Patterns', user_id: $user_id})
                MERGE (u)-[:HAS_PATTERN_CATEGORY]->(cat)
                MERGE (pat:ProblemSolvingPattern {pattern: $pattern, user_id: $user_id})
                SET pat.evidence = $evidence,
                    pat.source   = 'llm'
                MERGE (cat)-[:HAS_PATTERN]->(pat)
                """,
                {
                    "user_id": user_id,
                    "pattern": pattern.pattern,
                    "evidence": pattern.evidence,
                },
            )

    # ──────────────────────────────────────────────────────────────────────────
    # JOB INGESTION
    # ──────────────────────────────────────────────────────────────────────────

    async def ingest_job_posting(
        self, job_id: str, extraction: JobPostingExtraction, recruiter_id: str | None = None
    ) -> None:
        """Write the job hierarchy into Neo4j from LLM extraction output."""
        await self._create_job_node(job_id, extraction, recruiter_id)
        await self._ingest_job_skills(job_id, extraction.skill_requirements)
        await self._ingest_job_domains(job_id, extraction.domain_requirements)
        await self._ingest_job_culture(job_id, extraction.work_styles)
        logger.info(f"LLM hierarchy written for job {job_id}")

    async def _create_job_node(self, job_id: str, extraction: JobPostingExtraction, recruiter_id: str | None = None) -> None:
        await self.client.run_write(
            """
            MERGE (j:Job {id: $job_id})
            SET j.title                = $title,
                j.company              = $company,
                j.remote_policy        = $remote_policy,
                j.company_size         = $company_size,
                j.experience_years_min = $exp_years_min,
                j.recruiter_id         = $recruiter_id,
                j.source               = 'llm',
                j.updated_at           = timestamp()
            """,
            {
                "job_id": job_id,
                "title": extraction.title,
                "company": extraction.company,
                "remote_policy": extraction.remote_policy,
                "company_size": extraction.company_size,
                "exp_years_min": extraction.experience_years_min,
                "recruiter_id": recruiter_id,
            },
        )

    async def _ingest_job_skills(self, job_id: str, requirements: list) -> None:
        for req in requirements:
            await self.client.run_write(
                """
                MATCH (j:Job {id: $job_id})
                MERGE (jsr:JobSkillRequirements {job_id: $job_id})
                MERGE (j)-[:HAS_SKILL_REQUIREMENTS]->(jsr)
                MERGE (jsf:JobSkillFamily {name: $family, job_id: $job_id})
                SET jsf.source = 'llm'
                MERGE (jsr)-[:HAS_SKILL_FAMILY_REQ]->(jsf)
                MERGE (r:JobSkillRequirement {name: $name, job_id: $job_id})
                SET r.required   = $required,
                    r.importance = $importance,
                    r.min_years  = $min_years,
                    r.source     = 'llm'
                MERGE (jsf)-[:REQUIRES_SKILL]->(r)
                """,
                {
                    "job_id": job_id,
                    "family": req.family or "Other",
                    "name": req.name,
                    "required": req.required,
                    "importance": req.importance,
                    "min_years": req.min_years,
                },
            )

    async def _ingest_job_domains(self, job_id: str, requirements: list) -> None:
        for req in requirements:
            await self.client.run_write(
                """
                MATCH (j:Job {id: $job_id})
                MERGE (jdr:JobDomainRequirements {job_id: $job_id})
                MERGE (j)-[:HAS_DOMAIN_REQUIREMENTS]->(jdr)
                MERGE (jdf:JobDomainFamily {name: $family, job_id: $job_id})
                SET jdf.source = 'llm'
                MERGE (jdr)-[:HAS_DOMAIN_FAMILY_REQ]->(jdf)
                MERGE (dr:JobDomainRequirement {name: $name, job_id: $job_id})
                SET dr.min_years = $min_years,
                    dr.source    = 'llm'
                MERGE (jdf)-[:REQUIRES_DOMAIN]->(dr)
                """,
                {
                    "job_id": job_id,
                    "family": req.family or "Other",
                    "name": req.name,
                    "min_years": req.min_years,
                },
            )

    async def _ingest_job_culture(self, job_id: str, work_styles: list) -> None:
        for ws in work_styles:
            await self.client.run_write(
                """
                MATCH (j:Job {id: $job_id})
                MERGE (jcr:JobCultureRequirements {job_id: $job_id})
                MERGE (j)-[:HAS_CULTURE_REQUIREMENTS]->(jcr)
                MERGE (w:WorkStyle {style: $style, job_id: $job_id})
                SET w.source = 'llm'
                MERGE (jcr)-[:HAS_WORK_STYLE]->(w)
                """,
                {"job_id": job_id, "style": ws.style},
            )

    # ──────────────────────────────────────────────────────────────────────────
    # MATCH EDGE LINKING (cross-graph reconciliation)
    # ──────────────────────────────────────────────────────────────────────────

    async def link_skill_matches(self, user_id: str) -> int:
        """
        Create MATCHES edges from this user's Skill nodes to any JobSkillRequirement
        nodes with the same name (case-insensitive). Called after user ingest.
        Returns the number of edges created/merged.
        """
        records = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
            MATCH (jr:JobSkillRequirement)
            WHERE toLower(trim(s.name)) = toLower(trim(jr.name))
            MERGE (s)-[:MATCHES]->(jr)
            RETURN count(*) AS linked
            """,
            {"user_id": user_id},
        )
        count = records[0]["linked"] if records else 0
        logger.info(f"Linked {count} skill MATCHES edges for user {user_id}")
        return count

    async def link_domain_matches(self, user_id: str) -> int:
        """
        Create MATCHES edges from this user's Domain nodes to any JobDomainRequirement
        nodes with the same name (case-insensitive). Called after user ingest.
        Returns the number of edges created/merged.
        """
        records = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
                  -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
            MATCH (dr:JobDomainRequirement)
            WHERE toLower(trim(d.name)) = toLower(trim(dr.name))
            MERGE (d)-[:MATCHES]->(dr)
            RETURN count(*) AS linked
            """,
            {"user_id": user_id},
        )
        count = records[0]["linked"] if records else 0
        logger.info(f"Linked {count} domain MATCHES edges for user {user_id}")
        return count

    async def link_job_skill_matches(self, job_id: str) -> int:
        """
        Create MATCHES edges from existing Skill nodes (all users) to this job's
        new JobSkillRequirement nodes. Called after job ingest.
        Returns the number of edges created/merged.
        """
        records = await self.client.run_query(
            """
            MATCH (jr:JobSkillRequirement {job_id: $job_id})
            MATCH (s:Skill)
            WHERE toLower(trim(s.name)) = toLower(trim(jr.name))
            MERGE (s)-[:MATCHES]->(jr)
            RETURN count(*) AS linked
            """,
            {"job_id": job_id},
        )
        count = records[0]["linked"] if records else 0
        logger.info(f"Linked {count} skill MATCHES edges for job {job_id}")
        return count

    async def link_job_domain_matches(self, job_id: str) -> int:
        """
        Create MATCHES edges from existing Domain nodes (all users) to this job's
        new JobDomainRequirement nodes. Called after job ingest.
        Returns the number of edges created/merged.
        """
        records = await self.client.run_query(
            """
            MATCH (dr:JobDomainRequirement {job_id: $job_id})
            MATCH (d:Domain)
            WHERE toLower(trim(d.name)) = toLower(trim(dr.name))
            MERGE (d)-[:MATCHES]->(dr)
            RETURN count(*) AS linked
            """,
            {"job_id": job_id},
        )
        count = records[0]["linked"] if records else 0
        logger.info(f"Linked {count} domain MATCHES edges for job {job_id}")
        return count
