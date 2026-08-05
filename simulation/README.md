# ClangWiki 本地模拟仓

该目录用于模拟 ClangWiki 的完整链路，不会调用真实模型。

`pdsch-demo/` 是一个最小 CMake 仓库，包含：

```text
pdsch/
├── encoder/
├── modulation/
└── mapping/
```

`fake-opencode.cmd` 会替代真实的 `opencode`，返回符合 ClangWiki 章节契约的 Markdown。它仅用于本机流程检查，不要用于生产。

## 运行模拟

在仓库根目录执行：

```powershell
python -m clangwiki generate `
  --repo "$PWD\simulation\pdsch-demo" `
  --workspace "$PWD\simulation\workspace" `
  --model "simulation/glm-5.1" `
  --opencode-executable "$PWD\simulation\fake-opencode.cmd" `
  --channel-module-path "src/pdsch" `
  --overwrite
```

如果设备没有安装 CMake，可提前提供 `workspace/build/compile_commands.json`，并追加 `--skip-cmake`。生产环境应移除假的启动器，改用真实的 `opencode`。
