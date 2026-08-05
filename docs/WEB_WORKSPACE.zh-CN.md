# ClangWiki 本地可视化工作区

ClangWiki 现在提供一个可选的本地 Web 工作区，用于查看分析结果、浏览层级 Markdown、查看 Clang 关系图和启动文档生成任务。它是 CLI 的可视化入口，不改变原有的 `clangwiki generate` 和 `opencode run` 生产链路。

## 架构

```text
浏览器
  │  HTTP / SSE（仅本机）
  ▼
ClangWiki Local Web Server
  ├── REST API：状态、模块树、文档、关系、任务
  ├── SSE：生成任务进度
  ├── 静态前端：clangwiki/web
  └── Job Manager：单任务串行、取消标记、错误记录
        │
        ▼
GenerationPipeline
  ├── CMake / compile_commands.json
  ├── Clang Analyzer
  ├── Hierarchical Knowledge Builder
  ├── Bottom-up Document Planner
  └── OpenCodeRunner
        │
        ▼
opencode run → 已认证的 OpenCode → GLM-5.1
```

本地 Web 服务不会：

- 接收、保存或读取 API Key；
- 启动 OpenCode Server；
- 引入 RAG、Embedding、Ollama 或向量数据库；
- 修改目标代码仓库。

OpenCode 的认证仍由目标设备上的 OpenCode 管理。Web 服务只使用 `opencode run` 子进程。

## 启动

在已安装 ClangWiki 的 Python 环境中执行：

```powershell
clangwiki serve `
  --repo "D:\projects\target-repository" `
  --workspace "D:\clangwiki-workspace" `
  --model "provider/glm-5.1" `
  --analyzer-executable "D:\tools\clangwiki-analyzer.exe" `
  --channel-module-path "src/phy/pdsch" `
  --channel-module-path "src/phy/pusch" `
  --host 127.0.0.1 `
  --port 8081
```

然后打开 `http://127.0.0.1:8081/`。

模型 ID 必须使用目标设备执行 `opencode models` 显示的真实值。Web 页面不提供 API Key 输入框，这是有意的安全边界。

Linux/WSL2 使用同一套命令，将 PowerShell 的反引号改为 Bash 换行符即可。

## 页面能力

- **Overview**：显示仓库路径、分析模式、模型、模块数量、叶子数量、关系数量和文档数量。
- **Documents**：按输出目录浏览 Markdown，支持简单渲染和路径过滤。
- **Relations**：将 `knowledge/relations.json` 中的关系绘制为可视化图，区分确定事实和候选关系。
- **Generation jobs**：启动一轮生成、查看实时进度、任务状态和输出结果。

任务按已有的自底向上顺序运行：信道下一层叶子 → 信道汇总 → 上层模块汇总 → 架构文档 → README。

## API

服务仅用于本机开发和生产设备上的受控工作区：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/status` | 服务、仓库、模型和分析状态 |
| GET | `/api/tree` | 模块树和模块元数据 |
| GET | `/api/relations` | Clang 关系事实 |
| GET | `/api/documents` | Markdown 文件索引 |
| GET | `/api/document?path=...` | 读取 output 内的一篇 Markdown |
| GET | `/api/jobs` | 任务历史 |
| GET | `/api/jobs/{id}/events` | SSE 实时进度流 |
| POST | `/api/generate` | 启动生成任务 |
| POST | `/api/jobs/{id}/cancel` | 请求取消正在运行的任务 |

默认只绑定 `127.0.0.1`。如果必须让同一内网的其他设备访问，应由管理员配置反向代理、身份认证和 TLS，不建议直接把服务绑定到 `0.0.0.0`。

## 与 seCall 前端的关系

本实现参考 seCall 的“单一端口提供 API 与 Web UI、SSE 推送任务状态、左侧导航 + 内容工作区”思路，但使用独立实现的 Python 标准库服务和静态前端。seCall 是 AGPL-3.0 项目；ClangWiki 没有复制其代码，后续若直接复用其源代码或组件，需要遵守相应许可证。

## 生产部署建议

1. 在目标设备完成 Python、CMake、LLVM/Clang 和 OpenCode 的安装。
2. 先用 `opencode run --model ...` 验证现有认证，再启动 Web 服务。
3. 使用明确的 `--channel-module-path` 配置信道边界；例如 `src/phy/pdsch` 的直接子目录作为叶子文档单元。
4. 为每个项目使用独立 workspace，避免任务日志和分析产物互相覆盖。
5. 将 Web 服务绑定到 localhost，必要时由企业网关提供访问控制。
6. 生产生成仍可使用 `clangwiki generate`；Web UI 只是同一 Pipeline 的可视化入口。
