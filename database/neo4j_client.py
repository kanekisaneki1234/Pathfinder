"""
Async Neo4j client — single source of truth for all database connectivity.

Initialized once at FastAPI startup via init_client(), then accessible
everywhere via get_client(). All Cypher execution flows through run_query
(reads) or run_write (writes).
"""

import logging
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)

# Module-level singleton
_client: "Neo4jClient | None" = None


class Neo4jClient:
    def __init__(self, uri: str, username: str, password: str):
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_pool_size=50,
        )

    async def verify_connectivity(self) -> None:
        await self._driver.verify_connectivity()
        logger.info("Neo4j connectivity verified")

    async def close(self) -> None:
        await self._driver.close()
        logger.info("Neo4j driver closed")

    async def run_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a read (or write) query and return all records as plain dicts."""
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            return await result.data()

    async def run_write(self, cypher: str, params: dict | None = None) -> None:
        """Execute a write query inside an explicit write transaction."""
        async with self._driver.session() as session:
            await session.execute_write(
                lambda tx: tx.run(cypher, params or {})
            )

    async def setup_constraints(self) -> None:
        """
        Create uniqueness constraints for all primary node types.
        Must be called once on startup before any data is written.

        Neo4j 5.x syntax: REQUIRE (a, b) IS UNIQUE for composite constraints.
        """
        constraints = [
            # Single-property constraints
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (j:Job) REQUIRE j.id IS UNIQUE",
            # Composite constraints (skill/domain names are unique per user)
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Skill) "
                "REQUIRE (s.name, s.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Domain) "
                "REQUIRE (d.name, d.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (sf:SkillFamily) "
                "REQUIRE (sf.name, sf.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (df:DomainFamily) "
                "REQUIRE (df.name, df.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (r:JobSkillRequirement) "
                "REQUIRE (r.name, r.job_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (dr:JobDomainRequirement) "
                "REQUIRE (dr.name, dr.job_id) IS UNIQUE"
            ),
            # Digital twin identity nodes — all scoped per user
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Anecdote) "
                "REQUIRE (a.name, a.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Motivation) "
                "REQUIRE (m.name, m.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Value) "
                "REQUIRE (v.name, v.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (g:Goal) "
                "REQUIRE (g.name, g.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (c:CultureIdentity) "
                "REQUIRE (c.name, c.user_id) IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT IF NOT EXISTS FOR (b:BehavioralInsight) "
                "REQUIRE (b.name, b.user_id) IS UNIQUE"
            ),
        ]
        for constraint in constraints:
            try:
                await self.run_write(constraint)
            except Exception as e:
                # Constraint may already exist — log but don't fail startup
                logger.debug(f"Constraint skipped (may already exist): {e}")

        logger.info("Neo4j constraints initialized")

    async def count_nodes_for_user(self, user_id: str) -> dict:
        """Return node counts at each hierarchy level for a user."""
        records = await self.run_query(
            """
            MATCH (u:User {id: $user_id})
            OPTIONAL MATCH (u)-[*1..2]->(cat)
            OPTIONAL MATCH (u)-[*1..3]->(fam)
              WHERE fam:SkillFamily OR fam:DomainFamily
            OPTIONAL MATCH (u)-[*1..4]->(leaf)
              WHERE leaf:Skill OR leaf:Domain OR leaf:Project
                 OR leaf:Experience OR leaf:Preference OR leaf:ProblemSolvingPattern
            RETURN
                count(DISTINCT cat) AS categories,
                count(DISTINCT fam) AS families,
                count(DISTINCT leaf) AS leaves
            """,
            {"user_id": user_id},
        )
        return records[0] if records else {"categories": 0, "families": 0, "leaves": 0}


def get_client() -> Neo4jClient:
    """Return the module-level singleton. Raises if init_client() was never called."""
    if _client is None:
        raise RuntimeError(
            "Neo4j client not initialized. Call init_client() at app startup."
        )
    return _client


async def init_client(uri: str, username: str, password: str) -> Neo4jClient:
    """Create and verify the singleton Neo4j client, then set up constraints."""
    global _client
    _client = Neo4jClient(uri, username, password)
    await _client.verify_connectivity()
    await _client.setup_constraints()
    logger.info(f"Neo4j client initialized: {uri}")
    return _client
