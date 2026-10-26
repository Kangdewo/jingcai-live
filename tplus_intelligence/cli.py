"""Example: python -m tplus_intelligence.cli --input examples/synthetic_input.json --output output/match_dossier.json"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .core import build_match_dossier


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    payload = json.loads(Path(a.input).read_text(encoding='utf-8'))
    dossier = build_match_dossier(payload)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Output: {out}; coverage={dossier['coverage']}; eligible_articles={dossier['media']['eligible_unique_articles']}")

if __name__ == '__main__':
    main()
