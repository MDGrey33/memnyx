"""Every global name a script uses is defined. A name deleted in one place and
still used in another fails only when that line runs, which for the capture is
minutes into a live run against AWS."""
import ast
import builtins
import symtable
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
MODULE_ATTRS = {"__file__", "__name__", "__doc__", "__spec__", "__builtins__", "__annotations__"}


def undefined_globals(source, name="<src>"):
    top = symtable.symtable(source, name, "exec")
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    used = {}

    def walk(t):
        for s in t.get_symbols():
            n = s.get_name()
            if t.get_type() != "module" and s.is_declared_global() and s.is_assigned():
                defined.add(n)
            if s.is_referenced() and s.is_global() and not (t.get_type() == "module" and (s.is_assigned() or s.is_imported())):
                used.setdefault(n, t.get_name())
        for c in t.get_children():
            walk(c)

    walk(top)
    return {n: where for n, where in used.items()
            if n not in defined and n not in MODULE_ATTRS and not hasattr(builtins, n)}


def module_defines(source, name="<src>"):
    top = symtable.symtable(source, name, "exec")
    return {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}


def missing_from_local_modules(sources):
    """{(script, "module.name")} for names taken from another script that it does
    not define: `from movement import X` and `movement.X` alike."""
    defines = {m: module_defines(src, m) for m, src in sources.items()}
    out = set()
    for script, src in sources.items():
        tree = ast.parse(src)
        alias = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in defines:
                        alias[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom) and node.module in defines:
                out |= {(script, f"{node.module}.{a.name}") for a in node.names if a.name not in defines[node.module]}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
                mod = alias[node.value.id]
                if node.attr not in defines[mod]:
                    out.add((script, f"{mod}.{node.attr}"))
    return out


class TestNoUndefinedNames(unittest.TestCase):
    def test_the_cross_module_check_finds_a_missing_name(self):
        sources = {"a": "X = 1\n", "b": "import a as m\nfrom a import X, Y\nprint(m.X, m.Z)\n"}
        self.assertEqual(missing_from_local_modules(sources), {("b", "a.Y"), ("b", "a.Z")})

    def test_every_name_taken_from_another_script_exists_there(self):
        sources = {p.stem: p.read_text() for p in SCRIPTS.glob("*.py")}
        self.assertEqual(missing_from_local_modules(sources), set())

    def test_the_check_finds_an_undefined_name(self):
        src = "X = 1\ndef f():\n    return X + Y\n"
        self.assertEqual(undefined_globals(src), {"Y": "f"})

    def test_the_check_accepts_imports_globals_and_builtins(self):
        src = ("import os\nfrom a import b as c\ntry:\n    import boto3\nexcept ImportError:\n    pass\n"
               "def f():\n    global G\n    G = len(os.sep)\n    return c, boto3, __file__\n"
               "def g():\n    return G\n")
        self.assertEqual(undefined_globals(src), {})

    def test_every_script_defines_what_it_uses(self):
        scripts = sorted(SCRIPTS.glob("*.py"))
        self.assertGreater(len(scripts), 5)
        for path in scripts:
            with self.subTest(script=path.name):
                self.assertEqual(undefined_globals(path.read_text(), path.name), {})


if __name__ == "__main__":
    unittest.main()
