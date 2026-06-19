"""
Parse file ma nguon bang tree-sitter.
Tra ve: symbols, imports, edges (call graph), routes (API).
Ho tro: JavaScript/TypeScript/TSX, C#.
Duyet de quy AST (ben hon query khi grammar doi phien ban).
"""
from functools import lru_cache

from tree_sitter_language_pack import get_parser

# Loai node = "dinh nghia" can trich, map -> kind
DEF_KINDS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "destructor_declaration": "destructor",
    "property_declaration": "property",
    "struct_declaration": "struct",
    "record_declaration": "record",
    "namespace_declaration": "namespace",
    "delegate_declaration": "delegate",
}

CONTAINER_TYPES = {
    "class_declaration", "abstract_class_declaration", "interface_declaration",
    "struct_declaration", "record_declaration", "enum_declaration",
    "namespace_declaration",
}

# Node co than chua loi goi -> dung lam "caller" khi ghi call edge
CALLABLE_TYPES = {
    "function_declaration", "generator_function_declaration", "method_definition",
    "method_declaration", "constructor_declaration", "destructor_declaration",
}

VAR_DECL_TYPES = {"lexical_declaration", "variable_declaration"}
FUNC_VALUE_TYPES = {"arrow_function", "function", "function_expression"}
CALL_TYPES = {"call_expression", "invocation_expression"}

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "all", "use"}


@lru_cache(maxsize=8)
def _parser(lang: str):
    return get_parser(lang)


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:300]


def _name_of(node, src: bytes):
    n = node.child_by_field_name("name")
    return _text(n, src) if n is not None else None


def _callee_name(fn_node, src: bytes):
    """Lay ten ham bi goi tu node 'function' cua call/invocation."""
    if fn_node is None:
        return None
    t = fn_node.type
    if t == "identifier":
        return _text(fn_node, src)
    # JS: a.b()  -> property; C#: a.B() -> name
    if t in ("member_expression", "member_access_expression"):
        prop = fn_node.child_by_field_name("property") or fn_node.child_by_field_name("name")
        if prop is not None:
            return _text(prop, src)
    return None


def _string_arg(call_node, src: bytes):
    """Lay string literal dau tien trong arguments (vd path cua route)."""
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return None
    for ch in args.children:
        if ch.type in ("string", "string_literal", "template_string"):
            return _text(ch, src).strip("'\"`")
    return None


def _compute_tag(file_path: str, lang: str, kind: str, name: str) -> str:
    """Heuristic gan nhan fe/be/event."""
    p = file_path.lower().replace("\\", "/")
    nm = (name or "").lower()

    if nm.startswith(("on", "handle")) or kind in ("event", "delegate"):
        return "event"

    fe_hint = any(s in p for s in ("/component", "/pages", "/views", "/ui", "/hooks", "/src/app"))
    be_hint = any(s in p for s in ("/controller", "/service", "/repositor", "/api",
                                   "/server", "/route", "/model", "/dao", "/middleware"))
    if lang in ("javascript", "typescript", "tsx"):
        if p.endswith((".tsx", ".jsx")) or fe_hint or nm.startswith("use"):
            return "fe"
        if be_hint:
            return "be"
        return ""
    if lang == "csharp":
        return "be"
    return ""


