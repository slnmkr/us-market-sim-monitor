import unittest

from scripts.market_monitor import build_portfolio, mark_to_market, quote_summary


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
        mtm = mark_to_market(portfolio, {"QQQ": {"close": 60.0}})
        self.assertEqual(mtm["cash"], 900.0)
        self.assertEqual(mtm["total_equity"], 1020.0)
        self.assertEqual(mtm["positions"][0]["unrealized_pnl"], 20.0)

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


if __name__ == "__main__":
    unittest.main()

