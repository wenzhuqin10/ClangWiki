from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectionSpec:
    heading: str
    requirements: tuple[str, ...]


@dataclass(frozen=True)
class DocumentSchema:
    purpose: str
    sections: tuple[SectionSpec, ...]


DOCUMENT_SCHEMAS: dict[str, DocumentSchema] = {
    "readme": DocumentSchema(
        purpose="作为整套 Wiki 的仓库级入口和阅读导航，不重复展开各模块正文。",
        sections=(
            SectionSpec("项目简介", ("说明项目用途、主要输入输出和适用范围。",)),
            SectionSpec("代码版本与分析范围", ("说明仓库路径、分析模式和证据覆盖边界。",)),
            SectionSpec("系统组成", ("概括主要模块及其职责，不虚构不存在的层级。",)),
            SectionSpec("模块导航", ("列出模块文档及每个模块的一句话定位。",)),
            SectionSpec("核心任务流程导航", ("列出证据能够支持的核心流程及对应文档。",)),
            SectionSpec("数据结构与 API 导航", ("链接数据结构、调用流程和 API 参考文档。",)),
            SectionSpec("推荐阅读顺序", ("按新成员理解仓库的顺序给出阅读路径。",)),
            SectionSpec("证据说明", ("解释编译器事实、源码事实、合理推断和无法确认信息的区别。",)),
            SectionSpec("已知覆盖限制", ("说明未分析文件、未解析符号、条件编译和上下文截断。",)),
        ),
    ),
    "architecture": DocumentSchema(
        purpose="描述仓库级模块边界、依赖、数据流和运行关系。",
        sections=(
            SectionSpec("系统目标与边界", ("说明系统解决的问题、输入输出以及不属于本系统的范围。",)),
            SectionSpec("总体模块分层", ("按层级或子系统组织模块，并给出结构化总览。",)),
            SectionSpec("模块职责", ("说明各模块负责与不负责的内容。",)),
            SectionSpec("模块依赖", ("说明包含关系和依赖方向，区分确定与候选关系。",)),
            SectionSpec("跨模块接口", ("列出关键跨模块函数、消息、回调或共享结构。",)),
            SectionSpec("核心数据流", ("说明关键数据从产生、转换到消费的过程。",)),
            SectionSpec("核心调用流程", ("给出有序调用链及源码位置。",)),
            SectionSpec("状态与时序关系", ("说明状态、事件、定时器、周期或并发上下文；证据不足时明确缺口。",)),
            SectionSpec("构建配置与运行变体", ("说明 CMake 目标、编译宏和可确认的运行路径差异。",)),
            SectionSpec("架构风险与证据限制", ("列出耦合、未解析关系、条件编译和分析限制。",)),
        ),
    ),
    "leaf-module": DocumentSchema(
        purpose="以信道目录的下一层功能子模块作为最小文档单元，面向领域任务理解、故障定位和代码修改描述直接源码事实。",
        sections=(
            SectionSpec("模块概述", ("说明所属信道、功能定位、职责边界、输入输出和直接源码目录。",)),
            SectionSpec("领域背景", ("说明该子模块对应的协议或领域问题、存在原因以及实时性、协议、内存、并发或硬件约束；设计意图无证据时不得补造。",)),
            SectionSpec("系统交互关系", ("说明调用者、被调用者、接口、消息、回调、事件、依赖和跨模块数据传递，并区分确定关系与候选关系。",)),
            SectionSpec("任务流程", ("按触发条件、入口、调用顺序、数据变化、分支、失败路径和输出描述该子模块参与的开发任务或业务流程。",)),
            SectionSpec("核心实现", ("说明文件分工、入口函数、关键函数、数据结构、算法、配置字段、错误路径和资源生命周期；源码位置必须可追溯。",)),
            SectionSpec("状态与时序", ("说明状态迁移、定时器、中断、回调、周期、Slot/Frame/TTI 关系以及并发上下文。",)),
            SectionSpec("调试与故障定位", ("按现象给出排查顺序、代码位置、状态、可见日志或断点和验证方法；不得虚构日志、错误码或运行现象。",)),
            SectionSpec("设计经验", ("总结源码或工程资料能够支持的设计取舍、兼容性、Legacy 约束、已知限制和可复用经验，并明确区分事实、推断与无法确认内容。",)),
            SectionSpec("Agent 开发导航", ("说明常见修改入口、影响范围、兄弟模块、接口和回归测试；给出下一步应阅读的源码或子文档。",)),
        ),
    ),
    "module-summary": DocumentSchema(
        purpose="基于已生成的直接子文档和本层直接源码，自底向上汇聚父模块，不重复复制叶子级实现细节。",
        sections=(
            SectionSpec("模块概述", ("说明本节点在通信基带系统中的层级、范围、父级位置、直接子模块和整体职责边界。",)),
            SectionSpec("领域背景", ("说明该层级对应的协议或领域目标、子模块共同约束和为什么需要这样的层次划分。",)),
            SectionSpec("系统交互关系", ("提炼子模块之间以及与上下游模块之间已确认的接口、调用、消息、回调和依赖关系。",)),
            SectionSpec("任务流程", ("从直接子文档中汇聚跨子模块的主业务链路、触发条件、关键分支和失败路径。",)),
            SectionSpec("核心实现", ("总结父级公共实现、共享数据结构、配置和关键入口，引用子模块文档而不重复复制叶子级函数细节。",)),
            SectionSpec("状态与时序", ("汇总跨子模块状态、Slot/Frame/TTI、定时器、并发、内存或硬件资源约束。",)),
            SectionSpec("调试与故障定位", ("给出从父级入口向子模块下钻的排查顺序、证据位置和验证方法，并明确无法定位的部分。",)),
            SectionSpec("设计经验", ("总结能够由子文档或本层源码支持的架构取舍、兼容性、Legacy 约束、已知限制和可复用经验。",)),
            SectionSpec("Agent 开发导航", ("说明修改某个子模块可能影响的兄弟模块、公共接口、回归范围和推荐下钻顺序，并列出子文档链接与证据限制。",)),
        ),
    ),
    "data-structures": DocumentSchema(
        purpose="提供可追溯的数据结构事实、使用关系和生命周期说明。",
        sections=(
            SectionSpec("范围与索引", ("列出本文覆盖的 struct、class、enum 和 typedef。",)),
            SectionSpec("核心结构体", ("逐项说明名称、位置、用途、字段及字段语义证据。",)),
            SectionSpec("枚举与类型别名", ("说明枚举值、typedef 和源码位置。",)),
            SectionSpec("初始化与生命周期", ("说明创建、初始化、更新、释放和所有权。",)),
            SectionSpec("读写与传递关系", ("说明读取者、写入者、接口传递和并发访问。",)),
            SectionSpec("配置与消息映射", ("说明结构体与配置、消息或运行上下文的关系。",)),
            SectionSpec("证据与待确认字段", ("列出源码证据及无法由静态分析确定的字段语义。",)),
        ),
    ),
    "call-flows": DocumentSchema(
        purpose="记录确定的跨文件、跨模块调用流程以及未确认候选关系。",
        sections=(
            SectionSpec("流程索引", ("列出本文覆盖的流程、入口和涉及模块。",)),
            SectionSpec("触发条件与前置状态", ("说明流程如何启动以及需要的状态或配置。",)),
            SectionSpec("确定调用链", ("仅使用确定 CALLS 边给出有序调用链和源码位置。",)),
            SectionSpec("数据与配置传播", ("说明关键参数、结构体和字段如何沿调用链传递。",)),
            SectionSpec("分支与失败路径", ("说明条件分支、返回值和已确认的异常路径。",)),
            SectionSpec("时序与并发关系", ("说明事件顺序、周期、回调、中断或线程关系。",)),
            SectionSpec("候选调用与未解析关系", ("单独列出 POSSIBLE_CALL 和 lexical 关系，不得混入确定调用链。",)),
            SectionSpec("源码证据与覆盖限制", ("列出关键文件、符号和分析缺口。",)),
        ),
    ),
    "api-reference": DocumentSchema(
        purpose="以 Clang 提取事实为主体，提供可核验的接口参考。",
        sections=(
            SectionSpec("API 索引", ("按模块或文件列出可见 API。",)),
            SectionSpec("函数签名与位置", ("保留完整标识符、参数、返回类型和源码位置。",)),
            SectionSpec("参数与返回值", ("仅说明源码或注释能够支持的语义。",)),
            SectionSpec("调用者与被调用者", ("区分确定调用关系和候选关系。",)),
            SectionSpec("副作用与状态要求", ("说明全局状态、资源、并发或前置条件；无法确认时明确说明。",)),
            SectionSpec("错误处理", ("说明返回码、错误分支和可见日志，不虚构契约。",)),
            SectionSpec("配置与条件编译", ("说明影响接口可见性或行为的宏和配置。",)),
            SectionSpec("证据与限制", ("列出证据位置、未解析接口和缺失语义。",)),
        ),
    ),
}

# Compatibility for callers that used the pre-hierarchy module schema name.
DOCUMENT_SCHEMAS["module"] = DOCUMENT_SCHEMAS["leaf-module"]


def get_document_schema(document_type: str) -> DocumentSchema:
    try:
        return DOCUMENT_SCHEMAS[document_type]
    except KeyError as exc:
        raise ValueError(f"不支持的文档类型：{document_type}") from exc


def required_section_headings(document_type: str) -> tuple[str, ...]:
    return tuple(section.heading for section in get_document_schema(document_type).sections)


def render_schema_instructions(document_type: str) -> str:
    schema = get_document_schema(document_type)
    lines = [
        f"文档目的：{schema.purpose}",
        "",
        "必须以一个一级标题开始，并严格按照以下顺序输出二级章节。不得改名、遗漏、合并或增加二级章节：",
    ]
    for index, section in enumerate(schema.sections, start=1):
        lines.append(f"{index}. `## {section.heading}`")
        lines.extend(f"   - {requirement}" for requirement in section.requirements)
    lines.extend([
        "",
        "任何章节缺少足够证据时，仍须保留该章节，并明确写出“当前证据无法确定”以及需要补充的材料；不得为了填满章节而推测。",
    ])
    return "\n".join(lines)
