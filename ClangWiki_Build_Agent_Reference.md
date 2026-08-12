# ClangWiki Build Agent 实现参考文档

## 1. 文档目的

本文档用于指导 Build Agent 按照既定技术路线完成 **ClangWiki** 的本地实现与集成。

ClangWiki 的目标是：

> 面向 C/C++ 代码仓，利用 CMake 与 Clang 获取可靠的编译器级结构信息，经由知识组织、文档规划和上下文构建后，通过 `opencode run` 调用 OpenCode Agent 与 GLM-5.1，自动生成结构化 Markdown 技术文档。

本项目第一版不采用 Embedding、向量数据库或 RAG 作为核心组件。

第一版优先保证：

- 编译数据库能够生成；
- Clang 静态分析能够执行；
- 结构化知识能够保存；
- 文档任务能够规划；
- 上下文能够按任务构建；
- `opencode run` 能够稳定调用；
- Markdown 文档能够落盘；
- 整个流程可重复、可诊断、可扩展。

---

## 2. 系统定位

ClangWiki 不是新的通用 Agent，也不负责重新实现模型调用能力。

其系统定位是：

> 构建在 OpenCode Agent 之上的、面向 C/C++ 代码仓逆向文档生成的领域应用框架。

整体分层如下：

```text
Domain Application Layer
└── ClangWiki
    ├── Build Environment Manager
    ├── Compiler Analysis
    ├── Knowledge Base
    ├── Document Planner
    ├── Context Builder
    ├── OpenCode Runner
    └── Markdown Output Manager

Agent Layer
└── OpenCode

LLM Layer
└── GLM-5.1

Tool Layer
├── CMake
├── LLVM / Clang
├── File System
├── Git
└── Python / Shell
```

职责边界：

```text
ClangWiki：组织、分析、规划、构建上下文、调用 Agent、管理输出
OpenCode：执行 Agent 任务、读取文件、调用模型
GLM-5.1：理解代码语义、总结、推理、撰写文档
Clang：提供语法和语义层面的确定性结构信息
CMake：恢复项目真实构建环境并生成编译数据库
```

---

## 3. 总体技术路线

```text
C/C++ Repository
├── CMakeLists.txt
├── Source Files
└── Header Files
        │
        ▼
Build Environment Manager
├── Detect CMake Project
├── Run CMake Configure
├── Generate compile_commands.json
└── Validate Compilation Database
        │
        ▼
Clang Compiler Analysis
├── Parse Translation Units
├── Extract Symbols
├── Extract Function Calls
├── Extract Include Relations
├── Extract Types and Records
└── Extract Global Variables
        │
        ▼
Knowledge Base
├── Symbol Table
├── Function Table
├── Type Table
├── Call Graph
├── Include Graph
├── Module Map
└── Source Locations
        │
        ▼
Document Planner
├── Plan Architecture Document
├── Plan Module Documents
├── Plan Data Structure Document
└── Plan API Reference
        │
        ▼
Context Builder
├── Select Relevant Symbols
├── Select Relevant Relations
├── Select Source Snippets
├── Control Context Size
└── Generate Task Context
        │
        ▼
opencode run
        │
        ▼
OpenCode Agent
        │
        ▼
GLM-5.1
        │
        ▼
Markdown Validator
        │
        ▼
Wiki Output
```

---

## 4. 第一版范围

### 4.1 必须实现

1. 接收一个本地 C/C++ 代码仓路径；
2. 检测根目录或指定目录中的 `CMakeLists.txt`；
3. 调用 CMake 生成 `compile_commands.json`；
4. 验证编译数据库是否有效；
5. 调用 Clang 分析器处理编译数据库中的源码文件；
6. 输出结构化 JSON 中间结果；
7. 根据文件目录、目标和符号关系划分模块；
8. 生成文档任务清单；
9. 为每个任务生成独立上下文文件；
10. 调用 `opencode run`；
11. 捕获标准输出；
12. 将标准输出保存为 Markdown；
13. 校验文档是否为空、是否包含明显错误输出；
14. 记录每个阶段的日志和错误。

### 4.2 第一版不实现

- Embedding；
- 向量数据库；
- 语义检索服务；
- 代码问答；
- Web 前端；
- 分布式任务调度；
- 多仓库联合分析；
- 实时增量索引；
- 自动修复源代码；
- 自动修改构建系统；
- 复杂多 Agent 协作。

---

