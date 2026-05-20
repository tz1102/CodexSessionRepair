from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import build_unified_index, default_codex_home, delete_thread, repair_codex_indexes, ThreadNotFoundError
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codex-local",
        description="让同一台电脑上的 Codex 本地项目和线程不再被账号/token 登录方式切开。",
    )
    parser.add_argument(
        "--codex-home",
        default=str(default_codex_home()),
        help="Codex 本地数据目录，默认是当前用户的 ~/.codex。",
    )
    subparsers = parser.add_subparsers(dest="command")

    open_parser = subparsers.add_parser("open", help="打开本地统一视图。")
    open_parser.add_argument("--host", default="127.0.0.1")
    open_parser.add_argument("--port", type=int, default=8787)
    open_parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器。")

    subparsers.add_parser("list", help="在命令行打印统一后的项目和线程概览。")
    subparsers.add_parser("doctor", help="检查当前是否存在索引缺失。")
    subparsers.add_parser("repair", help="备份后修复 Codex 本地索引。")
    delete_parser = subparsers.add_parser("delete", help="备份后删除指定线程。")
    delete_parser.add_argument("thread_id", help="要删除的线程 ID。")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="跳过交互确认。")

    args = parser.parse_args()
    command = args.command or "open"
    codex_home = Path(args.codex_home)

    if command == "open":
        serve(codex_home, host=args.host, port=args.port, open_browser=not args.no_browser)
        return
    if command == "list":
        _print_list(codex_home)
        return
    if command == "doctor":
        _print_doctor(codex_home)
        return
    if command == "repair":
        result = repair_codex_indexes(codex_home)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    if command == "delete":
        _print_delete(codex_home, args.thread_id, args.yes)
        return
    parser.print_help()


def _print_list(codex_home: Path) -> None:
    index = build_unified_index(codex_home)
    print(f"Codex 本地目录: {index.codex_home}")
    print(f"项目: {index.total_projects}，线程: {index.total_threads}")
    for project in index.projects:
        print(f"\n[{project.thread_count}] {project.cwd}")
        for thread in project.threads[:8]:
            flags = []
            if not thread.in_sqlite:
                flags.append("缺 sqlite")
            if not thread.in_session_index:
                flags.append("缺 index")
            suffix = f" ({', '.join(flags)})" if flags else ""
            print(f"  - {thread.title}{suffix}")


def _print_doctor(codex_home: Path) -> None:
    index = build_unified_index(codex_home)
    print(f"项目: {index.total_projects}，线程: {index.total_threads}")
    print(f"缺 sqlite 索引: {len(index.missing_sqlite_threads)}")
    print(f"缺 session_index 索引: {len(index.missing_session_index_threads)}")
    if index.missing_sqlite_threads or index.missing_session_index_threads:
        print("可运行: .\\codex-local.cmd repair")
    else:
        print("本地索引看起来是完整的。")


def _print_delete(codex_home: Path, thread_id: str, yes: bool) -> None:
    if not yes:
        answer = input(f"将备份后删除线程 {thread_id}。输入 DELETE 确认: ")
        if answer != "DELETE":
            print("已取消。")
            return
    try:
        result = delete_thread(codex_home, thread_id)
    except ThreadNotFoundError as exc:
        print(str(exc))
        raise SystemExit(1) from exc
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
