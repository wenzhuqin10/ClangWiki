# 无线基带代码知识图谱规范

## 1. 定位

ClangWiki 的代码关系图是代码知识图谱的可视化入口，不是 LLM 凭语义猜出的流程图。确定事实来自 `compile_commands.json`、CMake、libclang、源码和人工确认；规则与 LLM 结果只能形成候选关系，确认前不参与确定调用链。

```text
权威模块树：仓库 → 信道 → 子模块 → 文件 → 符号
属性知识图：调用 → 数据 → 配置 → 消息 → 状态 → 文档 → 领域概念
社区分析：高耦合群 → 核心节点 → 桥接节点 → 循环与孤点
```

模块树负责稳定导航，知识图谱负责解释跨模块关系，社区只提供架构观察，不自动改写模块边界。

## 2. 图层与实体

| 图层 | 主要实体 | 来源 |
|---|---|---|
| 构建与代码事实 | `Repository`、`BuildTarget`、`TranslationUnit`、`Module`、`File`、`Function`、`Parameter`、`Struct`、`Field`、`Enum`、`Typedef`、`Macro`、`GlobalVariable`、`ExternalSymbol` | CMake、编译数据库、libclang |
| 无线基带领域 | `PhysicalChannel`、`ReferenceSignal`、`HARQ`、`Interface`、`Message`、`PDU`、`ConfigItem`、`State`、`Timer`、`ExecutionContext`、`LogPoint`、`Assertion`、`TestCase`、`StandardClause` | 保守规则、显式源码证据 |
| 文档知识 | `Document`、`DocumentSection`、`ManualPage`、`Annotation`、`Tag` | Wiki 与人工知识 |
| 图分析 | `Community`、Hub、Bridge、Cycle、Orphan 指标 | NetworkX |

局部变量不会作为全局节点。参数、字段等细粒度实体只在符号详情、接口视图和数据流视图按需展开，避免大仓库图谱失控。

## 3. 关系与证据等级

主要结构关系包括 `CONTAINS`、`BUILDS`、`COMPILES`、`DECLARES`、`DEFINES`、`HAS_PARAMETER` 和 `HAS_FIELD`。代码关系包括 `INCLUDES`、`CALLS`、`POSSIBLE_CALL`、`REFERENCES`、`READS`、`WRITES`、`USES_TYPE`、`PASSES_TO`、`RETURNS_TYPE`、`REGISTER_CALLBACK` 和 `INVOKES_CALLBACK`。领域与知识关系包括 `IMPLEMENTS_CHANNEL`、`PARTICIPATES_IN`、`CONFIGURES`、`RUNS_IN`、`LOGS`、`ASSERTS`、`SPECIFIED_BY`、`TESTS`、`DOCUMENTS`、`MENTIONS` 和 `EVIDENCE_FOR`。

每条边保存：

```text
status: confirmed | candidate | rejected
origin: compiler | build | source | rule | llm | user
confidence
repository_id / run_id / git_commit
source_uri / line_start / line_end
extractor / extractor_version / reason
```

- 编译器、构建系统和源码显式关系：实线；
- 领域规则：点线；
- 词法、LLM 或歧义关系：虚线并显示“候选”；
- 被拒绝关系默认隐藏；
- `POSSIBLE_CALL` 和候选跨仓关系永远不会进入默认确定路径。

逻辑边与证据分表保存。同一条 `A --CALLS--> B` 可以关联多个调用位置，但前端只画一条聚合边，并在证据检查器中列出全部位置。

## 4. 构建过程

1. 检查本机分析器、`libclang.dll` 和编译数据库；
2. 统计 C/C++ 源文件、编译数据库覆盖、成功解析及失败翻译单元；
3. 从编译数据库创建 `BuildTarget`、`TranslationUnit` 和精确编译配置；
4. 使用 Clang USR 合并声明与定义并提取直接调用、类型、字段读写、回调与包含；
5. 无法唯一解析的函数指针或词法调用保留为 `POSSIBLE_CALL`；
6. 运行 `baseband-generic` 领域规则，仅在多项编译器证据满足时确认领域分类；
7. 接入 Wiki 元数据和人工知识；
8. 计算 Louvain 社区、Degree、Betweenness、PageRank、Hub、Bridge、Cycle 和 Orphan；
9. 保存当前属性图、证据和不可变运行快照。

原生分析器不可用或翻译单元解析失败时，图谱会持续显示“部分分析”警告。此时词法调用仍为候选，不能伪装成完整调用链。

## 5. 前端工作台

工作台采用三栏结构：左侧深色视图与社区导航，中间浅色渐进图画布，右侧证据检查器。预设视图为：

1. 架构导航；
2. 社区耦合；
3. 模块依赖；
4. 调用链；
5. 数据与配置流；
6. 接口与消息；
7. Wiki 知识图。

默认只显示确定关系，单次初始图控制在 250 个节点左右，邻居展开限制为 80 个节点并支持一至三跳。用户可以 Shift 点击两个节点查询有向路径，在节点检查器中预览源码，在边检查器中查看全部证据并确认或否决候选关系，导出 JSON、SVG、PNG 或 GraphML，并比较最近两个图谱运行快照。

## 6. 检索与 RAG

仓库索引会为已确认且与开发任务相关的关系建立 FTS 图谱证据块，但不会对每条边执行 Embedding。查询先命中符号、Wiki、源码和关键词，再沿已确认关系扩展，最终形成 `[G]` 证据：

```text
[G1] pdsch_encode --CALLS--> ldpc_encode
     来源：PDSCH/encoder/pdsch.c:42
     状态：confirmed，origin=compiler
```

候选边默认不进入 RAG。即使显式启用候选关系，模型也必须使用“可能”表达，不能把社区邻近或名称相似表述为调用事实。

## 7. 命令与接口

```powershell
clangwiki --data-root D:\clangwiki-data graph build repo-...
clangwiki --data-root D:\clangwiki-data graph analyze repo-...
clangwiki --data-root D:\clangwiki-data graph status repo-...
clangwiki --data-root D:\clangwiki-data graph diff repo-... run-old run-new
```

主要接口：`GET /api/graph`、`GET /api/graph/nodes/{id}`、`GET /api/graph/neighbors`、`POST /api/graph/path`、`GET /api/graph/communities`、`GET /api/graph/hubs`、`GET /api/graph/bridges`、`GET /api/graph/cycles`、`GET /api/graph/diagnostics`、`GET /api/graph/diff`、`GET /api/graph/export.graphml`。

## 8. 验收重点

- 编译数据库覆盖率与失败翻译单元可见；
- 确定 `CALLS` 与候选 `POSSIBLE_CALL` 可明确区分；
- 有向路径方向正确，候选边默认不参与；
- 节点详情能打开源码位置并显示全部证据；
- PDSCH、DMRS、HARQ、MCS、TBS、接口与 PDU 能形成保守领域关联；
- 社区、核心、桥梁、循环和孤点分析可用，但不修改模块层级；
- 图谱关系能够以 `[G]` 引用参与问答，且引用可解析；
- 两个运行快照可以报告新增、删除和变化的节点及关系。
