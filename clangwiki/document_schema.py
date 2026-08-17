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

# Navigation-first document contracts.  Generation is bottom-up, while an
# Agent consumes these documents top-down: repository -> subsystem -> channel
# -> leaf -> source facts.  Each level therefore owns a different information
# architecture instead of sharing one generic chapter list.
DOCUMENT_SCHEMAS.update(
    {
        "repository-guide": DocumentSchema(
            purpose="作为 Agent 阅读代码仓的第一入口，把业务任务快速路由到正确子系统、信道和证据范围。",
            sections=(
                SectionSpec("仓库定位与分析范围", ("说明仓库目标、技术域、非目标范围、Git版本和静态分析覆盖。",)),
                SectionSpec("快速任务导航", ("使用任务到目标文档的路由表，优先回答应该阅读哪里。",)),
                SectionSpec("系统分层与模块地图", ("展示顶层模块、职责边界、上下游和直接子文档，不展开局部实现。",)),
                SectionSpec("仓库级关键业务流程", ("仅描述跨越多个技术域的主流程，并把流程节点链接到下层文档。",)),
                SectionSpec("公共接口与共享数据", ("列出跨域接口、共享上下文和公共数据契约，详细字段链接事实参考。",)),
                SectionSpec("构建、运行与配置变体", ("说明CMake目标、编译宏、仿真/生产及软件/硬件路径差异。",)),
                SectionSpec("分析覆盖与证据限制", ("列出未覆盖源码、失败翻译单元、候选关系和需要运行时确认的内容。",)),
            ),
        ),
        "subsystem-guide": DocumentSchema(
            purpose="作为技术域或子系统地图，把仓库级任务继续路由到信道、流程或功能模块。",
            sections=(
                SectionSpec("子系统定位与职责边界", ("说明整体位置、负责与不负责范围、输入输出和父级关系。",)),
                SectionSpec("子模块导航", ("逐项给出直接子模块职责、适用问题、目标文档和不适用范围。",)),
                SectionSpec("入口、出口与接口契约", ("说明对外入口、请求、输出、回调和共享上下文。",)),
                SectionSpec("跨模块主流程", ("仅汇聚跨越多个直接子模块的流程，并在节点处链接子文档。",)),
                SectionSpec("状态、时序与资源约束", ("说明跨模块状态、实时周期、并发、内存和硬件资源约束。",)),
                SectionSpec("故障现象导航", ("使用现象到子模块的排查路由表，不复制叶子级断点清单。",)),
                SectionSpec("跨模块修改影响", ("说明公共接口或子模块修改对兄弟模块和回归范围的影响。",)),
                SectionSpec("证据边界与继续阅读", ("列出直接子文档、事实参考、缺失证据和下一步阅读路径。",)),
            ),
        ),
        "channel-playbook": DocumentSchema(
            purpose="恢复信道端到端业务，并把具体开发、配置和故障问题路由到信道下一级功能模块。",
            sections=(
                SectionSpec("信道定位与处理目标", ("说明协议信道定位、代码职责、数据来源、输出和新传/重传等范围。",)),
                SectionSpec("功能子模块地图", ("列出直接功能子模块、输入输出、业务关键词、常见现象和文档链接。",)),
                SectionSpec("端到端业务流程", ("按实际先后顺序汇聚信道主链路，节点下钻到叶子文档。",)),
                SectionSpec("输入输出与数据契约", ("说明请求、运行时上下文、HARQ、缓冲区和最终输出契约。",)),
                SectionSpec("配置与协议参数传播", ("说明配置产生、转换、缓存和最终消费位置，区分协议解释与仓库事实。",)),
                SectionSpec("状态、HARQ与时序", ("说明新传重传、NDI/RV、Frame/Slot、任务和资源生命周期。",)),
                SectionSpec("故障定位决策树", ("从信道级现象逐步路由到上游、叶子或下游模块，并给出确认方式。",)),
                SectionSpec("开发任务路由", ("把典型修改需求映射到主叶子、关联叶子、风险和回归范围。",)),
                SectionSpec("继续下钻与证据限制", ("列出直接叶子文档、外部关联模块和当前未覆盖链路。",)),
            ),
        ),
        "leaf-engineering": DocumentSchema(
            purpose="把一个内聚业务功能完整映射到领域约束、源码、调用链、数据、异常和修改验证方法。",
            sections=(
                SectionSpec("功能目标与责任边界", ("说明父流程位置、触发条件、输入输出以及负责与不负责范围。",)),
                SectionSpec("领域原理与实现约束", ("只解释理解当前实现所需的协议、算法、实时、内存或硬件约束。",)),
                SectionSpec("源码地图", ("使用文件-符号-作用表列出真实路径、行号和关键入口。",)),
                SectionSpec("执行流程与调用链", ("描述入口、检查、计算、调用、分支、错误和输出，区分确定与候选调用。",)),
                SectionSpec("数据结构与字段语义", ("说明关键结构和字段的创建者、写入者、读取者、传播和生命周期。",)),
                SectionSpec("配置、宏与运行模式", ("说明配置来源、Feature宏、条件编译及软件/硬件和仿真/生产分支。",)),
                SectionSpec("状态、时序与资源生命周期", ("说明状态、Frame/Slot、回调、线程、缓冲区和硬件任务生命周期。",)),
                SectionSpec("异常路径与故障定位", ("按现象列出代码分支、检查位置、可见证据和验证方法，不虚构日志。",)),
                SectionSpec("修改指南与影响分析", ("给出修改入口、接口和结构影响、兄弟模块、风险及回归范围。",)),
                SectionSpec("测试与验证", ("列出可由仓库支持的单元、向量、仿真、集成、性能和回归方法。",)),
                SectionSpec("相关文档与证据限制", ("链接父文档、相关叶子、事实参考和源码，并声明静态分析限制。",)),
            ),
        ),
    }
)

