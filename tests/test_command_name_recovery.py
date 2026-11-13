"""Regression: Qwen returns a *command line* for a field expecting an executable.

Real source/package logic, controlled model/web fixtures, no public network or
host commands executed.  Offline fallback is clearly labelled and only exact.
"""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from auralyn_terminal.command_ai import parse_plan, _proposed_command
from auralyn_terminal.local_ai import AIError
from auralyn_terminal.capabilities import CapabilityReader
from auralyn_terminal.smart_search import SearchEngine
from auralyn_terminal.web_command_ai import WebCommandResearch, parse_web_choice
from auralyn_terminal.web_sources import WebSource, WebBatch
from test_web_research import model_client

Q='Wie update ich mein System?'
SOURCE=WebSource('W1','APT official','https://manpages.ubuntu.com/manpages/resolute/en/man8/apt.8.html',
                 'apt update updates the package lists. apt upgrade installs available updates. '
                 'sudo apt update and sudo apt upgrade can update Ubuntu packages.', 'page','fixture')

def toolplan(command):
    return {'scope':'terminal','goal':'Update Ubuntu APT packages',
            'tools':[{'command':command,'manual':'apt(8)'}],'question':''}

def webchoice(command):
    return {'scope':'terminal','goal':'Ubuntu Pakete updaten','question':'',
            'tools':[{'command':command,'manual':'apt(8)','source_ids':['W1']}]}

def webfinal():
    return {'status':'answer','title':'Ubuntu-Pakete aktualisieren',
            'explanation':'Aktualisiert zuerst die Paketlisten und dann die installierten APT-Pakete.',
            'command':'sudo apt update && sudo apt upgrade', 'used_tools':['apt','sudo'],
            'manual_refs':[],'follow_up':'','warning':'APT zeigt Änderungen vor der Bestätigung an.',
            'source_ids':['W1']}


