"""
Graph visualization service — generates an interactive pyvis HTML file.

Fetches the full subgraph for a user (all nodes up to depth 6) from Neo4j
and renders it as a force-directed graph using pyvis.

Uses apoc.path.subgraphAll for subgraph extraction (requires APOC plugin).
Falls back to pure-Cypher variable-length path if APOC is unavailable.

IMPORTANT: Always use net.write_html(filepath), NOT net.show(filepath).
net.show() calls webbrowser.open() which hangs in server environments.
"""

import logging
import os

import networkx as nx
from pyvis.network import Network

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# Node colors by type
NODE_TYPE_COLORS: dict[str, str] = {
    "User": "#E74C3C",
    "SkillCategory": "#2980B9",
    "SkillFamily": "#5DADE2",
    "Skill": "#AED6F1",
    "ProjectCategory": "#1E8449",
    "Project": "#82E0AA",
    "DomainCategory": "#8E44AD",
    "DomainFamily": "#BB8FCE",
    "Domain": "#D7BDE2",
    "ExperienceCategory": "#D35400",
    "Experience": "#F0B27A",
    "PreferenceCategory": "#117A65",
    "Preference": "#76D7C4",
    "PatternCategory": "#7D6608",
    "ProblemSolvingPattern": "#F9E79F",
    "Job": "#C0392B",
    "JobSkillRequirements": "#2471A3",
    "JobSkillFamily": "#7FB3D3",
    "JobSkillRequirement": "#BFD7ED",
    "JobDomainRequirements": "#7D3C98",
    "JobDomainFamily": "#BFA9D4",
    "JobDomainRequirement": "#DDD0EA",
    "JobCultureRequirements": "#148F77",
    "WorkStyle": "#76D7C4",
}

NODE_SIZES: dict[str, int] = {
    "User": 40, "Job": 35,
    "SkillCategory": 25, "DomainCategory": 25,
    "ProjectCategory": 25, "ExperienceCategory": 20,
    "SkillFamily": 18, "DomainFamily": 18,
    "Skill": 14, "Domain": 14, "Project": 16,
    "Experience": 14, "Preference": 12,
    "ProblemSolvingPattern": 12,
}

DEFAULT_NODE_COLOR = "#BDC3C7"
DEFAULT_NODE_SIZE = 12

# APOC labelFilter strings — blocks traversal INTO these node types
# Used in apoc.path.subgraphAll to prevent cross-user contamination via MATCHES edges
_USER_LABEL_FILTER = (
    "-Job|-JobSkillRequirements|-JobSkillFamily|-JobSkillRequirement"
    "|-JobDomainRequirements|-JobDomainFamily|-JobDomainRequirement"
    "|-JobCultureRequirements|-WorkStyle"
)
_JOB_LABEL_FILTER = (
    "-User|-SkillCategory|-SkillFamily|-Skill"
    "|-DomainCategory|-DomainFamily|-Domain"
    "|-ProjectCategory|-Project"
    "|-ExperienceCategory|-Experience"
    "|-PreferenceCategory|-Preference"
    "|-PatternCategory|-ProblemSolvingPattern"
)

# Types that belong exclusively to the user hierarchy
USER_NODE_TYPES: frozenset[str] = frozenset({
    "User",
    "SkillCategory", "SkillFamily", "Skill",
    "ProjectCategory", "Project",
    "DomainCategory", "DomainFamily", "Domain",
    "ExperienceCategory", "Experience",
    "PreferenceCategory", "Preference",
    "PatternCategory", "ProblemSolvingPattern",
})

# Types that belong exclusively to the job hierarchy
JOB_NODE_TYPES: frozenset[str] = frozenset({
    "Job",
    "JobSkillRequirements", "JobSkillFamily", "JobSkillRequirement",
    "JobDomainRequirements", "JobDomainFamily", "JobDomainRequirement",
    "JobCultureRequirements", "WorkStyle",
})


