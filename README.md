# code-memory

App local quét codebase → lưu cấu trúc (hàm, class, import, skeleton...) vào index truy vấn được, rồi **chat hỏi về codebase** bằng model local `agent-7b-v2` (Ollama). Giải quyết giới hạn context nhỏ của model: chỉ nạp **đúng phần liên quan** thay vì cả codebase.

- Giao diện: **Web UI local** (trình duyệt)
- Chế độ: **read-only** (giải thích, không sửa file)
- Ngôn ngữ index: **JavaScript / TypeScript / TSX / C#**

## Cài đặt

Yêu cầu: Ollama đang chạy với model `agent-7b-v2`.

```powershell
cd C:\Github\Code\Repository\code-memory
# Tạo venv riêng (khuyến nghị) hoặc dùng lại venv đã có chromadb/torch/ollama
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Nếu không tạo `.venv` riêng, `start.bat` sẽ tự dùng venv Ollama tại
> `C:\Agent\Agent_Ollama\Ollama\.venv` (đã có sẵn các thư viện nặng).

## Chạy

- **Cách 0 (khuyên):** chạy 1 lần để tạo icon trên Desktop:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
  ```
  (thêm `-AutoStart` để chạy cùng Windows). Sau đó **double-click icon "code-memory"** trên Desktop là xong.
- **Cách 1:** double-click `scripts\start_hidden.vbs` → tự mở trình duyệt, không hiện console.
- **Cách 2:** double-click `scripts\start.bat`.
- **Cách 3 (thủ công):** `python -m codemem.api.server` rồi mở http://127.0.0.1:8077

## Dùng

1. Mở app → ô "Đường dẫn project" nhập đường dẫn repo cần hỏi → bấm **Index**.
2. Chờ index xong (lần đầu lâu, lần sau chỉ index file thay đổi).
3. Hỏi: "hàm X làm gì?", "luồng đăng nhập chạy thế nào?", "class Y nằm ở đâu?"...

## Kiến trúc

```
codemem/
├── indexer/   walker (quét) + parser (tree-sitter) + runner (điều phối)
├── storage/   db (SQLite) + vectors (ChromaDB)
├── retrieval/ search (hybrid → context pack)
├── chat/      agent (RAG + Ollama stream)
└── api/       server (FastAPI + Web UI)
web/           giao diện chat
```

## Tính năng

- Index JS/TS/TSX/C# (tree-sitter, tăng dần theo hash)
- Hỏi đáp RAG: ghép **ngữ cảnh codebase** + **brain 14k bài học** vào câu trả lời
- **Call graph**: ai gọi ai (nút liên quan trong câu trả lời, API `/api/related/{name}`)
- **Route API**: tự trích endpoint Express / ASP.NET (nút **Routes**, API `/api/routes`)
- **Tag** FE / BE / event cho symbol
- **Auto re-index**: theo dõi file project, đổi là cập nhật (watchdog)
- **Xoá index** + tự dọn khi đổi project (tránh phình DB)
- **Tóm tắt AI** (nút **Tóm tắt**): LLM tóm tắt "tác dụng" từng file + dựng **bản đồ tổng quan** dự án (nút **Tổng quan**), nạp vào ngữ cảnh để trả lời sâu hơn
- **1-click + icon**: shortcut Desktop (`install_shortcut.ps1`)

## Roadmap

- **Phase 1 ✅:** index file/symbol + chat RAG.
- **Phase 2 ✅:** call graph, trích route API, tag FE/BE/event, auto re-index.
- **Phase 3 ✅:** LLM tóm tắt "tác dụng", project overview, context pack thông minh, đóng gói 1-click + icon.