## 5. 推荐目录结构

```text
clangwiki/
├── README.md
├── pyproject.toml
├── config.example.yaml
├── clangwiki.py
│
├── clangwiki/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── logging.py
│   │
│   ├── build/
│   │   ├── detector.py
│   │   ├── cmake_manager.py
│   │   └── compilation_database.py
│   │
│   ├── analyzer/
│   │   ├── runner.py
│   │   ├── schema.py
│   │   └── clang_analyzer.exe
│   │
│   ├── knowledge/
│   │   ├── builder.py
│   │   ├── repository.py
│   │   └── schema.py
│   │
│   ├── planner/
│   │   └── document_planner.py
│   │
│   ├── context/
│   │   ├── context_builder.py
│   │   ├── selector.py
│   │   └── renderer.py
│   │
│   ├── opencode/
│   │   ├── runner.py
│   │   └── result_parser.py
│   │
│   ├── output/
│   │   ├── markdown_validator.py
│   │   └── output_manager.py
│   │
│   └── pipeline/
│       └── generate.py
│
├── prompts/
│   ├── architecture.md
│   ├── module.md
│   ├── data_structures.md
│   └── api_reference.md
│
├── agents/
│   └── clangwiki-doc.md
│
├── tests/
│   ├── test_cmake_manager.py
│   ├── test_compilation_database.py
│   ├── test_document_planner.py
│   ├── test_context_builder.py
│   └── test_opencode_runner.py
│
└── workspace/
    ├── build/
    ├── analysis/
    ├── knowledge/
    ├── tasks/
    ├── logs/
    └── output/
```

要求：

- 核心 Python 代码放在 `clangwiki/` 包中；
- Prompt 模板与代码分离；
- Clang 分析器作为独立可执行程序；
- 中间产物统一写入工作目录；
- 不要默认污染目标代码仓；
- 除非用户明确指定，否则最终 Wiki 输出到外部工作目录。

---

## 6. 命令行接口

```bash
python clangwiki.py generate \
  --repo "D:\projects\target_repository" \
  --workspace "D:\clangwiki_workspace" \
  --output "D:\clangwiki_workspace\output" \
  --model "provider/glm-5.1"
```

推荐参数：

| 参数 | 必需 | 说明 |
|---|---:|---|
| `--repo` | 是 | 目标代码仓根目录 |
| `--workspace` | 否 | 中间结果目录 |
| `--output` | 否 | 最终文档目录 |
| `--model` | 否 | OpenCode 中配置的模型标识 |
| `--agent` | 否 | OpenCode Agent 名称 |
| `--build-dir` | 否 | CMake 构建目录 |
| `--clean` | 否 | 是否清理旧工作目录 |
| `--skip-cmake` | 否 | 使用已有编译数据库 |
| `--skip-analysis` | 否 | 使用已有分析结果 |
| `--only` | 否 | 只生成指定类型文档 |
| `--verbose` | 否 | 输出详细日志 |

---

## 7. Build Environment Manager

### 7.1 输入仓库

```text
repository/
├── CMakeLists.txt
├── module_a/
│   ├── a.c
│   └── a.h
├── module_b/
│   ├── b.c
│   └── b.h
└── main.c
```

### 7.2 CMake 配置命令

Windows PowerShell：

```powershell
cmake -S "D:\repo\demo" `
      -B "D:\clangwiki_workspace\build" `
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

Linux 或 WSL2：

```bash
cmake -S /path/to/repo \
      -B /path/to/workspace/build \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

### 7.3 编译数据库验证

生成后必须验证：

- 文件是否存在；
- JSON 是否可解析；
- 根节点是否为数组；
- 每项是否包含 `directory`；
- 每项是否包含 `file`；
- 每项是否包含 `command` 或 `arguments`；
- 源文件路径是否存在；
- 至少包含一个 `.c` 或 `.cpp` 文件。

### 7.4 源码覆盖率检查

扫描仓库全部源码文件，再与 `compile_commands.json` 中的 `file` 字段比较。

```json
{
  "repository_source_count": 38,
  "compdb_source_count": 35,
  "covered_source_count": 35,
  "uncovered_sources": [
    "legacy/unused.c",
    "tests/mock_only.c",
    "tools/helper.c"
  ]
}
```

Build Agent 不应自动修改 `CMakeLists.txt`，只记录并报告未覆盖文件。

---

## 8. Clang 静态分析层

### 8.1 推荐技术

