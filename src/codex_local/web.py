from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import ThreadNotFoundError, build_unified_index, delete_thread, delete_threads, repair_codex_indexes


def serve(codex_home: Path, host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(codex_home))
    url = f"http://{host}:{port}"
    print(f"Codex Local 正在运行: {url}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


def _make_handler(codex_home: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(_INDEX_HTML)
                return
            if parsed.path == "/api/index":
                query = parse_qs(parsed.query)
                home = Path(query.get("codexHome", [str(codex_home)])[0])
                self._send_json(build_unified_index(home).to_dict())
                return
            self.send_error(404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/repair":
                self._send_json(repair_codex_indexes(codex_home).to_dict())
                return
            if parsed.path == "/api/delete":
                payload = self._read_json_body()
                thread_id = str(payload.get("thread_id") or "").strip()
                if not thread_id:
                    self._send_json({"error": "缺少 thread_id。"}, status=400)
                    return
                try:
                    self._send_json(delete_thread(codex_home, thread_id).to_dict())
                except ThreadNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=404)
                return
            if parsed.path == "/api/delete-batch":
                payload = self._read_json_body()
                raw_thread_ids = payload.get("thread_ids")
                if not isinstance(raw_thread_ids, list):
                    self._send_json({"error": "缺少 thread_ids。"}, status=400)
                    return
                thread_ids = [str(thread_id).strip() for thread_id in raw_thread_ids if str(thread_id).strip()]
                if not thread_ids:
                    self._send_json({"error": "至少选择一个线程。"}, status=400)
                    return
                self._send_json(delete_threads(codex_home, thread_ids).to_dict())
                return
            self.send_error(404)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


_INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Local</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #18202a;
      --muted: #667085;
      --line: #d8dee7;
      --accent: #1463ff;
      --warning: #a45b00;
      --ok: #247a3f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
      font-size: 14px;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 2;
      background: rgba(246, 247, 249, 0.94);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--line);
    }
    .bar {
      max-width: 1180px;
      margin: 0 auto;
      padding: 16px 20px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }
    .sub {
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
    }
    .actions {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    button, input {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      font: inherit;
    }
    button {
      padding: 0 12px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 18px 20px 36px;
    }
    .status {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .metric b {
      display: block;
      font-size: 22px;
      margin-bottom: 4px;
    }
    .metric span { color: var(--muted); }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) auto auto auto auto auto;
      gap: 10px;
      margin-bottom: 12px;
      align-items: center;
    }
    input {
      width: 100%;
      padding: 0 12px;
    }
    input.thread-check {
      width: 18px;
      height: 18px;
      margin: 0;
      padding: 0;
      accent-color: var(--accent);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    button.danger-action {
      border-color: #d92d20;
      color: #b42318;
      background: #fff5f3;
    }
    .selected-count {
      color: var(--muted);
      white-space: nowrap;
    }
    .project {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 10px;
      overflow: hidden;
    }
    .project-head {
      padding: 12px 14px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      border-bottom: 1px solid var(--line);
      cursor: pointer;
    }
    .cwd {
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .counts {
      color: var(--muted);
      white-space: nowrap;
    }
    .thread {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 12px;
      padding: 11px 14px;
      border-bottom: 1px solid #edf0f4;
      align-items: start;
    }
    .thread:last-child { border-bottom: 0; }
    .thread-select {
      display: flex;
      align-items: start;
      padding-top: 2px;
    }
    .title {
      font-weight: 560;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .meta {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .badges {
      display: flex;
      gap: 6px;
      align-items: start;
      white-space: nowrap;
    }
    .thread-tools {
      display: flex;
      gap: 8px;
      align-items: start;
      justify-content: end;
      white-space: nowrap;
    }
    .thread-tools .badges {
      white-space: inherit;
    }
    .badge {
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 2px 8px;
      font-size: 12px;
      color: var(--muted);
    }
    .badge.warn {
      border-color: #f1c27d;
      color: var(--warning);
      background: #fff7ec;
    }
    .badge.ok {
      border-color: #a7d7b8;
      color: var(--ok);
      background: #f0fbf4;
    }
    button.danger {
      height: 26px;
      border-color: #d92d20;
      color: #b42318;
      background: #fff5f3;
      padding: 0 9px;
    }
    .empty {
      background: var(--panel);
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 760px) {
      .bar, .toolbar, .project-head, .thread { grid-template-columns: 1fr; }
      .actions { justify-content: start; flex-wrap: wrap; }
      .status { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .badges, .thread-tools { white-space: normal; flex-wrap: wrap; justify-content: start; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>Codex Local</h1>
        <div class="sub" id="home">读取本机 Codex 数据中...</div>
      </div>
      <div class="actions">
        <button id="refresh">刷新</button>
        <button class="primary" id="repair">修复索引</button>
      </div>
    </div>
  </header>
  <main>
    <section class="status">
      <div class="metric"><b id="projects">0</b><span>项目</span></div>
      <div class="metric"><b id="threads">0</b><span>线程</span></div>
      <div class="metric"><b id="sqliteMissing">0</b><span>缺 sqlite 索引</span></div>
      <div class="metric"><b id="indexMissing">0</b><span>缺列表索引</span></div>
    </section>
    <div class="toolbar">
      <input id="filter" placeholder="搜索项目路径或线程标题">
      <button id="expand">展开/收起</button>
      <button id="selectVisible">选择当前</button>
      <button id="clearSelected">清空选择</button>
      <button class="danger-action" id="deleteSelected" disabled>批量删除</button>
      <span class="selected-count" id="selectedCount">已选 0 个</span>
    </div>
    <section id="content"></section>
  </main>
  <script>
    let data = null;
    let collapsed = new Set();
    let selected = new Set();

    const $ = (id) => document.getElementById(id);

    async function load() {
      const res = await fetch('/api/index');
      data = await res.json();
      render();
    }

    function render() {
      if (!data) return;
      pruneSelection();
      $('home').textContent = `本地目录：${data.codex_home}`;
      $('projects').textContent = data.total_projects;
      $('threads').textContent = data.total_threads;
      $('sqliteMissing').textContent = data.missing_sqlite_threads;
      $('indexMissing').textContent = data.missing_session_index_threads;
      $('selectedCount').textContent = `已选 ${selected.size} 个`;
      $('deleteSelected').disabled = selected.size === 0;
      $('clearSelected').disabled = selected.size === 0;

      const q = $('filter').value.trim().toLowerCase();
      const projects = data.projects
        .map(project => ({
          ...project,
          threads: project.threads.filter(thread => {
            const haystack = `${project.cwd} ${thread.title} ${thread.preview}`.toLowerCase();
            return !q || haystack.includes(q);
          })
        }))
        .filter(project => project.threads.length);

      if (!projects.length) {
        $('content').innerHTML = '<div class="empty">没有匹配的本地线程。</div>';
        return;
      }

      $('content').innerHTML = projects.map(project => {
        const isCollapsed = collapsed.has(project.cwd);
        const body = isCollapsed ? '' : project.threads.map(renderThread).join('');
        return `<article class="project">
          <div class="project-head" data-cwd="${escapeHtml(project.cwd)}">
            <div class="cwd">${escapeHtml(project.cwd)}</div>
            <div class="counts">${project.threads.length} 个线程 · ${escapeHtml(project.latest_updated_at_iso || '')}</div>
          </div>
          ${body}
        </article>`;
      }).join('');

      document.querySelectorAll('.project-head').forEach(el => {
        el.addEventListener('click', () => {
          const cwd = el.dataset.cwd;
          if (collapsed.has(cwd)) collapsed.delete(cwd);
          else collapsed.add(cwd);
          render();
        });
      });
      document.querySelectorAll('[data-delete-thread]').forEach(el => {
        el.addEventListener('click', (event) => {
          event.stopPropagation();
          deleteThread(el.dataset.deleteThread);
        });
      });
      document.querySelectorAll('[data-select-thread]').forEach(el => {
        el.addEventListener('click', (event) => {
          event.stopPropagation();
        });
        el.addEventListener('change', () => {
          if (el.checked) selected.add(el.dataset.selectThread);
          else selected.delete(el.dataset.selectThread);
          render();
        });
      });
    }

    function renderThread(thread) {
      const badges = [];
      if (!thread.in_sqlite) badges.push('<span class="badge warn">缺 sqlite</span>');
      if (!thread.in_session_index) badges.push('<span class="badge warn">缺列表</span>');
      if (!badges.length) badges.push('<span class="badge ok">已索引</span>');
      const checked = selected.has(thread.id) ? ' checked' : '';
      return `<div class="thread">
        <label class="thread-select" title="选择线程">
          <input class="thread-check" type="checkbox" data-select-thread="${escapeHtml(thread.id)}"${checked}>
        </label>
        <div>
          <div class="title">${escapeHtml(thread.title)}</div>
          <div class="meta">${escapeHtml(thread.updated_at_iso || '')} · ${escapeHtml(thread.id || '')} · ${escapeHtml(thread.rollout_path || '')}</div>
        </div>
        <div class="thread-tools">
          <div class="badges">${badges.join('')}</div>
          <button class="danger" title="备份后删除线程" data-delete-thread="${escapeHtml(thread.id)}">删除</button>
        </div>
      </div>`;
    }

    function findThread(threadId) {
      for (const project of data.projects) {
        for (const thread of project.threads) {
          if (thread.id === threadId) return thread;
        }
      }
      return null;
    }

    function pruneSelection() {
      const allThreadIds = new Set();
      for (const project of data.projects) {
        for (const thread of project.threads) allThreadIds.add(thread.id);
      }
      for (const threadId of Array.from(selected)) {
        if (!allThreadIds.has(threadId)) selected.delete(threadId);
      }
    }

    function visibleThreadIds() {
      if (!data) return [];
      const q = $('filter').value.trim().toLowerCase();
      const ids = [];
      for (const project of data.projects) {
        for (const thread of project.threads) {
          const haystack = `${project.cwd} ${thread.title} ${thread.preview}`.toLowerCase();
          if (!q || haystack.includes(q)) ids.push(thread.id);
        }
      }
      return ids;
    }

    function selectedThreads() {
      const threads = [];
      if (!data) return threads;
      for (const project of data.projects) {
        for (const thread of project.threads) {
          if (selected.has(thread.id)) threads.push(thread);
        }
      }
      return threads;
    }

    async function deleteThread(threadId) {
      const thread = findThread(threadId);
      const title = thread ? thread.title : threadId;
      if (!confirm(`删除这个线程吗？\n\n${title}\n\n会先自动备份，删除后列表会刷新。`)) return;
      const res = await fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId })
      });
      const result = await res.json();
      if (result.provider_bridge_target) {
        alert(`provider: ${result.provider_bridge_target}\nrollout bridge: ${result.provider_bridged_rollouts}\nsqlite bridge: ${result.provider_bridged_sqlite_threads}`);
      }
      if (!res.ok) {
        alert(result.error || '删除失败。');
        return;
      }
      alert(`已删除\n线程: ${result.title || result.thread_id}\n备份: ${result.backup_dir}`);
      await load();
    }

    async function deleteSelectedThreads() {
      const threads = selectedThreads();
      if (!threads.length) return;
      const preview = threads.slice(0, 6).map(thread => `- ${thread.title}`).join('\n');
      const more = threads.length > 6 ? `\n... 还有 ${threads.length - 6} 个` : '';
      if (!confirm(`删除选中的 ${threads.length} 个线程吗？\n\n${preview}${more}\n\n会逐条自动备份，删除后列表会刷新。`)) return;
      const res = await fetch('/api/delete-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_ids: threads.map(thread => thread.id) })
      });
      const result = await res.json();
      if (!res.ok) {
        alert(result.error || '批量删除失败。');
        return;
      }
      for (const item of result.deleted || []) selected.delete(item.thread_id);
      const failureText = result.failed_count
        ? `\n失败: ${result.failed_count}\n${(result.failures || []).map(item => `${item.thread_id}: ${item.error}`).join('\n')}`
        : '';
      alert(`批量删除完成\n成功: ${result.deleted_count}\n失败: ${result.failed_count}${failureText}`);
      await load();
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }

    $('refresh').addEventListener('click', load);
    $('filter').addEventListener('input', render);
    $('expand').addEventListener('click', () => {
      collapsed = collapsed.size ? new Set() : new Set(data.projects.map(project => project.cwd));
      render();
    });
    $('selectVisible').addEventListener('click', () => {
      for (const threadId of visibleThreadIds()) selected.add(threadId);
      render();
    });
    $('clearSelected').addEventListener('click', () => {
      selected.clear();
      render();
    });
    $('deleteSelected').addEventListener('click', deleteSelectedThreads);
    $('repair').addEventListener('click', async () => {
      if (!confirm('修复前会自动备份 state_5.sqlite 和 session_index.jsonl。继续吗？')) return;
      const res = await fetch('/api/repair', { method: 'POST' });
      const result = await res.json();
      alert(`修复完成\nsqlite: ${result.inserted_sqlite_threads}\n列表索引: ${result.added_session_index_entries}\n备份: ${result.backup_dir}`);
      await load();
    });
    load().catch(err => {
      $('content').innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
    });
  </script>
</body>
</html>
"""
