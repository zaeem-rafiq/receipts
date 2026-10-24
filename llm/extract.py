"""Build-time: deck.md -> claims.json (names + claim text only) via Nicrron; numbers are parsed later by regex in engine/load.py.
Without NICRRON_API_KEY it writes the fallback (logos_fallback.json) and labels source='fallback'. Hands off through Roundtable."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from integrations import nicrron, roundtable  # noqa: E402

DATA = ROOT / "data_room"
PROMPT = ("Extract from this pitch deck (1) every customer logo name on the customers slide, in order, and (2) these claims as exact "
          "quotes: ARR (id 'arr'), customer count ('customers'), enterprise customer count ('enterprise'), the raise ('ask'). "
          'Return JSON only: {"logos":[{"name":..,"slide":..}],"claims":[{"id":..,"text":..,"slide":..,"quote":..}]}. '
          "Copy text exactly; do not convert numbers.\n\n")


def main():
    deck = (DATA / "deck.md").read_text()
    fb = json.loads((DATA / "logos_fallback.json").read_text())
    doc, source = None, "fallback"
    if nicrron.enabled():
        try:
            text, _ = nicrron.chat([{"role": "user", "content": PROMPT + deck}], max_tokens=1500, json_mode=True)
            doc = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            assert all(c["quote"] in deck for c in doc["claims"]), "quote not in deck"
            # The model may paraphrase `text`; the number the engine parses must be the one in the deck-verified quote.
            from engine.load import parse_claim_number
            for c in doc["claims"]:
                assert parse_claim_number(c["text"]) == parse_claim_number(c["quote"]), f"claim {c['id']}: number differs from the deck quote"
            assert len(doc["logos"]) == len(fb["logos"])
            for i, l in enumerate(doc["logos"]):
                l["slot"] = f"logo_{i + 1:02d}"
            source = "llm"
        except Exception as e:
            print("extraction failed, using fallback:", type(e).__name__, e)
            doc = None
    if doc is None:
        doc = {"logos": fb["logos"], "claims": fb["claims"]}
    doc["source"] = source
    v = roundtable.put_file("claims.json", doc, note=f"source={source}")
    (DATA / "claims.json").write_text(json.dumps(doc, indent=1))
    print(f"claims.json written (source={source}, roundtable v{v})")


if __name__ == "__main__":
    main()
