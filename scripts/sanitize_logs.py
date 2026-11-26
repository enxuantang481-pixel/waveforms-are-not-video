"""Before committing: strip the local account name from logs and environment dumps.

Replaces /home/<name> with ~ and the owner/group columns of `ls -l` lines with "user".
Usage (repo root): python scripts/sanitize_logs.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = list((ROOT / "results").rglob("*.log")) + list((ROOT / "env").glob("*.txt"))
HOME = re.compile(r"/home/(?!conda/)[^/\s\"']+")
LS = re.compile(r"^([-dl][rwxsStT-]{9}\S*\s+\d+\s+)(\S+)(\s+)(\S+)", re.M)

for p in FILES:
    s = p.read_text(encoding="utf-8", errors="replace")
    t = HOME.sub("~", s)
    t = LS.sub(lambda m: m.group(1) + "user" + m.group(3) + "user", t)
    if t != s:
        p.write_text(t, encoding="utf-8", newline="\n")
        print("sanitized", p.relative_to(ROOT))
