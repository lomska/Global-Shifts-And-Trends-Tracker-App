"""
Runs every test_*.py in this folder as a subprocess (they're plain scripts, not
pytest-based) and prints a pass/fail summary. Usage: `python tests/run_all.py`
from the project root, or `python run_all.py` from inside tests/.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
test_files = sorted(p for p in HERE.glob("test_*.py"))

results = []
for path in test_files:
    print(f"\n{'=' * 60}\n{path.name}\n{'=' * 60}")
    proc = subprocess.run([sys.executable, str(path)], cwd=str(HERE))
    results.append((path.name, proc.returncode == 0))

print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
failed = [name for name, ok in results if not ok]
for name, ok in results:
    print(f"{'PASS' if ok else 'FAIL'}: {name}")

if failed:
    print(f"\n{len(failed)} test(s) failed: {', '.join(failed)}")
    sys.exit(1)
print(f"\nAll {len(results)} tests passed.")