- Clang LibTooling；
- AST Matchers；
- Compilation Database；
- RecursiveASTVisitor。

`clang -Xclang -ast-dump` 只用于原型和调试，不作为正式核心数据源。

### 8.2 分析器调用

```powershell
clang_analyzer.exe `
  --compdb "D:\clangwiki_workspace\build" `
  --source-root "D:\repo\demo" `
  --output "D:\clangwiki_workspace\analysis"
```

### 8.3 最低提取内容

#### 函数

```json
{
  "id": "src/network.c::network_init",
  "name": "network_init",
  "file": "src/network.c",
  "line": 42,
  "is_definition": true,
  "return_type": "int",
  "parameters": [
    {
      "name": "config",
      "type": "const network_config_t *"
    }
  ]
}
```

#### 调用关系

```json
{
  "caller": "src/network.c::network_init",
  "callee": "src/socket.c::socket_create",
  "file": "src/network.c",
  "line": 51,
  "resolution": "resolved"
}
```

无法解析时必须标记：

```json
{
  "caller": "src/network.c::network_init",
  "callee_name": "platform_socket_create",
  "resolution": "unresolved"
}
```

#### 结构体

```json
{
  "id": "include/network.h::network_config_t",
  "kind": "struct",
  "name": "network_config_t",
  "file": "include/network.h",
  "line": 18,
  "fields": [
    {
      "name": "address",
      "type": "const char *"
    },
    {
      "name": "port",
      "type": "uint16_t"
    }
  ]
}
```

#### Include 关系

```json
{
  "source": "src/network.c",
  "target": "include/network.h",
  "line": 3,
  "is_system": false
}
```

### 8.4 输出文件

```text
analysis/
├── files.json
├── functions.json
├── calls.json
├── records.json
├── typedefs.json
├── enums.json
├── globals.json
├── includes.json
├── macros.json
└── diagnostics.json
```

诊断错误不得被静默忽略。

---

## 9. Knowledge Base

第一版使用 JSON 文件即可，后续可迁移至 SQLite。

```text
knowledge/
├── repository.json
├── modules.json
├── symbols.json
├── call_graph.json
├── include_graph.json
├── type_relations.json
└── source_coverage.json
```

模块划分优先依据：

1. 顶层目录；
2. 子目录；
3. CMake target；
4. 文件名前缀；
5. Include 关系；
6. 调用关系。

知识库必须区分：

- 编译器直接确定的事实；
- 框架规则推断的信息；
- LLM 生成的语义解释。

不要把 LLM 生成的描述回写为编译器事实。

---

## 10. Document Planner

Document Planner 决定：

- 生成哪些文档；
- 每篇文档属于什么类型；
- 每篇文档需要哪些模块；
- 每篇文档使用哪个 Prompt；
- 每篇文档输出到哪里。

通信基带仓采用与源码层级同构的输出：

```text
output/
├── README.md
├── Architecture.md
├── Modules/
│   └── src/
│       ├── index.md                 # src 父级汇总
│       └── phy/
│           ├── index.md             # PHY 子系统汇总
│           ├── pdsch/
│           │   ├── index.md         # PDSCH 信道汇总
│           │   ├── encoder/index.md # PDSCH 编码叶子
│           │   └── mapping/index.md # PDSCH 映射叶子
│           └── pusch/index.md       # PUSCH 信道汇总
├── DataStructures.md
├── CallFlows.md
└── APIReference.md
```

任务清单示例：

```json
[
  {
    "task_id": "leaf-module-src--phy--pdsch--encoder",
    "document_type": "leaf-module",
    "title": "encoder 信道内叶子模块",
    "output_relative_path": "Modules/src/phy/pdsch/encoder/index.md",
    "module_ids": ["src--phy--pdsch--encoder"],
    "hierarchy_role": "leaf",
    "child_document_paths": []
  },
  {
    "task_id": "module-summary-src--phy--pdsch",
    "document_type": "module-summary",
    "title": "pdsch 信道汇总",
    "output_relative_path": "Modules/src/phy/pdsch/index.md",
    "module_ids": ["src--phy--pdsch"],
    "hierarchy_role": "aggregate",
    "child_document_paths": [
      "Modules/src/phy/pdsch/encoder/index.md",
      "Modules/src/phy/pdsch/mapping/index.md"
    ]
  }
]
```

第一版必须采用：

```text
一篇文档 = 一个任务 = 一次 opencode run
```

任务顺序必须是叶子优先、父级随后，最后才生成 `Architecture.md` 和 `README.md`。父级任务将直接子文档作为输入，实现逐层向上总结。

---

## 11. Context Builder

Context Builder 根据文档任务选择：

- 模块文件；
- 公开符号；
- 关键内部符号；
- 函数调用关系；
- Include 依赖；
- 数据结构；
- 入口函数；
- 核心源码片段；
- Clang 诊断信息；
- 文档生成要求。

上下文示例：

```markdown
# ClangWiki Document Task

