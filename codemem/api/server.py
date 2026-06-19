"""FastAPI: API code-memory + phuc vu Web UI."""
import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import WEB_DIR, HOST, PORT
from ..storage import db, vectors
from ..indexer.runner import index_project
from ..retrieval.search import build_context
from ..chat.agent import ChatSession

app = FastAPI(title="code-memory")
session = ChatSession()


class IndexBody(BaseModel):
    path: str


class ChatBody(BaseModel):
    message: str


@app.get("/api/status")
def status():
    db.init_db()
    return db.get_status()


@app.post("/api/index")
def do_index(body: IndexBody):
    import os
    if not os.path.isdir(body.path):
        return JSONResponse({"error": f"Khong tim thay thu muc: {body.path}"}, status_code=400)
    stats = index_project(body.path)
    return stats


@app.get("/api/search")
def search(q: str):
    context, sources = build_context(q)
    return {"context": context, "sources": sources}


@app.get("/api/structure")
def structure():
    return {"files": db.get_structure()}


@app.get("/api/symbol/{name}")
def symbol(name: str):
    return {"symbols": db.get_symbols_by_name(name, limit=20)}


@app.get("/api/file")
def file(path: str):
    return {
        "file": db.get_file_row(path),
        "symbols": db.get_symbols_for_files([path]),
    }


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
    """Xoa toan bo index (SQLite + ChromaDB) -> tra lai dung luong."""
    db.init_db()
    db.clear_all()
    vectors.clear_all()
    return {"ok": True}


# Phuc vu Web UI (mount cuoi cung de khong de len API routes)
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main():
    import uvicorn
    db.init_db()
    print(f"code-memory chay tai http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
