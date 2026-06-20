"""Hybrid retrieval co grounding: semantic (nguong distance) + lexical (token) -> context pack."""
import os
import re

from ..config import TOP_K, CONTEXT_CHAR_BUDGET, SEMANTIC_MAX_DISTANCE
from ..storage import db, vectors

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _rel(path):
    root = db.get_meta("project_root")
    if root:
        try:
            return os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
    return path


def _candidates(query: str):
    """Gop semantic (loc theo nguong) + lexical (theo tung token). Loai trung."""
    seen, out = set(), []

    # 1) Semantic — chi giu cai du gan (distance <= nguong)
    for m in vectors.query(query, n=TOP_K):
        if m.get("kind") in ("file", "summary"):
            continue
        dist = m.get("_distance")
        if dist is not None and dist > SEMANTIC_MAX_DISTANCE:
            continue
        key = (m.get("file_path"), m.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"file_path": m.get("file_path"), "name": m.get("name"),
                    "kind": m.get("kind"), "start_line": m.get("start_line"),
                    "signature": None, "score": dist})

    # 2) Lexical — tach cau hoi thanh token, tim symbol theo tung token
    tokens = {t.lower() for t in _WORD.findall(query)}
    for tok in tokens:
        for s in db.search_symbols(tok, limit=8):
            key = (s["file_path"], s["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"file_path": s["file_path"], "name": s["name"],
                        "kind": s["kind"], "start_line": s["start_line"],
                        "signature": s["signature"], "score": None})
    return out


def build_context(query: str):
    """Tra ve (context_text, sources_relative). Rong -> khong du chung cu."""
    cands = _candidates(query)
    if not cands:
        return "", []

    lines = []
    overview = db.get_meta("overview")
    if overview:
        lines += ["=== TONG QUAN DU AN (do AI tom tat tu evidence) ===", overview[:1200], ""]

    lines.append("=== SYMBOL LIEN QUAN ===")
    files_order = []
    for c in cands[:15]:
        sig = c["signature"]
        if not sig and c["name"]:
            row = db.get_symbol_in_file(c["name"], c["file_path"])  # file-scoped, dung signature
            sig = row["signature"] if row else ""
        loc = _rel(c["file_path"]) + (f":{c['start_line']}" if c.get("start_line") else "")
        lines.append(f"- [{c['kind']}] {c['name']}  ({loc})")
        if sig:
            lines.append(f"    {sig}")
        if c["file_path"] not in files_order:
            files_order.append(c["file_path"])

    # Evidence: than ham/doc cho vai symbol dau (de giai thich 'lam gi')
    ev = ["\n=== EVIDENCE (trich nguyen van tu source) ==="]
    for c in cands[:3]:
        row = db.get_symbol_in_file(c["name"], c["file_path"]) if c["name"] else None
        if not row:
            continue
        loc = _rel(c["file_path"]) + f":{row.get('start_line','')}"
        body = (row.get("body") or "").strip()
        doc = (row.get("doc") or "").strip()
        if doc:
            ev.append(f"# {c['name']} ({loc}) doc: {doc[:200]}")
        if body:
            ev.append(f"# {c['name']} ({loc})\n{body}")
    if len(ev) > 1:
        lines += ev

    # Call graph — CHI hien edge resolve duoc toi symbol noi bo (loai built-in/external)
    cg = ["\n=== CALL GRAPH (noi bo) ==="]
    for c in cands[:3]:
        nm = c["name"]
        if not nm:
            continue
        callees = [x for x in db.get_callees(nm, 12) if db.symbol_exists(x)]
        callers = [x for x in db.get_callers(nm, 12) if db.symbol_exists(x)]
        if callees or callers:
            cg.append(f"{nm}: goi -> [{', '.join(callees)}] | duoc goi boi <- [{', '.join(callers)}]")
    if len(cg) > 1:
        lines += cg

    text = "\n".join(lines)

    # Skeleton + summary cac file lien quan, cat theo budget
    used = []
    sk_parts = ["\n=== CAU TRUC FILE LIEN QUAN ==="]
    for fp in files_order:
        sk = db.get_skeleton(fp)
        if not sk:
            continue
        summ = db.get_file_summary(fp)
        block = (f"[TOM TAT] {summ}\n{sk}" if summ else sk)
        if len(text) + len("\n".join(sk_parts)) + len(block) > CONTEXT_CHAR_BUDGET:
            break
        sk_parts.append(block)
        used.append(_rel(fp))
    if len(sk_parts) > 1:
        text += "\n" + "\n\n".join(sk_parts)

    return text, used


def get_related(name: str):
    """Call-graph cua 1 symbol, chi giu edge noi bo da resolve."""
    return {
        "name": name,
        "definitions": [
            {**d, "rel_path": _rel(d["file_path"])} for d in db.get_symbols_by_name(name, 10)
        ],
        "calls": [x for x in db.get_callees(name, 30) if db.symbol_exists(x)],
        "called_by": [x for x in db.get_callers(name, 30) if db.symbol_exists(x)],
    }
