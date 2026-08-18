# ClangWiki 多仓知识平台架构

## 1. 目标与边界

ClangWiki 是本机单用户平台，而不是 IDE、代码托管服务或远程 Agent。它把多个 C/C++ 代码仓、不可变生成 Wiki、人工工程知识和 Clang 关系图组织为一个可审计知识空间。

```text
React 中文工作台
        │ 同源 HTTP / SSE
FastAPI 本地服务（127.0.0.1）
├── 多仓与逻辑集合管理
├── SQLite 任务中心
├── Wiki / 批注 / 人工知识
├── Clang 代码图谱
├── 混合检索与 RAG
└── 现有 ClangWiki Pipeline
        │
        ├── CMake + compile_commands.json
        ├── libclang C API 分析器
        └── opencode run → 已认证 GLM-5.1
```

平台不接触模型 API Key；不读取 OpenCode 凭据；不复制、合并、删除或编辑源代码仓。

## 2. 数据根目录

```text
clangwiki-data/
├── clangwiki.db
├── repositories/<repo-id>/
│   ├── repository.json
│   ├── runs/<run-id>/{analysis,knowledge,tasks,logs,output,manifest.json}
│   └── index/{chunks.usearch,index-manifest.json}
├── collections/<collection-id>/{output,index,tasks,logs}
├── models/
├── backups/
└── tmp/
```

Windows 中不使用符号链接。“当前 Wiki”由 SQLite 中的 `repositories.active_run_id` 指向。每个运行快照独立保存，生成文档不可直接编辑。

## 3. SQLite 实体

| 实体 | 职责 |
|---|---|
| `repositories` / `runs` | 源码路径、配置、提交、快照和当前版本。 |
| `collections` / `collection_repositories` | 不复制源码的逻辑合仓。 |
| `jobs` / `job_events` | 可恢复的分析、生成、索引和集合任务及 SSE 进度。 |
| `knowledge_nodes` / `knowledge_edges` | 仓库、模块、文件、符号、文档与关系图。 |
| `documents` / `annotations` / `tags` / `document_revisions` | 生成快照、人工知识、批注、标签和历史。 |
| `chunks` / `chunks_fts` | 稳定知识切块、FTS5 和向量键。 |
| `conversations` / `turns` / `citations` | RAG 短会话、回答和本轮引用。 |

数据库带 `PRAGMA user_version` 迁移，启用 WAL 和外键约束。

## 4. 文档生成粒度

对于通信基带的信道根目录，下一层源码目录被定义为叶子模块：

```text
src/phy/pdsch
├── encoder/       # 叶子 Wiki
├── modulation/    # 叶子 Wiki
├── mapping/       # 叶子 Wiki
└── dmrs/          # 叶子 Wiki
        ↓
pdsch/             # 父级汇聚 Wiki
        ↓
phy/ → 仓库架构 → README
```

叶子文档用 Clang 事实、有限源码上下文和 `opencode run` 生成；RAG 不替代叶子文档的事实生产。父级只阅读直接子文档、直接源码和已确认关系，避免再次把全仓源码塞入模型。

## 5. 图谱与跨仓关系

节点类型：`repository`、`module`、`file`、`symbol`、`document`、`external`。关系类型：`CONTAINS`、`DEPENDS_ON`、`INCLUDES`、`CALLS`、`POSSIBLE_CALL`、`REFERENCES`、`DEFINES`、`DOCUMENTS`、`RELATED_TO`。

跨仓关系按以下顺序建立：完整符号名与签名一致（编译器/确定关系）、公共头文件与编译目标匹配、用户确认的别名、仅名称相似的候选关系。候选关系不会进入确定调用链，也不能作为强事实用于 RAG 回答。

前端默认按模块聚合加载；用户再下钻到文件或符号级，避免一次渲染整个中大型仓库。

## 6. 增量规则

| 变化 | 处理 |
|---|---|
| 源文件或叶子模块变化 | 重新生成受影响叶子与所有父级汇聚文档。 |
| 公共头文件变化 | 根据反向包含关系扩大受影响范围。 |
| CMake、编译数据库、模块边界变化 | 执行完整分析与生成。 |
| Embedding 配置变化 | 只重建向量索引。 |
| 集合成员或成员当前快照变化 | 重建集合关系和集合级 Wiki。 |

没有 Git 时以内容哈希比较。每次运行保留 Git 提交、文件哈希、配置哈希、Schema 版本和 Embedding 配置档。

## 7. 任务并发

SQLite 持久化任务状态。默认最多允许：一个 `opencode run` 文档/集合任务、一个 CPU 分析或索引任务；同一仓库禁止两个写入型任务并发。服务重启后正在执行的任务会保留为中断记录。文档任务每完成一篇文档即原子更新断点；失败、取消或中断后可创建新快照继续剩余任务。继续前必须验证仓库、源码哈希、生成配置和文档 Schema 一致，否则只能从头重新生成。

## 8. 安全约束

- 前后端同源，默认仅 `127.0.0.1`。
- API 不接受 API Key、token、password、secret 或 credential 字段。
- 源码查看以已注册仓根目录为边界，拒绝任意路径读取和目录逃逸。
- 删除仓库只删除注册信息/可选平台产物，不操作源仓。
- 手工 Markdown 不解析原始 HTML，前端默认安全渲染。
