"""
Centralized taxonomy definitions for the job matching system.

All Neo4j node labels, relationship types, and match weights are defined here
to prevent typo-driven schema drift across the codebase.
"""

from enum import Enum


class NodeLabel(str, Enum):
    # User hierarchy
    USER = "User"
    SKILL_CATEGORY = "SkillCategory"
    SKILL_FAMILY = "SkillFamily"
    SKILL = "Skill"
    PROJECT_CATEGORY = "ProjectCategory"
    PROJECT = "Project"
    DOMAIN_CATEGORY = "DomainCategory"
    DOMAIN_FAMILY = "DomainFamily"
    DOMAIN = "Domain"
    EXPERIENCE_CATEGORY = "ExperienceCategory"
    EXPERIENCE = "Experience"
    PREFERENCE_CATEGORY = "PreferenceCategory"
    PREFERENCE = "Preference"
    PATTERN_CATEGORY = "PatternCategory"
    PROBLEM_SOLVING_PATTERN = "ProblemSolvingPattern"
    # Job hierarchy
    JOB = "Job"
    JOB_SKILL_REQUIREMENTS = "JobSkillRequirements"
    JOB_SKILL_FAMILY = "JobSkillFamily"
    JOB_SKILL_REQUIREMENT = "JobSkillRequirement"
    JOB_DOMAIN_REQUIREMENTS = "JobDomainRequirements"
    JOB_DOMAIN_FAMILY = "JobDomainFamily"
    JOB_DOMAIN_REQUIREMENT = "JobDomainRequirement"
    JOB_CULTURE_REQUIREMENTS = "JobCultureRequirements"
    WORK_STYLE = "WorkStyle"


class RelType(str, Enum):
    # User → Category
    HAS_SKILL_CATEGORY = "HAS_SKILL_CATEGORY"
    HAS_PROJECT_CATEGORY = "HAS_PROJECT_CATEGORY"
    HAS_DOMAIN_CATEGORY = "HAS_DOMAIN_CATEGORY"
    HAS_EXPERIENCE_CATEGORY = "HAS_EXPERIENCE_CATEGORY"
    HAS_PREFERENCE_CATEGORY = "HAS_PREFERENCE_CATEGORY"
    HAS_PATTERN_CATEGORY = "HAS_PATTERN_CATEGORY"
    # Category → Family
    HAS_SKILL_FAMILY = "HAS_SKILL_FAMILY"
    HAS_DOMAIN_FAMILY = "HAS_DOMAIN_FAMILY"
    # Family → Leaf
    HAS_SKILL = "HAS_SKILL"
    HAS_DOMAIN = "HAS_DOMAIN"
    # Category → Leaf (no family level)
    HAS_PROJECT = "HAS_PROJECT"
    HAS_EXPERIENCE = "HAS_EXPERIENCE"
    HAS_PREFERENCE = "HAS_PREFERENCE"
    HAS_PATTERN = "HAS_PATTERN"
    # Cross-entity
    DEMONSTRATES_SKILL = "DEMONSTRATES_SKILL"
    IN_DOMAIN = "IN_DOMAIN"
    # Job hierarchy
    HAS_SKILL_REQUIREMENTS = "HAS_SKILL_REQUIREMENTS"
    HAS_DOMAIN_REQUIREMENTS = "HAS_DOMAIN_REQUIREMENTS"
    HAS_CULTURE_REQUIREMENTS = "HAS_CULTURE_REQUIREMENTS"
    HAS_SKILL_FAMILY_REQ = "HAS_SKILL_FAMILY_REQ"
    HAS_DOMAIN_FAMILY_REQ = "HAS_DOMAIN_FAMILY_REQ"
    REQUIRES_SKILL = "REQUIRES_SKILL"
    REQUIRES_DOMAIN = "REQUIRES_DOMAIN"
    HAS_WORK_STYLE = "HAS_WORK_STYLE"
    # Cross-graph matching
    MATCHES = "MATCHES"  # Skill → JobSkillRequirement, Domain → JobDomainRequirement


class MatchWeight:
    """Weights for the two base scoring dimensions. Must sum to 1.0.
    Culture and preferences are bonus signals, not weighted dimensions."""
    SKILLS: float = 0.65
    DOMAIN: float = 0.35


class SkillImportanceWeight:
    """Score weights for job skill requirement importance levels."""
    MUST_HAVE: float = 1.0
    NICE_TO_HAVE: float = 0.5
    DEFAULT: float = 0.8


