"""FastAPI: API code-memory + phuc vu Web UI."""
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import WEB_DIR, HOST, PORT, MODEL, NUM_CTX, OLLAMA_URL
from ..storage import db, vectors
from ..indexer.runner import index_project, INDEX_LOCK
from ..indexer.watcher import manager as watcher
from ..indexer import summarizer
from ..retrieval.search import build_context, get_related
from ..chat.agent import ChatSession

app = FastAPI(title="code-memory")
session = ChatSession()


class IndexBody(BaseModel):
    path: str


class ChatBody(BaseModel):
    message: str


class ProjectBody(BaseModel):
    id: int


@app.get("/api/status")
def status():
    db.init_db()
    s = db.get_status()
    s["summary"] = db.summary_counts()
    s["model"] = MODEL
    s["num_ctx"] = NUM_CTX
    return s


@app.get("/api/health")
def health():
    """Trang thai he thong (khong ep load embedding)."""
    db.init_db()
    from ..indexer.runner import cleanup_scheduler_status
    p = db.get_active_project()
    return {
        "db": True,
        "vector": vectors.health(),         # chroma ok? embedding failed? reason
        "active_project": p["name"] if p else None,
        "watcher": watcher.observer is not None,
        "cleanup": db.tombstone_stats(),    # pending/failed/last_error cleanup intent (#P0-10)
        "cleanup_scheduler": cleanup_scheduler_status(),  # running/busy/stuck (#P0-10)
    }


@app.get("/api/models")
def models():
    """Doc model that tu Ollama (/api/tags) - khong hard-code."""
    try:
        import ollama
        data = ollama.Client(host=OLLAMA_URL).list()
        names = [m.get("model") or m.get("name") for m in data.get("models", [])]
        return {"current": MODEL, "models": [n for n in names if n], "ollama_ok": True}
    except Exception as e:
        return {"current": MODEL, "models": [], "ollama_ok": False, "error": str(e)}


@app.get("/api/projects")
def projects():
    db.init_db()
    return {"projects": db.list_projects()}


@app.post("/api/project/select")
def project_select(body: ProjectBody):
    """Doi project active: KHONG wipe; reset chat; chuyen watcher. Toan bo stop->mutate->start
    trong INDEX_LOCK de khong interleave voi index/flush (#P0-6)."""
    with INDEX_LOCK:
        if not db.project_exists(body.id):   # check trong lock -> khong race voi delete
            return JSONResponse({"error": "Project khong ton tai"}, status_code=404)
        watcher.stop()
        db.set_active_project(body.id)
        session.history.clear()             # khong mang history sang project khac
        p = db.get_active_project()
        if p and os.path.isdir(p["root"]):
            try:
                watcher.start(p["root"], project_id=p["id"])
            except Exception as e:
                print(f"[warn] watcher: {e}")
    # Repair vector pending cua project moi o nen (#P0-5)
    if p:
        import threading
        from ..indexer.runner import reconcile_vectors
        threading.Thread(target=lambda: reconcile_vectors(p["id"]), daemon=True).start()
    return {"ok": True, "active": p}


@app.post("/api/project/delete")
def project_delete(body: ProjectBody):
    """Xoa 1 project (SQLite + vector) - KHONG dung den project khac."""
    # Toan bo check->stop->mutate->start trong lock (#P0-6) de khong race voi index/select.
    with INDEX_LOCK:
        if not db.project_exists(body.id):
            return JSONResponse({"error": "Project khong ton tai"}, status_code=404)
        if db.active_project_id() == body.id:
            watcher.stop()
            session.history.clear()
        db.delete_project(body.id)          # ghi project intent atomic + tu chon active ke tiep
        vec_ok = vectors.delete_project(body.id)
        if vec_ok:
            db.ack_tombstone("project", body.id)         # fail -> intent giu lai, worker retry (#P0-10)
        p = db.get_active_project()
        if p and os.path.isdir(p["root"]):
            try:
                watcher.start(p["root"], project_id=p["id"])
            except Exception:
                pass
    # Partial result: SQLite da xoa; bao ro vector co xoa duoc khong (#P0-10)
    return {"ok": True, "vector_deleted": vec_ok, "active": p}


@app.post("/api/reconcile")
def reconcile():
    """Repair vector pending/stale cho project active (#P0-5)."""
    from ..indexer.runner import reconcile_vectors
    pid = db.active_project_id()
    if pid is None:
        return JSONResponse({"error": "Chua co project active"}, status_code=400)
    return reconcile_vectors(pid)


