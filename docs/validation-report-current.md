# 当前电脑验证报告

日期：2026-07-22  
工作目录：`D:\Users\QinLianxi\Desktop\deepwiki`

## 环境

| 项目 | 结果 |
|---|---|
| CPU | AMD Ryzen 7 8845H |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU，8188 MiB |
| GPU 驱动 | 572.83 |
| Python | 3.9.13（项目虚拟环境已建立） |
| Node.js | v24.15.0 |
| 硬件虚拟化 | 已开启 |
| WSL2 | Windows 功能尚未启用；启用操作需要管理员权限 |
| 本机 C++ 编译器 | TDM-GCC g++ 可用 |
| Clang/LibTooling | 尚未安装，需在 WSL2 中验证 |

## 已通过

- Python 项目可编辑安装成功，锁定依赖安装成功。
- 自动化测试：`6 passed`。
- Python 源码编译检查通过。
- CMake/Makefile 测试仓由本机 g++ 编译并运行成功，输出 `DEEPWIKI`，退出码为 0。
- 无 Clang 环境下的降级分析成功，能提取类、函数、宏、Include、继承和候选调用。
- SQLite、FTS5、向量存储、符号检索、图扩展与 Wiki 编排测试通过。
- OpenCode Server 协议测试通过：创建会话、显式模型、仓库目录、禁用工具、结构化输出和删除会话。
- FastAPI 服务实际启动成功，根路由与 OpenAPI 文档可访问。
- 没有遗留测试 API、winget 或 npm 安装进程。

## 尚未通过及原因

| 验证项 | 状态 | 原因/下一步 |
|---|---|---|
| WSL2 Ubuntu 24.04 | 阻塞 | 当前进程无管理员权限；运行 `scripts/setup-wsl.ps1` 后重启 |
| Clang LibTooling 编译器分析 | 阻塞 | 依赖 WSL2；运行 `scripts/build-analyzer.sh` |
| Ollama 安装 | 阻塞 | winget 下载最终指向 GitHub，当前 GitHub 443 不可达 |
| BGE-M3 GPU/CPU 对比 | 阻塞 | 依赖 Ollama 和模型下载；运行 `python -m cppwiki.benchmark` |
| OpenCode Server | 已通过 | 1.18.4；`/global/health` 健康，Provider 列表可读取 |
| OpenCode → Qwen3.5-4B | 阻塞 | OpenCode 已就绪，但 Ollama 与模型尚未安装 |
| nga/OpenCode → GLM-5.1 | 目标机验收 | 企业权限仅在迁移后的电脑可用 |
| DeepWiki-Open Next.js 前端合并 | 阻塞 | GitHub 仓库无法克隆；核心后端 API 已独立完成 |

## 迁移验收顺序

1. 管理员运行 WSL2 安装脚本并完成 Ubuntu 初始化。
2. 网络允许访问依赖源后运行 WSL bootstrap、Clang 构建和模型安装脚本。
3. 依次运行 `dev-gpu`、`dev-cpu` 验证及设备对比工具。
4. 目标电脑切换 `target-cpu-glm`，核实企业 Provider/Model ID。
5. 重新生成测试仓和真实仓库的编译数据库及向量索引。
