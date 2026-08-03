# 部署与使用说明

本说明面向另一台生产设备。此工程不要求在当前开发机运行；请在目标设备按以下步骤部署。

## 1. 前置条件

| 组件 | 用途 | 必需 |
|---|---|---:|
| Python 3.10+ | 运行 ClangWiki CLI | 是 |
| CMake | 生成 `compile_commands.json` | 是 |
| LLVM/Clang 开发包 | 构建 `clangwiki-analyzer` | 是，正式 `full` 分析 |
| OpenCode 或兼容企业启动器 | 通过 `opencode run` 调用模型 | 是 |
| 已认证的 GLM-5.1 Provider | OpenCode 的模型访问权 | 是 |

不需要：API Key 文件、Ollama、Embedding、向量数据库、OpenCode Server、WSL2。WSL2/Linux 只是
部分 C/C++ 项目的推荐构建环境，Windows 原生 CMake/LLVM 同样可用。

## 2. 安装 ClangWiki

```powershell
git clone https://github.com/wenzhuqin10/ClangWiki.git
Set-Location ClangWiki
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Linux/WSL2：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## 3. 构建 Clang 分析器

Windows 需要已安装 LLVM 的开发组件及 CMake。若 `find_package(Clang)` 不能定位 LLVM，按本机
LLVM 安装路径设置 `CMAKE_PREFIX_PATH` 后重试。

```powershell
.\scripts\build-analyzer.ps1
```

Linux/WSL2：

```bash
sudo apt install cmake clang llvm-dev libclang-dev
chmod +x scripts/build-analyzer.sh
./scripts/build-analyzer.sh
```

然后在生成命令中传入生成的 `bin/clangwiki-analyzer[.exe]`。未提供时程序仍会运行，
但会在 `analysis/diagnostics.json` 中标记为 `partial`，不具备完整编译器语义保证。

## 4. 配置 OpenCode 与 GLM-5.1

ClangWiki 不配置 API Key。请按照组织规定，在 OpenCode 中完成认证并确认真实模型 ID：

```powershell
opencode models
opencode run --model "provider/glm-5.1" "只回复 GLM_READY"
```

`provider/glm-5.1` 只是示例，必须替换为 `opencode models` 显示的准确名称。若组织只能通过
`nga` 调用 OpenCode 且它兼容标准 CLI 参数，后续命令使用 `--opencode-executable nga`。

可选：安装只读文档 Agent。推荐使用 OpenCode 自带的 `opencode agent create`，授予 `read,glob,grep`
并拒绝 `bash,edit,webfetch,websearch`。也可以将仓库中的 [Agent 模板](../agents/clangwiki-doc.md)
复制到 OpenCode 文档所示的全局或项目 Agent 目录，并确认：

```powershell
opencode agent list
```

若尚未安装该 Agent，生成时传递 `--agent ""`，ClangWiki 将不附加 `--agent` 参数。

## 5. 一条命令生成 Wiki

```powershell
clangwiki generate `
  --repo "D:\projects\target-repository" `
  --workspace "D:\clangwiki-workspace" `
  --model "provider/glm-5.1" `
  --analyzer-executable "D:\projects\ClangWiki\bin\clangwiki-analyzer.exe" `
  --channel-module-path "src/phy/pdsch" `
  --channel-module-path "src/phy/pusch" `
  --channel-module-path "src/phy/pdcch" `
  --channel-module-path "src/phy/pucch"
```

程序只运行 CMake 的**配置**步骤以生成编译数据库，不执行 `cmake --build`，不会修改目标仓的
`CMakeLists.txt` 或源代码。默认拒绝覆盖已有 Markdown；确认重生成时显式加入 `--overwrite`。

常用选项：

```text
--only architecture            只生成系统架构文档
--only module                  只生成各模块文档
--channel-module-path <path>   指定信道根目录；其直接子目录成为叶子
--leaf-module-path <path>      高级覆盖：直接指定叶子；不能与上一参数并用
--skip-cmake                   复用 workspace/build/compile_commands.json
--skip-analysis                复用 workspace/analysis/*.json
--opencode-executable nga      使用企业兼容启动器
--timeout-seconds 1200         放宽单篇文档模型调用超时
```

### 5.1 信道下一层叶子模块

`--channel-module-path` 使用目标仓根目录下的相对目录。指定 `src/phy/pdsch` 后，`pdsch/encoder`、`pdsch/modulation`、`pdsch/mapping` 等直接子目录分别成为叶子。叶子目录内部更深的源码不继续拆分。

框架先生成信道内部叶子文档，再生成 PDSCH/PUSCH 信道汇总，然后生成 `src/phy`、`src` 等父级汇总，最后生成仓库架构和首页。直接位于 `pdsch` 根目录的源码作为 PDSCH 汇总的直接证据。

如果不提供边界参数，框架会尝试识别常见物理信道名称，并使用其直接子目录作为叶子；若信道没有子目录则退回信道自身，若没有识别到信道则退回第一层目录。生产仓建议显式配置。

目录结构不规则时可以使用 `--leaf-module-path` 直接指定实际叶子路径。两类参数不能同时使用，路径不存在或信道下没有源码子目录时会明确报错。

## 6. 认证与权限

| 主体 | 权限/职责 |
|---|---|
| ClangWiki | 读取目标仓，写入 workspace，启动已认证 CLI。 |
| OpenCode | 管理 Provider、凭据和模型请求。 |
| 文档 Agent | 仅读取已批准的仓与上下文；不得编辑、执行 shell 或联网。 |
| GLM-5.1 | 根据上下文生成 Markdown。 |

无需给 ClangWiki 任何 API、HTTP 端口或密钥访问权限。若企业策略禁止子进程使用 OpenCode CLI，
则需要管理员明确授权该自动化方式；不要尝试复制 OpenCode 的认证文件或绕过该限制。

## 7. 故障定位

- `CMakeError`：检查目标仓是否可由 CMake 配置，以及所需工具链/依赖是否已安装。
- `CompilationDatabaseError`：检查 build 目录是否生成有效 `compile_commands.json`。
- `partial` 模式：构建并传入 `clangwiki-analyzer`，查看 `analysis/diagnostics.json`。
- `OpenCodeError`：确认 `opencode models`、模型 ID、企业启动器兼容性及 Agent 是否已安装；查看
  `workspace/logs/opencode/*.stderr.txt`。
- `MarkdownValidationError`：保留原始 stdout/stderr，修正模型或 Prompt 后只重跑该 workspace。
