"""Hybrid retrieval co grounding: semantic (nguong distance) + lexical (token) -> context pack.

#P0-QR: tokenizer giu tech token ngan (qr), bo dau tieng Viet, expand intent scan/qr/camera; corpus
rong (name/signature/doc/body/path/skeleton/summary); dung ca semantic kind=file|summary; ranking ha
diem/loai source generated (.cache/page-ssr/vendor/node_modules) va icon helper.
"""
import os
import re
import unicodedata

from ..config import TOP_K, CONTEXT_CHAR_BUDGET, SEMANTIC_MAX_DISTANCE
from ..storage import db, vectors

_WORD = re.compile(r"[A-Za-z0-9]+")

# Stopword (da bo dau) - tu chung trong cau hoi tieng Viet/eng, khong mang y nghia tim kiem.
_STOP = {
    "tim", "cho", "tui", "minh", "ham", "co", "cac", "cua", "mot", "la", "va", "the", "nay",
    "giup", "cai", "chuc", "nang", "chac", "voi", "trong", "khong", "duoc", "nhu", "thi", "ra",
    "function", "func", "method", "class", "that", "with", "for", "and", "the", "code", "file",
}

# Mo rong intent: token -> nhom token lien quan (scan/qr/camera) de khong bo sot synonyms.
_EXPAND = {
    "qr": {"qr", "qrcode", "qrreader", "scan", "scanner", "camera", "barcode", "zxing"},
    "qrcode": {"qr", "qrcode", "scan", "scanner"},
    "scan": {"scan", "scanner", "qr", "qrcode", "camera", "barcode"},
    "scanner": {"scan", "scanner", "qr", "qrcode", "camera"},
    "quet": {"scan", "scanner", "qr", "qrcode", "camera"},     # 'quét'
    "ma": {"qr", "qrcode", "barcode"},                          # 'mã'
    "camera": {"camera", "scan", "scanner", "qr"},
    "barcode": {"barcode", "scan", "scanner", "qr"},
}

# Duong dan generated/cache/vendor -> loai khoi evidence (#P0-QR).
_GEN_MARK = (
    "/.cache/", "page-ssr", "/node_modules/", "/.next/", "/.nuxt/", "/dist/", "/build/", "/out/",
    "/.gatsby/", "/.astro/", "/.parcel-cache/", "/.turbo/", "/.vercel/", "/.svelte-kit/", "/vendor/",
)
# Icon helper (react-icons): Tb/Fa/Md/Io/... + ten ket thuc 'Icon' -> ha diem manh.
_ICON_RE = re.compile(r"^(Tb|Fa|Md|Io|Ai|Bi|Bs|Fi|Gi|Hi|Ri|Si|Vsc|Cg|Im|Lu|Pi|Tfi|Wi)[A-Z]")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _is_generated(fp: str) -> bool:
    low = (fp or "").replace("\\", "/").lower()
    return any(m in low for m in _GEN_MARK)


def _path_bonus(fp: str) -> float:
    low = (fp or "").replace("\\", "/").lower()
    return -0.15 if "/src/" in low else 0.0     # source that trong src/ -> uu tien nhe


def _name_penalty(name: str) -> float:
    n = name or ""
    if _ICON_RE.match(n) or n.endswith("Icon"):
        return 5.0                              # icon helper -> ha diem manh
    return 0.0


def _tokenize(query: str):
    """Token tu query: bo dau, lowercase, giu token >=2 ky tu (gom 'qr'), bo stopword, + expand intent."""
    norm = _strip_accents(query).lower()
    toks = {w for w in _WORD.findall(norm) if len(w) >= 2 and w not in _STOP}
    expanded = set(toks)
    for t in toks:
        expanded |= _EXPAND.get(t, set())
    return expanded


def _rel(path):
    root = db.get_active_root()
    if root:
        try:
            return os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
    return path


def _candidates(query: str):
    """Gop semantic + lexical (symbol + file) -> list candidate da rank. Loai source generated."""
    seen, out = set(), []
    pid = db.active_project_id()

    def _add(file_path, name, kind, start_line, signature, rank):
        if _is_generated(file_path):           # khong dua cache/vendor/generated vao evidence
            return
        key = (file_path, name)
        if key in seen:
            return
        seen.add(key)
        rank += _path_bonus(file_path) + _name_penalty(name or "")
        out.append({"file_path": file_path, "name": name, "kind": kind,
                    "start_line": start_line, "signature": signature, "rank": rank})

    # 1) Semantic — symbol giu cai du gan; file/summary -> dung de keo file lien quan (#P0-QR)
    for m in vectors.query(query, n=TOP_K, project_id=pid):
        dist = m.get("_distance")
        if dist is not None and dist > SEMANTIC_MAX_DISTANCE:
            continue
        kind = m.get("kind")
        base = dist if dist is not None else 0.5
        if kind in ("file", "summary"):
            _add(m.get("file_path"), None, "file", None, None, base + 0.2)
        else:
            _add(m.get("file_path"), m.get("name"), kind, m.get("start_line"), None, base)

    # 2) Lexical — token -> symbol (name/signature/doc/body) + file (path/skeleton/summary)
    tokens = _tokenize(query)
    for tok in tokens:
        for s in db.search_symbols(tok, limit=8, project_id=pid):
            _add(s["file_path"], s["name"], s["kind"], s["start_line"], s["signature"], 0.6)
        for f in db.search_files(tok, limit=5, project_id=pid):
            _add(f["path"], None, "file", None, None, 0.9)

    out.sort(key=lambda c: c["rank"])
    return out


def build_context(query: str):
    """Tra ve (context_text, sources_relative). Rong -> khong du chung cu."""
    cands = _candidates(query)
    if not cands:
        return "", []

    lines = []
    overview = db.get_overview()
    if overview:
        lines += ["=== TONG QUAN DU AN (do AI tom tat tu evidence) ===", overview[:1200], ""]

    lines.append("=== SYMBOL LIEN QUAN ===")
    files_order = []
    for c in cands[:15]:
        if c["file_path"] and c["file_path"] not in files_order:
            files_order.append(c["file_path"])
        if not c["name"]:                      # candidate muc file -> chi gop file, khong in dong symbol
            continue
        sig = c["signature"]
        if not sig:
            row = db.get_symbol_in_file(c["name"], c["file_path"])  # file-scoped, dung signature
            sig = row["signature"] if row else ""
        loc = _rel(c["file_path"]) + (f":{c['start_line']}" if c.get("start_line") else "")
        lines.append(f"- [{c['kind']}] {c['name']}  ({loc})")
        if sig:
            lines.append(f"    {sig}")

    # Evidence: than ham/doc cho vai symbol dau (de giai thich 'lam gi')
    ev = ["\n=== EVIDENCE (trich nguyen van tu source) ==="]
    for c in [c for c in cands[:6] if c["name"]][:3]:
        row = db.get_symbol_in_file(c["name"], c["file_path"])
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
    for c in [c for c in cands[:6] if c["name"]][:3]:
        nm = c["name"]
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
