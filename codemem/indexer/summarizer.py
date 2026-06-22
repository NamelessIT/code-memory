"""
Phase 3 (grounded): dung Ollama tom tat 'tac dung' tung file + dung project overview.
- CHI tom tat tu evidence (skeleton co kem doc/signature).
- Cam bia cong nghe/file khong xuat hien trong evidence; thieu thi ghi 'khong ro'.
- KHONG luu chuoi loi lam summary; file loi -> bo qua, dem error.
- File doi da bi xoa summary (db.upsert_file) -> tu sinh lai.
"""
import threading

import ollama

from ..config import MODEL, OLLAMA_URL, NUM_CTX
from ..storage import db, vectors
from .runner import INDEX_LOCK

_client = ollama.Client(host=OLLAMA_URL)

progress = {"running": False, "done": 0, "total": 0, "errors": 0, "phase": "idle"}
_lock = threading.Lock()


def _ask(system, user, max_ctx=4096):
    """Tra ve text, hoac None neu loi (KHONG tra chuoi loi lam summary)."""
    try:
        r = _client.chat(
            model=MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            options={"num_ctx": max_ctx, "temperature": 0.0},
        )
        txt = (r.get("message", {}).get("content") or "").strip()
        return txt or None
    except Exception:
        return None


_FILE_SYS = (
    "Bạn tóm tắt vai trò một file mã nguồn bằng tiếng Việt, 1-2 câu, dựa DUY NHẤT vào "
    "cấu trúc/chữ ký/comment được cung cấp. KHÔNG suy diễn công nghệ/thư viện/framework "
    "nếu chúng không xuất hiện. Nếu không đủ thông tin, trả 'Không rõ chức năng từ cấu trúc hiện có.'"
)

_OVERVIEW_SYS = (
    "Bạn là kiến trúc sư phần mềm. Dựa DUY NHẤT vào tóm tắt các file dưới đây, viết bản đồ tổng "
    "quan dự án bằng tiếng Việt: module/tầng chính, luồng nghiệp vụ, FE/BE. TUYỆT ĐỐI không nêu "
    "công nghệ (database, cache, message queue, framework...) nếu không xuất hiện trong các tóm tắt. "
    "Ngắn gọn, có cấu trúc."
)


def summarize_file(skeleton: str):
    return _ask(_FILE_SYS, f"Cấu trúc file:\n{(skeleton or '')[:3500]}")


def build_overview(project_id=None):
    sums = db.all_file_summaries(limit=400, project_id=project_id)
    if not sums:
        return ""
    rev = db.summaries_revision(project_id=project_id)   # snapshot truoc LLM (#P0-6)
    import os
    body = "\n".join(f"- {os.path.basename(s['path'])}: {s['summary']}" for s in sums)[:8000]
    ov = _ask(_OVERVIEW_SYS, f"Tóm tắt các file:\n{body}", max_ctx=NUM_CTX)   # LLM ngoai lock
    if ov:
        # Commit overview trong INDEX_LOCK + re-check project con ton tai VA tap summary chua doi
        # (#P0-6): _ask co the keo dai trong khi file re-index (xoa summary, invalidate overview) ->
        # overview build tu summary cu la stale, KHONG duoc ghi de.
        with INDEX_LOCK:
            if db.project_exists(project_id) and db.summaries_revision(project_id=project_id) == rev:
                db.set_overview(ov, project_id=project_id)
    return ov or ""


def run_summarize(make_overview=True):
    global progress
    with _lock:
        if progress["running"]:
            return
        progress = {"running": True, "done": 0, "total": 0, "errors": 0, "phase": "summarizing"}
    try:
        pid = db.active_project_id()       # bind cung pid tu dau -> switch UI khong doi target
        progress["project_id"] = pid
        files = db.files_needing_summary(project_id=pid)
        progress["total"] = len(files)
        for f in files:
            snap_gen = f.get("vector_gen", 0)
            summ = summarize_file(f["skeleton"] or "")   # LLM ngoai lock
            if not summ:                   # khong luu chuoi loi lam summary
                progress["errors"] += 1
                progress["done"] += 1
                continue
            # Commit summary/vector trong INDEX_LOCK + re-check (#P0-6): truoc khi ghi, file co the
            # da bi re-index (vector_gen doi) hoac project/file da xoa. Drop ket qua cu -> khong ghi
            # summary/vector mo coi hoac de len noi dung moi.
            with INDEX_LOCK:
                if not db.project_exists(pid):
                    break                  # project da xoa -> dung han job
                st = db.file_vector_state(f["path"], pid)
                if st is None or st[0] != snap_gen:
                    progress["done"] += 1  # file da re-index/xoa -> bo summary cu
                    continue
                db.set_file_summary(f["path"], summ, project_id=pid)
                vectors.index_summary(f["path"], f["lang"], summ, project_id=pid, generation=snap_gen)
            progress["done"] += 1
        if make_overview:
            progress["phase"] = "overview"
            build_overview(project_id=pid)
    finally:
        progress["phase"] = "done"
        progress["running"] = False


def start_background(make_overview=True):
    threading.Thread(target=run_summarize, args=(make_overview,), daemon=True).start()
