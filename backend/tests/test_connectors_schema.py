"""M9 Slice 1 — ConnectorInfo/ConnectorItem schema shape."""
import pytest
from pydantic import ValidationError

from app.schemas import ConnectorInfo, ConnectorItem


def test_connector_info_allows_not_connected_with_null_timestamps():
    info = ConnectorInfo(
        name="google", label="Google / Gmail", auth_kind="oauth",
        configured=False, status="not_connected",
    )
    assert info.connected_at is None
    assert info.provider_user_id is None
    assert info.can_write_email is None
    assert info.items == []


def test_connector_info_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ConnectorInfo(
            name="google", label="Google", auth_kind="oauth",
            configured=True, status="bogus",
        )


def test_connector_item_status_is_connector_vocabulary():
    item = ConnectorItem(
        item_id="itm1", institution_name="Chase",
        status="connected", last_sync_at=None,
    )
    assert item.status == "connected"
    with pytest.raises(ValidationError):
        ConnectorItem(item_id="i", institution_name="x", status="active", last_sync_at=None)
