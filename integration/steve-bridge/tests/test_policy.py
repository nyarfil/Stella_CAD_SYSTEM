import os
import pytest
from stella_steve_bridge import policy

SCRATCH = os.path.abspath(os.path.join(os.sep, "tmp_scratch_test"))
OK = "def run(context):\n    return 1\n"


def codes(src, mode="execute"):
    return {v["code"] for v in policy.check(src, mode, SCRATCH)}


def test_accepts_plain_code():
    assert policy.check(OK, "execute", SCRATCH) == []
    assert policy.check("import math, json, re\ndef run(context):\n    return re.compile('a').pattern\n", "execute", SCRATCH) == []


@pytest.mark.parametrize("module", ["socket", "ssl", "http.client", "urllib.request", "requests", "subprocess",
                                    "ctypes", "webbrowser", "ftplib", "smtplib", "importlib", "builtins"])
def test_banned_imports(module):
    assert "banned_import" in codes("import %s\n%s" % (module, OK))
    assert "banned_import" in codes("from %s import x\n%s" % (module, OK))


@pytest.mark.parametrize("snippet", [
    "import os\nos.system('x')", "import os\nos.popen('x')", "import os as o\no.system('x')",
    "from os import system", "from os import popen as p", "import os\nos.execv('a', [])", "import os\nos.remove('a')",
    "from os import *"])
def test_os_calls(snippet):
    assert "banned_os_call" in codes(snippet + "\n" + OK)


@pytest.mark.parametrize("snippet", ["eval('1')", "exec('x=1')", "compile('1','a','eval')", "__import__('os')",
                                     "f = eval"])
def test_eval_exec_compile_import(snippet):
    assert "banned_name" in codes("def run(context):\n    " + snippet + "\n")


def test_re_compile_allowed_builtins_compile_not():
    assert codes("import re\ndef run(context):\n    return re.compile('x')\n") == set()


def test_open_write_rules():
    inside = os.path.join(SCRATCH, "a.txt").replace("\\", "\\\\")
    assert codes("def run(c):\n    open(r'%s','w').write('x')\n" % os.path.join(SCRATCH, "a.txt")) == set()
    assert "write_outside_scratch" in codes("def run(c):\n    open('/etc/x','w')\n")
    assert "write_outside_scratch" in codes("def run(c):\n    open('relative.txt','w')\n")
    assert "write_outside_scratch" in codes("def run(c):\n    open(p,'w')\n")
    assert "write_outside_scratch" in codes("def run(c):\n    open(r'%s','w')\n" % os.path.join(SCRATCH, "..", "x.txt"))
    assert "open_mode" in codes("def run(c):\n    open('a', m)\n")
    assert codes("def run(c):\n    return open('a').read()\n") == set()   # read is fine
    assert "open_alias" in codes("def run(c):\n    f = open\n")
    assert "write_outside_scratch" in codes("import io\ndef run(c):\n    io.open('x','wb')\n")
    assert "banned_attr" in codes("def run(c):\n    p.write_text('x')\n")
    assert inside


@pytest.mark.parametrize("snippet", [
    "app.activeDocument", "app.activeProduct", "ui.activeSelections", "ui.activeWorkspace",
    "data.activeProject", "data.activeFolder", "data.activeHub", "getattr(app, 'activeDocument')"])
def test_live_getters_blocked(snippet):
    assert "live_context_access" in codes("def run(context):\n    return " + snippet + "\n")


def test_value_objecttype_and_dunders():
    assert "unsafe_value_introspection" in codes("def run(c):\n    return p.value.objectType\n")
    assert "banned_dunder" in codes("def run(c):\n    return ().__class__.__bases__\n")
    assert "banned_attr" in codes("import sys\ndef run(c):\n    return sys.modules\n")


def test_run_required_and_syntax_and_size():
    assert "no_run" in codes("x = 1\n")
    assert "syntax" in codes("def run(:\n")
    assert "too_large" in codes("#" * (policy.MAX_CODE + 1))
    assert "empty" in codes("   ")


def test_query_mode_rejects_mutation_execute_allows():
    mutating = ["design.userParameters.add('a')", "x.deleteMe()", "doc.saveAs('a')", "p.expression = '1'",
                "root.features.extrudeFeatures.addSimple(1)", "i.createInput(1)"]
    for snippet in mutating:
        src = "def run(c):\n    " + snippet + "\n"
        assert "query_mutation" in codes(src, "query"), snippet
        assert "query_mutation" not in codes(src, "execute"), snippet
    assert codes("def run(c):\n    return [b.name for b in c['root'].bRepBodies]\n", "query") == set()


def test_unit_helpers_appended_after_code_and_validate():
    src = policy.with_unit_helpers(OK)
    assert src.startswith(OK.rstrip("\n"))   # line numbers of user code unchanged
    ns = {}
    exec(compile(src, "x", "exec"), ns)
    assert ns["to_cm"](25.4) == pytest.approx(2.54)
    assert ns["to_mm"](2.54) == pytest.approx(25.4)
    for bad in ("1", None, True, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ns["to_cm"](bad)
        with pytest.raises(ValueError):
            ns["to_mm"](bad)