## Task Metadata

- Task ID: leaf-module-src--phy--pdsch--encoder
- Document Type: leaf-module
- Output: Modules/src/phy/pdsch/encoder/index.md
- Repository: D:\repo\demo

## Target Module

- Module ID: src--phy--pdsch--encoder
- Module Name: PDSCH Encoder

## Files

- src/network/network.c
- src/network/socket.c
- include/network/network.h

## Public Symbols

### network_init

- Kind: function
- Location: src/network/network.c:42
- Return type: int
- Parameters:
  - const network_config_t *config
- Calls:
  - network_load_config
  - socket_create
  - socket_bind

## Documentation Requirements

1. 说明模块职责。
2. 说明主要文件分工。
3. 说明初始化、运行和清理流程。
4. 说明关键数据结构。
5. 说明主要调用关系。
6. 不得虚构不存在的接口。
7. 保留原始符号名称。
8. 输出完整 Markdown 正文。
```

不要默认把整个源码文件全文加入上下文。

---

## 12. OpenCode Agent 配置

推荐建立专用 Agent：

```text
.opencode/
└── agents/
    └── clangwiki-doc.md
```

参考内容：

```markdown
---
description: 根据 Clang 静态分析结果生成 C/C++ 项目技术文档
mode: primary
model: provider/glm-5.1
permission:
  read: allow
  glob: allow
  grep: allow
  bash: deny
  edit: deny
  webfetch: deny
  websearch: deny
---

你是 ClangWiki 的文档生成 Agent。

你的任务是根据 ClangWiki 提供的结构化分析结果和目标代码仓源码，
生成准确、完整、可追溯的中文 Markdown 技术文档。

必须遵守以下规则：

1. Clang 结构化分析结果是语法和语义事实基础。
2. 可以读取源码补充行为解释。
3. 不得虚构不存在的模块、函数、参数、类型和调用关系。
4. 无法确认的信息必须明确写为“无法从当前上下文确定”。
5. 保留函数名、结构体名、宏名、文件名和参数名。
6. 区分编译器确定事实与代码语义解释。
7. 只输出最终 Markdown 正文。
8. 不输出生成过程。
9. 不修改代码仓中的任何文件。
10. 不执行构建、安装或网络访问命令。
```

推荐权限：

```text
read       allow
glob       allow
grep       allow
edit       deny
bash       deny
webfetch   deny
websearch  deny
```

---

## 13. `opencode run` 调用

推荐命令：

```powershell
Get-Content -Raw "D:\clangwiki_workspace\tasks\module_network_context.md" |
  opencode run `
    "从标准输入读取 ClangWiki 任务上下文，只输出最终 Markdown 正文。" `
    --agent "clangwiki-doc" `
    --model "provider/glm-5.1"
```

Python 调用：

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class OpenCodeRunner:
    def __init__(
        self,
        model: str,
        agent: str = "clangwiki-doc",
        executable: str = "opencode",
    ) -> None:
        self.model = model
        self.agent = agent
        self.executable = executable

    def run(
        self,
        repository: Path,
        context_file: Path,
        output_file: Path,
    ) -> None:
        repository = repository.resolve()
        context_file = context_file.resolve()
        output_file = output_file.resolve()

        if not repository.is_dir():
            raise FileNotFoundError(f"代码仓不存在：{repository}")

        if not context_file.is_file():
            raise FileNotFoundError(f"上下文文件不存在：{context_file}")

        prompt = (
            "从标准输入读取 ClangWiki 任务上下文并生成技术文档。"
            "只输出最终 Markdown 正文，不要输出解释、前言或代码围栏。"
        )

        command = [
            self.executable,
            "run",
            prompt,
            "--model",
            self.model,
            "--agent",
            self.agent,
        ]

        result = subprocess.run(
            command,
            cwd=repository,
            input=context_file.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "OpenCode 执行失败\n"
                f"退出码：{result.returncode}\n"
                f"stderr：{result.stderr}"
            )

        markdown = result.stdout.strip()

        if not markdown:
            raise RuntimeError("OpenCode 未返回任何 Markdown 内容")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(markdown + "\n", encoding="utf-8")
