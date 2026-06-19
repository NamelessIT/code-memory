"""
Parse file ma nguon bang tree-sitter -> danh sach symbol.
Ho tro: JavaScript/TypeScript/TSX, C#.
Dung duyet de quy AST (ben hon query khi grammar doi phien ban).
"""
from functools import lru_cache

from tree_sitter_language_pack import get_parser

# Loai node = "dinh nghia" can trich, map -> kind
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
    # C# (mot so node trung ten voi JS/TS: class_declaration, interface_declaration, enum_declaration)
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "destructor_declaration": "destructor",
    "property_declaration": "property",
    "struct_declaration": "struct",
    "record_declaration": "record",
    "namespace_declaration": "namespace",
    "delegate_declaration": "delegate",
}

# Loai node "container" -> day ten vao parent stack
CONTAINER_TYPES = {
    "class_declaration", "abstract_class_declaration", "interface_declaration",
    "struct_declaration", "record_declaration", "enum_declaration",
    "namespace_declaration",
}

# Loai node khai bao bien co the chua arrow function (JS/TS)
VAR_DECL_TYPES = {"lexical_declaration", "variable_declaration"}
FUNC_VALUE_TYPES = {"arrow_function", "function", "function_expression"}


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
    if n is not None:
        return _text(n, src)
    return None


def parse_symbols(content: str, lang: str):
    """
    Tra ve (symbols, imports).
    symbols: list dict {kind, name, signature, start_line, end_line, parent, exported}
    imports: list str (import/using statements, dung cho skeleton)
    """
    src = content.encode("utf-8")
    tree = _parser(lang).parse(src)

    symbols = []
    imports = []

    def visit(node, parent_name):
        ntype = node.type

        # Thu thap import / using
        if ntype in ("import_statement", "using_directive", "import_declaration"):
            imports.append(_first_line(_text(node, src)))

        captured_child_parent = parent_name

        # Arrow function gan vao bien: const foo = () => {...}
        if ntype in VAR_DECL_TYPES:
            for decl in node.children:
                if decl.type == "variable_declarator":
                    value = decl.child_by_field_name("value")
                    if value is not None and value.type in FUNC_VALUE_TYPES:
                        name_node = decl.child_by_field_name("name")
                        if name_node is not None:
                            symbols.append({
                                "kind": "function",
                                "name": _text(name_node, src),
                                "signature": _first_line(_text(decl, src)),
                                "start_line": decl.start_point[0] + 1,
                                "end_line": decl.end_point[0] + 1,
                                "parent": parent_name,
                                "exported": _is_exported(node),
                            })

        # Cac dinh nghia chinh
        if ntype in DEF_KINDS:
            name = _name_of(node, src)
            if name:
                symbols.append({
                    "kind": DEF_KINDS[ntype],
                    "name": name,
                    "signature": _first_line(_text(node, src)),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "parent": parent_name,
                    "exported": _is_exported(node),
                })
                if ntype in CONTAINER_TYPES:
                    captured_child_parent = name

        for child in node.children:
            visit(child, captured_child_parent)

    visit(tree.root_node, None)
    return symbols, imports


def _is_exported(node) -> bool:
    p = node.parent
    while p is not None:
        if p.type in ("export_statement", "export"):
            return True
        # chi di len 2 cap de tranh nham
        if p.type in ("program", "source_file", "statement_block"):
            break
        p = p.parent
    return False


def build_skeleton(file_path: str, symbols, imports) -> str:
    """Dan y cau truc file -> dung de embed + cho agent doc nhanh."""
    lines = [f"FILE: {file_path}"]
    if imports:
        lines.append("IMPORTS:")
        for imp in imports[:25]:
            lines.append(f"  {imp}")
    lines.append("SYMBOLS:")
    for s in symbols:
        prefix = f"[{s['kind']}]"
        parent = f" (in {s['parent']})" if s.get("parent") else ""
        lines.append(f"  {prefix} {s['name']}{parent} :: {s['signature']}")
    return "\n".join(lines)
