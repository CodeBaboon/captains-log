"""Compile every source file against the oldest Python this app supports.

The Pi runs Debian bookworm's Python 3.11 while development may happen on a
newer one, so syntax that works locally can fail on deployment. Run this
before pushing.
"""

import ast
import pathlib
import sys

TARGET = (3, 11)

failures = []
for path in sorted(pathlib.Path(__file__).parent.glob("*.py")):
    try:
        ast.parse(path.read_text(), filename=str(path), feature_version=TARGET)
    except SyntaxError as exc:
        failures.append(f"  {path.name}:{exc.lineno}: {exc.msg}")

target = ".".join(str(n) for n in TARGET)
if failures:
    print(f"Syntax not valid on Python {target}:")
    print("\n".join(failures))
    sys.exit(1)
print(f"all files parse on Python {target}")