def parse_file(content: str, lang: str, file_path: str = ""):
    """
    Tra ve dict: {symbols, imports, edges, routes}.
    - symbols: {kind,name,signature,start_line,end_line,parent,exported,tag}
    - edges:   {caller, callee} (call graph trong file)
    - routes:  {method, path, handler, line}
    """
    src = content.encode("utf-8")
    tree = _parser(lang).parse(src)

    symbols, imports, edges, routes = [], [], [], []

    def visit(node, parent_name, caller_name):
        ntype = node.type
        child_parent = parent_name
        child_caller = caller_name

        if ntype in ("import_statement", "using_directive", "import_declaration"):
            imports.append(_first_line(_text(node, src)))

        # Arrow function gan vao bien: const foo = () => {...}
        if ntype in VAR_DECL_TYPES:
            for decl in node.children:
                if decl.type == "variable_declarator":
                    value = decl.child_by_field_name("value")
                    if value is not None and value.type in FUNC_VALUE_TYPES:
                        nn = decl.child_by_field_name("name")
                        if nn is not None:
                            fname = _text(nn, src)
                            symbols.append({
                                "kind": "function", "name": fname,
                                "signature": _first_line(_text(decl, src)),
                                "start_line": decl.start_point[0] + 1,
                                "end_line": decl.end_point[0] + 1,
                                "parent": parent_name, "exported": _is_exported(node),
                                "tag": _compute_tag(file_path, lang, "function", fname),
                            })
                            # Duyet than arrow voi caller = fname
                            for c in decl.children:
                                visit(c, parent_name, fname)
                            return

        if ntype in DEF_KINDS:
            name = _name_of(node, src)
            if name:
                symbols.append({
                    "kind": DEF_KINDS[ntype], "name": name,
                    "signature": _first_line(_text(node, src)),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "parent": parent_name, "exported": _is_exported(node),
                    "tag": _compute_tag(file_path, lang, DEF_KINDS[ntype], name),
                })
                if ntype in CONTAINER_TYPES:
                    child_parent = name
                if ntype in CALLABLE_TYPES:
                    child_caller = name
                # C#: route tu attribute [HttpGet("...")] gan tren method
                if ntype == "method_declaration":
                    _extract_cs_routes(node, src, name, routes)

        # Call edge + route Express
        if ntype in CALL_TYPES:
            fn = node.child_by_field_name("function")
            callee = _callee_name(fn, src)
            if callee:
                if caller_name:
                    edges.append({"caller": caller_name, "callee": callee})
                # Express: app.get('/x', ...) / router.post(...)
                if (fn is not None and fn.type == "member_expression"
                        and callee in HTTP_METHODS):
                    path = _string_arg(node, src)
                    if path and path.startswith("/"):
                        routes.append({
                            "method": callee.upper(), "path": path,
                            "handler": caller_name or "", "line": node.start_point[0] + 1,
                        })

        for child in node.children:
            visit(child, child_parent, child_caller)

    visit(tree.root_node, None, None)
    return {"symbols": symbols, "imports": imports, "edges": edges, "routes": routes}


def _extract_cs_routes(method_node, src, method_name, routes):
    """C#: tim attribute [HttpGet(\"...\")] / [Route(\"...\")] tren method."""
    for ch in method_node.children:
        if ch.type != "attribute_list":
            continue
        for attr in ch.children:
            if attr.type != "attribute":
                continue
            aname_node = attr.child_by_field_name("name")
            aname = _text(aname_node, src) if aname_node is not None else ""
            if aname.startswith("Http"):
                method = aname[4:].upper() or "GET"
                path = _attr_string(attr, src) or ""
                routes.append({"method": method, "path": path,
                               "handler": method_name, "line": method_node.start_point[0] + 1})


def _attr_string(attr_node, src):
    """Tim string literal bat ky trong attribute (de quy)."""
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
        if p.type in ("program", "source_file", "statement_block"):
            break
        p = p.parent
    return False


def build_skeleton(file_path: str, symbols, imports) -> str:
    lines = [f"FILE: {file_path}"]
    if imports:
        lines.append("IMPORTS:")
        for imp in imports[:25]:
            lines.append(f"  {imp}")
    lines.append("SYMBOLS:")
    for s in symbols:
        tag = f" <{s['tag']}>" if s.get("tag") else ""
        parent = f" (in {s['parent']})" if s.get("parent") else ""
        lines.append(f"  [{s['kind']}]{tag} {s['name']}{parent} :: {s['signature']}")
    return "\n".join(lines)
