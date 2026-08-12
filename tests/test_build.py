import json
from pathlib import Path

import pytest

from clangwiki.build import (
    create_fallback_compilation_database,
    source_coverage,
    validate_compilation_database,
)
from clangwiki.errors import CompilationDatabaseError


def test_validates_compilation_database(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    compdb = tmp_path / "compile_commands.json"
    compdb.write_text(json.dumps([{"directory": str(tmp_path), "file": str(source), "command": "cc -c main.c"}]), encoding="utf-8")
    assert validate_compilation_database(compdb) == compdb.resolve()
    assert source_coverage(tmp_path, compdb)["covered_source_count"] == 1


def test_rejects_invalid_compilation_database(tmp_path: Path):
    path = tmp_path / "compile_commands.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(CompilationDatabaseError):
        validate_compilation_database(path)


def test_creates_partial_compilation_database_for_source_subtree(tmp_path: Path):
    repo = tmp_path / "subtree"
    source_dir = repo / "PHY" / "PDSCH"
    source_dir.mkdir(parents=True)
    source = source_dir / "pdsch.c"
    source.write_text("int pdsch_run(void) { return 0; }\n", encoding="utf-8")

    compdb = create_fallback_compilation_database(repo, tmp_path / "build")
    entries = json.loads(compdb.read_text(encoding="utf-8"))

    assert len(entries) == 1
    assert Path(entries[0]["file"]) == source.resolve()
    assert entries[0]["clangwiki_partial"] is True
    assert source_coverage(repo, compdb)["covered_source_count"] == 1
