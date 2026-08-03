import json
from pathlib import Path

from clangwiki.knowledge import build_knowledge
from clangwiki.models import AnalysisBundle
from clangwiki.planner import plan_documents


def test_channel_leaves_are_planned_before_parent_summaries(tmp_path: Path):
    repo = tmp_path / "repo"
    pdsch = repo / "src" / "phy" / "pdsch" / "pdsch.c"
    pusch = repo / "src" / "phy" / "pusch" / "pusch.c"
    pdsch.parent.mkdir(parents=True)
    pusch.parent.mkdir(parents=True)
    pdsch.write_text("void pdsch_run(void) {}\n", encoding="utf-8")
    pusch.write_text("void pusch_run(void) {}\n", encoding="utf-8")

    compdb = tmp_path / "compile_commands.json"
    compdb.write_text(
        json.dumps(
            [
                {"directory": str(repo), "file": str(pdsch), "command": f"cc -c {pdsch}"},
                {"directory": str(repo), "file": str(pusch), "command": f"cc -c {pusch}"},
            ]
        ),
        encoding="utf-8",
    )
    analysis = AnalysisBundle(
        "full",
        files=[{"path": "src/phy/pdsch/pdsch.c"}, {"path": "src/phy/pusch/pusch.c"}],
        symbols=[
            {"qualified_name": "pdsch_run", "file_path": "src/phy/pdsch/pdsch.c"},
            {"qualified_name": "pusch_run", "file_path": "src/phy/pusch/pusch.c"},
        ],
    )

    modules = build_knowledge(
        repo,
        compdb,
        analysis,
        tmp_path / "knowledge",
        ("src/phy/pdsch", "src/phy/pusch"),
    )

    assert modules["src--phy--pdsch"].is_leaf
    assert modules["src--phy--pdsch"].is_channel_leaf
    assert modules["src--phy--pusch"].is_leaf
    assert modules["src--phy"].child_ids == ("src--phy--pdsch", "src--phy--pusch")

    tasks = plan_documents(modules, ("module",))
    task_types = [task.document_type for task in tasks]
    assert task_types[:2] == ["leaf-module", "leaf-module"]
    parent_task = next(task for task in tasks if task.task_id == "module-summary-src--phy")
    assert parent_task.child_document_paths == (
        "Modules/src/phy/pdsch/index.md",
        "Modules/src/phy/pusch/index.md",
    )
