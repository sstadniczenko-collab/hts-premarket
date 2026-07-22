"""Ocena AI potencjalnego wpływu newsów na cenę — Claude Haiku.

Zasilane świeżymi nagłówkami z yfinance (zero nowych zależności). Aktywne TYLKO
gdy w środowisku jest ANTHROPIC_API_KEY (GitHub Secret w Action / lokalny .env).
Bez klucza skaner działa normalnie, po prostu pomija sekcję news.
"""
from __future__ import annotations

import json
import os

MODEL = "claude-haiku-4-5-20251001"

_BIAS = {"byczy", "niedźwiedzi", "neutralny", "obustronne ryzyko"}
_STRENGTH = {"niski", "średni", "wysoki"}

_client = None


def _load_env_local() -> None:
    """Lokalnie: dociągnij klucz z .env obok repo lub z Y:\\15_AI\\02_TRADING\\.env
    (jak vtrade_analyzer). W GitHub Actions klucz jest już w środowisku (Secret)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, ".env"), os.path.join(here, "..", ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v


def available() -> bool:
    _load_env_local()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def fetch_headlines(yf_symbol: str, limit: int = 6) -> list[dict]:
    import yfinance as yf
    out: list[dict] = []
    try:
        news = yf.Ticker(yf_symbol).news or []
    except Exception:
        return out
    for item in news[:limit]:
        c = item.get("content") or item
        title = c.get("title") or item.get("title")
        pub = c.get("pubDate") or item.get("providerPublishTime") or ""
        if title:
            out.append({"title": str(title), "pub": str(pub)[:19]})
    return out


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _parse_json(txt: str) -> dict:
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
    lo, hi = txt.find("{"), txt.rfind("}")
    return json.loads(txt[lo:hi + 1])


def assess(asset: str, name: str, headlines: list[dict], model: str = MODEL) -> dict | None:
    """Ocena wpływu newsów na TEN instrument. Zwraca dict lub None (brak nagłówków)."""
    if not headlines:
        return None
    hl = "\n".join(f"- {h['title']}" for h in headlines)
    prompt = (
        "Jesteś analitykiem rynkowym. Na podstawie świeżych nagłówków oceń "
        f"POTENCJALNY krótkoterminowy wpływ na cenę instrumentu {name} ({asset}).\n\n"
        f"Nagłówki:\n{hl}\n\n"
        "Zwróć TYLKO JSON (bez markdown, bez komentarza) w formacie:\n"
        '{"bias":"byczy|niedźwiedzi|neutralny|obustronne ryzyko",'
        '"strength":"niski|średni|wysoki",'
        '"catalyst":"najważniejszy katalizator w max 6 słowach",'
        '"note":"jedno zdanie po polsku: jak to może ruszyć cenę i na co uważać"}\n'
        "Oceniaj wpływ NA TEN konkretny instrument (nie ogólny sentyment rynku). "
        "Jeśli nagłówki nie dotyczą instrumentu — bias=neutralny, strength=niski."
    )
    try:
        msg = _get_client().messages.create(
            model=model, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        d = _parse_json(msg.content[0].text)
        bias = str(d.get("bias", "")).strip()
        strg = str(d.get("strength", "")).strip()
        return {
            "bias": bias if bias in _BIAS else "neutralny",
            "strength": strg if strg in _STRENGTH else "niski",
            "catalyst": str(d.get("catalyst", ""))[:60],
            "note": str(d.get("note", ""))[:220],
            "n_headlines": len(headlines),
        }
    except Exception as e:
        return {"error": str(e)[:140]}


def enrich(results: list[dict], limit: int = 6, model: str = MODEL) -> int:
    """Dokłada r['news'] do każdego instrumentu. Zwraca liczbę ocenionych.
    No-op gdy brak klucza."""
    if not available():
        print("News AI: brak ANTHROPIC_API_KEY — pomijam ocenę newsów.")
        return 0
    n = 0
    for r in results:
        hp = fetch_headlines(r.get("yf", ""), limit)
        res = assess(r["asset"], r.get("name", r["asset"]), hp, model)
        r["news"] = res
        if res and "error" not in res:
            n += 1
        elif res and "error" in res:
            print(f"  ! news {r['asset']}: {res['error']}")
    return n
