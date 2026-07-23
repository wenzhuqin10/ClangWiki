# 固定版本与来源

第一版验证基线：

| 组件 | 版本/要求 |
|---|---|
| Ubuntu | 24.04 LTS |
| Python | 3.9+；目标环境建议系统 Python 3.12 |
| FastAPI | 0.115.6 |
| Pydantic | 2.10.4 |
| HTTPX | 0.28.1 |
| pytest | 8.3.4 |
| Ollama | 安装时记录 `ollama --version`；当前网络未完成下载 |
| Embedding | `bge-m3`（Ollama，567M，8K） |
| 开发生成模型 | `qwen3.5:4b` |
| OpenCode | 1.18.4（当前 Windows 已验证） |
| Clang/LLVM | Ubuntu 24.04 仓库配套版本，Clang 与 libclang 必须一致 |

外部参考：

- DeepWiki-Open：<https://github.com/AsyncFuncAI/deepwiki-open>
- OpenCode Server：<https://opencode.ai/docs/server/>
- Clang LibTooling：<https://clang.llvm.org/docs/LibTooling.html>

本仓创建时 GitHub 443 连接不可用，未能拉取 DeepWiki-Open 源码。恢复网络后应将
其 Next.js 前端作为独立提交接入本项目 API，避免把本地核心实现误记为上游代码。
