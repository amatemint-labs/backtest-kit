"""Files that ship in the repository must not carry anyone's machine paths or usernames."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABSOLUTE = re.compile(r"(/Users/[^/\s\"']+|/home/[^/\s\"']+|/private/(tmp|var)/|/var/folders/|C:\\\\Users\\\\)")


def test_examples_and_plugins_have_no_absolute_paths():
    hits = []
    for base in ("examples", "plugins"):
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and p.suffix in (".json", ".csv", ".html", ".md", ".toml", ".py", ".pine"):
                for m in ABSOLUTE.finditer(p.read_text(errors="ignore")):
                    hits.append(f"{p.relative_to(ROOT)}: {m.group(0)}")
    assert not hits, "machine paths found:\n" + "\n".join(hits[:20])
