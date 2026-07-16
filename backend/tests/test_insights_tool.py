"""The get_insights assistant tool reads cached cards (no generation)."""
import json
from datetime import date

from app import tools
from app.store import store

TODAY = date.today()


def test_get_insights_tool_reads_cached_cards(client):
    store.upsert_insight(day=TODAY, domain="fitness", code="recovery_band",
                         tone="positive", headline="Recovery is green",
                         body="Recovery is 80% — primed.", signals={}, source="rules")
    result_json, action = tools.execute("get_insights", {})
    result = json.loads(result_json)
    assert action is None
    assert result["insights"][0]["headline"] == "Recovery is green"
    assert result["insights"][0]["tone"] == "positive"
