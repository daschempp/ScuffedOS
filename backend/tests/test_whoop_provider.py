"""WhoopProvider gains the on_connected/on_disconnect OAuthProvider hooks (M5 refactor).

on_connected kicks the fitness sync; on_disconnect deletes WHOOP's normalized
data via the store. Both exercised with monkeypatched collaborators — no
network, no DB.
"""
from app.providers.whoop import WhoopProvider


def test_on_connected_kicks_the_fitness_sync(monkeypatch):
    from app import fitness_sync
    calls = []
    monkeypatch.setattr(fitness_sync, "tick", lambda now=None: calls.append(now) or 0)
    WhoopProvider().on_connected()
    assert len(calls) == 1


def test_on_disconnect_deletes_whoop_provider_data(monkeypatch):
    from app import store as store_mod
    deleted = []
    monkeypatch.setattr(
        store_mod.store, "delete_provider_data",
        lambda provider: deleted.append(provider) or True,
    )
    WhoopProvider().on_disconnect()
    assert deleted == ["whoop"]
