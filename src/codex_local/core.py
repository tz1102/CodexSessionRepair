from __future__ import annotations

import json
import shutil
import sqlite3
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


THREAD_TABLE_INSERT_COLUMNS = [
    "id",
    "rollout_path",
    "created_at",
    "updated_at",
    "source",
    "model_provider",
    "cwd",
    "title",
    "sandbox_policy",
    "approval_mode",
    "tokens_used",
    "has_user_event",
    "archived",
    "cli_version",
    "first_user_message",
    "memory_mode",
    "model",
    "reasoning_effort",
    "created_at_ms",
    "updated_at_ms",
    "thread_source",
    "preview",
]


@dataclass
class ThreadRecord:
    id: str
    title: str
    cwd: str
    rollout_path: str
    created_at_ms: int
    updated_at_ms: int
    source: str = "unknown"
    model_provider: str = "unknown"
    first_user_message: str = ""
    preview: str = ""
    cli_version: str = ""
    sandbox_policy: str = "unknown"
    approval_mode: str = "unknown"
    memory_mode: str = "enabled"
    model: str | None = None
    reasoning_effort: str | None = None
    thread_source: str | None = "user"
    in_sqlite: bool = False
    in_session_index: bool = False

    @property
    def created_at(self) -> int:
        return max(self.created_at_ms // 1000, 0)

    @property
    def updated_at(self) -> int:
        return max(self.updated_at_ms // 1000, 0)

    @property
    def updated_at_iso(self) -> str:
        return _ms_to_iso(self.updated_at_ms)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["updated_at_iso"] = self.updated_at_iso
        data["needs_repair"] = not (self.in_sqlite and self.in_session_index)
        return data


@dataclass
class ProjectRecord:
    cwd: str
    threads: list[ThreadRecord] = field(default_factory=list)

    @property
    def thread_count(self) -> int:
        return len(self.threads)

    @property
    def latest_updated_at_ms(self) -> int:
        return max((thread.updated_at_ms for thread in self.threads), default=0)

    @property
    def missing_sqlite_count(self) -> int:
        return sum(1 for thread in self.threads if not thread.in_sqlite)

    @property
    def missing_session_index_count(self) -> int:
        return sum(1 for thread in self.threads if not thread.in_session_index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cwd": self.cwd,
            "thread_count": self.thread_count,
            "latest_updated_at_ms": self.latest_updated_at_ms,
            "latest_updated_at_iso": _ms_to_iso(self.latest_updated_at_ms),
            "missing_sqlite_count": self.missing_sqlite_count,
            "missing_session_index_count": self.missing_session_index_count,
            "threads": [thread.to_dict() for thread in self.threads],
        }


@dataclass
class UnifiedIndex:
    codex_home: Path
    projects: list[ProjectRecord]
    missing_sqlite_threads: list[ThreadRecord]
    missing_session_index_threads: list[ThreadRecord]

    @property
    def total_projects(self) -> int:
        return len(self.projects)

    @property
    def total_threads(self) -> int:
        return sum(project.thread_count for project in self.projects)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codex_home": str(self.codex_home),
            "total_projects": self.total_projects,
            "total_threads": self.total_threads,
            "missing_sqlite_threads": len(self.missing_sqlite_threads),
            "missing_session_index_threads": len(self.missing_session_index_threads),
            "projects": [project.to_dict() for project in self.projects],
        }


@dataclass
class RepairResult:
    backup_dir: Path
    inserted_sqlite_threads: int
    added_session_index_entries: int
    provider_bridge_target: str = ""
    provider_bridged_rollouts: int = 0
    provider_bridged_sqlite_threads: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_dir": str(self.backup_dir),
            "inserted_sqlite_threads": self.inserted_sqlite_threads,
            "added_session_index_entries": self.added_session_index_entries,
            "provider_bridge_target": self.provider_bridge_target,
            "provider_bridged_rollouts": self.provider_bridged_rollouts,
            "provider_bridged_sqlite_threads": self.provider_bridged_sqlite_threads,
        }


@dataclass
class DeleteResult:
    backup_dir: Path
    thread_id: str
    title: str
    removed_sqlite_threads: int
    removed_session_index_entries: int
    rollout_moved: bool
    backup_rollout_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_dir": str(self.backup_dir),
            "thread_id": self.thread_id,
            "title": self.title,
            "removed_sqlite_threads": self.removed_sqlite_threads,
            "removed_session_index_entries": self.removed_session_index_entries,
            "rollout_moved": self.rollout_moved,
            "backup_rollout_path": str(self.backup_rollout_path) if self.backup_rollout_path else "",
        }


