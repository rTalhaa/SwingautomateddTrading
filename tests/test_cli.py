from __future__ import annotations

import json
import unittest
from pathlib import Path

from bos75.cli import main, run_replay_payload
from bos75.models import EventType, StrategyState


class ReplayCliTests(unittest.TestCase):
    def test_run_replay_payload_returns_serialized_result(self) -> None:
        result = run_replay_payload(
            {
                "symbol": "EURUSD",
                "seed": {
                    "active_high": {"price": "100", "timestamp": "seed_high", "index": 0},
                    "active_low": {"price": "90", "timestamp": "seed_low", "index": 0},
                },
                "events": [
                    {
                        "type": "candle",
                        "bullish_leg_start_index": 1,
                        "candle": {
                            "timestamp": "t1",
                            "index": 1,
                            "open": "98",
                            "high": "102",
                            "low": "88",
                            "close": "101",
                        },
                    }
                ],
            }
        )

        self.assertEqual(result["state"], StrategyState.WAITING_FOR_BULLISH_RETRACE_ENTRY.value)
        self.assertEqual(result["pending_setup"]["entry"], "91.00")
        self.assertIsNone(result["position"])
        self.assertEqual(result["commands"][0]["command_type"], "place_pending_limit")
        self.assertEqual(result["commands"][0]["order_type"], "buy_limit")
        self.assertIn(
            EventType.PENDING_ORDER_PLACED.value,
            [log["event"] for log in result["logs"]],
        )

    def test_example_bullish_replay_fixture_runs_to_target_exit(self) -> None:
        fixture = Path(__file__).parents[1] / "examples" / "bullish_replay.json"
        result = run_replay_payload(json.loads(fixture.read_text(encoding="utf-8")))

        self.assertEqual(result["state"], StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS.value)
        self.assertIsNone(result["pending_setup"])
        self.assertIsNone(result["position"])
        self.assertEqual(len(result["commands"]), 1)
        self.assertEqual(result["logs"][-1]["event"], EventType.TARGET_HIT.value)

    def test_main_replay_writes_output_file(self) -> None:
        import tempfile

        fixture = Path(__file__).parents[1] / "examples" / "bullish_replay.json"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "result.json"

            exit_code = main(["replay", str(fixture), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["state"], StrategyState.WAITING_FOR_BULLISH_OR_BEARISH_BOS.value)


if __name__ == "__main__":
    unittest.main()
