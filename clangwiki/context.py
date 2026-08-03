from __future__ import annotations

from pathlib import Path

from .document_schema import render_schema_instructions
from .io import write_text
from .models import AnalysisBundle, DocumentTask, Module


def build_context(
    task: DocumentTask,
    repo: Path,
    modules: dict[str, Module],
    analysis: AnalysisBundle,
    output_path: Path,
    language: str,
    max_source_chars: int,
    generated_output_root: Path | None = None,
) -> Path:
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
        f"- 输出语言：{language}", f"- 仓库：{repo}", f"- 层级角色：{task.hierarchy_role}",
        "", "## 文档章节契约", render_schema_instructions(task.document_type),
        "", "## 证据使用规则",
        "1. 编译器证据：`certainty=compiler` 的符号和关系可表述为 Clang 分析确认的事实。",
        "2. 源码证据：源代码中直接可见的赋值、分支、日志和资源操作可表述为源码确认的事实。",
        "3. 合理推断：根据命名、目录或多条关系作出的解释必须明确使用“推测”“可能”或“根据现有证据推断”。",
        "4. 无法确认：缺少运行数据、设计文档、提交历史或完整调用关系时，必须明确写出“当前证据无法确定”。",
        "5. `certainty=lexical` 或 `POSSIBLE_CALL` 只能放在候选或待确认内容中，不能叙述为确定的运行时调用。",
        "6. 协议或通用领域知识只能辅助解释，不能冒充当前仓库的真实实现。",
        "7. 保持文件名、宏名、类型名、函数名和参数名原样，并尽量附带 `路径:行号`。",
        "8. 只输出最终 Markdown 正文，不输出生成过程、代码围栏外壳或致歉说明。",
        "", "## 模块层级与直接源码",
    ]
    for module_id in task.module_ids:
        module = modules[module_id]
        parent = modules.get(module.parent_id) if module.parent_id else None
        blocks.extend(
            [
                f"### {module.display_name} (`{module.module_id}`)",
                f"- 源码路径：`{module.source_path or '.'}`",
                f"- 层级深度：{module.depth}",
                f"- 节点类型：{'信道内叶子模块' if module.is_channel_child_leaf else '最小叶子模块' if module.is_leaf else '信道父级汇总模块' if module.is_channel_root else '父级汇总模块'}",
                f"- 父模块：`{parent.module_id}`" if parent else "- 父模块：无",
                "- 子模块：" + (", ".join(f"`{child_id}`" for child_id in module.child_ids) or "无"),
                "- 本层直接拥有的源码文件：",
                *([f"  - `{file}`" for file in module.files] or ["  - 无；本节点完全由子模块向上汇聚。"]),
            ]
        )

    blocks.extend(["", "## 已生成的直接子文档"])
    if task.child_document_paths:
        available_children = {
            relative_path: generated_output_root / relative_path
            for relative_path in task.child_document_paths
            if generated_output_root is not None and (generated_output_root / relative_path).is_file()
        }
        per_child_budget = max(1, max_source_chars // max(1, len(available_children)))
        for relative_path in task.child_document_paths:
            child_path = available_children.get(relative_path)
            if child_path is None:
                blocks.append(f"- `{relative_path}`：尚未生成或本次任务未包含该子文档。")
                continue
            content = child_path.read_text(encoding="utf-8", errors="replace")
            excerpt = content[:per_child_budget]
            blocks.extend(
                [
                    f"### 子文档 `{relative_path}`",
                    "<child_document>",
                    excerpt,
                    "</child_document>",
                ]
            )
            if len(excerpt) < len(content):
                blocks.append("> 该子文档因上下文预算被截断，汇总时必须在限制章节中说明。")
    else:
        blocks.append("- 无。叶子模块应直接依据 Clang 事实和源码生成最小单元文档。")
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
            blocks.append(
                "\n> 为控制上下文长度，未加入其余源文件内容。文档必须在限制章节中说明上下文已截断，"
                "只能依据上述符号与关系事实描述未附源码的部分。"
            )
            break
        blocks.append(block)
        used += len(block)
    write_text(output_path, "\n".join(blocks) + "\n")
    return output_path


def _language_hint(suffix: str) -> str:
    return "c" if suffix.lower() in {".c", ".h"} else "cpp"
