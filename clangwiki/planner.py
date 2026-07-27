from __future__ import annotations

from .models import DocumentTask, Module


def plan_documents(modules: dict[str, Module], only: tuple[str, ...] = ()) -> list[DocumentTask]:
    requested = set(only)
    def include(kind: str) -> bool:
        return not requested or kind in requested

    tasks: list[DocumentTask] = []
    all_modules = tuple(modules)
    if include("readme"):
        tasks.append(DocumentTask("readme", "readme", "项目文档首页", "README.md", all_modules))
    if include("architecture"):
        tasks.append(DocumentTask("architecture", "architecture", "系统架构", "Architecture.md", all_modules))
    if include("module"):
        for module in modules.values():
            filename = f"Modules/{module.module_id}.md"
            tasks.append(DocumentTask(f"module-{module.module_id}", "module",
                f"{module.display_name} 模块", filename, (module.module_id,)))
    if include("data-structures"):
        tasks.append(DocumentTask("data-structures", "data-structures", "数据结构", "DataStructures.md", all_modules))
    if include("call-flows"):
        tasks.append(DocumentTask("call-flows", "call-flows", "核心调用流程", "CallFlows.md", all_modules))
    if include("api-reference"):
        tasks.append(DocumentTask("api-reference", "api-reference", "API 参考", "APIReference.md", all_modules))
    return tasks

