"""Snapshot gate for the committed API reference under docs/api/.

The tool-layer docstrings are the API contract. docs/api/ is that contract
rendered to markdown by pydoc-markdown and checked into the repo, so agents and
GitHub readers get the reference by browsing, with nothing to build.

Generation logic lives in this module and nowhere else. Two entry points share
it:

  uv run --frozen pytest
      verifies the committed pages are current; read-only, it never writes
      inside the repo

  uv run --frozen python tests/test_api_docs.py --write
      regenerates docs/api/ in place; this is the heal command every failure
      message points at

Only the per-module pages are snapshot-gated. docs/api/README.md is authored by
hand, not generated, so it sits outside the comparison and is safe to edit.
"""

from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / ".shared" / "tools"
API_DOCS_DIR = REPO_ROOT / "docs" / "api"
INDEX_FILE = "README.md"

HEAL_COMMAND = "uv run --frozen python tests/test_api_docs.py --write"


def tool_module_names() -> list[str]:
    """Every module in the tool layer, enumerated from disk rather than listed.

    A hand-maintained list would silently stop covering a module the day one is
    added, so the surface is discovered instead: every .py file in the canonical
    tools directory except the package initializer.

    The scope is the tools package and nothing else. Tests are consumers of this
    API rather than part of it, and they churn far more often than the tool
    layer, so documenting them would spam the snapshot gate for no reader's
    benefit. Do not widen this to tests/.
    """
    return sorted(
        p.stem for p in TOOLS_DIR.glob("*.py") if p.name != "__init__.py"
    )


def _pydoc_markdown_executable() -> Path:
    """Locate the pydoc-markdown console script inside the running interpreter's env."""
    bin_dir = Path(sys.executable).parent
    for candidate in (bin_dir / "pydoc-markdown", bin_dir / "pydoc-markdown.exe"):
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "pydoc-markdown is not installed in this environment. "
        "It ships in the dev dependency group: run `uv sync`."
    )


def _config_for(module_name: str) -> str:
    """The pydoc-markdown configuration, spelled out rather than left to defaults.

    Two settings carry weight and are deliberate.

    The default processor chain includes `smart`, which sniffs a docstring
    style per module and reformats accordingly. One Google-style `Returns:`
    anywhere in a module flips the whole module into Google mode, and that pass
    dedents every docstring in it, collapsing the indented CLI and JSON blocks
    the tool layer writes on purpose into run-on paragraphs. Dropping `smart`
    renders docstrings as their authors laid them out, and renders every module
    the same way.

    `escape_html_in_docstring` protects the angle-bracket placeholders the tool
    layer uses throughout (`<part-path>`, `<dir>`, `<fmt>`). Left unescaped,
    a rendering host reads them as unknown HTML tags and drops them, so the
    placeholder disappears from the page and the reader sees a command with a
    hole in it. Escaped, every placeholder survives. Escaping is blunt and also
    reaches code blocks, where the escape sequences would be visible, so
    _fence_indented_code_blocks undoes it exactly there.
    """
    return (
        "{loaders: [{type: python, "
        f"modules: [tools.{module_name}], "
        "search_path: [.shared]}], "
        "processors: [{type: filter}, {type: crossref}], "
        "renderer: {type: markdown, escape_html_in_docstring: true}}"
    )


def _restore_harmless_entities(markdown: str) -> str:
    """Put quotes and apostrophes back as themselves.

    The renderer escapes every HTML-significant character, but only the angle
    brackets and the ampersand actually need it in markdown text. Quotes and
    apostrophes come back as entities that render fine yet leave the raw file
    noisy for anyone, human or agent, who reads the markdown rather than the
    rendered page. No tool docstring writes an entity literally, so decoding
    these two is unambiguous.
    """
    return markdown.replace("&quot;", '"').replace("&#x27;", "'")


def _fence_indented_code_blocks(markdown: str) -> str:
    """Turn indented code blocks into fenced ones and unescape inside them.

    Escaping is applied to the whole docstring, which keeps placeholders alive
    in prose but leaves visible escape sequences in the CLI and JSON blocks the
    tool layer indents, and those are the lines a reader copies. A fence is the
    unambiguous way to say "this is code", and text inside one is never read as
    HTML, so the escaping can be undone there.

    A run of four-space-indented lines counts as a code block only when a blank
    line precedes it, matching the markdown rule that indented code cannot
    interrupt a paragraph. Continuation lines under a shallower list or heading
    therefore stay prose, and stay escaped, which is what they need.
    """
    lines = markdown.split("\n")
    out: list[str] = []
    index = 0
    inside_fence = False

    while index < len(lines):
        line = lines[index]

        if line.startswith("```"):
            inside_fence = not inside_fence
            out.append(line)
            index += 1
            continue

        preceded_by_blank = not out or out[-1].strip() == ""
        starts_code_block = (
            not inside_fence
            and preceded_by_blank
            and line.startswith("    ")
            and line.strip()
        )
        if not starts_code_block:
            out.append(line)
            index += 1
            continue

        block: list[str] = []
        while index < len(lines):
            current = lines[index]
            if not current.strip():
                lookahead = index
                while lookahead < len(lines) and not lines[lookahead].strip():
                    lookahead += 1
                if lookahead < len(lines) and lines[lookahead].startswith("    "):
                    block.extend(lines[index:lookahead])
                    index = lookahead
                    continue
                break
            if not current.startswith("    "):
                break
            block.append(current)
            index += 1

        out.append("```")
        out.extend(html.unescape(entry[4:]) for entry in block)
        out.append("```")

    return "\n".join(out)