class VisualizationService:
    def __init__(self, client: Neo4jClient, output_dir: str = "./outputs"):
        self.client = client
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    async def generate_user_graph(self, user_id: str) -> str:
        """
        Generate an interactive pyvis HTML graph for a user.
        Returns the filepath of the generated HTML file.
        """
        nodes_data, edges_data = await self._fetch_graph_data(
            user_id, "User", label_filter=_USER_LABEL_FILTER
        )

        # Safety post-filter: drop any job-hierarchy nodes that slipped through
        allowed_ids = {n["id"] for n in nodes_data if n.get("type", "") in USER_NODE_TYPES}
        nodes_data = [n for n in nodes_data if n["id"] in allowed_ids]
        edges_data = [e for e in edges_data
                      if e["source_id"] in allowed_ids and e["target_id"] in allowed_ids]

        if not nodes_data:
            logger.warning(f"No nodes found for user {user_id}")

        G = nx.DiGraph()

        for node in nodes_data:
            node_id = node.get("id", "")
            label = str(node.get("label", ""))[:30]
            node_type = node.get("type", "default")

            G.add_node(
                node_id,
                label=label,
                title=(
                    f"{label}  ·  {node_type}"
                ),
                color=NODE_TYPE_COLORS.get(node_type, DEFAULT_NODE_COLOR),
                size=NODE_SIZES.get(node_type, DEFAULT_NODE_SIZE),
            )

        for edge in edges_data:
            src = edge.get("source_id", "")
            tgt = edge.get("target_id", "")
            rel = edge.get("rel_type", "")
            if src in G and tgt in G:
                G.add_edge(src, tgt, title=rel, label=rel, color="#7F8C8D")

        net = Network(
            height="850px",
            width="100%",
            directed=True,
            bgcolor="#1a1a2e",
            font_color="white",
            notebook=False,
            cdn_resources="in_line",
        )
        net.from_nx(G)

        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "springLength": 130,
              "springConstant": 0.05,
              "damping": 0.5,
              "avoidOverlap": 0.2
            },
            "stabilization": {
              "enabled": true,
              "iterations": 250
            }
          },
          "layout": {
            "improvedLayout": true
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
          },
          "edges": {
            "smooth": {
              "enabled": true,
              "type": "dynamic"
            },
            "arrows": {
              "to": {"enabled": true, "scaleFactor": 0.5}
            }
          }
        }
        """)

        filepath = os.path.join(self.output_dir, f"graph_{user_id}.html")
        net.write_html(filepath)

        logger.info(
            f"Generated graph for user {user_id}: "
            f"{len(nodes_data)} nodes, {len(edges_data)} edges → {filepath}"
        )
        return filepath

    async def generate_job_graph(self, job_id: str) -> str:
        """
        Generate an interactive pyvis HTML graph for a job.
        Returns the filepath of the generated HTML file.
        """
        nodes_data, edges_data = await self._fetch_graph_data(
            job_id, "Job", label_filter=_JOB_LABEL_FILTER
        )

        # Safety post-filter: drop any user-hierarchy nodes that slipped through
        allowed_ids = {n["id"] for n in nodes_data if n.get("type", "") in JOB_NODE_TYPES}
        nodes_data = [n for n in nodes_data if n["id"] in allowed_ids]
        edges_data = [e for e in edges_data
                      if e["source_id"] in allowed_ids and e["target_id"] in allowed_ids]

        if not nodes_data:
            logger.warning(f"No nodes found for job {job_id}")

        G = nx.DiGraph()

        for node in nodes_data:
            node_id = node.get("id", "")
            label = str(node.get("label", ""))[:30]
            node_type = node.get("type", "default")

            G.add_node(
                node_id,
                label=label,
                title=(
                    f"{label}  ·  {node_type}"
                ),
                color=NODE_TYPE_COLORS.get(node_type, DEFAULT_NODE_COLOR),
                size=NODE_SIZES.get(node_type, DEFAULT_NODE_SIZE),
            )

        for edge in edges_data:
            src = edge.get("source_id", "")
            tgt = edge.get("target_id", "")
            rel = edge.get("rel_type", "")
            if src in G and tgt in G:
                G.add_edge(src, tgt, title=rel, label=rel, color="#7F8C8D")

        net = Network(
            height="850px",
            width="100%",
            directed=True,
            bgcolor="#1a1a2e",
            font_color="white",
            notebook=False,
            cdn_resources="in_line",
        )
        net.from_nx(G)

        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "springLength": 130,
              "springConstant": 0.05,
              "damping": 0.5,
              "avoidOverlap": 0.2
            },
            "stabilization": {
              "enabled": true,
              "iterations": 250
            }
          },
          "layout": {
            "improvedLayout": true
          },
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
          },
          "edges": {
            "smooth": {
              "enabled": true,
              "type": "dynamic"
            },
            "arrows": {
              "to": {"enabled": true, "scaleFactor": 0.5}
            }
          }
        }
        """)

        filepath = os.path.join(self.output_dir, f"graph_job_{job_id}.html")
        net.write_html(filepath)

        logger.info(
            f"Generated graph for job {job_id}: "
            f"{len(nodes_data)} nodes, {len(edges_data)} edges → {filepath}"
        )
        return filepath

    async def generate_match_graph(self, user_id: str, job_id: str) -> str:
        """
        Generate a combined user+job pyvis graph showing match results.

        Colour coding:
          Green  (#27AE60) — matched Skill / JobSkillRequirement nodes
          Orange (#E67E22) — missing job requirements (gap)
          All others       — normal NODE_TYPE_COLORS

        MATCHES edges are drawn in bright green at double width.
        Output: graph_match_{user_id}_{job_id}.html
        """
        MATCH_COLOR = "#27AE60"
        MISSING_COLOR = "#E67E22"
        MATCH_EDGE_COLOR = "#2ECC71"

        # Fetch both subgraphs with label filters to prevent cross-entity contamination
        user_nodes, user_edges = await self._fetch_graph_data(
            user_id, "User", label_filter=_USER_LABEL_FILTER
        )
        job_nodes, job_edges = await self._fetch_graph_data(
            job_id, "Job", label_filter=_JOB_LABEL_FILTER
        )

        # Fetch match overlay
        matched_user_ids, matched_job_ids, missing_ids, matches_edges = (
            await self._fetch_match_overlay(user_id, job_id)
        )

        G = nx.DiGraph()

        all_nodes = user_nodes + job_nodes
        all_edges = user_edges + job_edges

        for node in all_nodes:
            node_id = node.get("id", "")
            label = str(node.get("label", ""))[:30]
            node_type = node.get("type", "default")

            if node_id in matched_user_ids or node_id in matched_job_ids:
                color = MATCH_COLOR
                tooltip_suffix = "  ✓ MATCHED"
            elif node_id in missing_ids:
                color = MISSING_COLOR
                tooltip_suffix = "  ✗ GAP"
            else:
                color = NODE_TYPE_COLORS.get(node_type, DEFAULT_NODE_COLOR)
                tooltip_suffix = ""

            G.add_node(
                node_id,
                label=label,
                title=f"{label}  ·  {node_type}{tooltip_suffix}",
                color=color,
                size=NODE_SIZES.get(node_type, DEFAULT_NODE_SIZE),
            )

        for edge in all_edges:
            src = edge.get("source_id", "")
            tgt = edge.get("target_id", "")
            rel = edge.get("rel_type", "")
            if src in G and tgt in G:
                G.add_edge(src, tgt, title=rel, label=rel, color="#7F8C8D")

        # Add MATCHES edges (cross-graph, bright green)
        for me in matches_edges:
            src = me.get("source_id", "")
            tgt = me.get("target_id", "")
            if src in G and tgt in G:
                G.add_edge(
                    src, tgt,
                    title="MATCHES",
                    label="MATCHES",
                    color=MATCH_EDGE_COLOR,
                    width=3,
                )

        net = Network(
            height="850px",
            width="100%",
            directed=True,
            bgcolor="#1a1a2e",
            font_color="white",
            notebook=False,
            cdn_resources="in_line",
        )
        net.from_nx(G)

        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "springLength": 150,
              "springConstant": 0.04,
              "damping": 0.5,
              "avoidOverlap": 0.3
            },
            "stabilization": {"enabled": true, "iterations": 300}
          },
          "layout": {"improvedLayout": true},
          "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
          },
          "edges": {
            "smooth": {"enabled": true, "type": "dynamic"},
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}}
          }
        }
        """)

        filepath = os.path.join(
            self.output_dir, f"graph_match_{user_id}_{job_id}.html"
        )

        # Inject legend before writing
        net.write_html(filepath)
        self._inject_legend(filepath)

        total_nodes = len(user_nodes) + len(job_nodes)
        total_edges = len(all_edges) + len(matches_edges)
        logger.info(
            f"Generated match graph {user_id}↔{job_id}: "
            f"{total_nodes} nodes, {total_edges} edges, "
            f"{len(matched_user_ids)} matched, {len(missing_ids)} gaps → {filepath}"
        )
        return filepath

    async def _fetch_match_overlay(
        self, user_id: str, job_id: str
    ) -> tuple[set, set, set, list]:
        """
        Return sets of element IDs for coloring the match graph, plus MATCHES edges.

        Returns:
          matched_user_ids  — Skill elementIds connected via MATCHES to this job
          matched_job_ids   — JobSkillRequirement elementIds matched by this user
          missing_ids       — JobSkillRequirement elementIds NOT matched by this user
          matches_edges     — list of {source_id, target_id} for MATCHES edges
        """
        # Matched pairs
        matched_records = await self.client.run_query(
            """
            MATCH (u:User {id: $user_id})-[:HAS_SKILL_CATEGORY]->(:SkillCategory)
                  -[:HAS_SKILL_FAMILY]->(:SkillFamily)-[:HAS_SKILL]->(s:Skill)
                  -[:MATCHES]->(jr:JobSkillRequirement)
                  <-[:REQUIRES_SKILL]-(:JobSkillFamily)
                  <-[:HAS_SKILL_FAMILY_REQ]-(:JobSkillRequirements)
                  <-[:HAS_SKILL_REQUIREMENTS]-(j:Job {id: $job_id})
            RETURN elementId(s) AS user_node_id, elementId(jr) AS job_node_id
            """,
            {"user_id": user_id, "job_id": job_id},
        )

        matched_user_ids = {r["user_node_id"] for r in matched_records}
        matched_job_ids = {r["job_node_id"] for r in matched_records}
        matches_edges = [
            {"source_id": r["user_node_id"], "target_id": r["job_node_id"]}
            for r in matched_records
        ]

        # Missing requirements
        missing_records = await self.client.run_query(
            """
            MATCH (j:Job {id: $job_id})-[:HAS_SKILL_REQUIREMENTS]->(:JobSkillRequirements)
                  -[:HAS_SKILL_FAMILY_REQ]->(:JobSkillFamily)
                  -[:REQUIRES_SKILL]->(jr:JobSkillRequirement)
            WHERE NOT EXISTS {
                MATCH (s:Skill {user_id: $user_id})-[:MATCHES]->(jr)
            }
            RETURN elementId(jr) AS missing_node_id
            """,
            {"user_id": user_id, "job_id": job_id},
        )
        missing_ids = {r["missing_node_id"] for r in missing_records}

        return matched_user_ids, matched_job_ids, missing_ids, matches_edges

    def _inject_legend(self, filepath: str) -> None:
        """Inject a color legend div into the generated pyvis HTML file."""
        legend_html = """
