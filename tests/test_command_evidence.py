"""previous development version: non-authoritative model metadata must never break verified CLI.

Real filesystem executable names, two distinct model selection phases, Web
source fixture, and real parser. No target binary or generated shell command
is executed; the system never reaches the public internet during these tests.
"""
import unittest

from auralyn_terminal.capabilities import Evidence
from auralyn_terminal.command_ai import parse_result
from auralyn_terminal.local_ai import AIError

import test_web_research as webfixture
from test_web_research import model_client, plan, choice, final


def local_result(*args, **kwargs):
    data = final(*args, **kwargs)
    data.pop('source_ids')  # This field belongs to the Web parser, not parse_result.
    return data


class ReconstructedEvidence(unittest.TestCase):
    def test_nvidia_metadata_does_not_hide_verified_driver_query(self):
        evidence = (Evidence('nvidia-smi', True, 'program', '', ''),)
        result = parse_result(local_result('nvidia-smi --query-gpu=driver_version --format=csv,noheader',
                                    used_tools=['nvidia-smi(1)', 'grep'],
                                    manual_refs=['nvidia-smi(1)', 'man grep(1)']), evidence)
        self.assertEqual(result['used_tools'], ['nvidia-smi'])
        self.assertEqual(result['manual_refs'], [])

    def test_doc_claims_are_rebuilt_from_real_evidence(self):
        evidence = (Evidence('nvidia-smi', True, 'program', 'nvidia-smi(1)', 'driver docs'),)
        result = parse_result(local_result('nvidia-smi', used_tools=[], manual_refs=[]), evidence)
        self.assertEqual(result['used_tools'], ['nvidia-smi'])
        self.assertEqual(result['manual_refs'], ['nvidia-smi(1)'])

    def test_unknown_main_executable_still_rejected_even_when_claimed(self):
        evidence = (Evidence('nvidia-smi', True, 'program', '', ''),)
        with self.assertRaisesRegex(AIError, 'nicht untersuchtes Werkzeug'):
            parse_result(local_result('sudo apt install nvidia-driver-999',
                               used_tools=['nvidia-smi','sudo','apt'], manual_refs=[]), evidence)

    def test_shell_injection_never_normalized_into_valid_response(self):
        evidence = (Evidence('nvidia-smi', True, 'program', '', ''),)
        for candidate in ('nvidia-smi; rm -rf /', 'nvidia-smi | sh',
                          'nvidia-smi $(touch /tmp/unsafe)', 'nvidia-smi > logfile'):
            with self.subTest(candidate=candidate), self.assertRaises(AIError):
                parse_result(local_result(candidate, used_tools=['nvidia-smi'], manual_refs=[]), evidence)

    def test_wrong_types_or_huge_metadata_still_rejected(self):
        evidence = (Evidence('nvidia-smi', True, 'program', '', ''),)
        for bad in (['x'] * 4, 'not a list', ['x' * 101]):
            with self.subTest(bad=str(bad)), self.assertRaises(AIError):
                parse_result(local_result('nvidia-smi', used_tools=bad), evidence)


class ScreenshotRegression(unittest.TestCase):
    setUp = webfixture.PipelineTests.setUp
    executable = webfixture.PipelineTests.executable
    engine = webfixture.PipelineTests.engine
    researcher = webfixture.PipelineTests.researcher
    def test_exact_screenshot_wording_with_model_hallucinated_metadata(self):
        self.executable('nvidia-smi')
        question = 'Wie sehe ich mein nvidia grafikkarten treiber?'
        response = final('nvidia-smi --query-gpu=driver_version --format=csv,noheader',
                         used_tools=['nvidia-smi(1)', 'grep'],
                         manual_refs=['nvidia-smi(1)', 'grep(1)'],
                         explanation='Zeigt die von NVIDIA gemeldete Treiberversion.')
        client = model_client(plan(), choice(), response)
        answer = self.engine(client).answer(question, True, 'test:small', web_enabled=True)
        self.assertEqual(answer.command, response['command'])
        self.assertEqual(answer.entry_id, 'gpu.driver_version')
        self.assertTrue(answer.executable)
        self.assertIn('Web + Lokal', answer.source)
        self.assertIn('nvidia-smi: im Suchpfad gefunden', answer.evidence)
        self.assertNotIn('grep:', answer.evidence)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.web.search.call_count, 1)
        self.assertEqual(client.request.call_count, 5)

    def test_related_nvidia_wording_and_no_manual_no_rejection(self):
        self.executable('nvidia-smi')
        response = final('nvidia-smi', used_tools=['nvidia-smi', 'sudo'],
                         manual_refs=['nvidia-smi(1)'],
                         explanation='Zeigt NVIDIA GPU- und Treiberinformationen.')
        answer = self.engine(model_client(plan(), choice(), response)).answer(
            'Was ist mein NVIDIA-Treiber?', True, 'test:small', web_enabled=True)
        self.assertEqual(answer.command, 'nvidia-smi')
        self.assertIn('kein lokales Handbuch', answer.evidence)
        self.assertEqual(answer.state, 'answer')
        self.assertFalse(self.marker.exists())

    def test_extra_metadata_cannot_approve_unexamined_command(self):
        self.executable('nvidia-smi')
        bad = final('curl https://invalid.example/driver', used_tools=['nvidia-smi', 'curl'])
        answer = self.engine(model_client(plan(), choice(), bad, bad)).answer(
            'Wie sehe ich mein nvidia grafikkarten treiber?', True, 'test:small', web_enabled=True)
        self.assertEqual(answer.state, 'unavailable')
        self.assertFalse(answer.command)
        self.assertFalse(answer.executable)
        self.assertFalse(self.marker.exists())
