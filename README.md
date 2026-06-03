# Codex Local

让同一台电脑上的 Codex 本地项目和线程不再因为账号登录 / token 登录被割裂。

## 最简单用法

```powershell
.\codex-local.cmd open
```

打开本地网页视图，默认读取当前用户的 `~\.codex`，按项目展示所有本地线程。

网页里每个线程右侧都有“删除”。删除前会自动备份索引和对应的 rollout 文件，确认后该线程会从本地列表、SQLite 索引和 `session_index.jsonl` 中移除。

网页列表支持多选线程后批量删除。可以先搜索筛选，再点“选择当前”只选中当前筛选结果；批量删除会逐条备份后删除，并在完成后刷新列表。

## 删除指定线程

```powershell
.\codex-local.cmd delete <线程ID>
```

命令行删除默认需要输入 `DELETE` 确认。想在脚本里直接执行：

```powershell
.\codex-local.cmd delete <线程ID> --yes
```

## 修复 Codex 本地索引

```powershell
.\codex-local.cmd repair
```

修复前会自动备份：

- `~\.codex\state_5.sqlite`
- `~\.codex\state_5.sqlite-shm`
- `~\.codex\state_5.sqlite-wal`
- `~\.codex\session_index.jsonl`

备份目录形如：

```text
~\.codex\codex-local-backups\20260519-181514
```

## 检查状态

```powershell
.\codex-local.cmd doctor
```

如果输出里缺失数量都是 0，说明本地索引已经完整。

## 设计原则

- 不读取或修改 `auth.json` 的 token 内容。
- 默认从本地 `sessions`、`state_5.sqlite`、`session_index.jsonl` 合并线程。
- `open` 默认用于查看，也提供备份后删除线程的入口。
- `repair` 只补缺失索引，先备份再写入。
- `delete` 会先备份索引和对应 rollout 文件，再移除本地线程记录。
- 不要求改系统 PowerShell 执行策略，统一用 `codex-local.cmd` 启动。
 
## Provider 桥接修复

`repair` 会读取 `~\.codex\config.toml` 里的当前 `model_provider`，并把本机历史中 `vscode`、`cli`、`appServer` 这类交互式线程的 `session_meta.payload.model_provider` 桥接到当前 provider。这样在账号登录和 API token/custom provider 之间来回切换后，Codex Desktop 左侧默认列表不会再只显示当前 provider 下的新线程。

账号登录通常不会在 `config.toml` 写入 `model_provider`。这种情况下，`repair` 会按 Codex 账号登录默认 provider `openai` 处理，把 token/custom provider 留下的交互式历史桥回 `openai`。

修复会先备份：

- `config.toml`
- `state_5.sqlite` / `state_5.sqlite-shm` / `state_5.sqlite-wal`
- `session_index.jsonl`
- 被修改的 `sessions/**/*.jsonl`

不会修改 subagent 线程，也不会读取或写入 `auth.json` 里的 token。
