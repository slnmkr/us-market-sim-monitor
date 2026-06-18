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

    def test_cpi_window_is_high_risk_before_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-07-13", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "high")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.65)
            self.assertTrue(any(item["risk_label"] == "cpi" for item in payload["active_events"]))

    def test_pce_window_is_high_risk_before_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-24", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "high")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.65)
            self.assertTrue(any(item["risk_label"] == "pce" for item in payload["active_events"]))

    def test_fomc_minutes_window_is_medium_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-07-07", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "medium")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.75)
            self.assertTrue(any(item["risk_label"] == "fomc_minutes" for item in payload["active_events"]))

    def test_fomc_meeting_window_is_high_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-07-28", events_path=events, policy_path=policy)
            self.assertEqual(payload["current_risk"]["risk_level"], "high")
            self.assertEqual(payload["current_risk"]["max_new_gross_exposure_pct"], 0.65)
            self.assertTrue(any(item["risk_label"] == "fomc" for item in payload["active_events"]))

    def test_next_events_include_upcoming_fomc_meeting(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-19", events_path=events, policy_path=policy)
            self.assertTrue(any(item["event"] == "FOMC Meeting - July 2026" for item in payload["next_events"]))

    def test_normal_when_no_window_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            events, policy = self._write_inputs(Path(tmp))
            payload = assess_event_risk("2026-06-28", events_path=events, policy_path=policy)
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
                            "date": "2026-06-25",
                            "time_et": "08:30",
                            "event": "Personal Income and Outlays - May 2026",
                            "status": "scheduled",
                            "source": "https://example.com/pce",
                        },
                        {
                            "date": "2026-07-02",
                            "time_et": "08:30",
                            "event": "Employment Situation - June 2026",
                            "status": "scheduled",
                            "source": "https://example.com/nfp",
                        },
                        {
                            "date": "2026-07-14",
                            "time_et": "08:30",
                            "event": "Consumer Price Index - June 2026",
                            "status": "scheduled",
                            "source": "https://example.com/cpi",
                        },
                        {
                            "date": "2026-07-08",
                            "time_et": "14:00",
                            "event": "FOMC Minutes - June 16-17 meeting",
                            "status": "scheduled",
                            "source": "https://example.com/fomc-minutes",
                        },
                        {
                            "date": "2026-07-29",
                            "time_et": "14:00",
                            "event": "FOMC Meeting - July 2026",
                            "status": "scheduled",
                            "source": "https://example.com/fomc-meeting",
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
                        {
                            "match": {"event_contains": "Consumer Price Index"},
                            "label": "cpi",
                            "risk_level": "high",
                            "pre_days": 2,
                            "post_days": 1,
                            "max_new_gross_exposure_pct": 0.65,
                            "action": "reduce inflation risk",
                        },
                        {
                            "match": {"event_contains": "Personal Income and Outlays"},
                            "label": "pce",
                            "risk_level": "high",
                            "pre_days": 2,
                            "post_days": 1,
                            "max_new_gross_exposure_pct": 0.65,
                            "action": "reduce pce risk",
                        },
                        {
                            "match": {"event_contains": "FOMC Minutes"},
                            "label": "fomc_minutes",
                            "risk_level": "medium",
                            "pre_days": 1,
                            "post_days": 0,
                            "max_new_gross_exposure_pct": 0.75,
                            "action": "review minutes",
                        },
                        {
                            "match": {"event_contains": "FOMC"},
                            "label": "fomc",
                            "risk_level": "high",
                            "pre_days": 2,
                            "post_days": 1,
                            "max_new_gross_exposure_pct": 0.65,
                            "action": "avoid leverage",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return events, policy


if __name__ == "__main__":
    unittest.main()
