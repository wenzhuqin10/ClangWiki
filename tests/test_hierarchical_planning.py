import json
from pathlib import Path

from clangwiki.knowledge import build_knowledge
from clangwiki.models import AnalysisBundle
from clangwiki.planner import plan_documents


def test_pdsch_children_are_leaves_and_pdsch_is_parent_summary(tmp_path: Path):
    repo = tmp_path / "repo"
    encoder = repo / "src" / "phy" / "pdsch" / "encoder" / "encode.c"
    mapper = repo / "src" / "phy" / "pdsch" / "mapping" / "map.c"
    channel_entry = repo / "src" / "phy" / "pdsch" / "pdsch.c"
    for source in (encoder, mapper, channel_entry):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("void run(void) {}\n", encoding="utf-8")

    compdb = tmp_path / "compile_commands.json"
    compdb.write_text(
        json.dumps(
            [
                {"directory": str(repo), "file": str(source), "command": f"cc -c {source}"}
                for source in (encoder, mapper, channel_entry)
            ]
        ),
        encoding="utf-8",
    )
    analysis = AnalysisBundle(
        "full",
        files=[
            {"path": "src/phy/pdsch/encoder/encode.c"},
            {"path": "src/phy/pdsch/mapping/map.c"},
            {"path": "src/phy/pdsch/pdsch.c"},
        ],
        symbols=[
            {"qualified_name": "encode", "file_path": "src/phy/pdsch/encoder/encode.c"},
            {"qualified_name": "map", "file_path": "src/phy/pdsch/mapping/map.c"},
            {"qualified_name": "pdsch_run", "file_path": "src/phy/pdsch/pdsch.c"},
        ],
    )

    modules = build_knowledge(
        repo,
        compdb,
        analysis,
        tmp_path / "knowledge",
        channel_module_paths=("src/phy/pdsch",),
    )

    assert modules["src--phy--pdsch--encoder"].is_leaf
    assert modules["src--phy--pdsch--encoder"].is_channel_child_leaf
    assert modules["src--phy--pdsch--mapping"].is_channel_child_leaf
    assert not modules["src--phy--pdsch"].is_leaf
    assert modules["src--phy--pdsch"].is_channel_root
    assert modules["src--phy--pdsch"].files == ["src/phy/pdsch/pdsch.c"]
    assert modules["src--phy--pdsch"].child_ids == (
        "src--phy--pdsch--encoder",
        "src--phy--pdsch--mapping",
    )

    tasks = plan_documents(modules, ("module",))
    leaf_task_ids = [task.task_id for task in tasks if task.document_type == "leaf-module"]
    assert "leaf-module-src--phy--pdsch--encoder" in leaf_task_ids
    assert "leaf-module-src--phy--pdsch--mapping" in leaf_task_ids
    pdsch_task = next(task for task in tasks if task.task_id == "module-summary-src--phy--pdsch")
    assert pdsch_task.child_document_paths == (
        "Modules/src/phy/pdsch/encoder/index.md",
        "Modules/src/phy/pdsch/mapping/index.md",
    )
