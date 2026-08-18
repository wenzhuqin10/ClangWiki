# ClangWiki

ClangWiki 是一个面向通信基带等大型 C/C++ 代码仓的**本机单用户代码知识平台**。它以 Clang/`libclang` 提取的代码事实为基础，按“信道根目录的下一层子模块”为最小叶子文档单元，自底向上生成 Wiki；同时管理多个仓库、逻辑知识空间、代码关系图、人工知识和有引用的 RAG 问答。

```text
本地 C/C++ 代码仓
    → CMake / compile_commands.json
    → Clang 静态事实（模块、文件、符号、调用与包含）
    → 叶子模块 Wiki → 父级汇聚 Wiki
    → SQLite / FTS / 可选本地 Embedding / 关系图
    → opencode run → 已认证的 GLM-5.1
    → 带 [W]/[C]/[G]/[M] 引用的知识问答
```

模型认证始终由目标设备上的 OpenCode 管理。ClangWiki **不接收、不保存、不读取 API Key**，也不会读取 OpenCode 的认证文件。

## 核心能力

- 多本地代码仓独立注册、生成快照、索引与运行历史；删除注册记录不会删除源码。
- 逻辑知识空间：跨仓检索、跨仓候选接口关系、集合 Wiki；不复制或合并任何代码仓。
- Clang 代码图谱：仓库、模块、文件、符号四层可视化，可筛选确定关系和候选关系。
- 生成快照不可直接修改；人工知识页、批注、标签和版本历史独立保存并统一检索。
- 混合检索：精确符号、SQLite FTS5、默认 BGE-M3 ONNX + USearch 向量、图关系扩展和 RRF 融合。
- RAG 问答：每轮重新检索，短会话，回答必须携带可验证的 Wiki、源码、图谱或人工知识引用。
- 受限模块并发：同层叶子模块可并发调用 `opencode run`；父级与仓库级文档仍按依赖顺序汇聚。
- FastAPI + React 本地工作台，中文界面、深色左栏/浅色内容区；仅监听 `127.0.0.1`。
- Windows 离线部署：运行时不需要 Node.js、Docker、Ollama、Neo4j 或外部向量数据库。

## 快速启动

生产机先按 [部署与使用说明](docs/DEPLOYMENT_AND_USAGE.zh-CN.md) 安装 Python 3.12、CMake、LLVM/Clang、OpenCode 和离线 wheel 包。然后：

```powershell
# 注册仓库；不输入 API Key
clangwiki --data-root "D:\clangwiki-data" repo add "D:\projects\pdsch-channel" `
  --name "PDSCH 信道仓" `
  --model "provider/glm-5.1" `
  --analyzer-executable "D:\ClangWiki\bin\clangwiki-analyzer.exe" `
  --module-generation-concurrency 2 `
  --channel-module-path "src/phy/pdsch"

# 启动本机中文工作台
clangwiki --data-root "D:\clangwiki-data" serve
```

打开 `http://127.0.0.1:8082/`，选择仓库后点击“生成 Wiki”。也可使用 CLI：

```powershell
clangwiki --data-root "D:\clangwiki-data" generate --repo-id "repo-..."
clangwiki --data-root "D:\clangwiki-data" index --repo-id "repo-..."
clangwiki --data-root "D:\clangwiki-data" search --repo-id "repo-..." "pdsch_encode"
clangwiki --data-root "D:\clangwiki-data" ask --repo-id "repo-..." "PDSCH 编码入口在哪里？"
```

旧的单仓命令仍兼容一个版本周期：

```powershell
clangwiki generate --repo "D:\projects\target" --workspace "D:\workspace" --model "provider/glm-5.1"
```

## 叶子模块粒度

针对 `src/phy/pdsch`，ClangWiki 默认将其**下一层**源码子目录作为叶子，例如：

```text
src/phy/pdsch
├── encoder/       ← 最小文档单元
├── modulation/    ← 最小文档单元
├── mapping/       ← 最小文档单元
└── dmrs/          ← 最小文档单元
```

框架先产生 `leaf-engineering` 叶子工程文档，再汇聚为 `channel-playbook` 信道任务手册、`subsystem-guide` 子系统导航和 `repository-guide` 仓库首读入口。不同层级使用各自的章节契约：越靠上越强调任务、故障和模块路由，越靠下越强调领域约束、源码地图、调用链、异常路径和修改验证。