```

必须设置：

```python
cwd=repository
```

这样 OpenCode 才能在目标仓库上下文中读取源码并识别项目级配置。

---

## 14. Markdown 输出管理

推荐由 ClangWiki 捕获 `opencode run` 标准输出，再自行写入文件。

```text
opencode stdout
        │
        ▼
Result Parser
        │
        ▼
Markdown Validator
        │
        ▼
Output Manager
        │
        ▼
*.md
```

最低校验规则：

- 非空；
- 字符数大于最低阈值；
- 不以错误堆栈开头；
- 不包含明显 CLI 日志；
- 至少包含一个 Markdown 标题；
- 不包含未闭合代码围栏；
- 编码为 UTF-8；
- 输出路径位于指定目录。

若校验失败，保存：

```text
logs/failed/module_network.stdout.txt
logs/failed/module_network.stderr.txt
```

不要覆盖已有有效文档。

---

## 15. 流水线主逻辑

```python
def generate_wiki(config):
    repository = validate_repository(config.repo)

    build_result = configure_cmake(
        repository=repository,
        build_dir=config.build_dir,
    )

    compilation_database = validate_compilation_database(
        build_result.compile_commands
    )

    analysis_result = run_clang_analyzer(
        repository=repository,
        compilation_database=compilation_database,
        output_dir=config.analysis_dir,
    )

    knowledge_base = build_knowledge_base(
        repository=repository,
        analysis_result=analysis_result,
        output_dir=config.knowledge_dir,
    )

    tasks = plan_documents(
        repository=repository,
        knowledge_base=knowledge_base,
    )

    for task in tasks:
        context_file = build_context(
            task=task,
            knowledge_base=knowledge_base,
            repository=repository,
        )

        raw_markdown = run_opencode(
            repository=repository,
            context_file=context_file,
            model=config.model,
            agent=config.agent,
        )

        validate_and_write_markdown(
            task=task,
            markdown=raw_markdown,
            output_dir=config.output_dir,
        )
```

---

## 16. 配置文件建议

```yaml
repository: D:/repo/demo
workspace: D:/clangwiki_workspace

build:
  generator: null
  build_dir: D:/clangwiki_workspace/build
  export_compile_commands: true

analyzer:
  executable: D:/clangwiki/bin/clang_analyzer.exe
  output_dir: D:/clangwiki_workspace/analysis
  include_macros: true
  include_system_headers: false

planner:
  generate_architecture: true
  generate_modules: true
  generate_data_structures: true
  generate_call_flows: true
  generate_api_reference: true

opencode:
  executable: opencode
  model: provider/glm-5.1
  agent: clangwiki-doc
  timeout_seconds: 900

output:
  directory: D:/clangwiki_workspace/output
  encoding: utf-8
  overwrite: false
