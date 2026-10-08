"""Static code policy for Python submitted through the bridge.

DEFENCE IN DEPTH, NOT A SANDBOX. An AST check cannot stop a determined author
(getattr tricks, Fusion API calls that write files, etc.). It catches accidental
and naive dangerous constructs before the code reaches Fusion. The real
boundaries are the bearer token, the document allow-list and review of the code.
"""
import ast
import os
import re

MAX_CODE = 60000
BANNED_IMPORTS = frozenset({
    "socket", "ssl", "http", "urllib", "urllib2", "urllib3", "requests", "httpx", "aiohttp",
    "subprocess", "ctypes", "webbrowser", "ftplib", "smtplib", "telnetlib", "poplib", "imaplib",
    "nntplib", "socketserver", "xmlrpc", "multiprocessing", "importlib", "builtins", "pty",
    "shutil", "winreg", "_winapi",
})
OS_DANGEROUS = frozenset({
    "system", "popen", "startfile", "remove", "unlink", "rmdir", "removedirs", "rename",
    "renames", "replace", "truncate", "kill", "killpg", "fork", "forkpty", "chmod", "chown",
    "symlink", "link", "putenv", "unsetenv", "open",
})
OS_DANGEROUS_PREFIXES = ("exec", "spawn", "popen")
ACTIVE_GETTERS = frozenset({"activeDocument", "activeProduct", "activeSelections", "activeWorkspace",
                            "activeProject", "activeFolder", "activeHub"})
BAD_DUNDERS = frozenset({"__import__", "__builtins__", "__globals__", "__subclasses__", "__bases__",
                         "__mro__", "__code__", "__closure__", "__loader__", "__spec__"})
# Reaching other documents / the Data Panel / exports / UI commands from submitted code.
# Rejected as attribute access AND as string constants (getattr / context['data'] tricks).
# False positives are accepted (e.g. file.close(), a dict key "data"); use `with open(...)`.
DOC_ACCESS = frozenset({"documents", "close", "save", "saveAs", "saveCopyAs", "dataFile", "data",
                        "exportManager", "commandDefinitions", "activate", "open"})
BAD_NAMES = frozenset({"eval", "exec", "compile", "__import__"})
BAD_ATTRS = frozenset({"eval", "exec", "write_text", "write_bytes", "unlink", "rmdir", "rmtree"})
QUERY_BAD_EXACT = frozenset({"add", "deleteMe", "save", "saveAs", "saveCopyAs", "close", "activate",
                             "execute", "moveTo", "isolate", "redo", "undo"})
QUERY_BAD_RE = re.compile(r"^(add|create|delete|remove|import)([A-Z_]|$)")
WRITE_CHARS = set("wax+")
MODE_RE = re.compile(r"^[rwaxbt+U]{1,4}$")


def _inside(path, scratch):
    p = os.path.normcase(os.path.abspath(path))
    s = os.path.normcase(os.path.abspath(scratch))
    return os.path.isabs(path) and p != s and p.startswith(s + os.sep)


