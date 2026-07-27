from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .build import source_coverage
from .io import write_json
from .models import AnalysisBundle, Module


def build_knowledge(repo: Path, compilation_database: Path, analysis: AnalysisBundle,
                    output_dir: Path) -> dict[str, Module]:
    """Group by the first source directory; facts retain their original certainty."""
    files_by_module: dict[str, list[str]] = defaultdict(list)
    for row in analysis.files:
        path = str(row["path"])
        first = path.split("/", 1)[0]
        module_id = "root" if "/" not in path else _safe_id(first)
        files_by_module[module_id].append(path)

    symbols_by_module: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol in analysis.symbols:
        path = str(symbol.get("file_path", ""))
        first = path.split("/", 1)[0]
        module_id = "root" if "/" not in path else _safe_id(first)
        symbols_by_module[module_id].append(symbol)

    modules = {
        module_id: Module(module_id, "根目录" if module_id == "root" else module_id,
                          sorted(files), symbols_by_module[module_id])
        for module_id, files in sorted(files_by_module.items())
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "repository.json", {
        "root": str(repo), "analysis_mode": analysis.mode,
        "diagnostics": analysis.diagnostics,
    })
    write_json(output_dir / "modules.json", [{"module_id": module.module_id,
        "display_name": module.display_name, "files": module.files,
        "symbol_count": len(module.symbols)} for module in modules.values()])
    write_json(output_dir / "symbols.json", analysis.symbols)
    write_json(output_dir / "relations.json", analysis.relations)
    write_json(output_dir / "source_coverage.json", source_coverage(repo, compilation_database))
    return modules


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-") or "root"