class ThreadNotFoundError(ValueError):
    pass


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def build_unified_index(codex_home: str | Path | None = None) -> UnifiedIndex:
    home = Path(codex_home) if codex_home else default_codex_home()
    session_records = _read_session_rollouts(home)
    sqlite_records = _read_sqlite_threads(home)
    session_index = _read_session_index(home)

    records: dict[str, ThreadRecord] = {}
    for thread_id, record in session_records.items():
        records[thread_id] = record

    for thread_id, sqlite_record in sqlite_records.items():
        existing = records.get(thread_id)
        if existing is None:
            records[thread_id] = sqlite_record
        else:
            records[thread_id] = _merge_thread(existing, sqlite_record)

    for thread_id, indexed in session_index.items():
        existing = records.get(thread_id)
        if existing is None:
            records[thread_id] = ThreadRecord(
                id=thread_id,
                title=indexed.get("thread_name") or thread_id,
                cwd="(unknown)",
                rollout_path="",
                created_at_ms=_iso_to_ms(indexed.get("updated_at")),
                updated_at_ms=_iso_to_ms(indexed.get("updated_at")),
                in_session_index=True,
            )
            continue
        existing.in_session_index = True
        if not _has_text(existing.title):
            existing.title = indexed.get("thread_name") or existing.id

    projects_by_cwd: dict[str, ProjectRecord] = {}
    for record in records.values():
        record.title = _clean_title(record.title or record.first_user_message or record.id)
        record.preview = record.preview or record.first_user_message or record.title
        record.cwd = _normalize_cwd(record.cwd)
        projects_by_cwd.setdefault(record.cwd, ProjectRecord(record.cwd)).threads.append(record)

    for project in projects_by_cwd.values():
        project.threads.sort(key=lambda item: item.updated_at_ms, reverse=True)

    projects = sorted(projects_by_cwd.values(), key=lambda item: item.latest_updated_at_ms, reverse=True)
    all_threads = [thread for project in projects for thread in project.threads]
    return UnifiedIndex(
        codex_home=home,
        projects=projects,
        missing_sqlite_threads=[thread for thread in all_threads if not thread.in_sqlite and thread.rollout_path],
        missing_session_index_threads=[thread for thread in all_threads if not thread.in_session_index],
    )


def repair_codex_indexes(codex_home: str | Path | None = None) -> RepairResult:
    home = Path(codex_home) if codex_home else default_codex_home()
    backup_dir = _backup_codex_indexes(home)
    provider_bridge_target, provider_bridged_rollouts, provider_bridged_sqlite = _bridge_interactive_threads_to_current_provider(
        home,
        backup_dir,
    )
    index = build_unified_index(home)

    inserted_sqlite = _insert_missing_sqlite_threads(home, index.missing_sqlite_threads)
    added_session_index = _append_missing_session_index(home, index.missing_session_index_threads)

    return RepairResult(
        backup_dir=backup_dir,
        inserted_sqlite_threads=inserted_sqlite,
        added_session_index_entries=added_session_index,
        provider_bridge_target=provider_bridge_target,
        provider_bridged_rollouts=provider_bridged_rollouts,
        provider_bridged_sqlite_threads=provider_bridged_sqlite,
    )


def delete_thread(codex_home: str | Path | None, thread_id: str) -> DeleteResult:
    home = Path(codex_home) if codex_home else default_codex_home()
    clean_thread_id = str(thread_id).strip()
    if not clean_thread_id:
        raise ThreadNotFoundError("线程 ID 不能为空。")

    thread = _find_thread(build_unified_index(home), clean_thread_id)
    if thread is None:
        raise ThreadNotFoundError(f"没有找到线程: {clean_thread_id}")

    backup_dir = _backup_codex_indexes(home)
    backup_rollout_path, rollout_moved = _move_rollout_to_backup(home, backup_dir, thread)
    removed_sqlite = _delete_sqlite_thread(home, clean_thread_id)
    removed_session_index = _remove_session_index_entry(home, clean_thread_id)

    return DeleteResult(
        backup_dir=backup_dir,
        thread_id=clean_thread_id,
        title=thread.title,
        removed_sqlite_threads=removed_sqlite,
        removed_session_index_entries=removed_session_index,
        rollout_moved=rollout_moved,
        backup_rollout_path=backup_rollout_path,
    )


