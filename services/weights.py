"""
Weight computation service — computes and stores expertise weights on Skill and Domain nodes.

Weight formula (clamped 0.0–1.0):
  weight = years * 0.4 + num_projects_demonstrating * 0.3 + level_val * 0.3

  level_val: beginner/shallow=0.2, intermediate/moderate=0.6, advanced/deep/expert=1.0

Called after user ingestion and after each graph edit mutation (Phase 3).
"""

import logging

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


async def recompute_weights(user_id: str, client: Neo4jClient) -> None:
    """Recompute and SET weight on all Skill and Domain nodes for a user."""
    await client.run_write(
        """
        MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
              -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
        OPTIONAL MATCH (p:Project {user_id: $user_id})-[:DEMONSTRATES_SKILL]->(s)
        WITH s, count(p) AS num_projects,
             CASE s.level
               WHEN 'beginner'     THEN 0.2
               WHEN 'intermediate' THEN 0.6
               WHEN 'advanced'     THEN 1.0
               WHEN 'expert'       THEN 1.0
               ELSE 0.4
             END AS level_val
        WITH s, num_projects, level_val,
             (coalesce(toFloat(s.years), 0.0) * 0.4
              + num_projects * 0.3
              + level_val * 0.3) AS raw
        SET s.weight = CASE WHEN raw > 1.0 THEN 1.0 WHEN raw < 0.0 THEN 0.0 ELSE raw END
        """,
        {"user_id": user_id},
    )

    await client.run_write(
        """
        MATCH (u:User {id: $user_id})-[:HAS_DOMAIN_CATEGORY]->(:DomainCategory)
              -[:HAS_DOMAIN_FAMILY]->(:DomainFamily)-[:HAS_DOMAIN]->(d:Domain)
        OPTIONAL MATCH (p:Project {user_id: $user_id})-[:IN_DOMAIN]->(d)
        WITH d, count(p) AS num_projects,
             CASE d.depth
               WHEN 'shallow'  THEN 0.2
               WHEN 'moderate' THEN 0.6
               WHEN 'deep'     THEN 1.0
               ELSE 0.4
             END AS depth_val
        WITH d, num_projects, depth_val,
             (coalesce(toFloat(d.years_experience), 0.0) * 0.4
              + num_projects * 0.3
              + depth_val * 0.3) AS raw
        SET d.weight = CASE WHEN raw > 1.0 THEN 1.0 WHEN raw < 0.0 THEN 0.0 ELSE raw END
        """,
        {"user_id": user_id},
    )

    logger.info(f"Weights recomputed for user {user_id}")
