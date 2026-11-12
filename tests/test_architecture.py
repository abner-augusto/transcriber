import ast
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "transcriber_cli"


def _imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module


def test_adr_0010_transcriber_cli_imports_only_the_standard_library_and_itself():
    allowed = sys.stdlib_module_names | {"transcriber_cli"}
    sources = sorted(CLI.rglob("*.py"))

    outside = [
        f"{path.relative_to(CLI.parent).as_posix()}: {module}"
        for path in sources
        for module in _imported_modules(path)
        if module.split(".")[0] not in allowed
    ]

    assert sources, "transcriber_cli has no source files"
    assert outside == []