@app.post("/api/cleanup/retry")
def cleanup_retry():
    """Retry cleanup intent (tombstone) - KHONG phu thuoc active project (#P0-10)."""
    from ..indexer.runner import cleanup_worker
    cleared = cleanup_worker()
    return {"cleared": cleared, "cleanup": db.tombstone_stats()}


@app.post("/api/summarize")
def summarize():
    """Tom tat 'tac dung' tung file + dung overview (chay nen)."""
    summarizer.start_background(make_overview=True)
    return {"ok": True}


@app.get("/api/summarize/status")
def summarize_status():
    return summarizer.progress


@app.get("/api/overview")
def overview():
    return {"overview": db.get_overview()}   # per-project (overview:{pid})


@app.post("/api/index")
def do_index(body: IndexBody):
    import os
    if not os.path.isdir(body.path):
        return JSONResponse({"error": f"Khong tim thay thu muc: {body.path}"}, status_code=400)
    # stop->index->start trong 1 lock (#P0-6): khong interleave voi index/select/delete khac
    with INDEX_LOCK:
        watcher.stop()
        stats = index_project(body.path)
        try:
            watcher.start(stats["project_root"], project_id=stats["project_id"])
        except Exception as e:
            print(f"[warn] watcher: {e}")
    return stats


@app.get("/api/search")
def search(q: str):
    context, sources = build_context(q)
    return {"context": context, "sources": sources}


@app.get("/api/structure")
def structure():
    return {"files": db.get_structure()}


@app.get("/api/routes")
def routes():
    return {"routes": db.get_routes()}


@app.get("/api/related/{name}")
def related(name: str):
    return get_related(name)


@app.get("/api/symbol/{name}")
def symbol(name: str):
    return {"symbols": db.get_symbols_by_name(name, limit=20)}


@app.get("/api/file")
def file(path: str):
    row = db.get_file_row(path)
    # Khong cho doc file thuoc project khac (chong leak)
    if row and row.get("project_id") != db.active_project_id():
        return JSONResponse({"error": "File khong thuoc project active"}, status_code=404)
    if not row:
        return JSONResponse({"error": "File khong ton tai trong index"}, status_code=404)
    return {"file": row, "symbols": db.get_symbols_for_file(path)}


@app.post("/api/chat")
def chat(body: ChatBody):
    def gen():
        for event in session.stream(body.message):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/reset")
def reset():
    session.history.clear()
    return {"ok": True}


@app.post("/api/clear")
def clear_index():
    """Xoa toan bo index (SQLite + ChromaDB). Dung watcher + reset chat (#P0-10)."""
    with INDEX_LOCK:                       # stop trong lock (#P0-6): index dang cho khong start lai watcher
        watcher.stop()
        db.init_db()
        db.clear_all()                     # da wipe ca vector_tombstones cu
        db.add_tombstone("collection")     # outbox: ghi intent TRUOC khi xoa vector (#P0-10)
        vec_ok = vectors.clear_all()
        if vec_ok:
            db.ack_tombstone("collection")  # thanh cong -> ack; fail -> intent giu lai retry
        session.history.clear()            # evidence da mat -> khong giu chat cu
    return {"ok": True, "sqlite_cleared": True, "vector_cleared": vec_ok,
            "pending_cleanup": db.tombstone_stats()["pending"]}


# Phuc vu Web UI (mount cuoi cung de khong de len API routes)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


@app.on_event("shutdown")
def _shutdown():
    """Dung scheduler + watcher sach khi tat (#P0-10 shutdown/cancel)."""
    from ..indexer.runner import stop_cleanup_scheduler
    stop_cleanup_scheduler()
    try:
        watcher.stop()
    except Exception:
        pass


def main():
    import uvicorn
    db.init_db()
    # Neu da tung index project va path con ton tai -> bat watcher (tranh crash startup)
    import threading
    from ..indexer.runner import reconcile_all_projects, start_cleanup_scheduler
    p = db.get_active_project()
    if p and os.path.isdir(p["root"]):
        try:
            watcher.start(p["root"], project_id=p["id"])
        except Exception as e:
            print(f"[warn] khong bat duoc watcher: {e}")
    # Reconcile MOI project (khong chi active) o nen - #P0-5/#P0-10
    threading.Thread(target=lambda: reconcile_all_projects(), daemon=True).start()
    # Recurring cleanup scheduler (intent backoff duoc retry khi den han) - #P0-10
    start_cleanup_scheduler()
    print(f"code-memory chay tai http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
