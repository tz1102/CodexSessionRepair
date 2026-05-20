import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_local.core import build_unified_index, delete_thread, repair_codex_indexes


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def create_state_db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute(
        """
        create table threads (
            id text primary key,
            rollout_path text not null,
            created_at integer not null,
            updated_at integer not null,
            source text not null,
            model_provider text not null,
            cwd text not null,
            title text not null,
            sandbox_policy text not null,
            approval_mode text not null,
            tokens_used integer not null default 0,
            has_user_event integer not null default 0,
            archived integer not null default 0,
            archived_at integer,
            git_sha text,
            git_branch text,
            git_origin_url text,
            cli_version text not null default '',
            first_user_message text not null default '',
            agent_nickname text,
            agent_role text,
            memory_mode text not null default 'enabled',
            model text,
            reasoning_effort text,
            agent_path text,
            created_at_ms integer,
            updated_at_ms integer,
            thread_source text,
            preview text not null default ''
        )
        """
    )
    for row in rows:
        con.execute(
            """
            insert into threads (
                id, rollout_path, created_at, updated_at, source, model_provider,
                cwd, title, sandbox_policy, approval_mode, tokens_used,
                has_user_event, archived, cli_version, first_user_message,
                memory_mode, created_at_ms, updated_at_ms, thread_source, preview
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, '', '', 0, 1, 0, ?, ?, 'enabled', ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["rollout_path"],
                row["created_at"],
                row["updated_at"],
                row.get("source", "vscode"),
                row.get("model_provider", "openai"),
                row["cwd"],
                row["title"],
                row.get("cli_version", ""),
                row.get("first_user_message", ""),
                row.get("created_at_ms"),
                row.get("updated_at_ms"),
                row.get("thread_source", "user"),
                row.get("preview", ""),
            ),
        )
    con.commit()
    con.close()


class CodexLocalIndexTests(unittest.TestCase):

    def test_build_unified_index_recovers_threads_missing_from_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            existing_rollout = home / "sessions/2026/05/01/rollout-2026-05-01T10-00-00-thread-a.jsonl"
            missing_rollout = home / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-b.jsonl"
            write_jsonl(existing_rollout, [
                {
                    "timestamp": "2026-05-01T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-a",
                        "timestamp": "2026-05-01T02:00:00.000Z",
                        "cwd": r"\\?\D:\idea_space\alpha",
                        "source": "vscode",
                        "model_provider": "openai",
                    },
                }
            ])
            write_jsonl(missing_rollout, [
                {
                    "timestamp": "2026-05-02T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-b",
                        "timestamp": "2026-05-02T02:00:00.000Z",
                        "cwd": r"D:\idea_space\beta",
                        "source": "vscode",
                        "model_provider": "openai",
                    },
                },
                {
                    "timestamp": "2026-05-02T02:00:01.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "帮我继续这个工程"}],
                    },
                },
            ])
            write_jsonl(home / "session_index.jsonl", [
                {"id": "thread-a", "thread_name": "已有线程", "updated_at": "2026-05-01T02:00:00Z"}
            ])
            create_state_db(home / "state_5.sqlite", [
                {
                    "id": "thread-a",
                    "rollout_path": str(existing_rollout),
                    "created_at": 1,
                    "updated_at": 1,
                    "cwd": r"\\?\D:\idea_space\alpha",
                    "title": "已有线程",
                    "created_at_ms": 1,
                    "updated_at_ms": 1,
                    "preview": "已有线程",
                }
            ])

            index = build_unified_index(home)

            self.assertEqual(index.total_threads, 2)
            self.assertEqual([project.cwd for project in index.projects], [r"D:\idea_space\beta", r"D:\idea_space\alpha"])
            beta = index.projects[0]
            self.assertEqual(beta.thread_count, 1)
            self.assertEqual(beta.threads[0].id, "thread-b")
            self.assertFalse(beta.threads[0].in_sqlite)
            self.assertEqual(beta.threads[0].title, "帮我继续这个工程")

    def test_repair_adds_missing_threads_and_updates_session_index_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            rollout = home / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-b.jsonl"
            write_jsonl(rollout, [
                {
                    "timestamp": "2026-05-02T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-b",
                        "timestamp": "2026-05-02T02:00:00.000Z",
                        "cwd": r"D:\idea_space\beta",
                        "source": "vscode",
                        "model_provider": "openai",
                        "cli_version": "0.test",
                    },
                },
                {
                    "timestamp": "2026-05-02T02:00:01.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "修复本地线程可见性"}],
                    },
                },
            ])
            write_jsonl(home / "session_index.jsonl", [])
            create_state_db(home / "state_5.sqlite", [])

            result = repair_codex_indexes(home)

            self.assertEqual(result.inserted_sqlite_threads, 1)
            self.assertEqual(result.added_session_index_entries, 1)
            self.assertTrue(result.backup_dir.exists())
            index_lines = (home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(index_lines), 1)
            self.assertEqual(json.loads(index_lines[0])["id"], "thread-b")

            con = sqlite3.connect(home / "state_5.sqlite")
            row = con.execute("select id, cwd, title from threads where id = 'thread-b'").fetchone()
            con.close()
            self.assertEqual(row, ("thread-b", r"D:\idea_space\beta", "修复本地线程可见性"))

    def test_repair_bridges_interactive_threads_to_current_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config.toml").write_text('model_provider = "custom"\n', encoding="utf-8")
            interactive_rollout = home / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-b.jsonl"
            subagent_rollout = home / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-c.jsonl"
            write_jsonl(interactive_rollout, [
                {
                    "timestamp": "2026-05-02T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-b",
                        "timestamp": "2026-05-02T02:00:00.000Z",
                        "cwd": r"D:\idea_space\beta",
                        "source": "vscode",
                        "model_provider": "openai",
                    },
                }
            ])
            write_jsonl(subagent_rollout, [
                {
                    "timestamp": "2026-05-02T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-c",
                        "timestamp": "2026-05-02T02:00:00.000Z",
                        "cwd": r"D:\idea_space\beta",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "thread-b"}}},
                        "model_provider": "my9527",
                    },
                }
            ])
            write_jsonl(home / "session_index.jsonl", [])
            create_state_db(home / "state_5.sqlite", [
                {
                    "id": "thread-b",
                    "rollout_path": str(interactive_rollout),
                    "created_at": 1,
                    "updated_at": 1,
                    "cwd": r"D:\idea_space\beta",
                    "title": "old provider thread",
                    "model_provider": "openai",
                    "created_at_ms": 1,
                    "updated_at_ms": 1,
                    "preview": "old provider thread",
                },
                {
                    "id": "thread-c",
                    "rollout_path": str(subagent_rollout),
                    "created_at": 1,
                    "updated_at": 1,
                    "cwd": r"D:\idea_space\beta",
                    "title": "subagent thread",
                    "source": '{"subagent":{"thread_spawn":{"parent_thread_id":"thread-b"}}}',
                    "model_provider": "my9527",
                    "created_at_ms": 1,
                    "updated_at_ms": 1,
                    "preview": "subagent thread",
                },
            ])

            result = repair_codex_indexes(home)

            self.assertEqual(result.provider_bridge_target, "custom")
            self.assertEqual(result.provider_bridged_rollouts, 1)
            self.assertEqual(result.provider_bridged_sqlite_threads, 1)

            interactive_meta = json.loads(interactive_rollout.read_text(encoding="utf-8").splitlines()[0])
            subagent_meta = json.loads(subagent_rollout.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(interactive_meta["payload"]["model_provider"], "custom")
            self.assertEqual(subagent_meta["payload"]["model_provider"], "my9527")
            self.assertTrue((result.backup_dir / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-b.jsonl").exists())

            con = sqlite3.connect(home / "state_5.sqlite")
            providers = dict(con.execute("select id, model_provider from threads").fetchall())
            con.close()
            self.assertEqual(providers["thread-b"], "custom")
            self.assertEqual(providers["thread-c"], "my9527")

    def test_delete_thread_removes_indexes_and_moves_rollout_to_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            rollout = home / "sessions/2026/05/02/rollout-2026-05-02T10-00-00-thread-b.jsonl"
            write_jsonl(rollout, [
                {
                    "timestamp": "2026-05-02T02:00:00.000Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-b",
                        "timestamp": "2026-05-02T02:00:00.000Z",
                        "cwd": r"D:\idea_space\beta",
                        "source": "vscode",
                        "model_provider": "openai",
                    },
                }
            ])
            write_jsonl(home / "session_index.jsonl", [
                {"id": "thread-b", "thread_name": "要删除的线程", "updated_at": "2026-05-02T02:00:00Z"},
                {"id": "thread-c", "thread_name": "保留线程", "updated_at": "2026-05-03T02:00:00Z"},
            ])
            create_state_db(home / "state_5.sqlite", [
                {
                    "id": "thread-b",
                    "rollout_path": str(rollout),
                    "created_at": 1,
                    "updated_at": 1,
                    "cwd": r"D:\idea_space\beta",
                    "title": "要删除的线程",
                    "created_at_ms": 1,
                    "updated_at_ms": 1,
                    "preview": "要删除的线程",
                }
            ])

            result = delete_thread(home, "thread-b")

            self.assertEqual(result.thread_id, "thread-b")
            self.assertEqual(result.removed_sqlite_threads, 1)
            self.assertEqual(result.removed_session_index_entries, 1)
            self.assertTrue(result.rollout_moved)
            self.assertFalse(rollout.exists())
            self.assertTrue(result.backup_rollout_path.exists())
            self.assertTrue((result.backup_dir / "state_5.sqlite").exists())
            self.assertTrue((result.backup_dir / "session_index.jsonl").exists())

            remaining_index_rows = [
                json.loads(line)
                for line in (home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([row["id"] for row in remaining_index_rows], ["thread-c"])

            con = sqlite3.connect(home / "state_5.sqlite")
            row_count = con.execute("select count(*) from threads where id = 'thread-b'").fetchone()[0]
            con.close()
            self.assertEqual(row_count, 0)

            index = build_unified_index(home)
            self.assertNotIn("thread-b", [thread.id for project in index.projects for thread in project.threads])


if __name__ == "__main__":
    unittest.main()
