"""Parser tests: Python/JS/C# symbols, parent, edges, routes, doc/body, tag."""
from codemem.indexer.parser import parse_file


def test_python_symbols_edges_doc():
    code = (
        "import os\n"
        "class Service:\n"
        "    def charge(self, amount):\n"
        '        """Charge money via gateway."""\n'
        "        return self.gateway.pay(amount)\n"
        "def helper(x):\n"
        "    return x + 1\n"
    )
    r = parse_file(code, "python", "services/pay.py")
    kinds = {(s["kind"], s["name"]) for s in r["symbols"]}
    assert ("class", "Service") in kinds
    assert ("method", "charge") in kinds      # method (in class), khong phai function
    assert ("function", "helper") in kinds
    charge = next(s for s in r["symbols"] if s["name"] == "charge")
    assert charge["parent"] == "Service"
    assert charge["doc"]                       # docstring captured
    assert charge["body"]                      # body evidence captured
    assert any(e["callee"] == "pay" for e in r["edges"])   # charge -> pay
    assert any("import os" in i for i in r["imports"])
    assert charge["tag"] == "be"               # segment 'services'


def test_js_function_and_arrow_edges():
    code = "export function getUser(id){ return find(id); }\nconst add = (a,b) => a + b;\n"
    r = parse_file(code, "javascript", "src/util.js")
    names = {s["name"] for s in r["symbols"]}
    assert "getUser" in names and "add" in names
    assert any(e["callee"] == "find" for e in r["edges"])


def test_js_express_route():
    code = "const r = require('express').Router();\nr.get('/users/:id', (q,s)=>{});\n"
    r = parse_file(code, "javascript", "routes/u.js")
    assert any(rt["method"] == "GET" and rt["path"] == "/users/:id" for rt in r["routes"])


def test_csharp_symbols():
    code = "namespace A { public class C { public int F(){ return g(); } } }"
    r = parse_file(code, "csharp", "C.cs")
    kinds = {(s["kind"], s["name"]) for s in r["symbols"]}
    assert ("class", "C") in kinds and ("method", "F") in kinds


def test_empty_file_ok():
    assert parse_file("", "python", "x.py")["symbols"] == []
