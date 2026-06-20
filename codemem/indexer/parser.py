"""
Parse file ma nguon bang tree-sitter.
Tra ve: symbols (kem doc + body evidence), imports, edges (call graph), routes.
Ho tro: Python, JavaScript/TypeScript/TSX, C#.
"""
from functools import lru_cache

from tree_sitter_language_pack import get_parser
from ..config import MAX_BODY_CHARS

DEF_KINDS = {
    # JS / TS
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    # C#
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "destructor_declaration": "destructor",
    "property_declaration": "property",
    "struct_declaration": "struct",
    "record_declaration": "record",
    "namespace_declaration": "namespace",
    "delegate_declaration": "delegate",
    # Python
    "function_definition": "function",   # -> "method" neu nam trong class
    "class_definition": "class",
}

CONTAINER_TYPES = {
    "class_declaration", "abstract_class_declaration", "interface_declaration",
    "struct_declaration", "record_declaration", "enum_declaration",
    "namespace_declaration", "class_definition",
}

CALLABLE_TYPES = {
    "function_declaration", "generator_function_declaration", "method_definition",
    "method_declaration", "constructor_declaration", "destructor_declaration",
    "function_definition",
}

VAR_DECL_TYPES = {"lexical_declaration", "variable_declaration"}
FUNC_VALUE_TYPES = {"arrow_function", "function", "function_expression"}
CALL_TYPES = {"call_expression", "invocation_expression", "call"}
IMPORT_TYPES = {"import_statement", "import_from_statement", "using_directive", "import_declaration"}

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "all", "use"}

# Ten thu muc (segment) goi y FE/BE - so khop CHINH XAC tung segment, khong substring.
FE_SEGMENTS = {"components", "component", "pages", "page", "views", "view", "ui", "hooks", "widgets"}
BE_SEGMENTS = {"controllers", "controller", "services", "service", "repositories", "repository",
               "api", "server", "routes", "route", "models", "model", "dao", "middleware",
               "handlers", "usecase", "usecases"}


@lru_cache(maxsize=8)
def _parser(lang: str):
    return get_parser(lang)


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _first_line(text: str) -> str:
    return (text.strip().splitlines()[0] if text.strip() else "")[:300]


def _name_of(node, src):
    n = node.child_by_field_name("name")
    return _text(n, src) if n is not None else None


def _callee_name(fn_node, src):
    if fn_node is None:
        return None
    t = fn_node.type
    if t == "identifier":
        return _text(fn_node, src)
    if t in ("member_expression", "member_access_expression"):
        prop = fn_node.child_by_field_name("property") or fn_node.child_by_field_name("name")
        return _text(prop, src) if prop is not None else None
    if t == "attribute":  # Python a.b()
        attr = fn_node.child_by_field_name("attribute")
        return _text(attr, src) if attr is not None else None
    return None


def _string_arg(call_node, src):
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return None
    for ch in args.children:
        if ch.type in ("string", "string_literal", "template_string"):
            return _text(ch, src).strip("'\"`")
    return None


def _python_docstring(node, src):
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    for ch in body.children:
        # Docstring co the la 'string' truc tiep hoac boc trong expression_statement
        if ch.type == "string":
            return _text(ch, src).strip().strip('"\'').strip()[:400]
        if ch.type == "expression_statement" and ch.child_count and ch.children[0].type == "string":
            return _text(ch.children[0], src).strip().strip('"\'').strip()[:400]
        if ch.type not in ("comment",):
            break
    return ""


def _leading_comment(node, src):
    out = []
    p = node.prev_sibling
    while p is not None and p.type in ("comment",):
        out.append(_text(p, src))
        p = p.prev_sibling
    return "\n".join(reversed(out))[:400]


def _doc_for(node, src, lang):
    return _python_docstring(node, src) if lang == "python" else _leading_comment(node, src)


def _body_evidence(node, src):
    """Than ham/class (cat gioi han) lam evidence de giai thich chuc nang."""
    return _text(node, src)[:MAX_BODY_CHARS]


def _compute_tag(rel_path, lang, kind, name):
    p = rel_path.replace("\\", "/").lower()
    segs = set(p.split("/"))
    nm = (name or "").lower()
    if nm.startswith(("on", "handle")) or kind in ("event", "delegate"):
        return "event"
    if lang in ("javascript", "typescript", "tsx"):
        if p.endswith((".tsx", ".jsx")) or (segs & FE_SEGMENTS) or nm.startswith("use"):
            return "fe"
        if segs & BE_SEGMENTS:
            return "be"
        return ""
    if lang == "csharp":
        return "be"
    if lang == "python":
        if segs & BE_SEGMENTS:
            return "be"
        return ""
    return ""


