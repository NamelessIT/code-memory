"""RAG chat: retrieve context tu code-memory -> Ollama agent-7b-v2 (stream)."""
import ollama

from ..config import MODEL, OLLAMA_URL, NUM_CTX
from ..retrieval.search import build_context
from . import brain_link

_client = ollama.Client(host=OLLAMA_URL)

SYSTEM_BASE = """Bạn là trợ lý hiểu codebase, trả lời bằng tiếng Việt, tự nhiên và chi tiết.
Bạn được cung cấp NGỮ CẢNH trích từ codebase của người dùng (symbol, chữ ký hàm, cấu trúc file).
Quy tắc:
- Trả lời DỰA TRÊN ngữ cảnh được cung cấp. Nếu ngữ cảnh không đủ, nói rõ và gợi ý file/hàm cần xem.
- Khi nhắc đến hàm/class, ghi kèm đường dẫn file và dòng nếu có.
- Giải thích rõ ràng: tác dụng, luồng chạy, liên quan. KHÔNG bịa hàm/file không có trong ngữ cảnh.
- Đây là chế độ CHỈ ĐỌC: không sửa file, chỉ giải thích và tư vấn."""

MAX_HISTORY_CHARS = 8000


class ChatSession:
    def __init__(self):
        self.history = []  # [{role, content}]

    def _trim(self):
        while sum(len(m["content"]) for m in self.history) > MAX_HISTORY_CHARS:
            self.history.pop(0)
            if self.history:
                self.history.pop(0)

    def stream(self, message: str):
        """Generator yield dict: {'type': 'sources'|'token'|'done'|'error', ...}."""
        context, sources = build_context(message)
        yield {"type": "sources", "sources": sources}

        system = SYSTEM_BASE

        # Bai hoc lien quan tu brain (14k lessons cua agent goc)
        brain_text = brain_link.lessons_for(message)
        if brain_text:
            system += f"\n\n=== KINH NGHIỆM LIÊN QUAN (BRAIN) ===\n{brain_text}"

        if context:
            system += f"\n\n=== NGỮ CẢNH CODEBASE ===\n{context}"
        elif not brain_text:
            system += "\n\n(Chưa có ngữ cảnh phù hợp — có thể project chưa được index, hoặc câu hỏi không khớp symbol nào.)"

        messages = [{"role": "system", "content": system}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": message})

        reply = ""
        try:
            for part in _client.chat(
                model=MODEL,
                messages=messages,
                stream=True,
                options={"num_ctx": NUM_CTX, "temperature": 0.3, "top_p": 0.9},
            ):
                chunk = part.get("message", {}).get("content", "")
                if chunk:
                    reply += chunk
                    yield {"type": "token", "text": chunk}
        except Exception as e:
            yield {"type": "error", "text": f"Lỗi gọi Ollama: {e}"}
            return

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()
        yield {"type": "done"}
