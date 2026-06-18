import json
import tempfile
import unittest
from pathlib import Path

from scripts.event_risk import assess_event_risk


class EventRiskTests(unittest.TestCase):
    def test_market_holiday_closes_new_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-19", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "closed")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.0)
            self.assertTrue(any(item["risk_label"] == "market_holiday" for item in payload["active_events"]))

    def test_nonfarm_window_is_high_risk_before_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-30", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "high")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.65)
            self.assertTrue(any(item["risk_label"] == "nonfarm_payroll" for item in payload["active_events"]))

    def test_normal_when_no_window_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-24", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "normal")
            self.assertEqual(payload["active_events"], [])

    def _write_inputs(self, root: Path):
        events = root / "events.json"
        policy = root / "policy.json"
        events.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "date": "2026-06-19",
                            "time_et": "all_day",
                            "event": "NYSE closed for Juneteenth National Independence Day",
                            "status": "market_holiday",
                            "source": "https://example.com/holiday",
                        },
                        {
                            "date": "2026-07-02",
                            "time_et": "08:30",
                            "event": "Employment Situation - June 2026",
                            "status": "scheduled",
                            "source": "https://example.com/nfp",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        policy.write_text(
            json.dumps(
                {
                    "default": {
                        "risk_level": "normal",
                        "max_new_gross_exposure_pct": 0.9,
                        "note": "No active window.",
                    },
                    "policies": [
                        {
                            "match": {"status": "market_holiday"},
                            "label": "market_holiday",
                            "risk_level": "closed",
                            "pre_days": 0,
                            "post_days": 0,
                            "max_new_gross_exposure_pct": 0.0,
                            "action": "closed",
                        },
                        {
                            "match": {"event_contains": "Employment Situation"},
                            "label": "nonfarm_payroll",
                            "risk_level": "high",
                            "pre_days": 3,
                            "post_days": 1,
                            "max_new_gross_exposure_pct": 0.65,
                            "action": "reduce",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return events, policy


if __name__ == "__main__":
    unittest.main()

