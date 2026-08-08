# 数据格式与准确性边界

## 工作目录契约

```text
workspace/
├── build/                 # CMake 生成的 compile_commands.json
├── analysis/
│   ├── files.json
│   ├── symbols.json
│   ├── relations.json
│   └── diagnostics.json
├── knowledge/
│   ├── repository.json
│   ├── modules.json
│   ├── module_tree.json
│   ├── symbols.json
│   ├── relations.json
│   └── source_coverage.json
├── tasks/
│   ├── tasks.json
│   └── contexts/<task-id>.md
├── logs/
│   └── opencode/<task-id>.{stdout,stderr}.txt
└── output/
```

所有文件使用 UTF-8。目标代码仓仅被读取；build、analysis、knowledge、tasks、logs 和 output
均在用户明确指定的 workspace 内。

## 模块层级记录

`modules.json` 中每个节点记录 `source_path`、`parent_id`、`child_ids`、`depth`、`is_leaf`、`is_channel_root`、`is_channel_child_leaf` 和本层直接拥有的源码文件。`module_tree.json` 保存根节点和父子关系。

信道根路径由 `--channel-module-path` 指定，其直接源码子目录成为叶子。叶子路径以下的目录和文件仍属于同一最小文档；PDSCH 等信道节点通过直接子文档向上汇聚。父节点只保存本层直接拥有的源码，不复制子节点符号。

## 符号记录

```json
{
  "kind": "function",
  "name": "network_init",
  "qualified_name": "network_init",
  "file_path": "src/network.c",
  "line_start": 42,
  "line_end": 78,
  "signature": "int network_init(const network_config_t *config)",
  "certainty": "compiler"
}
```

`certainty` 为 `compiler` 时来自 libclang AST；`lexical` 表示 Python 的保守辅助扫描。

## 关系记录

```json
{
  "source": "network_init",
  "target": "socket_create",
  "kind": "CALLS",
  "file_path": "src/network.c",
  "line": 51,
  "confidence": 1.0,
  "certainty": "compiler"
}
```

| kind | 解释 | 可靠性 |
|---|---|---|
| `CALLS` | Clang 能解析到直接被调函数。 | 确定调用 |
| `REFERENCES` | 函数对非局部变量的引用。 | 确定引用，不区分读写 |
| `INCLUDES` | 源文本中的 include 指令。 | 词法事实，不代表最终条件编译路径 |
| `POSSIBLE_CALL` | 间接调用或词法匹配。 | 候选，不能写成确定调用 |

## 上下文约束

每篇文档拥有独立上下文文件。上下文含任务目标、模块文件、符号、关系和受 `--max-source-chars-per-task`
控制的源码片段。该限制避免把整个仓库塞入一次模型请求；它是字符级保护，不等同于 GLM 服务端的精确 token 计数。
