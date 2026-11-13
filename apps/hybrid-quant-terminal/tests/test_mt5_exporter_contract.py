"""Static safety checks for the read-only MQL5 source (not compilation tests)."""

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "mql5/ReadOnlyMarketBridge.mq5"


def test_exporter_has_no_order_position_or_trade_helper_calls():
    text = SOURCE.read_text(encoding="utf-8")
    forbidden = (
        "OrderSend",
        "OrderSendAsync",
        "PositionOpen",
        "PositionClose",
        "PositionModify",
        "OrderModify",
        "CTrade",
        "PositionsTotal",
        "PositionSelect",
    )
    assert not [name for name in forbidden if re.search(rf"\b{name}\b", text)]


def test_exporter_reads_only_shift_one_and_uses_sha256_handoff():
    text = SOURCE.read_text(encoding="utf-8")
    assert re.search(r"CopyRates\(Symbols\[s\],\s*Periods\[p\],\s*1,", text)
    assert "CRYPT_HASH_SHA256" in text
    assert '"copy_start_shift,1\\n"' in text
    assert '"series_synchronized,1\\n"' in text
    assert '"timestamp_semantics,broker_server_clock_unverified\\n"' in text
    assert "SERIES_SYNCHRONIZED" in text


def test_quote_freshness_requires_change_after_start_not_a_heartbeat():
    text = SOURCE.read_text(encoding="utf-8")
    assert "SymbolInfoTick(Symbols[index], tick)" in text
    assert "tick.time_msc > PreviousTickMsc[index]" in text
    assert "TickChangedAt[index] = GetTickCount64()" in text
    assert '"quote_seen_since_start,"' in text
    assert '"quote_age_ms,"' in text


def test_exporter_rechecks_terminal_attested_demo_source_without_credentials():
    text = SOURCE.read_text(encoding="utf-8")
    assert "AccountInfoInteger(ACCOUNT_TRADE_MODE)" in text
    assert "ACCOUNT_TRADE_MODE_DEMO" in text
    assert 'StringFind(lower, "exness") != 0' in text
    assert "bool approved = ApprovedDemoSource();" in text
    assert "bool synced = approved && connected" in text
    assert '"account_mode,demo\\n"' in text
    assert '"account_mode," + (approved ? "demo" : "unverified")' in text
    assert "ACCOUNT_LOGIN" not in text
    assert "ACCOUNT_NAME" not in text
