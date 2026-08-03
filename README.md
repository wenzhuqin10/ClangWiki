# ClangWiki

ClangWiki 是面向 C/C++ 代码仓的本地命令行文档生成框架。它先通过 CMake 和
Clang/LibTooling 提取确定性的代码事实，再按文档任务构造受限上下文，通过独立的
`opencode run` 调用已认证的 OpenCode/GLM-5.1，最终输出中文 Markdown Wiki。

```text
C/C++ repository
  → CMake / compile_commands.json
  → Clang static analysis
  → JSON knowledge artifacts
  → document tasks and bounded contexts
  → opencode run
  → OpenCode → GLM-5.1
  → Markdown Wiki
```

本版本**不包含 RAG、Embedding、Ollama、向量数据库、Web 服务或 OpenCode Server**。
ClangWiki 不接收、保存、读取或打印 API Key；目标设备上的 OpenCode 或企业包装器
（例如 `nga`）负责模型认证。

## 快速开始

完成目标设备的依赖安装和 OpenCode 认证后，直接运行：

```powershell
clangwiki generate `
  --repo "D:\projects\target-repository" `
  --workspace "D:\clangwiki-workspace" `
  --model "provider/glm-5.1"
```

没有安装为命令时可使用：

```powershell
python -m clangwiki generate --repo "D:\projects\target-repository"
```

详细步骤见 [部署与使用说明](docs/DEPLOYMENT_AND_USAGE.zh-CN.md)。

## 输出

```text
workspace/
├── analysis/       # Clang 与辅助分析的原始 JSON
├── knowledge/      # 模块、关系、覆盖率等知识产物
├── tasks/          # 每篇文档的上下文和任务清单
├── logs/           # 每项任务的 stdout、stderr 与错误记录
└── output/
    ├── README.md
    ├── Architecture.md
    ├── Modules/
    │   └── <source-path>/index.md   # 信道叶子与父级汇总形成同构目录树
    ├── DataStructures.md
    ├── CallFlows.md
    └── APIReference.md
```

## 文档

- [架构说明](docs/ARCHITECTURE.zh-CN.md)
- [部署与使用说明](docs/DEPLOYMENT_AND_USAGE.zh-CN.md)
- [数据格式与准确性边界](docs/DATA_CONTRACT.zh-CN.md)
- [文档输出规范](docs/DOCUMENT_OUTPUT_SPEC.zh-CN.md)
- [Build Agent 实现参考](ClangWiki_Build_Agent_Reference.md)

## 安全边界

- 默认通过 `opencode run` 启动一次性 CLI 任务，不启动 HTTP 服务。
- 文档 Agent 只读：允许 `read`、`glob`、`grep`；拒绝 `bash`、`edit`、网络工具。
- 目标仓库不会写入中间文件，所有产物均写入显式 workspace。
- Clang 确定的事实与 LLM 的语义说明分开保存，未解析调用不会写成确定调用。

## 基带信道级文档粒度

生产环境建议显式指定每个信道级叶子路径：

```powershell
clangwiki generate `
  --repo "D:\projects\target-repository" `
  --workspace "D:\clangwiki-workspace" `
  --model "provider/glm-5.1" `
  --leaf-module-path "src/phy/pdsch" `
  --leaf-module-path "src/phy/pusch"
```

ClangWiki 先生成信道级叶子文档，再逐层生成父模块、子系统、系统架构和首页。叶子路径以下的内部目录不会继续拆成独立文档。
