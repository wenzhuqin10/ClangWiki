from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class DomainRule:
    subtype: str
    patterns: tuple[str, ...]
    relation: str


BASEBAND_RULES: tuple[DomainRule, ...] = (
    DomainRule("physical_channel", ("pdsch", "pusch", "pdcch", "pucch", "pbch", "prach"), "IMPLEMENTS_CHANNEL"),
    DomainRule("reference_signal", ("dmrs", "ptrs", "srs", "csi_rs", "csirs", "ssb"), "PARTICIPATES_IN"),
    DomainRule("harq", ("harq", "ndi", "redundancy_version", "rv_index"), "PARTICIPATES_IN"),
    DomainRule("config_item", ("config", "cfg", "mcs", "tbs", "bwp", "numerology"), "CONFIGURES"),
    DomainRule("interface", ("fapi", "nfapi", "interface", "callback", "request", "response", "indication"), "PARTICIPATES_IN"),
    DomainRule("pdu", ("pdu", "message", "msg", "request", "response", "indication"), "PARTICIPATES_IN"),
    DomainRule("state", ("state", "status", "phase"), "PARTICIPATES_IN"),
    DomainRule("timer", ("timer", "timeout", "tti", "slot", "subframe", "frame"), "RUNS_IN"),
    DomainRule("execution_context", ("thread", "task", "worker", "isr", "interrupt"), "RUNS_IN"),
    DomainRule("log_point", ("log_", "trace_", "debug_"), "LOGS"),
    DomainRule("assertion", ("assert", "fatal", "panic"), "ASSERTS"),
    DomainRule("test_case", ("test_", "unittest", "simulation", "sim_"), "TESTS"),
)

STANDARD_RE = re.compile(r"\b(?:3GPP\s*)?(?P<series>3[68])\.(?P<number>\d{3})(?:\s*(?:§|section)\s*(?P<section>[\d.]+))?", re.I)


def enrich_baseband_graph(
    repository_id: str,
    run_id: str,
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    *,
    edge_factory,
    node_factory,
) -> list[dict[str, Any]]:
    """Create a conservative domain overlay from source-backed names and metadata.

    A name match is intentionally a candidate classification.  It becomes
    confirmed only when a project-owned symbol has a compiler origin and two
    independent fields (name/path/signature) match the same domain concept.
    """

    evidence: list[dict[str, Any]] = []
    code_nodes = [node for node in list(nodes.values()) if node.get("kind") in {"symbol", "file", "module"}]
    for node in code_nodes:
        metadata = _metadata(node)
        fields = {
            "name": str(node.get("name") or node.get("qualified_name") or "").lower(),
            "path": str(node.get("path") or "").lower(),
            "signature": str(metadata.get("signature") or "").lower(),
        }
        for rule in BASEBAND_RULES:
            matches = [field for field, value in fields.items() if any(_token_hit(value, token) for token in rule.patterns)]
            if not matches:
                continue
            concept = _concept_name(rule, fields)
            concept_id = f"domain:{repository_id}:{rule.subtype}:{_digest(concept)}"
            if concept_id not in nodes:
                nodes[concept_id] = node_factory(
                    concept_id,
                    repository_id,
                    run_id,
                    "domain",
                    concept.upper() if rule.subtype in {"physical_channel", "reference_signal", "harq"} else concept,
                    layer="domain",
                    subtype=rule.subtype,
                    certainty="rule",
                    metadata={"profile": "baseband-generic", "patterns": list(rule.patterns)},
                )
            compiler_backed = str(node.get("origin") or node.get("certainty") or "") == "compiler"
            confirmed = compiler_backed and len(matches) >= 2
            edge = edge_factory(
                repository_id,
                run_id,
                node["id"],
                concept_id,
                rule.relation,
                "rule",
                0.9 if confirmed else 0.68,
                {"matched_fields": matches, "profile": "baseband-generic"},
                status="confirmed" if confirmed else "candidate",
                origin="rule",
                confirmed=confirmed,
                evidence={
                    "source_uri": node.get("path"),
                    "line_start": node.get("line_start"),
                    "line_end": node.get("line_end"),
                    "extractor": "baseband-generic",
                    "reason": f"{rule.subtype} matched in {', '.join(matches)}",
                },
            )
            edges[edge["id"]] = edge
            evidence.append({
                "edge_id": edge["id"],
                "origin": "rule",
                "confidence": edge["confidence"],
                "source_uri": node.get("path"),
                "line_start": node.get("line_start"),
                "line_end": node.get("line_end"),
                "extractor": "baseband-generic",
                "reason": f"{rule.subtype} matched in {', '.join(matches)}",
            })

        for field, value in fields.items():
            for match in STANDARD_RE.finditer(value):
                label = f"{match.group('series')}.{match.group('number')}"
                if match.group("section"):
                    label += f" §{match.group('section')}"
                standard_id = f"domain:{repository_id}:standard_clause:{_digest(label)}"
                if standard_id not in nodes:
                    nodes[standard_id] = node_factory(
                        standard_id, repository_id, run_id, "domain", label,
                        layer="domain", subtype="standard_clause", certainty="source",
                        metadata={"explicit_reference": True},
                    )
                edge = edge_factory(
                    repository_id, run_id, node["id"], standard_id, "SPECIFIED_BY", "source", 1.0,
                    {"matched_field": field}, status="confirmed", origin="source", confirmed=True,
                    evidence={
                        "source_uri": node.get("path"),
                        "line_start": node.get("line_start"),
                        "line_end": node.get("line_end"),
                        "extractor": "standard-reference",
                        "reason": f"explicit standard reference found in {field}",
                    },
                )
                edges[edge["id"]] = edge
    return evidence


def _metadata(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("metadata")
    if isinstance(value, dict):
        return value
    value = node.get("metadata_json")
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _token_hit(value: str, token: str) -> bool:
    return bool(value and re.search(rf"(?:^|[^a-z0-9]){re.escape(token)}(?:$|[^a-z0-9])", value))


def _concept_name(rule: DomainRule, fields: dict[str, str]) -> str:
    for token in rule.patterns:
        if any(_token_hit(value, token) for value in fields.values()):
            return token
    return rule.subtype


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
