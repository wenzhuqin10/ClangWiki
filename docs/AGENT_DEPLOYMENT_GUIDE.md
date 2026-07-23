# C++ DeepWiki 目标环境智能体部署指南

本文供另一台电脑中的智能体执行部署。执行者必须逐项记录结果，不得跳过失败步骤，
不得把 API Key 写入代码、`.env`、命令历史、日志或最终报告。

## 1. 目标与完成标准

```text
C/C++ Repository
  → compile_commands.json
  → Clang LibTooling Analyzer
  → SQLite Symbol/Relation Graph + AST Chunks
  → Ollama / BGE-M3（CPU）
  → Symbol + FTS5 + FAISS + Graph Hybrid Retrieval
  → OpenCode Server → Z.AI API / GLM-5.1
  → FastAPI Wiki/Search API
```

完成标准：

1. 测试仓以 `full` 模式完成分析。
2. BGE-M3 明确使用 CPU，Top-10 检索召回率不低于 0.9。
3. OpenCode 以 `zai/glm-5.1` 完成真实请求。
4. `scripts/validate-target.sh` 退出码为 0。
5. Wiki 规划至少两个页面，首个页面正文不少于 100 字符。
6. 配置和日志中不存在 API Key。

不在本阶段范围内：Neo4j、完整 points-to 分析、跨线程严格数据流和公网部署。

## 2. 环境基线

| 项目 | 要求 |
|---|---|
| 主机 | Windows 11，Intel Core i7-14700 或同等级 |
| GPU | 可无独显；Intel UHD 770 不参与推理 |
| 内存 | 建议 16GB 以上，最低检查线 12GB |
| 磁盘 | 至少 15GB，建议 30GB |
| Linux | WSL2 + Ubuntu 24.04 |
| Embedding | Ollama `bge-m3`，`num_gpu=0` |
| Generator | OpenCode Server → GLM-5.1 |
| 端口 | FastAPI 8000、OpenCode 4096、Ollama 11434，均绑定 127.0.0.1 |

仓库必须位于 `/home/<user>/projects/cpp-deepwiki`，禁止长期从 `/mnt/c` 或 `/mnt/d` 构建。

## 3. 账户模式

部署前由用户选一种模式：

- 个人 Z.AI API（默认）：`scripts/deploy-target.sh zai`，端点为
  `https://api.z.ai/api/paas/v4`。
- Z.AI Coding Plan：仅在已购买并获准自动化调用时执行
  `scripts/deploy-target.sh coding-plan`，端点为
  `https://api.z.ai/api/coding/paas/v4`。
- 企业 OpenCode/nga：`scripts/deploy-target.sh enterprise`，随后把 `.env` 中
  `company` 改成企业 `/provider` 返回的真实 ID。

## 4. 强制安全规则

1. API Key 只能由用户在 `opencode auth login` 交互界面中输入。
2. 智能体不得要求用户在聊天中发送 Key。
3. 不得把 Key 写入 `opencode.json`、`.env`、脚本或报告。
4. 不得输出 `~/.local/share/opencode/auth.json` 内容。
5. 私有代码发送到 Z.AI 前，必须取得用户或组织授权。
6. 不得删除用户源码；清理仅限本项目 `.cppwiki`、测试 `build` 和日志。
7. 管理员授权、付费确认、企业策略或源码外发确认必须由用户完成。

## 5. Windows 与 WSL 检查

普通 PowerShell：

```powershell
Get-ComputerInfo | Select-Object WindowsProductName,WindowsVersion,OsArchitecture
Get-CimInstance Win32_Processor |
  Select-Object Name,VirtualizationFirmwareEnabled
wsl --status
wsl -l -v
```

要求 `VirtualizationFirmwareEnabled=True`，Ubuntu 的 `VERSION` 为 `2`。

若未安装 WSL，由用户以管理员 PowerShell 执行：

