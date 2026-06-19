"""
Phase 3: dung Ollama tom tat 'tac dung' cua tung file + dung project overview.
Cache theo summary trong SQLite (chi tom tat file chua co).
Chay nen, co tien do.
"""
import threading

import ollama

from ..config import MODEL, OLLAMA_URL, NUM_CTX
from ..storage import db, vectors

_client = ollama.Client(host=OLLAMA_URL)

# Trang thai tien do (cho UI poll)
progress = {"running": False, "done": 0, "total": 0, "phase": "idle"}
_lock = threading.Lock()


def _ask(system, user, max_ctx=4096):
    try:
        r = _client.chat(
            model=MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            options={"num_ctx": max_ctx, "temperature": 0.1},
        )
        return r["message"]["content"].strip()
    except Exception as e:
        return f"(loi tom tat: {e})"


def summarize_file(skeleton: str) -> str:
    """1-2 cau: file nay lam gi."""
    system = ("Bạn tóm tắt vai trò của một file mã nguồn bằng tiếng Việt, "
              "1-2 câu ngắn gọn, tập trung 'file này làm gì / chịu trách nhiệm gì'. "
              "Không liệt kê lại từng hàm.")
    return _ask(system, f"Cấu trúc file:\n{skeleton[:3500]}")


def build_overview() -> str:
    """Tong hop overview project tu cac file summary."""
    sums = db.all_file_summaries(limit=150)
    if not sums:
        return ""
    import os
    lines = [f"- {os.path.basename(s['path'])}: {s['summary']}" for s in sums]
    body = "\n".join(lines)[:7000]
    system = ("Bạn là kiến trúc sư phần mềm. Dựa trên tóm tắt các file dưới đây, "
              "viết một BẢN ĐỒ TỔNG QUAN dự án bằng tiếng Việt: các module/tầng chính, "
              "luồng nghiệp vụ chính, FE/BE. Ngắn gọn, có cấu trúc.")
    overview = _ask(system, f"Tóm tắt các file:\n{body}", max_ctx=NUM_CTX)
    db.set_meta("overview", overview)
    return overview


def run_summarize(make_overview=True):
    """Tom tat tat ca file chua co summary (chay nen). Cap nhat progress."""
    global progress
    with _lock:
        if progress["running"]:
            return
        progress = {"running": True, "done": 0, "total": 0, "phase": "summarizing"}

    try:
        files = db.files_needing_summary()
        progress["total"] = len(files)
        for f in files:
            summ = summarize_file(f["skeleton"] or "")
            db.set_file_summary(f["path"], summ)
            vectors.index_summary(f["path"], f["lang"], summ)
            progress["done"] += 1
        if make_overview:
            progress["phase"] = "overview"
            build_overview()
    finally:
        progress["phase"] = "done"
        progress["running"] = False


def start_background(make_overview=True):
    t = threading.Thread(target=run_summarize, args=(make_overview,), daemon=True)
    t.start()
