"""Checkpoint service — serializes Neo4j subgraphs to SQLite and restores them."""

import json
import logging
import uuid
from datetime import datetime, timezone

from database.neo4j_client import Neo4jClient
from database.sqlite_client import SQLiteClient
from models.schemas import GraphVersion

logger = logging.getLogger(__name__)


class CheckpointService:
    def __init__(
        self,
        neo4j: Neo4jClient,
        sqlite: SQLiteClient,
        output_dir: str = "./outputs",
    ):
        self.neo4j = neo4j
        self.sqlite = sqlite
        self.output_dir = output_dir

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_checkpoint(
        self,
        entity_type: str,
        entity_id: str,
        label: str,
        session_id: str | None = None,
    ) -> GraphVersion:
        """Serialize the current Neo4j subgraph for the entity to SQLite."""
        snapshot = await self._serialize_subgraph(entity_type, entity_id)
        version_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        await self.sqlite.execute(
            """
            INSERT INTO graph_snapshots
                (version_id, entity_type, entity_id, session_id, label, snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                entity_type,
                entity_id,
                session_id,
                label,
                json.dumps(snapshot),
                created_at,
            ),
        )

        logger.info(
            f"Checkpoint created: {version_id} ({entity_type}={entity_id}, label={label!r})"
        )
        return GraphVersion(
            version_id=version_id,
            entity_type=entity_type,
            entity_id=entity_id,
            session_id=session_id,
            label=label,
            created_at=created_at,
        )

    async def list_versions(
        self, entity_type: str, entity_id: str
    ) -> list[GraphVersion]:
        """Return the 10 most recent checkpoints for an entity (newest first)."""
        rows = await self.sqlite.fetchall(
            """
            SELECT version_id, entity_type, entity_id, session_id, label, created_at
            FROM graph_snapshots
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (entity_type, entity_id),
        )
        return [GraphVersion(**row) for row in rows]

    async def rollback(
        self, entity_type: str, entity_id: str, version_id: str
    ) -> None:
        """Restore a previously saved subgraph snapshot from SQLite into Neo4j."""
        row = await self.sqlite.fetchone(
            """
            SELECT snapshot_json
            FROM graph_snapshots
            WHERE version_id = ? AND entity_type = ? AND entity_id = ?
            """,
            (version_id, entity_type, entity_id),
        )
        if row is None:
            raise ValueError(
                f"Snapshot not found: version_id={version_id!r}, "
                f"entity_type={entity_type!r}, entity_id={entity_id!r}"
            )

        snapshot = json.loads(row["snapshot_json"])
        await self._restore_subgraph(entity_type, entity_id, snapshot)
        await self._relink_and_revisualize(entity_type, entity_id)
        logger.info(
            f"Rollback complete: version_id={version_id!r} "
            f"({entity_type}={entity_id})"
        )

    # ── Internal helpers ────────────────────────────────────────────────────────

    async def _serialize_subgraph(self, entity_type: str, entity_id: str) -> dict:
        """Fetch all nodes and edges that belong to this entity from Neo4j."""
        if entity_type == "user":
            nodes_query = (
                "MATCH (n) "
                "WHERE n.user_id = $entity_id OR (n:User AND n.id = $entity_id) "
                "RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props"
            )
            edges_query = (
                "MATCH (a)-[r]->(b) "
                "WHERE (a.user_id = $entity_id OR (a:User AND a.id = $entity_id)) "
                "AND (b.user_id = $entity_id OR (b:User AND b.id = $entity_id)) "
                "RETURN elementId(r) AS eid, type(r) AS rel_type, "
                "elementId(startNode(r)) AS from_eid, elementId(endNode(r)) AS to_eid"
            )
        else:  # job
            nodes_query = (
                "MATCH (n) "
                "WHERE n.job_id = $entity_id OR (n:Job AND n.id = $entity_id) "
                "RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props"
            )
            edges_query = (
                "MATCH (a)-[r]->(b) "
                "WHERE (a.job_id = $entity_id OR (a:Job AND a.id = $entity_id)) "
                "AND (b.job_id = $entity_id OR (b:Job AND b.id = $entity_id)) "
                "RETURN elementId(r) AS eid, type(r) AS rel_type, "
                "elementId(startNode(r)) AS from_eid, elementId(endNode(r)) AS to_eid"
            )

        nodes = await self.neo4j.run_query(nodes_query, {"entity_id": entity_id})
        edges = await self.neo4j.run_query(edges_query, {"entity_id": entity_id})
        return {"nodes": nodes, "edges": edges}

    async def _restore_subgraph(
        self, entity_type: str, entity_id: str, snapshot: dict
    ) -> None:
        """Delete current nodes then recreate nodes and edges from the snapshot."""
        # 1. Delete existing subgraph
        if entity_type == "user":
            delete_query = (
                "MATCH (n) "
                "WHERE (n:User AND n.id = $entity_id) OR n.user_id = $entity_id "
                "DETACH DELETE n"
            )
        else:
            delete_query = (
                "MATCH (n) "
                "WHERE (n:Job AND n.id = $entity_id) OR n.job_id = $entity_id "
                "DETACH DELETE n"
            )
        await self.neo4j.run_query(delete_query, {"entity_id": entity_id})

        # 2. Recreate nodes, building old-eid → new-eid mapping
        eid_map: dict[str, str] = {}
        for node_data in snapshot.get("nodes", []):
            old_eid: str = node_data["eid"]
            labels: list[str] = node_data["labels"]
            props: dict = node_data["props"]
            label_str = ":".join(labels)
            result = await self.neo4j.run_query(
                f"CREATE (n:{label_str} $props) RETURN elementId(n) AS new_eid",
                {"props": props},
            )
            if result:
                eid_map[old_eid] = result[0]["new_eid"]

        # 3. Recreate edges using the eid mapping
        for edge in snapshot.get("edges", []):
            from_eid = eid_map.get(edge["from_eid"])
            to_eid = eid_map.get(edge["to_eid"])
            rel_type: str = edge["rel_type"]
            if from_eid is None or to_eid is None:
                logger.warning(
                    f"Skipping edge {edge['eid']!r}: missing endpoint in eid_map"
                )
                continue
            await self.neo4j.run_query(
                f"MATCH (a) WHERE elementId(a) = $src "
                f"MATCH (b) WHERE elementId(b) = $tgt "
                f"CREATE (a)-[:{rel_type}]->(b)",
                {"src": from_eid, "tgt": to_eid},
            )

    async def _relink_and_revisualize(
        self, entity_type: str, entity_id: str
    ) -> None:
        """Re-run match linking and regenerate the visualization after rollback."""
        # Deferred imports to avoid circular dependencies
        from services.llm_ingestion import LLMIngestionService
        from services.visualization import VisualizationService

        ingestion = LLMIngestionService(self.neo4j)
        viz = VisualizationService(self.neo4j, self.output_dir)

        if entity_type == "user":
            await ingestion.link_skill_matches(entity_id)
            await ingestion.link_domain_matches(entity_id)
            await viz.generate_user_graph(entity_id)
        else:
            await ingestion.link_job_skill_matches(entity_id)
            await ingestion.link_job_domain_matches(entity_id)
            await viz.generate_job_graph(entity_id)