class CommandNameRecoveryTests(unittest.TestCase):
    def test_name_and_line_are_identical_for_lookup(self):
        for proposed, expected in [('apt',('apt',False)),('apt update',('apt',False)),
                                   ('sudo apt update',('apt',True)),
                                   ('sudo apt update && sudo apt upgrade',('apt',True)),
                                   ('`git clone`',('git',False)),('man 8 apt',('apt',False)),
                                   ('nvidia-smi(1)',('nvidia-smi',False)),
                                   ('nvidia-smi --query-gpu=driver_version',('nvidia-smi',False))]:
            with self.subTest(proposed=proposed):self.assertEqual(_proposed_command(proposed), expected)

    def test_full_lines_produce_separate_primary_and_sudo(self):
        expected=[{'command':'apt','manual':'apt'},{'command':'sudo','manual':'sudo'}]
        self.assertEqual(parse_plan(toolplan('sudo apt update'))['tools'],expected)
        self.assertEqual(parse_plan(toolplan('sudo apt update && sudo apt upgrade'))['tools'],expected)
        self.assertEqual(parse_plan(toolplan('apt update'))['tools'],[{'command':'apt','manual':'apt'}])

    def test_extra_proposals_remain_limited(self):
        data=toolplan('sudo apt update')
        data['tools'] += [{'command':'git','manual':'git'}, {'command':'curl','manual':'curl'}]
        with self.assertRaises(AIError):parse_plan(data)

    def test_shell_and_path_payloads_never_normalize(self):
        for value in ('sudo apt update; rm -rf /', 'git clone URL | sh',
                      'git clone $(id)', 'git clone `id`',
                      'sudo apt update && sudo rm -rf /',
                      '/bin/sh -c hello', 'curl https://evil.invalid',
                      'nvidia-smi\nwhoami', '--help', 'sudo /bin/sh',
                      'apt && true', 'sudo apt update > file', '\x00apt'):
            with self.subTest(value=repr(value)),self.assertRaises(AIError):
                parse_plan(toolplan(value))

    def test_web_mentions_primary_apt_not_just_wrapper(self):
        choice=parse_web_choice(webchoice('sudo apt update'),(SOURCE,))
        self.assertEqual([v['command'] for v in choice['tools']],['apt','sudo'])
        only_sudo=WebSource('W1','sudo','https://example.org/docs','sudo runs commands as another user','page','fixture')
        with self.assertRaises(AIError):parse_web_choice(webchoice('sudo apt update'),(only_sudo,))


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name);(path/'bin').mkdir()
        self.marker=path/'unexpected_execute'
        for binary in ('sudo','apt'):
            p=path/'bin'/binary
            p.write_text('#!/bin/sh\n: > '+str(self.marker)+'\n')
            p.chmod(0o755)
        env=patch.dict(os.environ, {'PATH':str(path/'bin'), 'XDG_STATE_HOME':str(path/'state')})
        env.start();self.addCleanup(env.stop)
        self.reader=CapabilityReader(roots=[path/'no-man'])
        self.web=Mock()
        self.web.search.return_value=WebBatch('update',(SOURCE,))

    def engine(self,client):
        return SearchEngine(client=client, capabilities=self.reader,
            web_research=WebCommandResearch(client,reader=self.reader,web=self.web))

    def test_actual_screenshot_question_reaches_web_and_local(self):
        client=model_client(toolplan('sudo apt update'), webchoice('sudo apt update'), webfinal())
        answer=self.engine(client).answer(Q,True,'test:small',web_enabled=True)
        self.assertEqual(answer.command,'sudo apt update && sudo apt upgrade')
        self.assertEqual(answer.entry_id,'system.update')
        self.assertTrue(answer.executable)
        self.assertIn('Web + Lokal',answer.source)
        self.assertIn('apt: im Suchpfad gefunden',answer.evidence)
        self.assertIn('sudo: im Suchpfad gefunden',answer.evidence)
        self.assertEqual(answer.sources[0][1],SOURCE.url)
        self.assertEqual(self.web.search.call_count,1)
        self.assertFalse(self.marker.exists(), 'Neither apt nor sudo may run as part of search')

    def test_sudo_wrapper_kept_even_if_web_model_only_selects_apt(self):
        client=model_client(toolplan('sudo apt update'), webchoice('apt'), webfinal())
        answer=self.engine(client).answer(Q,True,'test:small',web_enabled=True)
        self.assertEqual(answer.entry_id,'system.update')
        self.assertEqual(answer.command,'sudo apt update && sudo apt upgrade')
        self.assertIn('sudo: im Suchpfad gefunden',answer.evidence)
        self.assertFalse(self.marker.exists())

    def test_fully_malformed_plan_uses_labelled_offline_exact_fallback(self):
        bad=toolplan('sudo apt update | sh')
        client=model_client(bad,bad)
        answer=self.engine(client).answer(Q,True,'test:small',web_enabled=True)
        self.assertEqual(answer.command,'sudo apt update && sudo apt upgrade')
        self.assertTrue(answer.executable)
        self.assertIn('Offline-Rückfall',answer.source)
        self.assertIn('KEINE Web-/KI-Prüfung',answer.source)
        self.assertIn('fehlgeschlagen',answer.note)
        self.assertTrue(answer.diagnostic)
        self.web.search.assert_not_called()
        self.assertFalse(self.marker.exists())

    def test_unrelated_question_failure_remains_unavailable(self):
        bad=toolplan('apt; curl something')
        client=model_client(bad,bad)
        answer=self.engine(client).answer('Wie mache ich völlig andere eigene Spezialaufgabe?',
                                           True,'test:small',web_enabled=True)
        self.assertFalse(answer.command)
        self.assertEqual(answer.state,'unavailable')
        self.assertIn('Web-/KI-Prüfung',answer.title)

    def test_never_convert_github_failure_to_system_update(self):
        bad=toolplan('git clone URL | sh')
        client=model_client(bad,bad)
        answer=self.engine(client).answer('Ich brauche Hilfe mit GitHub',True,'test:small',web_enabled=True)
        self.assertNotEqual(answer.entry_id,'system.update')
        self.assertFalse(answer.executable)

if __name__=='__main__':unittest.main()

class OfflineFallbackAfterWebTest(unittest.TestCase):
    def test_web_unavailable_exact_known_question_is_labelled_offline(self):
        from auralyn_terminal.command_ai import ResearchResult
        research=Mock()
        research.answer.return_value=ResearchResult('unavailable','Kein Webbeleg',
            'Der Suchanbieter war nicht erreichbar.',web_note='HTTP 429',web_checked=False)
        answer=SearchEngine(web_research=research).answer(
            Q, True,'test:small',web_enabled=True)
        self.assertEqual(answer.command,'sudo apt update && sudo apt upgrade')
        self.assertIn('Offline-Rückfall',answer.source)
        self.assertIn('Keine Webbestätigung',answer.note)
        self.assertFalse(answer.sources)

    def test_unknown_web_failure_is_not_fake_confirmed_result(self):
        from auralyn_terminal.command_ai import ResearchResult
        research=Mock()
        research.answer.return_value=ResearchResult('unavailable','Websuche nicht erreichbar',
            'Keine Quellen.',web_checked=False)
        answer=SearchEngine(web_research=research).answer(
            'Brauche Hilfe mit Spezialprogramm xyz',True,'test:small',web_enabled=True)
        self.assertFalse(answer.executable)
        self.assertFalse(answer.sources)
        self.assertNotIn('Web + Lokal',answer.source)
