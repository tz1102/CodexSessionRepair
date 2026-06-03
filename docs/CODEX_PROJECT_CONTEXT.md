# Codex Local 项目索引

## 项目定位

Codex Local 是一个本地修复工具，用来把同一台机器上因账号登录、API token/custom provider 切换导致割裂的 Codex Desktop 本地线程重新合并到可见索引中。它只处理本机 `~\.codex` 下的本地数据，不读取或修改 `auth.json` token 内容。

## 整体架构

- `codex-local.cmd` / `codex-local.ps1`：Windows 启动脚本，设置 UTF-8、`PYTHONPATH=src`，再执行 `python -m codex_local`。
- `src/codex_local/cli.py`：命令行入口，提供 `open`、`list`、`doctor`、`repair`、`delete` 子命令。
- `src/codex_local/core.py`：核心业务层，负责读取 rollout、SQLite、`session_index.jsonl`，构建统一索引，执行备份、修复、删除。
- `src/codex_local/web.py`：内置 HTTP 服务和单页网页视图，调用 core API 展示、修复、单条删除和批量删除线程。
- `tests/test_core.py`：核心行为单元测试，使用临时 `~\.codex` 目录和临时 SQLite 库验证修复逻辑。

## 核心模块和关键对象

- `ThreadRecord`：统一后的线程记录，包含线程 id、cwd、rollout 路径、provider、标题、时间戳、是否存在于 SQLite / session_index 等状态。
- `ProjectRecord`：按 cwd 聚合线程，用于 CLI/web 按项目展示。
- `UnifiedIndex`：`build_unified_index()` 的输出，包含所有项目、缺 SQLite 的线程、缺 session_index 的线程。
- `RepairResult`：`repair_codex_indexes()` 的输出，记录备份目录、补齐条数、provider 桥接目标和桥接数量。
- `DeleteResult`：`delete_thread()` 的输出，记录备份和删除结果。

## 启动入口和配置

- Python 包入口：`src/codex_local/__main__.py` 调用 `cli.main()`。
- 默认 Codex 本地目录：`Path.home() / ".codex"`，可通过 `--codex-home` 覆盖。
- Codex 配置文件：`~\.codex\config.toml`。如果存在 `model_provider`，修复时以它为当前 provider；如果账号登录配置没有 `model_provider`，默认使用 `openai`。
- 本项目没有外部数据库服务、缓存或中间件依赖；只读写本机 SQLite 文件和 JSONL 文件。

## 本地数据依赖

- `~\.codex\sessions\**\rollout-*.jsonl`：线程原始记录。`session_meta.payload` 提供 id、cwd、source、model_provider 等元数据。
- `~\.codex\state_5.sqlite`：Codex Desktop 本地 SQLite 索引，核心表是 `threads`。
- `~\.codex\session_index.jsonl`：线程列表索引，按 id、thread_name、updated_at 存储。
- `~\.codex\codex-local-backups\YYYYMMDD-HHMMSS`：本工具修复/删除前生成的备份目录。

## 常见业务流程

- 展示统一列表：`build_unified_index()` 读取 rollout、SQLite、session_index，按 thread id 合并，再按 cwd 聚合成项目列表。
- 检查状态：`doctor` 调用 `build_unified_index()`，输出缺 SQLite 和缺 session_index 的数量。
- 修复索引：`repair_codex_indexes()` 先备份，再把交互式线程 provider 桥到当前 provider，然后补齐缺失 SQLite 线程和 `session_index.jsonl` 条目。
- 删除线程：`delete_thread()` 先构建统一索引定位线程，再备份索引和 rollout，把 rollout 移到备份目录，并删除 SQLite/session_index 中对应记录。
- 批量删除线程：`delete_threads()` 清理重复/空线程 ID 后逐条调用 `delete_thread()`，返回每条成功和失败结果。
- 网页操作：`web.py` 的 `/api/index`、`/api/repair`、`/api/delete`、`/api/delete-batch` 分别调用上述 core 函数。

## 重要文件

- `src/codex_local/core.py`：最重要。所有索引读取、provider 桥接、修复、删除逻辑都在这里。
- `tests/test_core.py`：修改 core 行为时必须优先更新并运行。
- `README.md`：用户使用说明，修复行为变化要同步更新。
- `codex-local.cmd`、`codex-local.ps1`：Windows 启动体验相关，通常只在启动参数或编码问题时修改。
- `src/codex_local/web.py`：网页展示和 API 封装，只有改网页交互时需要重点看。

## 一般不用看的文件

- `src/codex_local/__pycache__`、`tests/__pycache__`：生成缓存，不要手改。
- `.git`：版本控制内部文件，不要直接改。
- `LICENSE`：授权文件，非授权变更任务不用看。

## 后续源码读取策略

1. 先读本文件确认结构和数据流。
2. 行为修复优先看 `tests/test_core.py` 里是否已有相近用例，再看 `src/codex_local/core.py` 对应函数。
3. CLI 输出问题看 `src/codex_local/cli.py`，网页问题看 `src/codex_local/web.py`。
4. 涉及真实 Codex 本地数据时，先只读查询 `~\.codex\state_5.sqlite`、`config.toml` 和 `session_index.jsonl`；执行 `repair` 或 `delete` 前确认会生成备份。
5. 不要粘贴大段源码到文档或回复里，只总结路径、职责、调用关系和验证结果。
