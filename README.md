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

框架先产生叶子文档，再汇聚为 PDSCH、PHY 和仓库级文档。叶子文档严格采用面向基带开发的章节规范：定位与边界、领域约束、接口、任务流程、状态与时序、核心实现、配置、调试、开发导航、证据限制。

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
