# ClangWiki 架构说明

## 1. 定位与职责

ClangWiki 是 OpenCode 之上的 C/C++ 代码仓逆向文档应用框架，不是新的通用 Agent。

```text
ClangWiki      组织构建、分析、知识、任务、上下文和输出
OpenCode       执行一次性 Agent 任务并使用其既有认证
GLM-5.1        理解受限上下文、撰写 Markdown
CMake          恢复每个翻译单元的真实编译参数
Clang          提取 AST、直接调用、全局符号等编译器级事实
```

## 2. 总体流程

```text
Target repository
├── CMakeLists.txt
├── C/C++ source files
└── header files
        │
        ▼
Build Environment Manager                [ClangWiki + CMake]
├── validates repository
├── configures CMake only (does not build target code)
└── validates compile_commands.json
        │
        ▼
Compiler Analysis                        [Clang/LibTooling + ClangWiki]
├── compiler facts: functions, records, enums, globals
├── compiler facts: direct CALLS and REFERENCES
├── lexical supplements: INCLUDES, macros, unresolved calls
└── diagnostics and analysis mode
        │
        ▼
Knowledge and Planning                   [ClangWiki]
├── JSON artifacts and source coverage
├── hierarchical module tree
├── channel-level leaf boundaries
├── bottom-up document plan
└── one task = one output Markdown file
        │
        ▼
Bounded Context Builder                  [ClangWiki]
├── leaf: selects direct Clang facts and source snippets
├── parent: reads generated direct-child documents
├── repository: reads top-level summaries
└── writes task-specific context Markdown
        │
        ▼
opencode run                             [OpenCode CLI]
        │
        ▼
OpenCode → configured GLM-5.1            [Agent + LLM]
        │
        ▼
Markdown validator and writer            [ClangWiki]
└── workspace/output/*.md
```

## 3. 分层文档生成

通信基带代码仓按“源码层级树 + 信道叶子边界”组织文档。PDSCH、PUSCH、PDCCH 等信道级子模块是最小文档单元，其内部更深的 `encoder`、`mapper` 等目录不会再拆成独立文档。

```text
信道级叶子文档（直接读取 Clang 事实和源码）
        ↓
父模块汇总（读取直接子文档和本层直接源码）
        ↓
子系统汇总（继续读取直接子文档）
        ↓
Architecture.md
        ↓
README.md
```

生产环境应使用重复的 `--leaf-module-path` 明确指定仓库相对路径。自动识别仅作为未配置时的辅助策略，不能替代仓库维护者对模块边界的确认。

## 4. 分析模式

| 模式 | 含义 | 文档中的使用方式 |
|---|---|---|
| `full` | 已构建并执行 `clangwiki-analyzer`，读取编译数据库。 | `certainty=compiler` 可作为确定结构事实。 |
| `partial` | LibTooling 工具不可用或失败，使用词法辅助分析。 | 不应把调用/类型关系当作编译器级结论。 |

第一版故意不把词法结果伪装为编译器事实。宏展开、函数指针、回调、动态加载、条件编译的实际路径和跨线程数据流均不在确定性分析范围内。

## 5. `opencode run` 集成边界

ClangWiki 使用子进程调用：

```text
<opencode-executable> run --model <provider/model> --file <task-context.md> [--agent <agent>]
```

- `cwd` 始终是目标代码仓，供 OpenCode 读取已批准的源码。
- ClangWiki 只收集标准输出、写入 Markdown，并保存 stdout/stderr 日志。
- API Key 不会传入命令行、配置文件、日志或 workspace。
- 标准 OpenCode 可执行文件名是 `opencode`；企业环境可用 `--opencode-executable nga` 指向参数兼容的启动器。