<div style="
    position: fixed; top: 16px; left: 16px; z-index: 9999;
    background: rgba(26,26,46,0.92); border: 1px solid #444;
    border-radius: 8px; padding: 12px 16px; color: white;
    font-family: sans-serif; font-size: 13px; line-height: 1.8;
    pointer-events: none;">
  <b style="font-size:14px;">Match Legend</b><br>
  <span style="color:#27AE60;">&#9679;</span> Matched skill / domain<br>
  <span style="color:#E67E22;">&#9679;</span> Gap (job requires, not in profile)<br>
  <span style="color:#BDC3C7;">&#9679;</span> Hierarchy node<br>
  <span style="color:#2ECC71;">&#9472;&#9472;</span> MATCHES edge
</div>
"""
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("<body>", "<body>" + legend_html, 1)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    async def generate_recommendations_page(
        self, user_id: str, limit: int = 10
    ) -> str:
        """
        Generate a self-contained HTML recommendations dashboard for a user.

        Shows top-N ranked jobs as cards with score breakdown bars, matched/missing
        skill badges, and a "View Match Graph" link per job.
        Output: recommendations_{user_id}.html
        """
        from services.matching_engine import MatchingEngine

        engine = MatchingEngine(self.client)
        batch = await engine.rank_all_jobs_for_user(user_id)
        results = batch.results[:limit]

        def score_color(s: float) -> str:
            if s >= 0.7:
                return "#27AE60"
            if s >= 0.4:
                return "#F39C12"
            return "#E74C3C"

        def pct(s: float) -> str:
            return f"{int(round(s * 100))}%"

        def culture_badge(bonus: float) -> str:
            if bonus >= 0.7:
                color, label = "#27AE60", f"Culture fit {pct(bonus)}"
            elif bonus > 0:
                color, label = "#F39C12", f"Culture fit {pct(bonus)}"
            else:
                color, label = "#555", "Culture fit n/a"
            return (
                f'<span style="background:{color};color:#fff;border-radius:12px;'
                f'padding:2px 10px;margin:2px;font-size:12px;display:inline-block;">'
                f'{label}</span>'
            )

        def pref_badge(bonus: float) -> str:
            if bonus == 1.0:
                color, label = "#27AE60", "Prefs matched"
            elif bonus > 0:
                color, label = "#F39C12", f"Prefs {pct(bonus)}"
            else:
                color, label = "#555", "Prefs n/a"
            return (
                f'<span style="background:{color};color:#fff;border-radius:12px;'
                f'padding:2px 10px;margin:2px;font-size:12px;display:inline-block;">'
                f'{label}</span>'
            )

        cards_html = ""
        for rank, r in enumerate(results, 1):
            matched_skill_badges = "".join(
                f'<span style="background:#27AE60;color:#fff;border-radius:12px;'
                f'padding:2px 8px;margin:2px;font-size:12px;display:inline-block;">'
                f'{sk}</span>'
                for sk in r.matched_skills
            )
            missing_skill_badges = "".join(
                f'<span style="background:#E67E22;color:#fff;border-radius:12px;'
                f'padding:2px 8px;margin:2px;font-size:12px;display:inline-block;">'
                f'{sk}</span>'
                for sk in r.missing_skills
            )
            matched_domain_badges = "".join(
                f'<span style="background:#8E44AD;color:#fff;border-radius:12px;'
                f'padding:2px 8px;margin:2px;font-size:12px;display:inline-block;">'
                f'{d}</span>'
                for d in r.matched_domains
            )
            missing_domain_badges = "".join(
                f'<span style="background:#7D3C98;color:#ccc;border-radius:12px;'
                f'padding:2px 8px;margin:2px;font-size:12px;display:inline-block;'
                f'border:1px solid #8E44AD;">'
                f'{d}</span>'
                for d in r.missing_domains
            )

            sub_bars = [
                ("Skills",  r.skill_score,  "#3498DB", "65%"),
                ("Domain",  r.domain_score, "#8E44AD", "35%"),
            ]
            sub_bars_html = "".join(
                f'<div style="display:flex;align-items:center;margin:3px 0;">'
                f'<span style="width:60px;font-size:11px;color:#aaa;">{label} ({weight})</span>'
                f'<div style="flex:1;background:#2c2c4a;border-radius:4px;height:8px;margin:0 8px;">'
                f'<div style="width:{pct(val)};background:{color};height:8px;border-radius:4px;"></div>'
                f'</div>'
                f'<span style="font-size:11px;color:#ccc;width:35px;">{pct(val)}</span>'
                f'</div>'
                for label, val, color, weight in sub_bars
            )

            tc = score_color(r.total_score)
            match_graph_url = f"/api/v1/users/{user_id}/matches/{r.job_id}/visualize"
            company_display = r.company or "—"

            cards_html += f"""