# Backwards-compatible selectors and direct callers keep working, but every
# new task is planned with the explicit navigation-oriented schema names.
DOCUMENT_SCHEMAS["module"] = DOCUMENT_SCHEMAS["leaf-engineering"]
DOCUMENT_SCHEMAS["leaf-module"] = DOCUMENT_SCHEMAS["leaf-engineering"]
DOCUMENT_SCHEMAS["module-summary"] = DOCUMENT_SCHEMAS["subsystem-guide"]
DOCUMENT_SCHEMAS["readme"] = DOCUMENT_SCHEMAS["repository-guide"]


DOCUMENT_ROLE_RULES: dict[str, tuple[str, ...]] = {
    "leaf-module": (
        "当前文档是最小叶子单元，结论应主要来自本模块直接拥有的源码、符号和关系。",
        "在“核心实现”中保留文件、函数、结构体、配置、错误路径和资源生命周期等可定位细节。",
        "在“任务流程”中描述本模块内部的入口、调用顺序、数据变化和分支，不代替父级总结跨模块全流程。",
        "每个重要实现结论尽量给出源码路径和符号；没有证据的领域解释必须标记为推断或无法确认。",
        "叶子内部更深目录作为三级及以下内容组织，不再创建新的二级章节。",
    ),
    "module-summary": (
        "当前文档是父级汇总，已生成的直接子文档是主要输入，本层直接源码只用于补充公共入口和协调逻辑。",
        "九章均应提升到父模块粒度，重点提炼子模块组成、跨子模块关系、公共约束、主流程和下钻路径。",
        "不得机械拼接或大段复制子文档，不得重复罗列每个叶子的全部函数、字段、文件和算法细节。",
        "仅属于单个子模块的实现细节应使用一句话概括并链接对应子文档；跨两个及以上子模块的关系才在父级展开。",
        "在“核心实现”中只总结父级公共入口、共享数据、协调机制和关键分界点，不写成叶子 API 清单。",
        "在“调试与故障定位”中给出从父级现象到具体子模块的下钻顺序，不复制叶子级断点清单。",
        "在“Agent 开发导航”中列出直接子文档及其相对路径，并把常见修改任务路由到相应子模块。",
        "任何直接子文档缺失或被截断时，必须明确降低结论强度并说明汇总不完整。",
    ),
}

DOCUMENT_ROLE_RULES.update(
    {
        "repository-guide": (
            "当前文档是 Agent 的仓库首读入口，优先提供任务路由、模块边界和分析覆盖，不写成源码摘要大全。",
            "只展开跨技术域流程；局部实现必须链接到子系统、信道或叶子文档。",
            "快速任务导航必须说明用户意图、首选文档、继续下钻方向和不适用范围。",
        ),
        "subsystem-guide": (
            "当前文档是子系统导航地图，直接子文档是主要证据，原始源码只补充公共入口和接口契约。",
            "必须同时提供任务路由和故障现象路由，帮助 Agent 选择正确子模块。",
            "不得复制叶子函数清单、结构体字段或局部算法正文。",
        ),
        "channel-playbook": (
            "当前文档恢复一个信道的端到端业务，并把每个处理阶段链接到对应功能叶子。",
            "必须提供功能子模块地图、故障决策树和开发任务路由表。",
            "只展开跨叶子的配置、状态、HARQ和时序关系，局部实现留在叶子工程文档。",
        ),
        "leaf-engineering": (
            "当前文档是进入源码前的最深工程知识单元，结论主要来自本模块直接源码、Clang符号和关系。",
            "必须保留真实文件路径、符号、行号、调用链、数据传播、异常路径和验证方法。",
            "领域知识只用于解释仓库实现；没有代码、注释或工程资料支持时必须标记为推断或无法确认。",
        ),
    }
)


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


def render_document_role_instructions(document_type: str) -> str:
    rules = DOCUMENT_ROLE_RULES.get(document_type)
    if not rules:
        return "当前文档按仓库级或事实参考级任务要求生成。"
    return "\n".join(f"{index}. {rule}" for index, rule in enumerate(rules, start=1))