def _const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class _Checker(ast.NodeVisitor):
    def __init__(self, mode, scratch):
        self.mode, self.scratch = mode, scratch
        self.violations = []
        self.os_aliases = {"os"}
        self.sys_aliases = {"sys"}
        self.call_funcs = set()

    def bad(self, node, code, message):
        self.violations.append({"code": code, "line": getattr(node, "lineno", 0), "message": message})

    def visit_Import(self, node):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in BANNED_IMPORTS:
                self.bad(node, "banned_import", "import of '%s' is not allowed" % alias.name)
            if top == "os":
                self.os_aliases.add(alias.asname or "os")
            if top == "sys":
                self.sys_aliases.add(alias.asname or "sys")

    def visit_ImportFrom(self, node):
        if node.level:
            return
        top = (node.module or "").split(".")[0]
        if top in BANNED_IMPORTS:
            self.bad(node, "banned_import", "import from '%s' is not allowed" % node.module)
        if top == "os":
            for alias in node.names:
                if alias.name == "*" or alias.name in OS_DANGEROUS or alias.name.startswith(OS_DANGEROUS_PREFIXES):
                    self.bad(node, "banned_os_call", "from os import %s is not allowed" % alias.name)

    def visit_Name(self, node):
        if node.id in BAD_NAMES:
            self.bad(node, "banned_name", "use of '%s' is not allowed" % node.id)
        if node.id == "open" and isinstance(node.ctx, ast.Load) and id(node) not in self.call_funcs:
            self.bad(node, "open_alias", "open must be called directly")

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            value = node.value
            if value in ACTIVE_GETTERS or value in BAD_DUNDERS:
                self.bad(node, "live_context_access" if value in ACTIVE_GETTERS else "banned_dunder",
                         "string '%s' is not allowed (getattr bypass)" % value)
            elif value in DOC_ACCESS and value != "open":
                self.bad(node, "document_access", "string '%s' is not allowed (reaches other documents/Data Panel/exports)" % value)

    def visit_Attribute(self, node):
        attr = node.attr
        base = node.value.id if isinstance(node.value, ast.Name) else None
        if attr in ACTIVE_GETTERS:
            self.bad(node, "live_context_access", "%s follows the live UI; use the pinned context" % attr)
        if attr in BAD_DUNDERS:
            self.bad(node, "banned_dunder", "attribute %s is not allowed" % attr)
        if attr in DOC_ACCESS and not (attr == "open" and base in ("io", "codecs")):
            self.bad(node, "document_access", "attribute %s is not allowed (reaches other documents/Data Panel/exports)" % attr)
        if attr in BAD_ATTRS:
            self.bad(node, "banned_attr", "attribute %s is not allowed" % attr)
        if attr == "modules" and base in self.sys_aliases:
            self.bad(node, "banned_attr", "sys.modules is not allowed")
        if base in self.os_aliases and (attr in OS_DANGEROUS or attr.startswith(OS_DANGEROUS_PREFIXES)):
            self.bad(node, "banned_os_call", "os.%s is not allowed" % attr)
        if attr == "objectType" and isinstance(node.value, ast.Attribute) and node.value.attr == "value":
            self.bad(node, "unsafe_value_introspection", ".value.objectType crashes native Fusion probing")
        if self.mode == "query":
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.bad(node, "query_mutation", "attribute assignment/deletion is not allowed in a query")
            elif attr in QUERY_BAD_EXACT or QUERY_BAD_RE.match(attr):
                self.bad(node, "query_mutation", "'%s' looks like a mutating call; use execute" % attr)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        self.call_funcs.add(id(func))
        if isinstance(func, ast.Name) and func.id == "open":
            self._check_open(node, 0, 1, strict=True)
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            base = func.value.id if isinstance(func.value, ast.Name) else None
            if base in ("io", "codecs"):
                self._check_open(node, 0, 1, strict=True)
            elif base not in self.os_aliases:  # os.open is flagged by visit_Attribute
                self._check_open(node, None, 0, strict=False)
        self.generic_visit(node)

    def _check_open(self, node, path_idx, mode_idx, strict):
        mode_node = node.args[mode_idx] if len(node.args) > mode_idx else next(
            (k.value for k in node.keywords if k.arg == "mode"), None)
        mode = "r" if mode_node is None else _const_str(mode_node)
        if mode is None:
            if strict:
                self.bad(node, "open_mode", "open() mode must be a string literal")
            return
        if not MODE_RE.match(mode) or not (WRITE_CHARS & set(mode)):
            return
        path = None
        if path_idx is not None:
            path_node = node.args[path_idx] if len(node.args) > path_idx else next(
                (k.value for k in node.keywords if k.arg in ("file", "path")), None)
            path = _const_str(path_node) if path_node is not None else None
        if path is None or not self.scratch or not _inside(path, self.scratch):
            self.bad(node, "write_outside_scratch",
                     "writing files is only allowed at a literal absolute path inside the scratch dir")


def check(source, mode="execute", scratch_dir=None):
    """Return a list of violation dicts (empty list = accepted). mode: 'query' or 'execute'."""
    if not isinstance(source, str) or not source.strip():
        return [{"code": "empty", "line": 0, "message": "code is empty"}]
    if len(source) > MAX_CODE:
        return [{"code": "too_large", "line": 0, "message": "code exceeds %d characters" % MAX_CODE}]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"code": "syntax", "line": exc.lineno or 0, "message": "syntax error: %s" % exc.msg}]
    checker = _Checker(mode, scratch_dir)
    checker.visit(tree)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        checker.bad(tree, "no_run", "define def run(context) at module level")
    return checker.violations


# Appended AFTER the user's code so line numbers are unchanged; helpers are module
# globals, so they are available inside run(). No silent conversion anywhere else.
UNIT_PRELUDE = '''

def _stella_num(value, name):
    import math as _m
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not _m.isfinite(value):
        raise ValueError(name + " needs a finite number")
    return float(value)


def to_cm(mm):
    """Explicit millimetres -> Fusion internal centimetres."""
    return _stella_num(mm, "to_cm") / 10.0


def to_mm(cm):
    """Fusion internal centimetres -> millimetres."""
    return _stella_num(cm, "to_mm") * 10.0
'''


def with_unit_helpers(source):
    return source.rstrip("\n") + "\n" + UNIT_PRELUDE
