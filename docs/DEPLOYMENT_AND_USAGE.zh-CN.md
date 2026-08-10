# ClangWiki Windows 离线部署与使用说明

本文面向**另一台 Windows 生产设备**。部署完成后，生产设备可以在无 Node.js、无 Docker、无 Ollama、无外部向量服务的情况下运行 ClangWiki；模型仍通过该设备已经认证的 `opencode run` 调用。

## 1. 部署边界

| 项目 | 生产机要求 | 说明 |
|---|---:|---|
| Python 3.12 x64 | 必须 | 推荐固定到 3.12；3.13 仅做兼容性验证。 |
| CMake | 必须 | 为目标仓生成 `compile_commands.json`。 |
| LLVM/Clang x64 | 必须 | 运行 `clangwiki-analyzer.exe` 与 `libclang.dll`。 |
| OpenCode/企业兼容启动器 | 必须 | 已通过企业流程认证的 CLI。 |
| GLM-5.1 Provider | 必须 | 仅需在 OpenCode 中可用。 |
| BGE-M3 ONNX + USearch | 推荐 | 本地 CPU 向量检索；缺失时自动降级。 |
| Node.js | 不需要 | React 已在交付前构建为静态资源。 |
| API Key | 不需要且禁止输入 | 凭据由 OpenCode 管理。 |

服务只绑定 `127.0.0.1`；不支持局域网访问、多用户账号或在线编辑源码。

## 2. 建议目录

```text
D:\ClangWiki\                    # 程序安装目录
├── .venv\
├── clangwiki\
├── bin\
│   ├── clangwiki-analyzer.exe
│   └── libclang.dll
├── offline\
│   ├── wheels\                   # 管理员准备的离线 wheel
│   └── SHA256SUMS.txt
└── scripts\

D:\clangwiki-data\               # 可备份的数据根目录
├── clangwiki.db
├── repositories\
├── collections\
├── models\
└── backups\
```

目标代码仓可以位于任意已批准目录。ClangWiki 只保存其规范化路径，**不会复制、移动、删除或写入源码**。

## 3. 首次安装

管理员应先安装 Python 3.12 x64、CMake 和 LLVM x64。确认命令可用：

```powershell
py -3.12 --version
cmake --version
clang --version
opencode --version
opencode models
```

从交付介质复制程序包到 `D:\ClangWiki` 后，在 PowerShell 执行：

```powershell
Set-Location D:\ClangWiki
.\scripts\Install-ClangWiki.ps1 `
  -InstallRoot "D:\ClangWiki" `
  -WheelRoot "D:\ClangWiki\offline\wheels"
```

离线交付包中应含有 `fastapi`、`pydantic`、`uvicorn`、`httpx`、ClangWiki 及其依赖 wheel。默认 BGE-M3 向量检索还需包含与 Python 3.12 x64 匹配的 `numpy`、`usearch`、`onnxruntime`、`transformers` wheel，以及完整模型目录 `models/bge-m3/`（含 `onnx/model.onnx` 和 `onnx/model.onnx_data`）。运行时不下载模型。

## 4. Clang 分析器

交付中应直接包含：

```text
D:\ClangWiki\bin\clangwiki-analyzer.exe
D:\ClangWiki\bin\libclang.dll
```

使用本仓库构建时：

```powershell
Set-Location D:\ClangWiki
.\scripts\build-analyzer.ps1 -LLVMRoot "C:\Program Files\LLVM"
```

分析器采用 `libclang` C API；不要求 LibTooling 静态库、`LLVMConfig.cmake` 或 `ClangConfig.cmake`。如果分析器不可用，系统会使用明确标识为 `partial` 的词法辅助分析；图谱和文档会保留该证据等级，不能当作编译器确认事实。

## 5. OpenCode 和 GLM-5.1

ClangWiki 不保存任何凭据。请按组织流程先在生产机完成认证，并测试模型标识：

```powershell
opencode models
opencode run --model "provider/glm-5.1" "只回复 GLM_READY"
```

`provider/glm-5.1` 只是示例，必须以本机 `opencode models` 输出为准。企业使用兼容启动器时可将仓库配置中的 `opencode_executable` 设置为例如 `nga`，但必须兼容 `run --model --file` 参数。

建议使用只读 `clangwiki-doc` Agent：

```text
read      allow
glob      allow
grep      allow
edit      deny
bash      deny
webfetch  deny
websearch deny
```

OpenCode 只返回模型文本；Markdown 写入、格式校验和任务日志由 ClangWiki 完成。

## 6. 启动本地工作台

```powershell
D:\ClangWiki\scripts\Start-ClangWiki.ps1 `
  -InstallRoot "D:\ClangWiki" `
  -DataRoot "D:\clangwiki-data" `
  -Port 8082
