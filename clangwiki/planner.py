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
    requested = _normalise_requested_types(set(only))
    selected_modules = set(module_ids)

    def include(kind: str) -> bool:
        return not requested or kind in requested

    tasks: list[DocumentTask] = []
    all_modules = tuple(modules)
    top_modules = tuple(module for module in modules.values() if module.parent_id is None)

    # Bottom-up order is required: channel leaves first, then their parents.
    # ``module`` remains the backwards-compatible selector for both kinds of
    # hierarchy documents.  The more explicit selectors are used by the UI so
    # a user can generate only the smallest leaf documents or only the
    # bottom-up aggregate summaries.
    hierarchy_types = {"leaf-engineering", "channel-playbook", "subsystem-guide"}
    module_requested = not requested or bool(requested & hierarchy_types)
    if module_requested:
        ordered_modules = sorted(
            modules.values(),
            key=lambda module: (-module.depth, 0 if module.is_leaf else 1, module.source_path),
        )
        for module in ordered_modules:
            if selected_modules and module.module_id not in selected_modules:
                continue
            document_type = module_document_type(module)
            if requested and document_type not in requested:
                continue
            hierarchy_role = _hierarchy_role(document_type)
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
    if include("repository-architecture"):
        tasks.append(
            DocumentTask(
                "repository-architecture",
                "architecture",
                "系统架构",
                "Architecture.md",
                all_modules,
                hierarchy_role="repository",
                child_document_paths=tuple(module_document_path(module) for module in top_modules),
            )
        )
    if include("repository-guide"):
        navigation_sources = ("Architecture.md",) + tuple(
            module_document_path(module) for module in top_modules
        )
        tasks.append(
            DocumentTask(
                "repository-guide",
                "repository-guide",
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
        return "叶子工程文档"
    if module.is_leaf:
        return "叶子工程文档"
    if module.is_channel_root:
        return "信道任务手册"
    return "子系统导航"


def module_document_type(module: Module) -> str:
    if module.is_leaf:
        return "leaf-engineering"
    if module.is_channel_root:
        return "channel-playbook"
    return "subsystem-guide"


def _hierarchy_role(document_type: str) -> str:
    return {
        "leaf-engineering": "leaf",
        "channel-playbook": "channel",
        "subsystem-guide": "subsystem",
    }[document_type]


def _normalise_requested_types(requested: set[str]) -> set[str]:
    normalised = set(requested)
    if "module" in normalised:
        normalised.update({"leaf-engineering", "channel-playbook", "subsystem-guide"})
    if "leaf-module" in normalised:
        normalised.add("leaf-engineering")
    if "module-summary" in normalised:
        normalised.update({"channel-playbook", "subsystem-guide"})
    if "readme" in normalised:
        normalised.add("repository-guide")
    if "architecture" in normalised:
        normalised.add("repository-architecture")
    return normalised