```powershell
Set-Location "D:\Deploy\deepwiki"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup-wsl.ps1
```

如要求重启，智能体应记录状态并停止；重启后继续，不得提前声明完成。

## 6. 将源码放入 WSL

Ubuntu 首次初始化后执行：

```bash
sudo apt-get update
sudo apt-get install -y rsync
mkdir -p ~/projects/cpp-deepwiki
rsync -a \
  --exclude='.git' --exclude='.venv' --exclude='.cppwiki*' \
  --exclude='build' --exclude='logs' \
  /mnt/d/Deploy/deepwiki/ \
  ~/projects/cpp-deepwiki/
cd ~/projects/cpp-deepwiki
chmod +x scripts/*.sh
pwd
test "${PWD#/mnt/}" = "$PWD"
```

上面的 `D:\Deploy\deepwiki` 是建议的中转位置；如果目标机路径不同，智能体必须同时
修改 PowerShell 和 `/mnt/d/...` 来源路径。最后一条必须成功。不得复制开发机
`.venv`、`build` 或向量索引。

## 7. 基础部署

个人账户默认执行：

```bash
cd ~/projects/cpp-deepwiki
scripts/deploy-target.sh zai
```

脚本将安装编译工具、Python/FAISS、OpenCode、Ollama/BGE-M3，构建
`bin/cpp-analyzer`，并写入权限为 600 的生产 `.env`。不会安装本地生成模型。

企业要求内部 npm 镜像时，先设置：

```bash
export CPPWIKI_NPM_REGISTRY='https://<approved-internal-registry>'
```

基础检查：

```bash
scripts/preflight-target.sh
```

服务未启动可出现 WARN，但不得有其他 FAIL。

## 8. 人工认证检查点

必须由用户在终端完成：

```bash
cd ~/projects/cpp-deepwiki
opencode auth login
```

个人自定义 Provider：选择 `Other`，Provider ID 输入精确值 `zai`，仅在认证输入框
粘贴 Key。认证后只检查元数据：

```bash
opencode auth list
opencode models zai
```

必须看到 `zai/glm-5.1`。模型冒烟测试：

```bash
opencode run -m zai/glm-5.1 "只回复：GLM_5_1_READY"
```

输出必须包含 `GLM_5_1_READY`，且无 401、403、404、429 或模型不存在错误。

## 9. 启动服务

终端 A：

```bash
cd ~/projects/cpp-deepwiki
scripts/run-production.sh
```

终端 B：

```bash
curl -fsS http://127.0.0.1:11434/api/version | jq
curl -fsS http://127.0.0.1:4096/global/health | jq
curl -fsS http://127.0.0.1:4096/provider | jq '.connected'
curl -fsS http://127.0.0.1:8000/health | jq
```

要求 OpenCode `healthy=true`、`connected` 包含 `zai`，框架的 Embedding 与
Generator 均健康。Windows 浏览器访问 `http://127.0.0.1:8000/docs`。

## 10. 标准验收

```bash
cd ~/projects/cpp-deepwiki
scripts/validate-target.sh | tee logs/target-validation.log
```

该脚本执行环境检查、测试仓构建、离线测试、Clang full 分析、BGE-M3 CPU 检索、
GLM Wiki 规划与首个页面生成。通过条件：

```text
pytest: 全部通过
analysis.mode: full
recall_at_10: >= 0.9
generation.passed: true
进程退出码: 0
```

确认 CPU 模式：

```bash
ollama ps
grep '^CPPWIKI_EMBED_NUM_GPU=0$' .env
```

不得把 UHD 770 当作已验证的通用 GPU 推理设备。

## 11. 分析真实仓库

用户先确认源码允许外发。CMake 工程：

```bash
cd /path/to/repository
cmake -S . -B build -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build
```

Makefile 工程：

```bash
cd /path/to/repository
bear -- make -j8
```

提交分析：

