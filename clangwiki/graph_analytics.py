from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

import networkx as nx

from .database import Database, json_dumps


ANALYTIC_EDGE_KINDS = {
    "CALLS", "REFERENCES", "READS", "WRITES", "INCLUDES", "USES_TYPE",
    "REGISTER_CALLBACK", "INVOKES_CALLBACK", "DEPENDS_ON", "CROSS_REPO_CALL",
}

COMMUNITY_COLORS = (
    "#5965d8", "#47a487", "#d59649", "#9c6ad6", "#d55f6b", "#3c91b8",
    "#7f8b3d", "#ba6b3d", "#4c70a8", "#9a6f93", "#508876", "#b38842",
)


class GraphAnalytics:
    def __init__(self, database: Database) -> None:
        self.db = database

    def analyze(self, repository_id: str, run_id: str | None = None) -> dict[str, Any]:
        nodes = self.db.all(
            "SELECT * FROM knowledge_nodes WHERE repository_id=? AND kind IN ('symbol','external')"
            + (" AND run_id=?" if run_id else ""),
            (repository_id, run_id) if run_id else (repository_id,),
        )
        if not nodes:
            return {"communities": 0, "nodes": 0, "edges": 0, "cycles": 0}
        node_ids = {node["id"] for node in nodes}
        edge_rows = self.db.all(
            "SELECT * FROM knowledge_edges WHERE repository_id=? AND status='confirmed'",
            (repository_id,),
        )
        graph = nx.DiGraph()
        graph.add_nodes_from(node_ids)
        for edge in edge_rows:
            if edge["kind"] not in ANALYTIC_EDGE_KINDS:
                continue
            if edge["source_id"] in node_ids and edge["target_id"] in node_ids:
                graph.add_edge(edge["source_id"], edge["target_id"], kind=edge["kind"], weight=float(edge.get("weight") or 1.0))

        undirected = graph.to_undirected()
        non_orphans = {node for node in undirected if undirected.degree(node) > 0}
        communities: list[set[str]] = []
        if non_orphans:
            communities = [
                set(group) for group in nx.community.louvain_communities(
                    undirected.subgraph(non_orphans), seed=42, weight="weight"
                )
            ]
        communities.sort(key=lambda group: (-len(group), sorted(group)[0]))
        community_by_node: dict[str, str] = {}
        community_rows: list[dict[str, Any]] = []
        node_by_id = {node["id"]: node for node in nodes}
        for index, members in enumerate(communities):
            stable = _community_id(repository_id, members)
            names = _community_label(members, node_by_id)
            subgraph = undirected.subgraph(members)
            possible = len(members) * (len(members) - 1) / 2
            cohesion = (subgraph.number_of_edges() / possible) if possible else 0.0
            community_rows.append({
                "id": stable, "repository_id": repository_id, "run_id": run_id,
                "name": names, "color": COMMUNITY_COLORS[index % len(COMMUNITY_COLORS)],
                "member_count": len(members), "cohesion": cohesion,
                "metadata_json": json_dumps({"algorithm": "louvain", "seed": 42}),
            })
            for node_id in members:
                community_by_node[node_id] = stable

        degree = dict(graph.degree())
        in_degree = dict(graph.in_degree())
        out_degree = dict(graph.out_degree())
        pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_edges() else {node: 0.0 for node in graph}
        if graph.number_of_nodes() <= 2500:
            betweenness = nx.betweenness_centrality(graph, normalized=True, weight=None)
        else:
            sample = min(256, graph.number_of_nodes())
            betweenness = nx.betweenness_centrality(graph, k=sample, seed=42, normalized=True, weight=None)
        degree_values = sorted(degree.values(), reverse=True)
        hub_threshold = degree_values[max(0, min(len(degree_values) - 1, int(len(degree_values) * 0.05)))] if degree_values else 0
        bridge_nodes = {
            node for source, target in graph.edges()
            if community_by_node.get(source) and community_by_node.get(target)
            and community_by_node[source] != community_by_node[target]
            for node in (source, target)
        }
        metric_rows = [{
            "node_id": node_id, "repository_id": repository_id, "run_id": run_id,
            "degree": float(degree.get(node_id, 0)), "in_degree": float(in_degree.get(node_id, 0)),
            "out_degree": float(out_degree.get(node_id, 0)),
            "betweenness": float(betweenness.get(node_id, 0.0)), "pagerank": float(pagerank.get(node_id, 0.0)),
            "is_hub": int(degree.get(node_id, 0) >= max(2, hub_threshold)),
            "is_bridge": int(node_id in bridge_nodes), "is_orphan": int(degree.get(node_id, 0) == 0),
            "metadata_json": "{}",
        } for node_id in node_ids]

        cycle_components = [sorted(group) for group in nx.strongly_connected_components(graph) if len(group) > 1]
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM graph_communities WHERE repository_id=?", (repository_id,))
            connection.execute("DELETE FROM graph_metrics WHERE repository_id=?", (repository_id,))
            if community_rows:
                connection.executemany(
                    "INSERT INTO graph_communities(id,repository_id,run_id,name,color,member_count,cohesion,metadata_json) "
                    "VALUES(:id,:repository_id,:run_id,:name,:color,:member_count,:cohesion,:metadata_json)",
                    community_rows,
                )
            if metric_rows:
                connection.executemany(
                    "INSERT INTO graph_metrics(node_id,repository_id,run_id,degree,in_degree,out_degree,betweenness,pagerank,is_hub,is_bridge,is_orphan,metadata_json) "
                    "VALUES(:node_id,:repository_id,:run_id,:degree,:in_degree,:out_degree,:betweenness,:pagerank,:is_hub,:is_bridge,:is_orphan,:metadata_json)",
                    metric_rows,
                )
            for node_id in node_ids:
                connection.execute(
                    "UPDATE knowledge_nodes SET community_id=? WHERE id=?",
                    (community_by_node.get(node_id), node_id),
                )
        return {
            "communities": len(communities), "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "hubs": sum(row["is_hub"] for row in metric_rows), "bridges": len(bridge_nodes),
            "orphans": sum(row["is_orphan"] for row in metric_rows), "cycles": len(cycle_components),
            "cycle_components": cycle_components[:50],
        }

    def communities(self, repository_id: str) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM graph_communities WHERE repository_id=? ORDER BY member_count DESC,name",
            (repository_id,),
        )

    def ranked_nodes(self, repository_id: str, metric: str, limit: int = 30) -> list[dict[str, Any]]:
        allowed = {"hub": "m.is_hub=1", "bridge": "m.is_bridge=1", "orphan": "m.is_orphan=1"}
        condition = allowed[metric]
        return self.db.all(
            "SELECT n.*,m.degree,m.in_degree,m.out_degree,m.betweenness,m.pagerank,m.is_hub,m.is_bridge,m.is_orphan "
            "FROM graph_metrics m JOIN knowledge_nodes n ON n.id=m.node_id "
            f"WHERE m.repository_id=? AND {condition} ORDER BY m.betweenness DESC,m.degree DESC LIMIT ?",
            (repository_id, limit),
        )


def _community_id(repository_id: str, members: set[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:16]
    return f"community:{repository_id}:{digest}"


def _community_label(members: set[str], nodes: dict[str, dict[str, Any]]) -> str:
    tokens: Counter[str] = Counter()
    for node_id in members:
        node = nodes[node_id]
        value = f"{node.get('module_id') or ''} {node.get('name') or ''}".replace("/", " ").replace("_", " ")
        for token in value.split():
            if len(token) >= 3 and token.lower() not in {"src", "include", "common", "external"}:
                tokens[token.upper()] += 1
    labels = [token for token, _ in tokens.most_common(3)]
    return " / ".join(labels) if labels else f"耦合群 {len(members)}"
