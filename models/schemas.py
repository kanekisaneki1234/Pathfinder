"""
Pydantic schemas for two purposes:
1. Gemini structured output (response_schema) — controls LLM extraction format
2. FastAPI request/response bodies — controls API interface

Keep these separate to allow them to evolve independently.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI EXTRACTION SCHEMAS
# Passed as response_schema to GenerationConfig. Gemini enforces the JSON shape.
# ──────────────────────────────────────────────────────────────────────────────

class ExtractedSkill(BaseModel):
    name: str = Field(description="Canonical skill name, e.g. 'Python', 'React'")
    family: str = Field(
        description=(
            "Skill family grouping. Must be one of: "
            "Programming Languages, Web Frameworks, Databases, Cloud & DevOps, "
            "ML & AI, Data Engineering, Mobile Development, Testing & QA, "
            "Analytics & Visualization, Other"
        )
    )
    years: Optional[float] = Field(default=None, description="Years of experience, null if unknown")
    level: Optional[Literal["beginner", "intermediate", "advanced", "expert"]] = Field(
        default=None, description="Proficiency level inferred from context"
    )


class ExtractedProject(BaseModel):
    name: str = Field(description="Project name")
    description: str = Field(description="What the project does and its impact")
    skills_demonstrated: List[str] = Field(
        description="Skill names directly used in this project"
    )
    domain: Optional[str] = Field(
        default=None,
        description="Domain this project belongs to, e.g. 'FinTech', 'Healthcare'"
    )


class ExtractedDomain(BaseModel):
    name: str = Field(description="Specific domain area, e.g. 'Payment Systems', 'NLP'")
    family: str = Field(
        description=(
            "Domain family. Must be one of: "
            "FinTech, Healthcare, E-commerce, SaaS, Enterprise, Gaming, Education, Other"
        )
    )
    years_experience: Optional[float] = Field(
        default=None, description="Years of domain experience, null if unknown"
    )
    depth: Optional[Literal["shallow", "moderate", "deep"]] = Field(
        default=None, description="Depth of domain knowledge"
    )


class ExtractedExperience(BaseModel):
    title: str = Field(description="Job title")
    company: Optional[str] = Field(default=None, description="Company name, null if not mentioned")
    duration_years: Optional[float] = Field(
        default=None, description="Duration in years, null if unknown"
    )
    description: Optional[str] = Field(default=None, description="Role description")


class ExtractedPreference(BaseModel):
    type: str = Field(
        description=(
            "Preference type. Use one of: "
            "remote_work, company_size, work_style, role_type, location, salary_range"
        )
    )
    value: str = Field(description="Preference value, e.g. 'remote', 'startup', 'async-first'")


class ExtractedPattern(BaseModel):
    pattern: str = Field(
        description=(
            "Problem-solving pattern demonstrated, e.g. "
            "'systems thinker', 'data-driven', 'user-focused', 'performance-oriented'"
        )
    )
    evidence: Optional[str] = Field(
        default=None, description="Brief evidence from the profile"
    )


class UserProfileExtraction(BaseModel):
    """Top-level schema for Gemini user profile extraction. Passed as response_schema."""
    skills: List[ExtractedSkill] = Field(default_factory=list)
    projects: List[ExtractedProject] = Field(default_factory=list)
    domains: List[ExtractedDomain] = Field(default_factory=list)
    experiences: List[ExtractedExperience] = Field(default_factory=list)
    preferences: List[ExtractedPreference] = Field(default_factory=list)
    patterns: List[ExtractedPattern] = Field(default_factory=list)


class ExtractedJobSkillRequirement(BaseModel):
    name: str = Field(description="Skill name")
    family: str = Field(
        description=(
            "Skill family. Must be one of: "
            "Programming Languages, Web Frameworks, Databases, Cloud & DevOps, "
            "ML & AI, Data Engineering, Mobile Development, Testing & QA, "
            "Analytics & Visualization, Other"
        )
    )
    required: bool = Field(default=True, description="True if required, False if nice-to-have")
    importance: Literal["must_have", "nice_to_have"] = Field(
        default="must_have",
        description="must_have for required skills, nice_to_have for preferred"
    )
    min_years: Optional[int] = Field(
        default=None, description="Minimum years required, null if not specified"
    )


class ExtractedJobDomainRequirement(BaseModel):
    name: str = Field(description="Domain area required, e.g. 'Payment Systems'")
    family: str = Field(
        description=(
            "Domain family. Must be one of: "
            "FinTech, Healthcare, E-commerce, SaaS, Enterprise, Gaming, Education, Other"
        )
    )
    min_years: Optional[int] = Field(default=None)


class ExtractedWorkStyle(BaseModel):
    style: str = Field(
        description=(
            "Work style or culture indicator, e.g. "
            "'async-first', 'fast-paced', 'high-autonomy', 'collaborative', 'remote-first'"
        )
    )


class JobPostingExtraction(BaseModel):
    """Top-level schema for Gemini job posting extraction. Passed as response_schema."""
    title: str = Field(description="Job title")
    company: Optional[str] = Field(default=None, description="Company name")
    skill_requirements: List[ExtractedJobSkillRequirement] = Field(default_factory=list)
    domain_requirements: List[ExtractedJobDomainRequirement] = Field(default_factory=list)
    work_styles: List[ExtractedWorkStyle] = Field(default_factory=list)
    remote_policy: Optional[str] = Field(
        default=None,
        description="Remote policy: 'remote', 'hybrid', 'onsite'"
    )
    company_size: Optional[str] = Field(
        default=None,
        description="Company size: 'startup', 'mid-size', 'enterprise'"
    )
    experience_years_min: Optional[int] = Field(
        default=None, description="Minimum years of experience required"
    )


# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI REQUEST / RESPONSE SCHEMAS
# ──────────────────────────────────────────────────────────────────────────────

class IngestUserRequest(BaseModel):
    user_id: str = Field(description="Unique identifier for the user")
    profile_text: str = Field(
        description="Raw resume or profile text to process through the hybrid pipeline"
    )


class IngestJobRequest(BaseModel):
    job_id: str = Field(description="Unique identifier for the job posting")
    job_text: str = Field(
        description="Raw job posting text to process through the hybrid pipeline"
    )
    recruiter_id: Optional[str] = Field(default=None, description="ID of the recruiter who posted this job")


class MatchedSkill(BaseModel):
    skill: str
    user_years: Optional[float]
    user_level: Optional[str]
    required_years: Optional[int]
    importance: str
    contribution: float


class MatchResult(BaseModel):
    job_id: str
    job_title: str
    company: Optional[str]
    total_score: float          # base score: skills + domain only (0-1)
    skill_score: float
    domain_score: float
    culture_bonus: float        # bonus signal: work-style match ratio (0-1, not weighted)
    preference_bonus: float     # bonus signal: remote/company_size match ratio (0-1, not weighted)
    matched_skills: List[str]
    missing_skills: List[str]
    matched_domains: List[str]
    missing_domains: List[str]
    explanation: str


class BatchMatchResponse(BaseModel):
    user_id: str
    results: List[MatchResult]
    total_jobs_ranked: int


class CandidateResult(BaseModel):
    """Reverse-match result: one user scored against a specific job."""
    user_id: str
    total_score: float
    skill_score: float
    domain_score: float
    culture_bonus: float
    preference_bonus: float
    matched_skills: List[str]
    missing_skills: List[str]
    matched_domains: List[str]
    missing_domains: List[str]
    explanation: str


class BatchCandidateResponse(BaseModel):
    job_id: str
    results: List[CandidateResult]
    total_users_ranked: int


class IngestionStats(BaseModel):
    entity_id: str
    entity_type: Literal["user", "job"]
    skills_extracted: int = 0
    domains_extracted: int = 0
    projects_extracted: int = 0
    experiences_extracted: int = 0


class GraphVersion(BaseModel):
    version_id: str
    entity_type: str   # 'user' | 'job'
    entity_id: str
    session_id: Optional[str] = None
    label: str
    created_at: str


class CheckpointRequest(BaseModel):
    label: Optional[str] = Field(default=None, description="Human-readable label for this checkpoint")


class RollbackResponse(BaseModel):
    version_id: str
    entity_type: str
    entity_id: str
    status: str = "restored"
