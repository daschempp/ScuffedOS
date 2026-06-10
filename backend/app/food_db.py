"""Food-database lookup (M3) — USDA FoodData Central.

Resolves "chicken wrap" to candidate foods with macros so the assistant can
file a real meal (spec §3: phrase → DB lookup → confirm → macros filed).
USDA over Open Food Facts: its Foundation/SR/Survey sets cover *generic*
foods, which is what natural-language logging needs. DEMO_KEY works out of
the box (rate-limited); set FDC_API_KEY for a free unthrottled key.

Same seam as llm.py/memory_engine.py: tests call `configure(fake)` with an
object exposing `.search(query, limit)`; `configure(None)` simulates the
network being down. All failures degrade to None — the caller decides how
to phrase "lookup unavailable".
"""
from __future__ import annotations

import logging

from .config import settings

logger = logging.getLogger("scuffed_os.food_db")

_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
# FDC nutrient numbers: energy, protein, carbs, fat.
_NUTRIENTS = {"208": "kcal", "203": "protein_g", "205": "carbs_g", "204": "fat_g"}

_override: object | None | str = "unset"


def configure(override: object | None | str = "unset") -> None:
    global _override
    _override = override


def _normalize(food: dict) -> dict:
    macros = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for n in food.get("foodNutrients", []):
        key = _NUTRIENTS.get(str(n.get("nutrientNumber")))
        if key and n.get("value") is not None:
            macros[key] = float(n["value"])
    serving = "100 g"
    if food.get("servingSize") and food.get("servingSizeUnit"):
        serving = f'{food["servingSize"]:g} {food["servingSizeUnit"]} (macros per 100 g)'
    return {
        "fdc_id": food["fdcId"],
        "description": (food.get("description") or "").title(),
        "brand": food.get("brandOwner") or None,
        "serving": serving,
        "kcal": round(macros["kcal"]),
        "protein_g": round(macros["protein_g"], 1),
        "carbs_g": round(macros["carbs_g"], 1),
        "fat_g": round(macros["fat_g"], 1),
    }


def search(query: str, limit: int = 5) -> list[dict] | None:
    """Top matches with per-100g macros, or None if the lookup is unavailable."""
    if _override is None:
        return None
    if _override != "unset":
        return _override.search(query, limit)
    import httpx

    try:
        res = httpx.get(
            _SEARCH_URL,
            params={
                "api_key": settings.fdc_api_key,
                "query": query,
                "pageSize": limit,
                # Generic foods first; Branded only helps barcode-ish queries.
                "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"],
            },
            timeout=8.0,
        )
        res.raise_for_status()
        return [_normalize(f) for f in res.json().get("foods", [])[:limit]]
    except Exception as exc:
        logger.warning("food lookup failed: %s", exc)
        return None