每篇文档一级标题后都有框架确定性生成的导航卡。上层文档把直接子文档作为主要证据并自动补充下钻链接；如果模型大段复制子文档正文，质量门禁会拒绝写入。生成方向是自底向上，Agent 阅读方向是仓库 → 子系统 → 信道 → 叶子 → 源码。

入库时，文档分别保存到 `knowledge/documents/repository/`、`subsystems/`、`channels/`、`modules/` 和 `facts/`。数据库文档记录和检索切块同时保留 `document_role`、`module_id`、`module_folder` 与 `storage_path`，因此各层文档可以独立导航、过滤和重建索引。

## 模块生成并发

`module_generation_concurrency` 控制单个仓库一次生成中，同时运行的**叶子模块** OpenCode 任务数，允许范围为 `1–4`，默认 `2`。它是性能设置，不改变文档事实或章节模板；因此单独调整它不会使已有快照失效。

```text
叶子模块 A ─┐
叶子模块 B ─┼─ 最多 N 个并行 opencode run
叶子模块 C ─┘
                 ↓ 全部完成
父级模块汇总 → 架构文档 / README
```

父级汇总会读取直接子文档，所以必须等待其子模块完成；系统架构、首页和仓库级文档同样按依赖顺序生成。建议先使用默认值 `2`；只有确认企业 OpenCode 与模型额度支持时再调高至 `3` 或 `4`。

## 完整 Wiki、选择性维护与断点继续

工作台中的“生成/更新完整 Wiki”是首次建库和全仓更新入口，会执行分析、叶子文档生成、父级汇聚与入库。“选择性文档维护”只用于重新生成指定文档类型或模块，不是第二套生成流程；界面默认收起，避免干扰日常使用。

每完成一篇文档，流水线都会原子更新运行快照中的 `checkpoint.json`。任务失败、取消或服务意外中断后，可在仓库运行记录或任务中心选择“从断点继续”。系统会新建一个不可变运行快照，复用已完成文档和分析产物，只执行剩余任务。若源码、生成配置或文档 Schema 已变化，系统会拒绝复用旧断点并提示重新生成，避免把不同版本的内容混入同一 Wiki。

层级模块文档在运行快照中按源码层级镜像保存：

```text
repositories/<repo-id>/runs/<run-id>/output/Modules/
└── <代码仓对应模块路径>/
    └── index.md
```

该目录位于 ClangWiki 数据根目录，默认**不会写入或修改源代码仓**。前端 Wiki 页面按仓库文档与模块文档分组显示，可逐篇导出 Markdown，也可将当前完整 Wiki 按原有层级导出为 ZIP。若工程要求 Markdown 固定随代码仓保存，可在 Wiki 页面点击“同步到代码仓”，将当前有效快照写入注册仓库的 `docs/clangwiki/`。重复同步只更新 ClangWiki 清单中的文件，不删除目录内未被 ClangWiki 管理的人工文档；若目标目录已存在但没有管理清单，系统会拒绝覆盖。

## 文档

- [平台架构与数据边界](docs/PLATFORM_ARCHITECTURE.zh-CN.md)
- [部署、离线交付与日常使用](docs/DEPLOYMENT_AND_USAGE.zh-CN.md)
- [RAG、引用与检索规范](docs/RAG_AND_RETRIEVAL.zh-CN.md)
- [文档输出章节规范](docs/DOCUMENT_OUTPUT_SPEC.zh-CN.md)
- [原始数据格式与准确性边界](docs/DATA_CONTRACT.zh-CN.md)
- [Build Agent 实现参考](ClangWiki_Build_Agent_Reference.md)

## 安全边界

- 服务固定为本机地址；没有多用户、账号或局域网服务。
- 前后端同源，不配置宽泛 CORS。
- OpenCode Agent 应只允许 `read`、`glob`、`grep`，拒绝编辑、shell 和网络工具。
- ClangWiki 仅写入自身的数据根目录；目标源码仓只读。
- 候选跨仓关系和 `POSSIBLE_CALL` 永远不会混入确定调用链。
- Embedding 运行时缺失时自动退化为“符号 + 全文 + 图谱”检索，Wiki 服务仍可使用。