def _read_session_rollouts(home: Path) -> dict[str, ThreadRecord]:
    sessions_dir = home / "sessions"
    if not sessions_dir.exists():
        return {}

    records: dict[str, ThreadRecord] = {}
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        record = _read_rollout(path)
        if record is not None:
            records[record.id] = record
    return records


def _read_rollout(path: Path) -> ThreadRecord | None:
    meta: dict[str, Any] | None = None
    first_user_message = ""
    sandbox_policy = "unknown"
    approval_mode = "unknown"
    model = None
    reasoning_effort = None
    updated_ms = 0

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                updated_ms = max(updated_ms, _iso_to_ms(row.get("timestamp")))
                row_type = row.get("type")
                payload = row.get("payload") or {}
                if row_type == "session_meta" and meta is None:
                    meta = payload
                    continue
                if row_type == "turn_context":
                    sandbox = payload.get("sandbox_policy")
                    if isinstance(sandbox, dict):
                        sandbox_policy = sandbox.get("type") or sandbox_policy
                    approval_mode = payload.get("approval_policy") or approval_mode
                    model = payload.get("model") or model
                    continue
                if row_type == "response_item" and not first_user_message:
                    if payload.get("type") == "message" and payload.get("role") == "user":
                        candidate = _extract_text_content(payload.get("content"))
                        if _is_real_user_message(candidate):
                            first_user_message = candidate
    except OSError:
        return None

    if not meta:
        return None

    thread_id = meta.get("id") or _id_from_rollout_path(path)
    if not thread_id:
        return None

    created_ms = _iso_to_ms(meta.get("timestamp")) or updated_ms or _file_mtime_ms(path)
    updated_ms = updated_ms or _file_mtime_ms(path)
    title = _clean_title(first_user_message) or thread_id
    return ThreadRecord(
        id=str(thread_id),
        title=title,
        cwd=_normalize_cwd(str(meta.get("cwd") or "(unknown)")),
        rollout_path=str(path),
        created_at_ms=created_ms,
        updated_at_ms=max(updated_ms, created_ms),
        source=str(meta.get("source") or "unknown"),
        model_provider=str(meta.get("model_provider") or "unknown"),
        first_user_message=first_user_message,
        preview=first_user_message,
        cli_version=str(meta.get("cli_version") or ""),
        sandbox_policy=sandbox_policy,
        approval_mode=approval_mode,
        model=model,
        reasoning_effort=reasoning_effort,
        thread_source=str(meta.get("thread_source") or "user"),
    )


def _read_sqlite_threads(home: Path) -> dict[str, ThreadRecord]:
    db_path = home / "state_5.sqlite"
    if not db_path.exists():
        return {}
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        if not _has_table(con, "threads"):
            return {}
        rows = con.execute("select * from threads").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if con is not None:
            con.close()

    records: dict[str, ThreadRecord] = {}
    for row in rows:
        data = dict(row)
        thread_id = data.get("id")
        if not thread_id:
            continue
        created_ms = _coerce_int(data.get("created_at_ms")) or _coerce_int(data.get("created_at")) * 1000
        updated_ms = _coerce_int(data.get("updated_at_ms")) or _coerce_int(data.get("updated_at")) * 1000
        title = data.get("title") or data.get("first_user_message") or thread_id
        records[str(thread_id)] = ThreadRecord(
            id=str(thread_id),
            title=_clean_title(str(title)),
            cwd=_normalize_cwd(str(data.get("cwd") or "(unknown)")),
            rollout_path=str(data.get("rollout_path") or ""),
            created_at_ms=created_ms,
            updated_at_ms=max(updated_ms, created_ms),
            source=str(data.get("source") or "unknown"),
            model_provider=str(data.get("model_provider") or "unknown"),
            first_user_message=str(data.get("first_user_message") or ""),
            preview=str(data.get("preview") or data.get("first_user_message") or title),
            cli_version=str(data.get("cli_version") or ""),
            sandbox_policy=str(data.get("sandbox_policy") or "unknown"),
            approval_mode=str(data.get("approval_mode") or "unknown"),
            memory_mode=str(data.get("memory_mode") or "enabled"),
            model=data.get("model"),
            reasoning_effort=data.get("reasoning_effort"),
            thread_source=data.get("thread_source") or "user",
            in_sqlite=True,
        )
    return records


def _read_session_index(home: Path) -> dict[str, dict[str, Any]]:
    path = home / "session_index.jsonl"
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                thread_id = row.get("id")
                if thread_id:
                    rows[str(thread_id)] = row
    except OSError:
        return {}
    return rows