<div style="background:#16213e;border:1px solid #333;border-radius:10px;
            padding:20px;margin:16px 0;position:relative;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div>
      <span style="background:#2c2c4a;color:#aaa;border-radius:50%;
                   width:28px;height:28px;display:inline-flex;align-items:center;
                   justify-content:center;font-size:13px;margin-right:10px;">
        {rank}
      </span>
      <span style="font-size:20px;font-weight:bold;color:#fff;">{r.job_title}</span>
      <span style="color:#aaa;font-size:14px;margin-left:10px;">{company_display}</span>
    </div>
    <div style="text-align:right;">
      <div style="font-size:28px;font-weight:bold;color:{tc};">{pct(r.total_score)}</div>
      <div style="font-size:11px;color:#aaa;">base match score</div>
    </div>
  </div>

  <div style="margin:14px 0 8px;">
    <div style="background:#2c2c4a;border-radius:6px;height:12px;">
      <div style="width:{pct(r.total_score)};background:{tc};height:12px;border-radius:6px;"></div>
    </div>
  </div>

  <div style="margin:8px 0 6px;">{sub_bars_html}</div>

  <div style="margin:8px 0;">
    {culture_badge(r.culture_bonus)}
    {pref_badge(r.preference_bonus)}
  </div>

  <div style="font-size:12px;color:#aaa;margin-bottom:10px;font-style:italic;">
    {r.explanation}
  </div>

  {f'<div style="margin:4px 0;"><span style="color:#aaa;font-size:12px;">Skills matched: </span>{matched_skill_badges}</div>' if matched_skill_badges else ''}
  {f'<div style="margin:4px 0;"><span style="color:#aaa;font-size:12px;">Skills missing: </span>{missing_skill_badges}</div>' if missing_skill_badges else ''}
  {f'<div style="margin:4px 0;"><span style="color:#aaa;font-size:12px;">Domains matched: </span>{matched_domain_badges}</div>' if matched_domain_badges else ''}
  {f'<div style="margin:4px 0;"><span style="color:#aaa;font-size:12px;">Domains missing: </span>{missing_domain_badges}</div>' if missing_domain_badges else ''}

  <a href="{match_graph_url}" target="_blank"
     style="display:inline-block;margin-top:12px;padding:7px 16px;
            background:#2980B9;color:#fff;border-radius:6px;
            text-decoration:none;font-size:13px;">
    View Match Graph →
  </a>