# Skill taxonomy used in extraction prompts to guide Gemini categorization
SKILL_TAXONOMY = {
    "Programming Languages": [
        "Python", "JavaScript", "TypeScript", "Java", "Go", "Rust",
        "C++", "C#", "Ruby", "PHP", "Kotlin", "Swift", "Scala",
    ],
    "Web Frameworks": [
        "Django", "Flask", "FastAPI", "React", "Vue", "Angular",
        "Next.js", "Express", "Spring Boot", "Rails", "ASP.NET",
    ],
    "Databases": [
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Cassandra",
        "DynamoDB", "Elasticsearch", "Neo4j", "Oracle", "SQL Server",
    ],
    "Cloud & DevOps": [
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
        "CI/CD", "Jenkins", "GitHub Actions", "GitLab CI", "Ansible",
    ],
    "ML & AI": [
        "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow",
        "NLP", "Computer Vision", "Transformers", "scikit-learn", "Keras",
    ],
    "Data Engineering": [
        "Airflow", "Spark", "Kafka", "ETL", "Data Pipelines",
        "Snowflake", "dbt", "Databricks", "Hadoop",
    ],
    "Mobile Development": [
        "React Native", "Flutter", "iOS", "Android", "SwiftUI", "Jetpack Compose",
    ],
    "Testing & QA": [
        "pytest", "Jest", "Selenium", "Cypress", "JUnit", "TestNG",
    ],
    "Analytics & Visualization": [
        "Tableau", "Power BI", "Looker", "Grafana", "Kibana",
        "matplotlib", "seaborn", "D3.js", "Plotly", "Metabase",
    ],
}

# Work-style synonym map — normalizes free-text work styles to canonical keys.
# Used by the matching engine to fuzzy-match user culture preferences against
# job work-style requirements without requiring exact string equality.
WORK_STYLE_SYNONYMS: dict[str, frozenset] = {
    "remote": frozenset({
        "remote", "remote-first", "remote-friendly", "fully remote",
        "fully-remote", "distributed", "wfh", "work from home",
        "remote work", "remote only",
    }),
    "hybrid": frozenset({
        "hybrid", "hybrid-first", "hybrid-friendly", "flexible",
        "semi-remote", "partially remote", "remote-optional",
    }),
    "onsite": frozenset({
        "onsite", "on-site", "in-office", "in office", "on site",
        "office-based", "office based",
    }),
    "startup": frozenset({
        "startup", "start-up", "startup culture", "fast-paced startup",
        "early-stage", "small team",
    }),
    "fast-paced": frozenset({
        "fast-paced", "fast paced", "dynamic", "high-velocity",
        "high-growth", "high pace", "fast pace",
    }),
    "high-autonomy": frozenset({
        "high-autonomy", "high autonomy", "autonomous", "self-directed",
        "independent work", "independent", "self-starter",
    }),
    "collaborative": frozenset({
        "collaborative", "team-first", "team-oriented", "cooperative",
        "cross-functional", "team player", "collaborative team",
    }),
    "data-driven": frozenset({
        "data-driven", "data driven", "metrics-driven", "metrics-focused",
        "evidence-based", "data-driven culture",
    }),
    "agile": frozenset({
        "agile", "scrum", "kanban", "sprint-based", "iterative",
        "agile methodology",
    }),
    "async": frozenset({
        "async", "async-first", "asynchronous", "async-friendly",
        "async work",
    }),
    "design-focused": frozenset({
        "design-focused", "design focused", "design-first", "ux-driven",
        "product-focused",
    }),
}


def normalize_work_style(style: str) -> str:
    """Return the canonical key for a work-style term, or the lowercased term
    itself if it doesn't appear in any synonym group."""
    s = style.lower().strip()
    for canonical, synonyms in WORK_STYLE_SYNONYMS.items():
        if s in synonyms:
            return canonical
    return s


# Domain taxonomy used in extraction prompts
DOMAIN_TAXONOMY = {
    "FinTech": [
        "Payment Systems", "Banking", "Trading", "Cryptocurrency",
        "Lending", "Insurance", "Wealth Management", "RegTech",
    ],
    "Healthcare": [
        "Electronic Health Records", "Medical Imaging", "Telemedicine",
        "Clinical Trials", "Drug Discovery", "Healthcare Analytics",
    ],
    "E-commerce": [
        "Marketplaces", "Recommendations", "Inventory Management",
        "Order Fulfillment", "Customer Experience", "Payment Processing",
    ],
    "SaaS": [
        "CRM", "Analytics", "Collaboration Tools", "Project Management",
        "Marketing Automation", "Customer Support",
    ],
    "Enterprise": [
        "ERP", "Supply Chain", "HR Systems", "Financial Systems",
        "Business Intelligence", "Data Warehousing",
    ],
    "Gaming": [
        "Game Development", "Game Engines", "Multiplayer Systems",
        "Game Analytics", "LiveOps",
    ],
    "Education": [
        "EdTech", "Learning Management Systems", "Student Information Systems",
        "Online Learning", "Assessment Tools",
    ],
}