def _merge_thread(session_record: ThreadRecord, sqlite_record: ThreadRecord) -> ThreadRecord:
    session_record.in_sqlite = True
    session_record.rollout_path = sqlite_record.rollout_path or session_record.rollout_path
    session_record.title = sqlite_record.title or session_record.title
    session_record.preview = sqlite_record.preview or session_record.preview
    session_record.cwd = sqlite_record.cwd or session_record.cwd
    session_record.created_at_ms = min(
        value for value in [session_record.created_at_ms, sqlite_record.created_at_ms] if value
    )
    session_record.updated_at_ms = max(session_record.updated_at_ms, sqlite_record.updated_at_ms)
    session_record.source = sqlite_record.source or session_record.source
    session_record.model_provider = sqlite_record.model_provider or session_record.model_provider
    session_record.cli_version = sqlite_record.cli_version or session_record.cli_version
    session_record.sandbox_policy = sqlite_record.sandbox_policy or session_record.sandbox_policy
    session_record.approval_mode = sqlite_record.approval_mode or session_record.approval_mode
    session_record.model = sqlite_record.model or session_record.model
    session_record.reasoning_effort = sqlite_record.reasoning_effort or session_record.reasoning_effort
    session_record.thread_source = sqlite_record.thread_source or session_record.thread_source
    return session_record


def _backup_codex_indexes(home: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = home / "codex-local-backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "config.toml",
        "state_5.sqlite",
        "state_5.sqlite-shm",
        "state_5.sqlite-wal",
        "session_index.jsonl",
    ]:
        source = home / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    return backup_dir


def _bridge_interactive_threads_to_current_provider(home: Path, backup_dir: Path) -> tuple[str, int, int]:
    target_provider = _read_current_model_provider(home)
    if not target_provider:
        return "", 0, 0

    bridged_rollouts = _bridge_rollout_providers(home, backup_dir, target_provider)
    bridged_sqlite = _bridge_sqlite_providers(home, target_provider)
    return target_provider, bridged_rollouts, bridged_sqlite


def _read_current_model_provider(home: Path) -> str:
    config_path = home / "config.toml"
    if not config_path.exists():
        return ""
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    provider = data.get("model_provider")
    return provider.strip() if isinstance(provider, str) else ""


def _bridge_rollout_providers(home: Path, backup_dir: Path, target_provider: str) -> int:
    sessions_dir = home / "sessions"
    if not sessions_dir.exists():
        return 0

    changed = 0
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            continue
        updated_lines = _bridge_rollout_lines(lines, target_provider)
        if updated_lines is None:
            continue
        backup_path = backup_dir / _backup_relative_path(home, path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)
        path.write_text("".join(updated_lines), encoding="utf-8", newline="")
        changed += 1
    return changed


def _bridge_rollout_lines(lines: list[str], target_provider: str) -> list[str] | None:
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "session_meta":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or not _is_interactive_source(payload.get("source")):
            return None
        if payload.get("model_provider") == target_provider:
            return None
        payload["model_provider"] = target_provider
        line_ending = "\n" if line.endswith("\n") else ""
        lines[index] = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + line_ending
        return lines
    return None


def _bridge_sqlite_providers(home: Path, target_provider: str) -> int:
    db_path = home / "state_5.sqlite"
    if not db_path.exists():
        return 0

    con = sqlite3.connect(db_path, timeout=30)
    try:
        if not _has_table(con, "threads"):
            return 0
        cursor = con.execute(
            """
            update threads
            set model_provider = ?
            where source in ('vscode', 'cli', 'appServer')
              and model_provider <> ?
            """,
            (target_provider, target_provider),
        )
        con.commit()
        return cursor.rowcount if cursor.rowcount is not None else 0
    finally:
        con.close()


def _insert_missing_sqlite_threads(home: Path, threads: list[ThreadRecord]) -> int:
    if not threads:
        return 0
    db_path = home / "state_5.sqlite"
    if not db_path.exists():
        return 0

    con = sqlite3.connect(db_path)
    try:
        if not _has_table(con, "threads"):
            return 0
        existing_columns = {row[1] for row in con.execute("pragma table_info('threads')").fetchall()}
        columns = [column for column in THREAD_TABLE_INSERT_COLUMNS if column in existing_columns]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        sql = f"insert or ignore into threads ({column_sql}) values ({placeholders})"

        inserted = 0
        for thread in threads:
            before = con.total_changes
            con.execute(sql, [_thread_insert_value(thread, column) for column in columns])
            if con.total_changes > before:
                inserted += 1
        con.commit()
        return inserted
    finally:
        con.close()