</div>
"""

        if not results:
            cards_html = (
                '<p style="color:#aaa;text-align:center;margin-top:60px;">'
                "No jobs found. Ingest some job postings first.</p>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Job Recommendations — {user_id}</title>
</head>
<body style="margin:0;padding:0;background:#1a1a2e;color:#fff;
             font-family:'Segoe UI',Arial,sans-serif;min-height:100vh;">
  <div style="max-width:860px;margin:0 auto;padding:32px 24px;">
    <h1 style="color:#fff;font-size:26px;margin-bottom:4px;">
      Job Recommendations
    </h1>
    <p style="color:#aaa;font-size:14px;margin-bottom:8px;">
      User: <b style="color:#5DADE2;">{user_id}</b> &nbsp;·&nbsp;
      Top {len(results)} of {batch.total_jobs_ranked} job(s) ranked
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:16px 0 24px;">
    {cards_html}
  </div>
</body>
</html>"""

        filepath = os.path.join(
            self.output_dir, f"recommendations_{user_id}.html"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(
            f"Generated recommendations page for {user_id}: "
            f"{len(results)} jobs → {filepath}"
        )
        return filepath

    async def _fetch_graph_data(
        self, node_id: str, node_label: str, label_filter: str = ""
    ) -> tuple[list[dict], list[dict]]:
        """
        Fetch all nodes and edges reachable from the given root node (depth ≤ 6).
        Tries APOC first, falls back to pure Cypher.

        label_filter: APOC labelFilter string (e.g. "-Job|-JobSkillRequirement")
          that blocks traversal into unwanted node types, preventing cross-entity
          contamination via bidirectional MATCHES edges.
        """
        try:
            return await self._fetch_with_apoc(node_id, node_label, label_filter)
        except Exception as e:
            if "apoc" in str(e).lower() or "procedure" in str(e).lower():
                logger.info("APOC not available, using pure Cypher fallback")
                return await self._fetch_without_apoc(node_id, node_label, label_filter)
            raise

    async def _fetch_with_apoc(
        self, node_id: str, node_label: str, label_filter: str = ""
    ) -> tuple[list[dict], list[dict]]:
        """Subgraph extraction using APOC (preferred)."""
        query_params = {"node_id": node_id}
        # Build APOC config — include labelFilter only when provided
        apoc_config = "maxLevel: 6"
        if label_filter:
            apoc_config += f", labelFilter: '{label_filter}'"

        nodes = await self.client.run_query(
            f"""
            MATCH (root:{node_label} {{id: $node_id}})
            CALL apoc.path.subgraphAll(root, {{{apoc_config}}})
            YIELD nodes, relationships
            UNWIND nodes AS n
            WITH n
            RETURN DISTINCT
                elementId(n) AS id,
                coalesce(n.name, n.title, n.id, n.pattern, n.style, n.type, labels(n)[0], '') AS label,
                labels(n)[0] AS type
            """,
            query_params,
        )

        edges = await self.client.run_query(
            f"""
            MATCH (root:{node_label} {{id: $node_id}})
            CALL apoc.path.subgraphAll(root, {{{apoc_config}}})
            YIELD nodes, relationships
            UNWIND relationships AS r
            WITH r, startNode(r) AS sn, endNode(r) AS en
            RETURN DISTINCT
                elementId(sn) AS source_id,
                elementId(en) AS target_id,
                type(r) AS rel_type
            """,
            query_params,
        )

        return nodes, edges

    async def _fetch_without_apoc(
        self, node_id: str, node_label: str, label_filter: str = ""
    ) -> tuple[list[dict], list[dict]]:
        """Subgraph extraction using pure Cypher (APOC fallback).
        label_filter is ignored here since the pure-Cypher path uses directional
        traversal (->), which doesn't traverse MATCHES edges bidirectionally.
        """
        query_params = {"node_id": node_id}
        nodes = await self.client.run_query(
            f"""
            MATCH path = (root:{node_label} {{id: $node_id}})-[*0..6]->(n)
            WITH DISTINCT n
            RETURN
                elementId(n) AS id,
                coalesce(n.name, n.title, n.id, n.pattern, n.style, n.type, labels(n)[0], '') AS label,
                labels(n)[0] AS type
            """,
            query_params,
        )

        edges = await self.client.run_query(
            f"""
            MATCH path = (root:{node_label} {{id: $node_id}})-[*0..6]->(n)
            WITH DISTINCT relationships(path) AS rels
            UNWIND rels AS r
            WITH r, startNode(r) AS sn, endNode(r) AS en
            RETURN DISTINCT
                elementId(sn) AS source_id,
                elementId(en) AS target_id,
                type(r) AS rel_type
            """,
            query_params,
        )

        return nodes, edges
