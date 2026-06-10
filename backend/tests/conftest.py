import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store


@pytest.fixture(autouse=True)
def fresh_store():
    """Reset the in-memory store to its seed state around every test.

    Routers hold a reference to the module-level singleton, so it must be reset
    in place rather than replaced.
    """
    store.__init__()
    yield
    store.__init__()


@pytest.fixture()
def client():
    return TestClient(app)
