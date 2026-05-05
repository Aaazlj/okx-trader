import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class DummyOKXClient:
    def __init__(self, positions):
        self.positions = positions
        self.closed = []

    def get_positions(self, inst_id=None):
        return self.positions

    def close_position(self, inst_id, td_mode=None, pos_side=None):
        self.closed.append((inst_id, td_mode, pos_side))
        return True


@pytest.mark.asyncio
async def test_manual_close_position_passes_margin_mode_and_pos_side(monkeypatch):
    from api import positions

    client = DummyOKXClient([
        {"instId": "BTC-USDT-SWAP", "pos": "1", "mgnMode": "isolated", "posSide": "long"}
    ])
    monkeypatch.setattr(positions, "_client", client)

    result = await positions.close_position(
        "btc-usdt-swap",
        positions.ClosePositionRequest(pos_side="long"),
    )

    assert result == {"message": "已提交市价平仓", "symbol": "BTC-USDT-SWAP", "pos_side": "long"}
    assert client.closed == [("BTC-USDT-SWAP", "isolated", "long")]


@pytest.mark.asyncio
async def test_manual_close_position_requires_side_for_multiple_positions(monkeypatch):
    from api import positions

    client = DummyOKXClient([
        {"instId": "BTC-USDT-SWAP", "pos": "1", "mgnMode": "cross", "posSide": "long"},
        {"instId": "BTC-USDT-SWAP", "pos": "1", "mgnMode": "cross", "posSide": "short"},
    ])
    monkeypatch.setattr(positions, "_client", client)

    with pytest.raises(HTTPException) as exc:
        await positions.close_position("BTC-USDT-SWAP", None)

    assert exc.value.status_code == 400
    assert client.closed == []