def parse_file(content: str, lang: str, rel_path: str = ""):
    src = content.encode("utf-8")
    tree = _parser(lang).parse(src)
    symbols, imports, edges, routes = [], [], [], []

    def add_symbol(node, kind, name, parent):
        symbols.append({
            "kind": kind, "name": name,
            "signature": _first_line(_text(node, src)),
            "doc": _doc_for(node, src, lang),
            "body": _body_evidence(node, src),
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "parent": parent, "exported": _is_exported(node),
            "tag": _compute_tag(rel_path, lang, kind, name),
        })

    def visit(node, parent_name, caller_name):
        ntype = node.type
        child_parent, child_caller = parent_name, caller_name

        if ntype in IMPORT_TYPES:
            imports.append(_first_line(_text(node, src)))

        if ntype in VAR_DECL_TYPES:
            for decl in node.children:
                if decl.type == "variable_declarator":
                    value = decl.child_by_field_name("value")
                    if value is not None and value.type in FUNC_VALUE_TYPES:
                        nn = decl.child_by_field_name("name")
                        if nn is not None:
                            fname = _text(nn, src)
                            add_symbol(decl, "function", fname, parent_name)
                            for c in decl.children:
                                visit(c, parent_name, fname)
                            return

        if ntype in DEF_KINDS:
            name = _name_of(node, src)
            if name:
                kind = DEF_KINDS[ntype]
                if ntype == "function_definition" and parent_name:  # Python method
                    kind = "method"
                add_symbol(node, kind, name, parent_name)
                if ntype in CONTAINER_TYPES:
                    child_parent = name
                if ntype in CALLABLE_TYPES:
                    child_caller = name
                if ntype == "method_declaration":
                    _extract_cs_routes(node, src, name, routes)

        if ntype in CALL_TYPES:
            fn = node.child_by_field_name("function")
            callee = _callee_name(fn, src)
            if callee:
                if caller_name:
                    edges.append({"caller": caller_name, "callee": callee})
                if (fn is not None and fn.type == "member_expression" and callee in HTTP_METHODS):
                    path = _string_arg(node, src)
                    if path and path.startswith("/"):
                        routes.append({"method": callee.upper(), "path": path,
                                       "handler": caller_name or "", "line": node.start_point[0] + 1})

        for child in node.children:
            visit(child, child_parent, child_caller)

    visit(tree.root_node, None, None)
    return {"symbols": symbols, "imports": imports, "edges": edges, "routes": routes}


def _extract_cs_routes(method_node, src, method_name, routes):
    for ch in method_node.children:
        if ch.type != "attribute_list":
            continue
        for attr in ch.children:
            if attr.type != "attribute":
                continue
            an = attr.child_by_field_name("name")
            aname = _text(an, src) if an is not None else ""
            if aname.startswith("Http"):
                routes.append({"method": (aname[4:].upper() or "GET"),
                               "path": _attr_string(attr, src) or "",
                               "handler": method_name, "line": method_node.start_point[0] + 1})


def _attr_string(attr_node, src):
    stack = list(attr_node.children)
    while stack:
        n = stack.pop(0)
        if n.type == "string_literal_content":
            return _text(n, src)
        if n.type in ("string_literal", "string"):
            return _text(n, src).strip('"').strip("'")
        stack.extend(n.children)
    return None


def _is_exported(node) -> bool:
    p = node.parent
    while p is not None:
        if p.type in ("export_statement", "export"):
            return True
        if p.type in ("program", "source_file", "module", "statement_block"):
            break
        p = p.parent
    return False


def build_skeleton(rel_path, symbols, imports) -> str:
    lines = [f"FILE: {rel_path}"]
    if imports:
        lines.append("IMPORTS:")
        for imp in imports[:25]:
            lines.append(f"  {imp}")
    lines.append("SYMBOLS:")
    for s in symbols:
        tag = f" <{s['tag']}>" if s.get("tag") else ""
        parent = f" (in {s['parent']})" if s.get("parent") else ""
        doc = f"  # {s['doc'].splitlines()[0]}" if s.get("doc") else ""
        lines.append(f"  [{s['kind']}]{tag} {s['name']}{parent} :: {s['signature']}{doc}")
    return "\n".join(lines)
