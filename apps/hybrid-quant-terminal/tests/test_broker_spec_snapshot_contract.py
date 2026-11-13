"""Static safety checks; these do not compile or run the MT5 script."""

from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "mql5" / "BrokerSpecificationSnapshot.mq5"
)


def test_snapshot_is_read_only_and_limits_account_scope() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("OrderSend(", "OrderSendAsync(", "CTrade", "ACCOUNT_LOGIN"):
        assert forbidden not in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    assert "TERMINAL_CONNECTED" in source
    assert 'StringFind(server,"Exness")' in source


def test_snapshot_keeps_unavailable_values_and_quote_time_distinct() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"EURUSDm"' in source and '"XAUUSDm"' in source
    assert "SYMBOL_TRADE_TICK_VALUE_PROFIT" in source
    assert "SYMBOL_TRADE_TICK_VALUE_LOSS" in source
    assert "unavailable_not_inferred" in source
    assert "broker_time_timezone_unverified" in source
    assert "self_reported_not_authenticated" in source


def test_native_probe_uses_hypothetical_calculation_without_trade_execution() -> None:
    source = (SCRIPT.parent / "BrokerNativeRiskProbe.mq5").read_text(encoding="utf-8")
    assert "OrderCalcProfit(" in source and "OrderCalcMargin(" in source
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    for forbidden in (
        "OrderSend(",
        "OrderSendAsync(",
        "OrderCheck(",
        "CTrade",
        "ACCOUNT_LOGIN",
    ):
        assert forbidden not in source
    assert "FileMove(" in source and ".partial" in source


def test_specification_snapshot_requires_synchronized_symbol_and_partial_publication() -> (
    None
):
    source = SCRIPT.read_text(encoding="utf-8")
    assert "SymbolIsSynchronized(" in source
    assert "SYMBOL_SELECT" in source
    assert "FileMove(" in source and ".partial" in source
