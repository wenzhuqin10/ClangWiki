# 目标电脑迁移检查表

完整执行流程见 `docs/AGENT_DEPLOYMENT_GUIDE.md`；本表仅用于最终复核。

- [ ] BIOS 虚拟化已开启，`wsl -l -v` 显示 Ubuntu 24.04 / VERSION 2。
- [ ] 仓库位于 WSL 的 `~/projects`，而不是 `/mnt/c`。
- [ ] `scripts/bootstrap-wsl.sh` 重复执行无错误。
- [ ] `scripts/build-analyzer.sh` 生成 `bin/cpp-analyzer`。
- [ ] `ollama list` 包含 `bge-m3`。
- [ ] `CPPWIKI_EMBED_NUM_GPU=0`，`ollama ps` 显示 CPU 执行。
- [ ] `nga/OpenCode` 的 `/global/health` 返回健康。
- [ ] `/provider` 中存在配置的 GLM Provider ID。
- [ ] 企业凭据未写入 `.env`、Git、日志或测试报告。
- [ ] 测试仓生成 `compile_commands.json` 并以 `full` 模式分析。
- [ ] 三个标注查询均在 Top-10 中召回目标符号。
- [ ] Wiki 页面中的源码引用均可定位到对应行。
- [ ] 真实仓库重新建库，没有复制开发机的 `.cppwiki` 缓存。
