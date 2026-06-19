"""Hybrid retrieval: semantic (Chroma) + keyword (SQLite) -> context pack."""
from ..config import TOP_K, CONTEXT_CHAR_BUDGET
from ..storage import db, vectors


def _candidates(query: str):
    """Gop ket qua semantic + keyword, giu thu tu uu tien, loai trung."""
    seen = set()
    out = []

    # 1) Semantic (uu tien cao)
    for m in vectors.query(query, n=TOP_K):
        if m.get("kind") == "file":
            continue
        key = (m.get("file_path"), m.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "file_path": m.get("file_path"),
            "name": m.get("name"),
            "kind": m.get("kind"),
            "start_line": m.get("start_line"),
            "signature": None,
        })

    # 2) Keyword (bo sung)
    for s in db.search_symbols(query, limit=15):
        key = (s["file_path"], s["name"])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "file_path": s["file_path"],
            "name": s["name"],
            "kind": s["kind"],
            "start_line": s["start_line"],
            "signature": s["signature"],
        })

    return out


def build_context(query: str):
    """
    Tra ve (context_text, sources).
    context_text: gom danh sach symbol lien quan + skeleton cac file lien quan, <= budget.
    sources: list file_path da dung.
    """
    cands = _candidates(query)
    if not cands:
        return "", []

    # Danh sach symbol lien quan (lay signature tu DB neu thieu)
    lines = ["=== SYMBOL LIEN QUAN ==="]
    files_order = []
    for c in cands[:15]:
        sig = c["signature"]
        if not sig and c["name"]:
            rows = db.get_symbols_by_name(c["name"], limit=1)
            sig = rows[0]["signature"] if rows else ""
        loc = f"{c['file_path']}"
        if c.get("start_line"):
            loc += f":{c['start_line']}"
        lines.append(f"- [{c['kind']}] {c['name']}  ({loc})")
        if sig:
            lines.append(f"    {sig}")
        if c["file_path"] not in files_order:
            files_order.append(c["file_path"])

    # Skeleton cac file lien quan, cat theo budget
    text = "\n".join(lines)
    used = []
    sk_parts = ["\n=== CAU TRUC FILE LIEN QUAN ==="]
    for fp in files_order:
        sk = db.get_skeleton(fp)
        if not sk:
            continue
        if len(text) + len("\n".join(sk_parts)) + len(sk) > CONTEXT_CHAR_BUDGET:
            break
        sk_parts.append(sk)
        used.append(fp)

    if len(sk_parts) > 1:
        text += "\n" + "\n\n".join(sk_parts)

    return text, used
