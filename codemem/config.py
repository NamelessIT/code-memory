"""Cau hinh tap trung cho code-memory."""
from pathlib import Path

# --- Thu muc du lieu (nam trong repo, da gitignore) ---
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "code_index.db"
CHROMA_DIR = DATA_DIR / "vector_index"
WEB_DIR = ROOT_DIR / "web"

# --- Server ---
HOST = "127.0.0.1"
PORT = 8077

# --- Ollama (tai dung model da fine-tune) ---
OLLAMA_URL = "http://localhost:11434"
MODEL = "agent-7b-v2"
NUM_CTX = 8192

# --- Embedding (giong brain.py: all-MiniLM-L6-v2, da cache san) ---
EMBED_MODEL = "all-MiniLM-L6-v2"
CHROMA_COLLECTION = "code"

# --- Brain (tai dung 14k bai hoc tu agent goc) ---
BRAIN_DIR = Path.home() / ".agent-brain"
USE_BRAIN = True            # gan brain lessons vao ngu canh chat
BRAIN_LESSONS_K = 4         # so bai hoc lien quan lay ra moi cau hoi

# --- Retrieval / context pack ---
TOP_K = 12                 # so symbol lay ra moi truy van
CONTEXT_CHAR_BUDGET = 9000  # ~ 3500 token, chua cho cau hoi + lich su + tra loi trong 8K

# --- Index ---
# Map duoi file -> ngon ngu tree-sitter
LANG_BY_EXT = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".cs": "csharp",
}

# Thu muc bo qua khi quet
IGNORE_DIRS = {
    ".git", "node_modules", "bin", "obj", "dist", "build", "out",
    ".venv", "venv", "__pycache__", ".next", ".nuxt", "coverage",
    "packages", ".vs", ".idea", "Migrations",
}

MAX_FILE_BYTES = 1_500_000  # bo qua file qua lon (>1.5MB, thuong la build/minified)


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