def _append_missing_session_index(home: Path, threads: list[ThreadRecord]) -> int:
    if not threads:
        return 0
    path = home / "session_index.jsonl"
    existing = _read_session_index(home)
    additions = [thread for thread in threads if thread.id not in existing]
    if not additions:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for thread in additions:
            row = {
                "id": thread.id,
                "thread_name": _clean_title(thread.title or thread.id),
                "updated_at": thread.updated_at_iso,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(additions)


def _find_thread(index: UnifiedIndex, thread_id: str) -> ThreadRecord | None:
    for project in index.projects:
        for thread in project.threads:
            if thread.id == thread_id:
                return thread
    return None


def _move_rollout_to_backup(home: Path, backup_dir: Path, thread: ThreadRecord) -> tuple[Path | None, bool]:
    if not thread.rollout_path:
        return None, False

    source = Path(thread.rollout_path)
    if not source.exists() or not source.is_file():
        return None, False

    target = backup_dir / _backup_relative_path(home, source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target, True


def _backup_relative_path(home: Path, source: Path) -> Path:
    try:
        return source.resolve().relative_to(home.resolve())
    except (OSError, ValueError):
        safe_name = str(source).replace(":", "").replace("\\", "_").replace("/", "_")
        return Path("external-rollouts") / safe_name


def _delete_sqlite_thread(home: Path, thread_id: str) -> int:
    db_path = home / "state_5.sqlite"
    if not db_path.exists():
        return 0

    con = sqlite3.connect(db_path)
    try:
        if not _has_table(con, "threads"):
            return 0
        before = con.total_changes
        con.execute("delete from threads where id = ?", (thread_id,))
        con.commit()
        return con.total_changes - before
    finally:
        con.close()


def _remove_session_index_entry(home: Path, thread_id: str) -> int:
    path = home / "session_index.jsonl"
    if not path.exists():
        return 0

    kept_lines: list[str] = []
    removed = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            should_keep = True
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    row = {}
                if str(row.get("id") or "") == thread_id:
                    should_keep = False
                    removed += 1
            if should_keep:
                kept_lines.append(line if line.endswith("\n") else f"{line}\n")

    if removed:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(kept_lines)
    return removed


def _thread_insert_value(thread: ThreadRecord, column: str) -> Any:
    values = {
        "id": thread.id,
        "rollout_path": thread.rollout_path,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "source": thread.source or "unknown",
        "model_provider": thread.model_provider or "unknown",
        "cwd": thread.cwd,
        "title": _clean_title(thread.title or thread.id),
        "sandbox_policy": thread.sandbox_policy or "unknown",
        "approval_mode": thread.approval_mode or "unknown",
        "tokens_used": 0,
        "has_user_event": 1 if thread.first_user_message else 0,
        "archived": 0,
        "cli_version": thread.cli_version or "",
        "first_user_message": thread.first_user_message or "",
        "memory_mode": thread.memory_mode or "enabled",
        "model": thread.model,
        "reasoning_effort": thread.reasoning_effort,
        "created_at_ms": thread.created_at_ms,
        "updated_at_ms": thread.updated_at_ms,
        "thread_source": thread.thread_source or "user",
        "preview": thread.preview or thread.first_user_message or thread.title,
    }
    return values[column]


def _has_table(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
            if item.get("type") in {"input_text", "text"} and isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _is_real_user_message(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    ignored_prefixes = (
        "# AGENTS.md instructions",
        "<environment_context>",
        "<turn_aborted>",
    )
    return not any(stripped.startswith(prefix) for prefix in ignored_prefixes)


def _is_interactive_source(source: Any) -> bool:
    return isinstance(source, str) and source in {"vscode", "cli", "appServer"}


def _clean_title(text: str) -> str:
    title = " ".join(text.replace("\r", "\n").split())
    if len(title) > 120:
        return title[:117] + "..."
    return title


def _normalize_cwd(cwd: str) -> str:
    value = cwd.strip()
    if value.startswith("\\\\?\\"):
        value = value[4:]
    return value or "(unknown)"


def _id_from_rollout_path(path: Path) -> str:
    stem = path.stem
    if "-" not in stem:
        return stem
    return stem.rsplit("-", 1)[-1]


def _file_mtime_ms(path: Path) -> int:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return 0


def _iso_to_ms(value: Any) -> int:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return 0


def _ms_to_iso(value: int) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