```bash
curl -fsS -X POST http://127.0.0.1:8000/repositories/analyze \
  -H 'Content-Type: application/json' \
  -d '{"path":"/path/to/repository","compile_database":"/path/to/repository/build"}' \
  | tee /tmp/cppwiki-analysis.json | jq
jq '.mode,.confidence,.errors' /tmp/cppwiki-analysis.json
```

若 `mode` 不是 `full`，不得声称得到编译器级准确结果，应先修复编译数据库。

检索与 Wiki 规划：

```bash
REPOSITORY_ID='<returned-id>'
curl -fsS -X POST \
  "http://127.0.0.1:8000/repositories/$REPOSITORY_ID/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"程序入口和核心初始化调用流程","top_k":10,"expand_graph":true}' | jq

curl -fsS -X POST \
  "http://127.0.0.1:8000/repositories/$REPOSITORY_ID/wiki/plan" \
  -H 'Content-Type: application/json' \
  -d '{"language":"zh-CN","page_count":6}' | jq
```

## 12. 停止、清理与回滚

日志：`logs/ollama.log`、`logs/opencode.log`、`logs/target-validation.log`。

FastAPI 用 `Ctrl+C` 停止；后台服务执行：

```bash
scripts/stop-services.sh
```

更换 Embedding、仓库路径或主要编译选项后重新建索引。仅在确认当前目录精确为项目
根目录后执行：

```bash
cd ~/projects/cpp-deepwiki
scripts/stop-services.sh
rm -rf -- .cppwiki
```

禁止对 `~`、`/` 或工作区上级目录递归删除。

部署失败回滚：

```bash
cd ~/projects/cpp-deepwiki
scripts/stop-services.sh
opencode auth logout zai
mv .env ".env.failed.$(date +%Y%m%d-%H%M%S)"
```

保留源码、测试报告和日志，不得删除用户 C/C++ 仓库。

## 13. 常见故障

- WSL：确认 BIOS 虚拟化、执行 `wsl --update`，`wsl -l -v` 必须为 VERSION 2。
- npm：设置批准的 `CPPWIKI_NPM_REGISTRY` 后重新运行 bootstrap。
- 找不到模型：检查 `opencode debug config`，配置和认证 Provider ID 必须同为 `zai`。
- 401/403：重新认证并确认账户已开通 GLM-5.1；不得打印 Key。
- 404：模型 ID 必须是 `glm-5.1`；通用账户和 Coding Plan 端点不可混用。
- 429：暂停真实生成，减少页面和并发，检查额度及 Token 消耗。
- BGE-M3 慢：保持 batch size 4，排除 third-party/vendor/build/generated 目录。
- partial/fallback：检查 `compile_commands.json`、include path、宏和 C++ 标准参数。
- 端口占用：先用 `ss -ltnp | grep -E ':(8000|4096|11434)\b'` 查明归属，
  不得盲目终止未知进程。

## 14. 智能体最终报告模板

```text
部署模式：zai / coding-plan / enterprise
Windows 与 WSL 版本：
CPU / 内存 / 可用磁盘：
Clang / OpenCode / Ollama 版本：
Embedding：bge-m3，CPU确认方式：
Generator Provider/Model：
测试数量与结果：
analysis.mode：
recall_at_10：
generation.passed：
API 健康状态：
未完成项与阻塞原因：
日志路径：
```

报告不得包含 Key、认证文件内容或完整私有源码。

## 15. 权威接口依据

- OpenCode Provider：<https://opencode.ai/docs/providers>
- OpenCode Server：<https://opencode.ai/docs/server/>
- Z.AI HTTP API：<https://docs.z.ai/guides/develop/http/introduction>
- GLM-5.1：<https://docs.z.ai/guides/llm/glm-5.1>
- Ollama BGE-M3：<https://ollama.com/library/bge-m3>
- Clang LibTooling：<https://clang.llvm.org/docs/LibTooling.html>
