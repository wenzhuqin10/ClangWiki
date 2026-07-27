from __future__ import annotations

from pathlib import Path

from .io import write_text
from .models import AnalysisBundle, DocumentTask, Module


TEMPLATE_RULES = {
    "readme": "说明项目用途、构建入口、模块导航和阅读建议。",
    "architecture": "说明模块边界、包含依赖和确定的跨模块调用；候选调用必须标注为候选。",
    "module": "说明模块职责、文件分工、公共接口、关键数据结构和生命周期。",
    "data-structures": "聚焦 struct、class、enum、typedef 和它们的代码位置。",
    "call-flows": "按入口函数描述确定 CALLS 链；POSSIBLE_CALL 只能作为未确认的候选。",
    "api-reference": "列出可见函数、参数、返回类型和所在文件，不补造接口。",
}


def build_context(task: DocumentTask, repo: Path, modules: dict[str, Module], analysis: AnalysisBundle,
                  output_path: Path, language: str, max_source_chars: int) -> Path:
    selected_files = sorted({file for module_id in task.module_ids for file in modules[module_id].files})
    selected_symbols = [symbol for module_id in task.module_ids for symbol in modules[module_id].symbols]
    selected_names = {str(symbol.get("qualified_name") or symbol.get("name")) for symbol in selected_symbols}
    relations = [relation for relation in analysis.relations if relation.get("source") in selected_names
                 or relation.get("target") in selected_names
                 or relation.get("file_path") in selected_files]

    blocks = [
        "# ClangWiki Document Task",
        "", "## 任务元数据", f"- 任务 ID：{task.task_id}", f"- 文档类型：{task.document_type}",
        f"- 文档标题：{task.title}", f"- 输出路径：{task.output_relative_path}",
        f"- 输出语言：{language}", f"- 仓库：{repo}",
        "", "## 生成要求", TEMPLATE_RULES[task.document_type],
        "", "## 证据使用规则",
        "1. `certainty=compiler` 的符号和关系是编译器确定的事实。",
        "2. `certainty=lexical` 或 `POSSIBLE_CALL` 是辅助信息，不能叙述为确定的运行时事实。",
        "3. 仅依据本文件的事实和源代码片段写作；无法确认时请明确说明。",
        "4. 保持文件名、宏名、类型名、函数名和参数名原样；只输出 Markdown 正文。",
        "", "## 模块与文件",
    ]
    for module_id in task.module_ids:
        module = modules[module_id]
        blocks.extend([f"### {module.display_name} (`{module.module_id}`)", *[f"- `{file}`" for file in module.files]])
    blocks.extend(["", "## 符号事实"])
    for symbol in selected_symbols:
        blocks.append(f"- `{symbol.get('kind')}` `{symbol.get('qualified_name')}` — "
                      f"`{symbol.get('file_path')}:{symbol.get('line_start')}-{symbol.get('line_end')}` "
                      f"(certainty={symbol.get('certainty', 'compiler')})")
    blocks.extend(["", "## 关系事实"])
    for relation in relations:
        blocks.append(f"- `{relation.get('source')}` --{relation.get('kind')}--> `{relation.get('target')}` "
                      f"at `{relation.get('file_path')}:{relation.get('line')}` "
                      f"(confidence={relation.get('confidence')}, certainty={relation.get('certainty', 'compiler')})")
    blocks.extend(["", "## 源代码片段"])
    used = 0
    for relative in selected_files:
        source = repo / relative
        try:
            content = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        block = f"\n### `{relative}`\n```{_language_hint(source.suffix)}\n{content}\n```\n"
        if used + len(block) > max_source_chars:
            blocks.append(f"\n> 为控制上下文长度，未加入其余源文件内容；可依据上述符号与关系事实说明边界。")
            break
        blocks.append(block)
        used += len(block)
    write_text(output_path, "\n".join(blocks) + "\n")
    return output_path


def _language_hint(suffix: str) -> str:
    return "c" if suffix.lower() in {".c", ".h"} else "cpp"

