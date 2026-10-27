import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tplus_predict.agents as agents
from tplus_predict.runner import UTC, safe_slug


class TestProviderScheduling(unittest.TestCase):
    def test_budget_is_shared_fairly_across_providers(self):
        now = dt.datetime.now(UTC)
        forecasts = []
        for i in range(2):
            kickoff = now + dt.timedelta(minutes=60 + i * 5)
            forecasts.append({
                't_match_id': 't:2026-10-27:周二00' + str(i + 1),
                'home': 'Home' + str(i), 'away': 'Away' + str(i), 'league': 'Test',
                'kickoff_utc': kickoff.isoformat(),
                'information_cutoff_utc': now.isoformat(),
                'lead_minutes_at_recording': 60 + i * 5,
                'p_1x2': {'home': 0.4, 'draw': 0.3, 'away': 0.3},
                'market_overround': 0.12,
                'input_hash': 'hash' + str(i)
            })
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {
                'TPLUS_ENABLE_AI': '1',
                'TPLUS_AI_MAX_CALLS_PER_RUN': '2',
                'OPENAI_API_KEY': 'fake-openai',
                'TPLUS_OPENAI_MODEL': 'fake-openai-model',
                'GEMINI_API_KEY': 'fake-gemini',
                'TPLUS_GEMINI_MODEL': 'fake-gemini-model'
            }, clear=False):
                with patch.object(agents, 'openai_predict', return_value=({'home': 0.4, 'draw': 0.3, 'away': 0.3}, 'mock')) as op, \
                     patch.object(agents, 'gemini_predict', return_value=({'home': 0.3, 'draw': 0.4, 'away': 0.3}, 'mock')) as gm:
                    result = agents.run_agents(Path(tmp), forecasts, now)
        self.assertEqual(result['requests_attempted'], 2)
        self.assertEqual(len(result['predictions_saved']), 2)
        self.assertEqual(op.call_count, 1)
        self.assertEqual(gm.call_count, 1)


if __name__ == '__main__':
    unittest.main()
