from pathlib import Path

from cppwiki.analyzer import RepositoryAnalyzer


FIXTURE = Path(__file__).parent / "fixtures" / "cpp-sample"


def test_fallback_extracts_symbols_includes_and_relationships(tmp_path):
    analyzer = RepositoryAnalyzer(tmp_path / "missing-analyzer")
    result = analyzer.analyze(FIXTURE)

    names = {row["qualified_name"] for row in result.symbols}
    relations = {(row["source"], row["target"], row["kind"]) for row in result.relations}

    assert result.mode in {"fallback", "partial"}
    assert "Processor" in names
    assert any(name.endswith("Processor::execute") for name in names)
    assert "ENABLE_METRICS" in names
    assert any(row["kind"] == "INCLUDES" and row["target"] == "processor.h" for row in result.relations)
    assert ("Processor", "BaseProcessor", "INHERITS") in relations
    assert result.chunks
    assert all(row["line_start"] <= row["line_end"] for row in result.chunks)
