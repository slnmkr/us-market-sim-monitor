import unittest

from scripts.market_monitor import quote_summary
from scripts.paper_account import build_portfolio, mark_to_market, planned_orders, validate_trades


class PortfolioMathTests(unittest.TestCase):
    def test_build_portfolio_uses_only_filled_trades(self):
        trades = [
            {
                "symbol": "SPY",
                "side": "buy",
                "quantity": "2",
                "price": "100",
                "notional_usd": "200",
                "status": "planned",
            },
            {
                "symbol": "SPY",
                "side": "buy",
                "quantity": "1",
                "price": "100",
                "notional_usd": "100",
                "status": "filled",
            },
        ]
        portfolio = build_portfolio(trades, 1000.0)
        self.assertEqual(portfolio["cash"], 900.0)
        self.assertEqual(portfolio["positions"]["SPY"].quantity, 1.0)

    def test_mark_to_market(self):
        trades = [
            {
                "symbol": "QQQ",
                "side": "buy",
                "quantity": "2",
                "price": "50",
                "notional_usd": "100",
                "status": "filled",
            }
        ]
        portfolio = build_portfolio(trades, 1000.0)
        mtm = mark_to_market(portfolio, {"QQQ": {"close": 60.0}}, 1000.0)
        self.assertEqual(mtm["cash"], 900.0)
        self.assertEqual(mtm["total_equity"], 1020.0)
        self.assertEqual(mtm["positions"][0]["unrealized_pnl"], 20.0)
        self.assertEqual(mtm["return_pct"], 2.0)

    def test_quote_summary_calculates_change(self):
        snapshot = {
            "quotes": [
                {
                    "symbol": "SPY",
                    "source": "example",
                    "bars": [
                        {"date_utc": "2026-01-01", "close": 100.0},
                        {"date_utc": "2026-01-02", "close": 105.0},
                    ],
                }
            ]
        }
        out = quote_summary(snapshot)
        self.assertEqual(out["SPY"]["change"], 5.0)
        self.assertEqual(out["SPY"]["change_pct"], 5.0)

    def test_validate_trades_enforces_planned_limits(self):
        trades = [
            {
                "trade_date": "2026-01-01",
                "time_et": "09:30",
                "symbol": "SPY",
                "side": "buy",
                "quantity": "1000",
                "price": "100",
                "notional_usd": "100000",
                "status": "planned",
                "reason": "test",
                "sources": "https://example.com",
                "notes": "Synthetic test",
            }
        ]
        errors = validate_trades(trades, 100000.0)
        self.assertTrue(any("planned gross exposure" in item for item in errors))
        self.assertTrue(any("SPY planned exposure" in item for item in errors))

    def test_validate_trades_requires_sources_for_planned_rows(self):
        trades = [
            {
                "trade_date": "2026-01-01",
                "time_et": "09:30",
                "symbol": "SPY",
                "side": "buy",
                "quantity": "1",
                "price": "100",
                "notional_usd": "100",
                "status": "planned",
                "reason": "test",
                "sources": "",
                "notes": "Synthetic test",
            }
        ]
        errors = validate_trades(trades, 100000.0)
        self.assertTrue(any("need source URLs" in item for item in errors))

    def test_planned_orders_extracts_only_plans(self):
        trades = [
            {
                "trade_date": "2026-01-01",
                "time_et": "09:30",
                "symbol": "spy",
                "side": "buy",
                "quantity": "1",
                "price": "100",
                "notional_usd": "100",
                "status": "planned",
                "reason": "test",
                "sources": "https://example.com",
                "notes": "Synthetic test",
            },
            {
                "trade_date": "2026-01-01",
                "time_et": "09:30",
                "symbol": "QQQ",
                "side": "buy",
                "quantity": "1",
                "price": "100",
                "notional_usd": "100",
                "status": "filled",
                "reason": "test",
                "sources": "https://example.com",
                "notes": "Synthetic test",
            },
        ]
        plans = planned_orders(trades)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["symbol"], "SPY")


if __name__ == "__main__":
    unittest.main()
