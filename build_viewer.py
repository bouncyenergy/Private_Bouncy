#!/usr/bin/env python3
"""
Bygger viewer/arbitrage.html: en fristående sida med all data inbäddad.
Den går att ladda ner och öppna direkt i webbläsaren (dubbelklicka), utan webbserver.

Körs efter update_data.py:
    python update_data.py
    python build_viewer.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
NAMES = {"summary": "summary.json", "depth": "depth.json", "slope": "slope.json"}


def main() -> int:
    template = (ROOT / "viewer_template.html").read_text(encoding="utf-8")
    embed = {}
    for key, fname in NAMES.items():
        path = DATA / fname
        if path.exists():
            embed[key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            print(f"Varning: {path} saknas")
    if "summary" not in embed or "depth" not in embed:
        print("Ingen data att bädda in. Kör update_data.py först.")
        return 1
    payload = json.dumps(embed, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    assert "/*EMBED_JSON*/null" in template
    out = ROOT / "viewer" / "arbitrage.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("/*EMBED_JSON*/null", payload), encoding="utf-8")
    print(f"Skrev {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