def render_module(module_name: str) -> str:
    """Render one tool module to markdown, banner included.

    Runs pydoc-markdown against the canonical .shared tree rather than the
    tools symlink, so generation does not depend on symlink support, and from
    the repo root with a relative search path, so no absolute path can reach the
    output. The renderer emits no timestamps and no source line anchors, which
    is what lets the result be committed and compared byte for byte.
    """
    result = subprocess.run(
        [str(_pydoc_markdown_executable()), _config_for(module_name)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    banner = (
        f"> Generated from the `tools/{module_name}.py` docstrings, never hand-edited.\n"
        f"> Regenerate with `{HEAL_COMMAND}`.\n"
    )
    return banner + _fence_indented_code_blocks(
        _restore_harmless_entities(result.stdout)
    )


def generate_into(target_dir: Path) -> dict[str, str]:
    """Render every tool module into target_dir; return {filename: content}."""
    target_dir.mkdir(parents=True, exist_ok=True)
    rendered = {}
    for module_name in tool_module_names():
        filename = f"{module_name}.md"
        content = render_module(module_name)
        (target_dir / filename).write_text(content, encoding="utf-8", newline="\n")
        rendered[filename] = content
    return rendered


def _committed(filename: str) -> str | None:
    """Read a committed page, normalizing line endings for CRLF checkouts."""
    path = API_DOCS_DIR / filename
    if not path.exists():
        return None
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def test_committed_api_docs_are_current(tmp_path):
    """Every committed module page matches a fresh render of its docstrings."""
    fresh = generate_into(tmp_path / "api")

    stale = []
    for filename, expected in fresh.items():
        actual = _committed(filename)
        if actual is None:
            stale.append(f"{filename} (missing)")
        elif actual != expected:
            stale.append(f"{filename} (out of date)")

    assert not stale, (
        "docs/api/ no longer matches the tool-layer docstrings.\n"
        f"Affected: {', '.join(stale)}\n"
        f"Regenerate with: {HEAL_COMMAND}"
    )


def test_no_orphaned_api_doc_pages():
    """docs/api/ carries no page for a module that no longer exists."""
    expected = {f"{name}.md" for name in tool_module_names()} | {INDEX_FILE}
    present = {p.name for p in API_DOCS_DIR.glob("*.md")}
    orphans = sorted(present - expected)

    assert not orphans, (
        f"docs/api/ carries pages with no matching tool module: {orphans}\n"
        f"Regenerate with: {HEAL_COMMAND}"
    )


def test_api_docs_carry_no_em_or_en_dashes():
    """The repo's typography rule reaches the generated pages too.

    Docstrings and the trailing attribute comments pydoc-markdown promotes to
    documentation are both doc input, so a dash in either one lands in a
    committed page. The remedy is always to fix the source and regenerate,
    never to edit the page.
    """
    offenders = []
    for path in sorted(API_DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "—" in line or "–" in line:
                offenders.append(f"docs/api/{path.name}:{lineno}")

    assert not offenders, (
        "em or en dashes reached the API reference; fix the source docstring "
        f"or attribute comment, then run: {HEAL_COMMAND}\n"
        f"Offending lines: {offenders}"
    )


def test_api_docs_index_exists():
    """The authored index is present; it is never generated, only linked from."""
    assert (API_DOCS_DIR / INDEX_FILE).is_file(), (
        f"docs/api/{INDEX_FILE} is missing. It is authored by hand, "
        "not produced by the heal command, so restore it from git."
    )


def _write() -> int:
    """Regenerate docs/api/ in place and drop pages for deleted modules."""
    rendered = generate_into(API_DOCS_DIR)
    for name in sorted(rendered):
        print(f"wrote docs/api/{name}")

    keep = set(rendered) | {INDEX_FILE}
    for path in sorted(API_DOCS_DIR.glob("*.md")):
        if path.name not in keep:
            path.unlink()
            print(f"removed orphaned docs/api/{path.name}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(_write())
    print(f"usage: python tests/test_api_docs.py --write\n\nheal command: {HEAL_COMMAND}")
    raise SystemExit(2)