```

浏览器打开：`http://127.0.0.1:8082/`。

可直接使用命令：

```powershell
& "D:\ClangWiki\.venv\Scripts\clangwiki.exe" `
  --data-root "D:\clangwiki-data" serve --port 8082
```

不要把服务绑定到公网或局域网地址。本版本不设计用户认证和远程访问控制。

## 7. 注册、生成与索引

### 7.1 注册基带信道仓

```powershell
clangwiki --data-root "D:\clangwiki-data" repo add "D:\projects\pdsch-channel" `
  --name "PDSCH 信道仓" `
  --model "provider/glm-5.1" `
  --analyzer-executable "D:\ClangWiki\bin\clangwiki-analyzer.exe" `
  --channel-module-path "src/phy/pdsch"
```

`--channel-module-path "src/phy/pdsch"` 的语义是：将 PDSCH 的**下一层**源码目录（例如 `encoder`、`mapping`、`dmrs`）作为叶子模块；框架先生成叶子文档，再汇聚 PDSCH、PHY 和仓库 Wiki。

### 7.2 生成仓库 Wiki

```powershell
clangwiki --data-root "D:\clangwiki-data" repo list
clangwiki --data-root "D:\clangwiki-data" generate --repo-id "repo-xxxxxxxxxxxxxxxx"
```

同一仓库的写入型任务会串行执行。每次成功生成都会形成新的不可变快照，数据库中的 `active_run_id` 指向当前版本；可在工作台“运行历史”中切换成功快照。

### 7.3 逻辑知识空间

```powershell
clangwiki --data-root "D:\clangwiki-data" collection create "基带知识空间" `
  --repo-id "repo-mac" --repo-id "repo-phy" --repo-id "repo-common"
clangwiki --data-root "D:\clangwiki-data" collection list
```

知识空间不会合并代码，而是建立成员仓的集合级关系、Wiki 和索引。候选跨仓关系需要工程师在图谱界面确认后才能作为确定关系使用。

### 7.4 检索和问答

```powershell
clangwiki --data-root "D:\clangwiki-data" index --repo-id "repo-phy"
clangwiki --data-root "D:\clangwiki-data" search --repo-id "repo-phy" "pdsch_encode"
clangwiki --data-root "D:\clangwiki-data" ask --repo-id "repo-phy" "PDSCH 编码入口在哪里？"
```

`ask` 每轮都会重新做符号、全文、可用向量和图关系检索，并将证据编号写入 `context.md`。模型回答必须使用 `[W1]`、`[C2]`、`[G3]`、`[M4]` 一类引用；无效引用经一次修复仍失败时，系统不会展示未经校验的回答。

## 8. 增量与备份

运行记录保存 Git 提交、源码哈希、编译数据库哈希、模块边界配置哈希、Schema 版本和 Embedding 配置档：

- 代码未变化时直接复用当前快照；
- 叶子模块变化时重生成该叶子及父级汇聚文档；
- 头文件变化会沿包含关系扩大影响范围；
- CMake、编译数据库或模块边界变化时执行完整运行；
- Embedding 配置变化时只重建索引；
- 集合成员或当前快照变化时只重建集合关系与集合文档。

备份数据根目录：

```powershell
.\scripts\Backup-ClangWiki.ps1 -DataRoot "D:\clangwiki-data" -Destination "E:\backup"
```

恢复时先停止服务，再解压同一版本的数据根目录；不要把备份中的数据库与不兼容程序版本混用。

## 9. 故障定位

| 现象 | 检查顺序 |
|---|---|
| CMake 配置失败 | 目标仓构建依赖、工具链、`CMakeLists.txt`、生成日志。 |
| 没有 `compile_commands.json` | 确认 CMake 配置成功且导出了编译数据库。 |
| 仅 partial 分析 | 检查 `clangwiki-analyzer.exe`、`libclang.dll`、LLVM 版本和 `analysis/diagnostics.json`。 |
| OpenCode 调用失败 | 运行 `opencode models` 和最小 `opencode run`；检查运行快照中的 `logs/opencode`。 |
| 向量检索不可用 | 检查可选 wheel 与模型缓存；系统会自动继续符号、全文和图谱检索。 |
| RAG 回答校验失败 | 查看本轮保存的证据与 OpenCode stdout；确认模型遵守引用契约。 |

## 10. 兼容命令

为兼容旧脚本，以下单仓命令保留一个版本周期：

```powershell
clangwiki generate --repo "D:\projects\target" --workspace "D:\workspace" --model "provider/glm-5.1"
```

它不会自动注册到多仓平台。新生产环境应优先使用 `repo add`、`generate --repo-id` 和 `serve --data-root`。
