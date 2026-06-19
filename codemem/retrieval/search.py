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

    lines = []
    # Project overview (neu da tom tat - Phase 3)
    overview = db.get_meta("overview")
    if overview:
        lines.append("=== TỔNG QUAN DỰ ÁN ===")
        lines.append(overview[:1200])
        lines.append("")

    # Danh sach symbol lien quan (lay signature tu DB neu thieu)
    lines.append("=== SYMBOL LIEN QUAN ===")
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

    # Call graph cho vai symbol dau (ai goi / goi ai)
    cg = ["\n=== CALL GRAPH (LIEN QUAN) ==="]
    for c in cands[:3]:
        nm = c["name"]
        if not nm:
            continue
        callees = db.get_callees(nm, limit=8)
        callers = db.get_callers(nm, limit=8)
        if callees or callers:
            cg.append(f"{nm}:")
            if callees:
                cg.append(f"  goi -> {', '.join(callees)}")
            if callers:
                cg.append(f"  duoc goi boi <- {', '.join(callers)}")
    if len(cg) > 1:
        lines.extend(cg)

    # Skeleton cac file lien quan, cat theo budget
    text = "\n".join(lines)
    used = []
    sk_parts = ["\n=== CAU TRUC FILE LIEN QUAN ==="]
    for fp in files_order:
        sk = db.get_skeleton(fp)
        if not sk:
            continue
        summ = db.get_file_summary(fp)
        block = (f"[TÓM TẮT] {summ}\n{sk}" if summ else sk)
        if len(text) + len("\n".join(sk_parts)) + len(block) > CONTEXT_CHAR_BUDGET:
            break
        sk_parts.append(block)
        used.append(fp)

    if len(sk_parts) > 1:
        text += "\n" + "\n\n".join(sk_parts)

    return text, used


def get_related(name: str):
    """Thong tin call-graph cua 1 symbol (cho endpoint /api/related)."""
    return {
        "name": name,
        "definitions": db.get_symbols_by_name(name, limit=10),
        "calls": db.get_callees(name, limit=30),
        "called_by": db.get_callers(name, limit=30),
    }
