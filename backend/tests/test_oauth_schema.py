"""The generic OAuthStatus schema (M5): connected + list[ProviderStatus].

Structurally identical to the M4 FitnessStatus so the moved status test passes;
it is what the shared /api/oauth/status endpoint returns.
"""
from datetime import datetime, timezone

from app import schemas


def test_oauth_status_shape():
    assert hasattr(schemas, "OAuthStatus")
    ps = schemas.ProviderStatus(
        provider="whoop", status="connected",
        connected_at=datetime(2026, 6, 1, tzinfo=timezone.utc), last_sync_at=None,
        provider_user_id="u1",
    )
    m = schemas.OAuthStatus(connected=True, providers=[ps])
    dumped = m.model_dump()
    assert dumped["connected"] is True
    assert dumped["providers"][0]["provider"] == "whoop"
