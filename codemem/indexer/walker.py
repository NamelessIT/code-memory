"""Duyet codebase: liet ke file ma nguon, hash de index tang dan."""
import hashlib
from pathlib import Path

from ..config import LANG_BY_EXT, IGNORE_DIRS, MAX_FILE_BYTES


def detect_lang(path: Path):
    """Tra ve ten ngon ngu tree-sitter theo duoi file, hoac None neu khong ho tro."""
    return LANG_BY_EXT.get(path.suffix.lower())


def file_hash(path: Path) -> str:
    """SHA1 noi dung file -> phat hien file thay doi."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_source_files(root: str):
    """
    Duyet de quy root, yield (path_tuyet_doi, lang) cho moi file ma nguon ho tro.
    Bo qua thu muc rac va file qua lon.
    """
    root_path = Path(root).resolve()
    for path in root_path.rglob("*"):
        # Bo qua neu nam trong thu muc ignore (bat ky cap nao)
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        lang = detect_lang(path)
        if not lang:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path, lang


def read_text(path: Path) -> str:
    """Doc file text, bo qua loi encoding."""
    return path.read_text(encoding="utf-8", errors="ignore")
