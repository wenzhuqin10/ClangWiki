# C++ DeepWiki

面向 C/C++ 代码仓的“编译器静态分析 + 混合 RAG + OpenCode/GLM”文档框架。

当前版本以实际目标环境为默认配置：

```text
Windows 11 + WSL2 Ubuntu 24.04
Clang/LibTooling
SQLite + FTS5 + FAISS
Ollama/BGE-M3（CPU）
OpenCode Server → Z.AI API → GLM-5.1
```

本机开发只运行离线测试和模拟网关，不要求安装完整目标环境。详细部署操作由目标环境中的
智能体按照 [目标环境智能体部署指南](docs/AGENT_DEPLOYMENT_GUIDE.md) 执行。

## 核心流程

```text
compile_commands.json
  → Clang LibTooling / 显式标记的降级分析
  → SQLite 符号图 + AST 代码块
  → BGE-M3
  → 精确符号 + FTS5 + FAISS + 图扩展
  → OpenCode Server
  → GLM-5.1
```

关系分为确定关系 `CALLS`、`INCLUDES`、`INHERITS`、`REFERENCES` 和低置信度
`POSSIBLE_CALL`。生成提示词禁止把候选边描述成确定调用。

## 配置

| 文件 | 用途 |
|---|---|
| `opencode.json` | 个人 Z.AI 通用 API、`zai/glm-5.1` |
| `config/opencode/zai-coding-plan.json` | Z.AI Coding Plan |
| `config/opencode/local-ollama.json` | 本地模拟生成 |
| `config/profiles/production-zai-cpu.env` | 目标个人账户配置 |
| `config/profiles/target-cpu-glm.env` | 企业 Provider 配置 |
| `config/profiles/dev-gpu.env` | 可选本地 GPU 模拟 |

API Key 只能通过 `opencode auth login` 保存到 OpenCode，不能写入上述文件。

## 目标环境快速部署

将仓库复制到 WSL 的 `~/projects/cpp-deepwiki` 后：

```bash
cd ~/projects/cpp-deepwiki
chmod +x scripts/*.sh
scripts/deploy-target.sh zai
```

用户完成认证：

```bash
opencode auth login
opencode auth list
opencode models zai
opencode run -m zai/glm-5.1 "只回复：GLM_5_1_READY"
```

启动和验收：

```bash
scripts/run-production.sh
# 另一个终端
scripts/validate-target.sh
```

完整步骤、安全检查、故障排查和回滚见
[AGENT_DEPLOYMENT_GUIDE.md](docs/AGENT_DEPLOYMENT_GUIDE.md)。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/repositories/analyze` | 分析、AST 切块并建立向量索引 |
| `GET` | `/repositories/{id}/analysis` | 查询分析模式、错误和统计 |
| `POST` | `/repositories/{id}/search` | 混合检索 |
| `POST` | `/repositories/{id}/wiki/plan` | 生成结构化 Wiki 规划 |
| `WS` | `/repositories/{id}/wiki/pages/{page_id}` | 生成 Markdown 页面 |
| `GET` | `/repositories/{id}/health` | 检查分析器、数据库、Embedding 与 Generator |

分析结果的 `mode` 必须显示给用户：

- `full`：编译数据库和 LibTooling 均成功。
- `partial`：编译环境不完整，结果经过组合补充。
- `fallback`：仅词法降级，不代表编译器级准确。

## 本地开发验证

本地不调用真实 Embedding 或 GLM：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q backend
```

模拟测试覆盖分析、SQLite/FTS5、向量检索、图扩展、OpenCode HTTP 协议、Wiki 规划
和 FastAPI 接口。

## 已知边界

- 函数指针、虚调用和宏展开后的调用以候选关系表示。
- 第一版不实现完整 points-to 和跨线程数据流分析。
- LibTooling 只分析编译数据库覆盖的翻译单元，其他文件由词法层补充。
- 无 FAISS 时会降级为余弦暴力检索，但目标部署必须安装 FAISS。

