"""Cau hinh tap trung cho code-memory. Uu tien bien moi truong (CODEMEM_*)."""
import os
from pathlib import Path

# --- Thu muc du lieu (nam trong repo, da gitignore) ---
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "code_index.db"
CHROMA_DIR = DATA_DIR / "vector_index"
WEB_DIR = ROOT_DIR / "web"

# Phien ban schema/parser/prompt -> doi thi invalidate du lieu phai sinh lai
SCHEMA_VERSION = "3"   # 3: multi-project (projects table + project_id)
SUMMARY_PROMPT_VERSION = "2"

# --- Server ---
HOST = os.getenv("CODEMEM_HOST", "127.0.0.1")
PORT = int(os.getenv("CODEMEM_PORT", "8077"))

# --- Ollama (cau hinh duoc, KHONG hard-code theo may tac gia) ---
OLLAMA_URL = os.getenv("CODEMEM_OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("CODEMEM_MODEL", "agent-7b-v2")   # default, doi qua env hoac /api/models
NUM_CTX = int(os.getenv("CODEMEM_NUM_CTX", "8192"))
OUTPUT_RESERVE_TOKENS = int(os.getenv("CODEMEM_OUTPUT_RESERVE", "1024"))

# --- Embedding (config duoc; app van chay lexical-only neu khong co) ---
EMBED_MODEL = os.getenv("CODEMEM_EMBED_MODEL", "all-MiniLM-L6-v2")
CHROMA_COLLECTION = "code"
# Nguong khoang cach semantic (chroma cosine distance): lon hon -> coi nhu khong lien quan
SEMANTIC_MAX_DISTANCE = float(os.getenv("CODEMEM_SEMANTIC_MAX_DISTANCE", "1.15"))

# --- Brain (tai dung 14k bai hoc tu agent goc) ---
BRAIN_DIR = Path.home() / ".agent-brain"
USE_BRAIN = os.getenv("CODEMEM_USE_BRAIN", "1") not in ("0", "false", "False")
BRAIN_LESSONS_K = int(os.getenv("CODEMEM_BRAIN_K", "3"))

# --- Retrieval / context pack ---
TOP_K = 12
# Uoc tinh token ~ chars/4. Budget evidence = ctx - reserve - cho he thong/lich su.
CONTEXT_CHAR_BUDGET = int(os.getenv("CODEMEM_CONTEXT_CHARS", "9000"))
MAX_BODY_CHARS = 900        # gioi han than ham luu lam evidence

# --- Index ---
LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".cs": "csharp",
}

# Thu muc bo qua khi quet (so khop khong phan biet hoa/thuong - xem walker).
# Bo "packages" (lam mat source monorepo) va "Migrations".
IGNORE_DIRS = {
    ".git", "node_modules", "bin", "obj", "dist", "build", "out",
    ".venv", "venv", "env", "__pycache__", ".next", ".nuxt", "coverage",
    ".vs", ".idea", ".pytest_cache", ".mypy_cache", "site-packages",
    # Cache/build generated cua FE framework -> tranh index ban sao .cache/page-ssr lam nhieu (#P0-QR)
    ".cache", ".gatsby", ".astro", ".parcel-cache", ".turbo", ".vercel", ".svelte-kit",
}

MAX_FILE_BYTES = 1_500_000


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
