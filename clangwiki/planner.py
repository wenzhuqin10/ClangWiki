from __future__ import annotations

from .models import DocumentTask, Module


def module_document_path(module: Module) -> str:
    path = module.source_path or "root"
    return f"Modules/{path}/index.md"


def plan_documents(
    modules: dict[str, Module],
    only: tuple[str, ...] = (),
    module_ids: tuple[str, ...] = (),
) -> list[DocumentTask]:
    requested = set(only)
    selected_modules = set(module_ids)

    def include(kind: str) -> bool:
        return not requested or kind in requested

    tasks: list[DocumentTask] = []
    all_modules = tuple(modules)
    top_modules = tuple(module for module in modules.values() if module.parent_id is None)

    # Bottom-up order is required: channel leaves first, then their parents.
    if include("module"):
        ordered_modules = sorted(
            modules.values(),
            key=lambda module: (-module.depth, 0 if module.is_leaf else 1, module.source_path),
        )
        for module in ordered_modules:
            if selected_modules and module.module_id not in selected_modules:
                continue
            document_type = "leaf-module" if module.is_leaf else "module-summary"
            hierarchy_role = "leaf" if module.is_leaf else "aggregate"
            tasks.append(
                DocumentTask(
                    task_id=f"{document_type}-{module.module_id}",
                    document_type=document_type,
                    title=f"{module.display_name} {_module_title_suffix(module)}",
                    output_relative_path=module_document_path(module),
                    module_ids=(module.module_id,),
                    hierarchy_role=hierarchy_role,
                    child_document_paths=tuple(
                        module_document_path(modules[child_id]) for child_id in module.child_ids
                    ),
                )
            )

    if include("data-structures"):
        tasks.append(DocumentTask("data-structures", "data-structures", "数据结构", "DataStructures.md", all_modules))
    if include("call-flows"):
        tasks.append(DocumentTask("call-flows", "call-flows", "核心调用流程", "CallFlows.md", all_modules))
    if include("api-reference"):
        tasks.append(DocumentTask("api-reference", "api-reference", "API 参考", "APIReference.md", all_modules))
    if include("architecture"):
        tasks.append(
            DocumentTask(
                "architecture",
                "architecture",
                "系统架构",
                "Architecture.md",
                all_modules,
                hierarchy_role="repository",
                child_document_paths=tuple(module_document_path(module) for module in top_modules),
            )
        )
    if include("readme"):
        navigation_sources = ("Architecture.md",) + tuple(
            module_document_path(module) for module in top_modules
        )
        tasks.append(
            DocumentTask(
                "readme",
                "readme",
                "项目文档首页",
                "README.md",
                all_modules,
                hierarchy_role="repository",
                child_document_paths=navigation_sources,
            )
        )
    return tasks


def _module_title_suffix(module: Module) -> str:
    if module.is_channel_child_leaf:
        return "信道内叶子模块"
    if module.is_leaf:
        return "最小叶子模块"
    if module.is_channel_root:
        return "信道汇总"
    return "模块汇总"
