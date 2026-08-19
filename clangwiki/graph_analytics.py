from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from typing import Any

import networkx as nx

from .database import Database, json_dumps


ANALYTIC_EDGE_KINDS = {
    "CALLS", "REFERENCES", "READS", "WRITES", "INCLUDES", "USES_TYPE",
    "PASSES_TO", "RETURNS_TYPE", "REGISTER_CALLBACK", "INVOKES_CALLBACK",
    "DEPENDS_ON", "CROSS_REPO_CALL",
}

SURPRISE_EDGE_KINDS = {
    "CALLS", "READS", "WRITES", "USES_TYPE", "PASSES_TO", "REGISTER_CALLBACK",
    "INVOKES_CALLBACK", "CONFIGURES", "CROSS_REPO_CALL",
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
            # External/unresolved nodes remain available in the graph for
            # evidence, but standard types (``int``, ``uint32_t``...) can have
            # enormous fan-out and would otherwise dominate hubs and
            # communities.  Core/bridge analytics therefore rank repository
            # symbols only.
            "SELECT * FROM knowledge_nodes WHERE repository_id=? AND kind='symbol'"
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
                current = graph.get_edge_data(edge["source_id"], edge["target_id"])
                weight = float(edge.get("weight") or 1.0) + float(current.get("weight") or 0.0) if current else float(edge.get("weight") or 1.0)
                kinds = set(current.get("kinds") or []) if current else set()
                kinds.add(str(edge["kind"]))
                graph.add_edge(edge["source_id"], edge["target_id"], kinds=sorted(kinds), weight=weight)

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
        pagerank = _pagerank_without_optional_numpy(graph) if graph.number_of_edges() else {node: 0.0 for node in graph}
        if graph.number_of_nodes() <= 2500:
            betweenness = nx.betweenness_centrality(graph, normalized=True, weight=None)
        else:
            sample = min(256, graph.number_of_nodes())
            betweenness = nx.betweenness_centrality(graph, k=sample, seed=42, normalized=True, weight=None)
        degree_values = sorted(degree.values(), reverse=True)
        hub_threshold = _percentile(degree_values, 0.90) if degree_values else 0.0
        bridge_nodes = {
            node for source, target in graph.edges()
            if community_by_node.get(source) and community_by_node.get(target)
            and community_by_node[source] != community_by_node[target]
            for node in (source, target)
        }
        community_span = {
            node_id: len({community_by_node.get(neighbor) for neighbor in graph.neighbors(node_id)
                          if community_by_node.get(neighbor) and community_by_node.get(neighbor) != community_by_node.get(node_id)})
            for node_id in node_ids
        }
        degree_norm = _normalise(degree)
        betweenness_norm = _normalise(betweenness)
        pagerank_norm = _normalise(pagerank)
        span_norm = _normalise(community_span)
        god_scores = {
            node_id: (
                0.25 * degree_norm.get(node_id, 0.0)
                + 0.25 * betweenness_norm.get(node_id, 0.0)
                + 0.20 * pagerank_norm.get(node_id, 0.0)
                + 0.20 * span_norm.get(node_id, 0.0)
                + 0.10 * _domain_weight(node_by_id[node_id])
            )
            for node_id in node_ids
        }
        # The weighted score is intentionally conservative (domain evidence
        # contributes only 0.10), so an absolute 0.55 cutoff hides every
        # genuine hub in large repositories.  Use the distribution of the
        # current graph and keep a modest floor so the coremap remains useful
        # for both tiny fixtures and real baseband codebases.
        god_threshold = max(0.20, _percentile(list(god_scores.values()), 0.95)) if god_scores else 1.0
        metric_rows = [{
            "node_id": node_id, "repository_id": repository_id, "run_id": run_id,
            "degree": float(degree.get(node_id, 0)), "in_degree": float(in_degree.get(node_id, 0)),
            "out_degree": float(out_degree.get(node_id, 0)),
            "betweenness": float(betweenness.get(node_id, 0.0)), "pagerank": float(pagerank.get(node_id, 0.0)),
            "is_hub": int(degree.get(node_id, 0) >= max(2, hub_threshold) and god_scores.get(node_id, 0.0) >= god_threshold),
            "is_bridge": int(node_id in bridge_nodes), "is_orphan": int(degree.get(node_id, 0) == 0),
            "god_score": float(god_scores.get(node_id, 0.0)),
            "god_type": _god_type(node_by_id[node_id], community_span.get(node_id, 0)),
            "community_span": int(community_span.get(node_id, 0)),
            "fan_in": float(in_degree.get(node_id, 0)),
            "fan_out": float(out_degree.get(node_id, 0)),
            "metadata_json": "{}",
        } for node_id in node_ids]

        cycle_components = [sorted(group) for group in nx.strongly_connected_components(graph) if len(group) > 1]
        insights = self._surprising_connections(repository_id, run_id, graph, node_by_id, community_by_node, god_scores, edge_rows)
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM graph_communities WHERE repository_id=?", (repository_id,))
            connection.execute("DELETE FROM graph_metrics WHERE repository_id=?", (repository_id,))
            connection.execute("DELETE FROM graph_insights WHERE repository_id=?", (repository_id,))
            if community_rows:
                connection.executemany(
                    "INSERT INTO graph_communities(id,repository_id,run_id,name,color,member_count,cohesion,metadata_json) "
                    "VALUES(:id,:repository_id,:run_id,:name,:color,:member_count,:cohesion,:metadata_json)",
                    community_rows,
                )
            if metric_rows:
                connection.executemany(
                    "INSERT INTO graph_metrics(node_id,repository_id,run_id,degree,in_degree,out_degree,betweenness,pagerank,is_hub,is_bridge,is_orphan,god_score,god_type,community_span,fan_in,fan_out,metadata_json) "
                    "VALUES(:node_id,:repository_id,:run_id,:degree,:in_degree,:out_degree,:betweenness,:pagerank,:is_hub,:is_bridge,:is_orphan,:god_score,:god_type,:community_span,:fan_in,:fan_out,:metadata_json)",
                    metric_rows,
                )
            if insights:
                connection.executemany(
                    "INSERT INTO graph_insights(id,repository_id,run_id,kind,source_id,target_id,score,reason_json,path_json,evidence_json,metadata_json,created_at) "
                    "VALUES(:id,:repository_id,:run_id,:kind,:source_id,:target_id,:score,:reason_json,:path_json,:evidence_json,:metadata_json,:created_at)",
                    insights,
                )
            for node_id in node_ids:
                connection.execute(
                    "UPDATE knowledge_nodes SET community_id=? WHERE id=?",
                    (community_by_node.get(node_id), node_id),
                )
        return {
            "communities": len(communities), "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "hubs": sum(row["is_hub"] for row in metric_rows), "bridges": len(bridge_nodes),
            "surprising_connections": len(insights),
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
            "SELECT n.*,m.degree,m.in_degree,m.out_degree,m.betweenness,m.pagerank,m.is_hub,m.is_bridge,m.is_orphan,"
            "m.god_score,m.god_type,m.community_span,m.fan_in,m.fan_out "
            "FROM graph_metrics m JOIN knowledge_nodes n ON n.id=m.node_id "
            f"WHERE m.repository_id=? AND {condition} ORDER BY m.god_score DESC,m.betweenness DESC,m.degree DESC LIMIT ?",
            (repository_id, limit),
        )

    def insights(self, repository_id: str, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conditions = ["repository_id=?"]
        parameters: list[Any] = [repository_id]
        if kind:
            conditions.append("kind=?")
            parameters.append(kind)
        rows = self.db.all(
            "SELECT * FROM graph_insights WHERE " + " AND ".join(conditions) + " ORDER BY score DESC LIMIT ?",
            tuple(parameters + [max(1, min(limit, 500))]),
        )
        for row in rows:
            row["reason"] = json.loads(row.get("reason_json") or "{}")
            row["path"] = json.loads(row.get("path_json") or "[]")
            row["evidence"] = json.loads(row.get("evidence_json") or "[]")
        return rows

    def _surprising_connections(
        self,
        repository_id: str,
        run_id: str | None,
        graph: nx.DiGraph,
        nodes: dict[str, dict[str, Any]],
        communities: dict[str, str],
        god_scores: dict[str, float],
        edge_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        edges_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for edge in edge_rows:
            pair = (edge["source_id"], edge["target_id"])
            if pair in graph.edges and edge["kind"] in SURPRISE_EDGE_KINDS and edge["status"] == "confirmed":
                edges_by_pair[pair].append(edge)
        candidates: list[dict[str, Any]] = []
        for (source_id, target_id), edges in edges_by_pair.items():
            source = nodes[source_id]
            target = nodes[target_id]
            source_module = str(source.get("module_id") or "")
            target_module = str(target.get("module_id") or "")
            source_community = communities.get(source_id)
            target_community = communities.get(target_id)
            cross_module = bool(source_module and target_module and source_module != target_module)
            cross_community = bool(source_community and target_community and source_community != target_community)
            if not cross_module and not cross_community:
                continue
            name_distance = 1.0 - _name_similarity(source, target)
            common = len(set(graph.successors(source_id)).intersection(set(graph.predecessors(target_id))))
            rarity = 1.0 / (1.0 + common)
            score = min(1.0, 0.35 * float(cross_module) + 0.25 * float(cross_community) +
                        0.20 * name_distance + 0.10 * rarity +
                        0.10 * max(god_scores.get(source_id, 0.0), god_scores.get(target_id, 0.0)))
            evidence_ids = [edge["id"] for edge in edges]
            evidence = self.db.all(
                "SELECT source_uri,line_start,line_end,origin,confidence,reason FROM graph_evidence WHERE edge_id IN (" +
                ",".join("?" for _ in evidence_ids) + ") LIMIT 12",
                tuple(evidence_ids),
            ) if evidence_ids else []
            kind = ", ".join(sorted({edge["kind"] for edge in edges}))
            candidates.append({
                "id": f"surprise:{repository_id}:{_digest(source_id + '|' + target_id + '|' + kind)}",
                "repository_id": repository_id, "run_id": run_id, "kind": "surprising_connection",
                "source_id": source_id, "target_id": target_id, "score": score,
                "reason_json": json_dumps({
                    "cross_module": cross_module, "cross_community": cross_community,
                    "name_distance": round(name_distance, 4), "common_neighbors": common,
                    "relation_kinds": kind.split(", "),
                    "summary": "跨模块/社区的确定关系，且名称或目录上缺少明显相似性。",
                }),
                "path_json": json_dumps([source_id, target_id]),
                "evidence_json": json_dumps(evidence),
                "metadata_json": json_dumps({"analysis": "direct-confirmed-edge-v1"}),
                "created_at": __import__("time").time(),
            })
        candidates.sort(key=lambda item: (-float(item["score"]), item["id"]))
        return candidates[:200]


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


def _normalise(values: dict[str, float | int]) -> dict[str, float]:
    maximum = max((float(value) for value in values.values()), default=0.0)
    if maximum <= 0.0:
        return {key: 0.0 for key in values}
    return {key: min(1.0, float(value) / maximum) for key, value in values.items()}


def _percentile(values: list[float | int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil((len(ordered) - 1) * percentile)))
    return ordered[index]


def _domain_weight(node: dict[str, Any]) -> float:
    value = " ".join(str(node.get(key) or "") for key in ("name", "qualified_name", "module_id", "subtype")).lower()
    tokens = ("pdsch", "pusch", "pdcch", "pucch", "prach", "harq", "dmrs", "ptrs", "fapi", "nfapi", "scheduler", "encoder", "mapper")
    return 1.0 if any(token in value for token in tokens) else 0.0


def _god_type(node: dict[str, Any], community_span: int) -> str:
    value = " ".join(str(node.get(key) or "") for key in ("name", "qualified_name", "module_id", "subtype")).lower()
    if any(token in value for token in ("config", "cfg", "param")):
        return "配置核心"
    if any(token in value for token in ("fapi", "nfapi", "interface", "request", "response", "callback")):
        return "接口核心"
    if any(token in value for token in ("harq", "tbs", "mcs", "rv", "bwp", "pdu", "buffer")):
        return "数据核心"
    if community_span >= 2:
        return "桥接核心"
    if any(token in value for token in ("thread", "worker", "slot", "tti", "task", "run", "process")):
        return "时序核心"
    return "流程核心"


def _name_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    def tokens(node: dict[str, Any]) -> set[str]:
        value = str(node.get("qualified_name") or node.get("name") or "")
        parts = re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", value.lower())
        return {part for part in parts if len(part) >= 2}

    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _pagerank_without_optional_numpy(graph: nx.DiGraph) -> dict[str, float]:
    """Run PageRank without making the optional RAG numeric stack mandatory.

    NetworkX 3.6 prefers its SciPy implementation when available, which
    imports NumPy even for a small graph.  Graph construction is a core
    feature and must remain usable on the lightweight offline installation,
    so fall back to NetworkX's pure-Python implementation when NumPy/SciPy
    are not installed.
    """
    try:
        return nx.pagerank(graph, weight="weight")
    except ModuleNotFoundError as exc:
        if exc.name not in {"numpy", "scipy"}:
            raise
        from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python

        return _pagerank_python(graph, weight="weight")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