```

不要在配置示例中写死真实密钥。

---

## 17. 日志与错误处理

日志示例：

```text
[BUILD] 检测到 CMakeLists.txt
[BUILD] 正在生成 compile_commands.json
[BUILD] 编译数据库包含 35 个翻译单元
[ANALYZE] 正在分析 src/network.c
[ANALYZE] 已提取 128 个函数
[KNOWLEDGE] 已构建 7 个模块
[PLAN] 已生成 11 个文档任务
[CONTEXT] 已生成 module_network_context.md
[OPENCODE] 正在生成 Modules/src/phy/pdsch/encoder/index.md
[OUTPUT] 文档校验通过
```

错误分类：

- `RepositoryError`
- `CMakeError`
- `CompilationDatabaseError`
- `ClangAnalysisError`
- `KnowledgeBuildError`
- `PlanningError`
- `ContextBuildError`
- `OpenCodeError`
- `MarkdownValidationError`

不要使用单一通用异常吞掉错误来源。

---

## 18. 测试要求

### 18.1 单元测试

至少覆盖：

- CMake 项目检测；
- 编译数据库解析；
- 源码覆盖率比较；
- 分析结果 Schema 校验；
- 模块划分；
- 文档任务规划；
- 上下文生成；
- OpenCode 命令组装；
- Markdown 校验。

### 18.2 集成测试

准备一个小型 C 项目：

```text
demo/
├── CMakeLists.txt
├── main.c
├── network.c
├── network.h
├── storage.c
└── storage.h
```

完整测试：

```text
CMake
→ compile_commands.json
→ Clang analysis
→ Knowledge Base
→ Document Tasks
→ Context Files
→ opencode run
→ Markdown Output
```

单元测试中不要真实调用模型，应提供 Mock OpenCode Runner。

---

## 19. 验收标准

### 19.1 环境验收

- 能检测 CMake；
- 能检测 Clang 或自定义分析器；
- 能检测 OpenCode；
- 能输出版本信息；
- 缺少依赖时给出清晰错误。

### 19.2 构建验收

- 能从仅包含 C 源码和 `CMakeLists.txt` 的仓库生成编译数据库；
- 不要求 Bear；
- 不要求 Ollama；
- 不要求 Embedding；
- 不要求向量数据库。

### 19.3 分析验收

至少正确提取：

- 源文件；
- 函数；
- 函数参数；
- 返回值；
- 结构体；
- 枚举；
- 全局变量；
- Include 关系；
- 函数调用关系；
- 源码位置。

### 19.4 文档生成验收

至少生成：

```text
Architecture.md
Modules/<source-path>/index.md
DataStructures.md
APIReference.md
```

每篇文档：

- 独立执行一次 `opencode run`；
- 有独立上下文文件；
- 有独立日志；
- 能单独重试；
- 输出为 UTF-8 Markdown。

### 19.5 安全验收

文档 Agent：

- 不修改源码；
- 不执行构建命令；
- 不访问网络；
- 不安装依赖；
- 不提交 Git；
- 不删除目标仓库文件。

---

## 20. 禁止事项

1. 不要让 OpenCode 替代 Clang 完成全部结构分析；
2. 不要一次性把整个代码仓全文放入单个 Prompt；
3. 不要把未解析调用标记为确定调用；
4. 不要将 LLM 推断结果保存为编译器事实；
5. 不要默认修改 `CMakeLists.txt`；
6. 不要要求项目必须运行在 Ubuntu；
7. 不要把 WSL2 写成系统核心组成；
8. 不要引入 Ollama；
9. 不要引入 Embedding；
10. 不要引入向量数据库；
11. 不要让 Agent 直接决定输出文件是否成功；
12. 不要忽略 Clang 诊断；
13. 不要在日志中输出密钥；
14. 不要给文档 Agent 开放源码编辑权限。

---

## 21. 推荐实现顺序

### 阶段一：最小闭环

```text
Repository
→ CMake
→ compile_commands.json
→ Clang Analyzer
→ symbols.json
→ context.md
→ opencode run
→ Module.md
```

### 阶段二：结构化知识

增加：

- Call Graph；
- Include Graph；
- Data Structures；
- Module Map。

### 阶段三：文档规划

增加：

- Architecture；
- 多模块文档；
- API Reference；
- Call Flows。

### 阶段四：稳定性

增加：

- 缓存；
- 失败重试；
- 输出校验；
- 诊断报告；
- 源码覆盖率检查。

---

## 22. 最终交付物

Build Agent 应交付：

```text
clangwiki/
├── 可运行的 Python CLI
├── Clang 分析器源码及可执行文件
├── 配置示例
├── Prompt 模板
├── OpenCode Agent 配置
├── 单元测试
├── 集成测试样例仓库
├── README
└── 架构与数据格式说明
```

最终用户应能执行：

```powershell
python clangwiki.py generate `
  --repo "D:\projects\target_repository" `
  --workspace "D:\clangwiki_workspace" `
  --model "provider/glm-5.1" `
  --agent "clangwiki-doc"
```

并得到：

```text
D:\clangwiki_workspace\output\
├── README.md
├── Architecture.md
├── Modules\
├── DataStructures.md
├── CallFlows.md
└── APIReference.md
```

---

## 23. 核心原则

```text
CMake 负责恢复构建环境
Clang 负责确定代码结构
ClangWiki 负责组织知识与任务
OpenCode 负责执行 Agent
GLM-5.1 负责理解与撰写
Markdown Validator 负责保证输出可用
```

ClangWiki 的核心价值不在于重复实现 Agent，而在于：

> 将编译器确定性的代码结构，与大语言模型的语义理解和文档生成能力进行分层结合，从而实现可控、可追溯、可扩展的代码仓逆向文档生成。
