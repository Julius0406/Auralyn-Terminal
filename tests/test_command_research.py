"""previous development version research regressions. LLM replies are fixtures, NOT real inference.

Real code reads temporary executable metadata and actual compressed fixture man
files. Real loopback HTTP exercises both inference phases. No suggested program,
package installation, network download or destructive command is executed.
"""
from __future__ import annotations
from dataclasses import replace
import gzip
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from auralyn_terminal.capabilities import CapabilityReader, Evidence, manual_text, excerpt, MAX_EXCERPT
from auralyn_terminal.command_ai import (CommandResearch, ResearchResult, PLAN_SCHEMA, RESULT_SCHEMA,
    parse_plan, parse_result, command_tools, exact_action)
from auralyn_terminal.local_ai import OllamaClient, AIError, Cancelled
from auralyn_terminal.smart_search import SearchEngine
from test_local_ai import MODEL, DETAILS, chat, FakeServer
from test_smart_search import FakeManual
from test_smart_ui import load_ui_class, owner, W

QUESTION = 'Wie installiere ich was von github per command?'
GIT_PLAN = {'scope': 'terminal', 'goal': 'Projekt herunterladen; Installation hängt vom Projekt ab.',
            'tools': [{'command': 'git', 'manual': 'git-clone'}], 'question': ''}
GIT_ANSWER = {'status': 'answer', 'title': 'GitHub-Projekt herunterladen',
    'explanation': 'Mit git clone lädst du das Projekt herunter. Das installiert es noch nicht.',
    'command': 'git clone REPOSITORY_URL', 'used_tools': ['git'], 'manual_refs': ['git-clone(1)'],
    'follow_up': 'Welches Projekt möchtest du installieren? Schicke den Repository-Link.', 'warning': ''}
# A deliberately short synthetic manual, not copied from a distributed manual.
MANUAL = '.TH GIT-CLONE 1\n.SH NAME\ngit-clone - retrieve a repository into a local directory\n.SH SYNOPSIS\n.B git clone\nREPOSITORY_URL [DIRECTORY]\n.SH DESCRIPTION\nCreates a local project copy; installation is a separate operation.\n'


def answer_payload(**values):
    return {**GIT_ANSWER, **values}


class ResearchFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.man = self.root / 'man'; (self.man / 'man1').mkdir(parents=True)
        self.marker = self.root / 'EXECUTED'
        self.add_tool('git')
        self.add_man('git-clone', MANUAL)
        self.env = patch.dict(os.environ, {'PATH': str(self.bin)})
        self.env.start()
        self.reader = CapabilityReader([self.man])
        self.cancel = threading.Event()

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def add_tool(self, name):
        tool = self.bin / name
        tool.write_text('#!/bin/sh\n/usr/bin/touch ' + str(self.marker) + '\n')
        tool.chmod(0o755)

    def add_man(self, name, text):
        (self.man / 'man1' / (name + '.1.gz')).write_bytes(gzip.compress(text.encode()))

    def client(self, plan=None, answer=None):
        client = OllamaClient()
        client.request = Mock(side_effect=[{'models': [MODEL]}, DETAILS,
            chat(json.dumps(GIT_PLAN if plan is None else plan)),
            chat(json.dumps(GIT_ANSWER if answer is None else answer))])
        return client

    def engine(self, client=None):
        return SearchEngine(client=client or self.client(), manual=FakeManual(), capabilities=self.reader)


class CapabilityTests(ResearchFixtures):
    def test_inventory_contains_installed_custom_names(self):
        self.add_tool('julius-custom-cli')
        self.assertIn('julius-custom-cli', self.reader.names(self.cancel))
        self.assertFalse(self.marker.exists())

    def test_inventory_never_runs_even_help(self):
        self.reader.hints('git', self.cancel)
        self.reader.inspect('git', 'git-clone', 'clone repository', self.cancel)
        self.assertFalse(self.marker.exists())

    def test_compressed_manual_read_as_text(self):
        e = self.reader.inspect('git', 'git-clone', 'clone', self.cancel)
        self.assertTrue(e.available)
        self.assertEqual(e.manual, 'git-clone(1)')
        self.assertIn('retrieve a repository', e.text)
        self.assertIn('git clone', e.text)

    def test_missing_program_not_false_impossibility(self):
        (self.bin / 'git').unlink()
        e = self.reader.inspect('git', 'git-clone', 'clone', self.cancel)
        self.assertFalse(e.available)
        self.assertTrue(e.text)
        self.assertIn('nicht im Suchpfad', e.description())

    def test_missing_docs_reported(self):
        self.add_tool('zzcustom')
        e = self.reader.inspect('zzcustom', 'zzcustom', 'custom', self.cancel)
        self.assertTrue(e.available)
        self.assertEqual(e.text, '')
        self.assertIn('kein lokales Handbuch', e.description())

    def test_no_executable_paths_in_model_payload(self):
        e = self.reader.inspect('git', 'git-clone', 'clone', self.cancel)
        self.assertNotIn(str(self.root), json.dumps(e.payload()))
        self.assertNotIn('PATH', e.payload())

    def test_unrelated_manual_name_refused(self):
        with self.assertRaises(ValueError):
            self.reader.inspect('git', 'sudo', 'test', self.cancel)

    def test_path_injection_cannot_read_private_file(self):
        for topic in ('../secret', '/etc/passwd', '--help', 'git;touch', 'git\nsecret'):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                self.reader.inspect('git', topic, 'test', self.cancel)

    def test_symlink_outside_manual_root_not_read(self):
        private = self.root / 'secret'; private.write_text('PRIVATE_FILE_CONTENT')
        (self.man / 'man1' / 'secret.1').symlink_to(private)
        e = self.reader.inspect('secret', 'secret', 'secret', self.cancel)
        self.assertFalse(e.text)

    def test_roff_shell_and_include_macros_not_interpreted(self):
        text = MANUAL + '\n.sy touch ' + str(self.marker) + '\n.so /etc/passwd\n.pso date\n'
        self.add_man('git-clone', text)
        e = self.reader.inspect('git', 'git-clone', 'git', self.cancel)
        self.assertNotIn('touch', e.text)
        self.assertNotIn('/etc/passwd', e.text)
        self.assertFalse(self.marker.exists())

    def test_builtin_is_detected_without_path(self):
        e = self.reader.inspect('cd', 'cd', 'change directory', self.cancel)
        self.assertTrue(e.available)
        self.assertEqual(e.kind, 'builtin')

    def test_cancel_before_read(self):
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.reader.inspect('git', 'git-clone', 'git', self.cancel)

    def test_bound_large_man_excerpt(self):
        self.add_man('git-clone', MANUAL + ('documentation\n' * 80000))
        e = self.reader.inspect('git', 'git-clone', 'git', self.cancel)
        self.assertLessEqual(len(e.text), MAX_EXCERPT)

    def test_failed_gzip_is_missing_not_crash(self):
        (self.man / 'man1' / 'git-clone.1.gz').write_bytes(b'not gzip')
        e = self.reader.inspect('git', 'git-clone', 'git', self.cancel)
        self.assertEqual(e.text, '')

    def test_inventory_cache_does_not_cache_availability(self):
        self.reader.names(self.cancel)
        (self.bin / 'git').unlink()
        self.assertFalse(self.reader.inspect('git', 'git', 'test', self.cancel).available)

    def test_requested_cli_prioritized_in_sample(self):
        self.add_tool('zz-julius-tool')
        hints = self.reader.hints('Wie benutze ich zz-julius-tool?', self.cancel)
        self.assertEqual(hints['installed_name_sample'][0], 'zz-julius-tool')
        self.assertTrue(hints['sample_is_incomplete'])


class PipelineTests(ResearchFixtures):
    def test_screenshot_question_uses_two_stage_research_not_release_rules(self):
        c = self.client()
        a = self.engine(c).answer(QUESTION, True, 'test:small')
        self.assertEqual(a.command, 'git clone REPOSITORY_URL')
        self.assertEqual(a.entry_id, '')
        self.assertFalse(a.executable)
        self.assertIn('Lokale KI', a.source)
        self.assertIn('Befehlsrecherche', a.source)
        self.assertIn('git-clone(1)', a.evidence)
        self.assertIn('installiert es noch nicht', a.text)
        self.assertEqual([call.args[0] for call in c.request.call_args_list],
                         ['/api/tags', '/api/show', '/api/chat', '/api/chat'])
        self.assertFalse(self.marker.exists())

    def test_model_sees_actual_manual_evidence_in_second_call(self):
        c = self.client(); self.engine(c).answer(QUESTION, True, 'test:small')
        payload = c.request.call_args_list[-1].args[1]
        data = json.loads(payload['messages'][1]['content'])
        self.assertEqual(data['question'], QUESTION)
        self.assertIn('retrieve a repository', data['local_evidence'][0]['excerpt'])
        self.assertTrue(data['local_evidence'][0]['available'])
        self.assertIs(payload['think'], False)
        self.assertEqual(payload['keep_alive'], 0)
        self.assertNotIn('Katalog:', payload['messages'][0]['content'])

    def test_question_has_no_required_keyword(self):
        a = self.engine().answer('Ich brauche den Inhalt des entfernten Versionsarchivs hier bei mir', True, 'test:small')
        self.assertEqual(a.command, GIT_ANSWER['command'])
        self.assertIn('Lokale KI', a.source)

    def test_well_known_ram_question_also_researched(self):
        self.add_tool('free'); self.add_man('free', '.TH FREE 1\n.SH NAME\nfree - display memory usage\n.SH SYNOPSIS\nfree -h\n')
        c = self.client({'scope': 'terminal', 'goal': 'Display memory', 'tools': [{'command':'free', 'manual':'free'}], 'question':''},
                        answer_payload(command='free -h', used_tools=['free'], manual_refs=['free(1)'], follow_up='',
                                       title='Arbeitsspeicher', explanation='Zeigt den Arbeitsspeicher an.'))
        a = self.engine(c).answer('Wie viel RAM ist frei?', True, 'test:small')
        self.assertEqual(a.entry_id, 'memory.usage'); self.assertTrue(a.executable)
        self.assertIn('Lokale KI', a.source)
        self.assertEqual(c.request.call_count, 4)

    def test_explain_request_never_gets_execute_permission(self):
        self.add_tool('free'); self.add_man('free', '.TH FREE 1\n.SH NAME\nfree - display memory usage\n')
        c = self.client({'scope':'terminal', 'goal':'Explain free', 'tools':[{'command':'free','manual':'free'}], 'question':''},
                        answer_payload(command='free -h',used_tools=['free'],manual_refs=['free(1)'],follow_up='',
                                       explanation='Zeigt den Arbeitsspeicher.'))
        a = self.engine(c).answer('Was macht free -h?', True, 'test:small')
        self.assertEqual(a.command, 'free -h'); self.assertFalse(a.executable)

    def test_no_automatic_install_when_git_missing(self):
        (self.bin / 'git').unlink()
        a = self.engine().answer(QUESTION, True, 'test:small')
        self.assertIn('nicht im Suchpfad', a.evidence)
        self.assertFalse(a.executable)
        self.assertFalse(self.marker.exists())

    def test_missing_manual_is_labelled_not_locally_verified(self):
        (self.man / 'man1' / 'git-clone.1.gz').unlink()
        c = self.client(answer=answer_payload(manual_refs=[]))
        a = self.engine(c).answer(QUESTION, True, 'test:small')
        self.assertIn('kein lokales Handbuch', a.evidence)
        self.assertIn('Modellwissen', a.note)
        self.assertIn('Lokale KI', a.source)

    def test_unseen_third_party_cli_not_restricted_to_catalog(self):
        self.add_tool('julius-tool')
        self.add_man('julius-tool', '.TH JULIUS 1\n.SH NAME\njulius-tool - inspect demonstration files\n.SH SYNOPSIS\njulius-tool inspect FILE\n')
        c = self.client({'scope':'terminal','goal':'Inspect a demonstration file',
                         'tools':[{'command':'julius-tool','manual':'julius-tool'}],'question':''},
                        answer_payload(title='Datei prüfen', explanation='Prüft eine Demo-Datei.',
                                       command='julius-tool inspect DATEI', used_tools=['julius-tool'],
                                       manual_refs=['julius-tool(1)'], follow_up='Welche Datei?'))
        a = self.engine(c).answer('Kann julius-tool meine Datei untersuchen?', True, 'test:small')
        self.assertEqual(a.command,'julius-tool inspect DATEI')
        self.assertFalse(a.executable)
        self.assertIn('julius-tool(1)',a.evidence)
        self.assertFalse(self.marker.exists())

    def test_app_transparency_remains_authoritative_without_model(self):
        c=self.client();a=self.engine(c).answer('Wie kann ich die transparents einstellen',True,'test:small')
        self.assertEqual(a.entry_id,'app.transparency')
        c.request.assert_not_called()

    def test_offline_does_not_call_model(self):
        c=self.client();a=self.engine(c).answer(QUESTION,False,'test:small')
        c.request.assert_not_called()
        self.assertIn('keine KI',a.source)

    def test_refusal_researched_then_exact_fixed_refusal(self):
        c=self.client({'scope':'reject','goal':'','tools':[],'question':''})
        a=self.engine(c).answer('Wie alt ist Elon Musk?',True,'test:small')
        self.assertEqual(a.text,'Anfrage Abgelehnt')
        self.assertIn('Lokale KI',a.source)
        self.assertFalse(a.command)
        self.assertEqual(c.request.call_count,3)

    def test_clarification_has_no_command(self):
        c=self.client({'scope':'clarify','goal':'','tools':[],'question':'Was möchtest du am Computer erledigen?'})
        a=self.engine(c).answer('Das brauche ich für eine besondere Arbeitsumgebung',True,'test:small')
        self.assertEqual(a.state,'clarify');self.assertFalse(a.command)
        self.assertIn('Lokale KI',a.source)

    def test_decline_does_not_display_model_trivia(self):
        c=self.client(answer=answer_payload(status='reject', explanation='Fremde Antwort über eine Person'))
        # Call pipeline directly to avoid intentional known-task offline fallback.
        a=CommandResearch(c,self.reader).answer(QUESTION,'test:small',self.cancel)
        self.assertEqual(a.state,'rejected');self.assertEqual(a.text,'')

    def test_invalid_second_command_does_not_switch_to_apt(self):
        c=self.client(answer=answer_payload(command='sudo apt upgrade',used_tools=['apt','sudo']))
        with self.assertRaises(AIError):
            CommandResearch(c,self.reader).answer(QUESTION,'test:small',self.cancel)
        self.assertFalse(self.marker.exists())

    def test_schema_error_has_explicit_offline_label(self):
        c=self.client(answer=answer_payload(command='git clone REPO; touch MARKER'))
        a=self.engine(c).answer(QUESTION,True,'test:small')
        self.assertIn('Offline-Rückfall',a.source)
        self.assertIn('Keine KI-Prüfung',a.note)
        self.assertFalse(a.executable)

    def test_no_history_env_values_or_executable_path_in_requests(self):
        c=self.client()
        with patch.dict(os.environ,{'PRIVATE_TEST_SECRET':'DO_NOT_SEND_1234'}):
            self.engine(c).answer(QUESTION,True,'test:small')
        payload=repr(c.request.call_args_list)
        self.assertNotIn('DO_NOT_SEND_1234',payload)
        self.assertNotIn(str(self.root),payload)
        self.assertNotIn('EXECUTED',payload)

    def test_cancel_between_first_and_second_model_call(self):
        c=self.client()
        original=self.reader.inspect
        def stop(*args):
            value=original(*args);self.cancel.set();return value
        with patch.object(self.reader,'inspect',side_effect=stop),self.assertRaises(Cancelled):
            CommandResearch(c,self.reader).answer(QUESTION,'test:small',self.cancel)
        self.assertEqual(c.request.call_count,3)

    def test_missing_model_no_generation(self):
        c=OllamaClient();c.request=Mock(return_value={'models':[]})
        with self.assertRaisesRegex(AIError,'nicht installiert'):
            CommandResearch(c,self.reader).answer(QUESTION,'test:small',self.cancel)
        self.assertEqual(c.request.call_count,1)

    def test_remote_model_blocked_before_question(self):
        c=self.client();c.request.side_effect=[{'models':[MODEL]}, {**DETAILS,'remote_host':'https://remote.invalid'}]
        with self.assertRaisesRegex(AIError,'Remote'):
            CommandResearch(c,self.reader).answer(QUESTION,'test:small',self.cancel)
        self.assertEqual(c.request.call_count,2)

    def test_real_loopback_two_chat_requests_and_evidence(self):
        count=0
        def route(handler):
            nonlocal count
            if handler.path=='/api/chat':
                count+=1; value=chat(json.dumps(GIT_PLAN if count==1 else GIT_ANSWER))
            else:
                value={'/api/tags':{'models':[MODEL]},'/api/show':DETAILS}[handler.path]
            encoded=json.dumps(value).encode()
            handler.send_response(200);handler.send_header('Content-Length',str(len(encoded)))
            handler.end_headers();handler.wfile.write(encoded)
        with FakeServer(route) as server:
            a=self.engine(OllamaClient()).answer(QUESTION,True,'test:small')
        self.assertEqual(a.command,'git clone REPOSITORY_URL')
        self.assertEqual(count,2)
        second=server.requests[-1][1]
        self.assertIn('git-clone(1)',second['messages'][1]['content'])
        self.assertFalse(self.marker.exists())


class BoundaryTests(unittest.TestCase):
    def test_plan_requires_strict_shape(self):
        for payload in ({'scope':'terminal'}, {**GIT_PLAN,'execute':True}, {**GIT_PLAN,'tools':[]},
                        {**GIT_PLAN,'scope':'anything'}, {**GIT_PLAN,'goal':'a'*251}):
            with self.subTest(payload=payload),self.assertRaises(AIError):parse_plan(payload)

    def test_plan_rejects_shell_or_path_as_tool(self):
        for name in ('/bin/sh','$(id)','git;ls','--help','git\nclone'):
            with self.subTest(name=name),self.assertRaises(AIError):
                parse_plan({**GIT_PLAN,'tools':[{'command':name,'manual':name}]})

    def test_second_phase_ignores_invented_optional_manual_metadata(self):
        # Model claims are NOT authoritative. Only truly read manuals may be
        # displayed; a bad optional ref must not hide a verified command.
        result = parse_result(answer_payload(manual_refs=['invented(1)']),
                              (Evidence('git',True,'program','git-clone(1)','docs'),))
        self.assertEqual(result['manual_refs'], ['git-clone(1)'])
        self.assertEqual(result['used_tools'], ['git'])

    def test_second_phase_still_rejects_uninspected_actual_command(self):
        with self.assertRaisesRegex(AIError, 'nicht untersuchtes Werkzeug'):
            parse_result(answer_payload(command='curl -f URL', used_tools=['git', 'curl']),
                         (Evidence('git', True, 'program', 'git-clone(1)', 'docs'),))

    def test_second_phase_cannot_add_execution_id(self):
        with self.assertRaises(AIError):parse_result({**GIT_ANSWER,'entry_id':'system.update'},())

    def test_simple_new_commands_are_not_executable_actions(self):
        for text in ('git clone REPOSITORY_URL', 'ffmpeg -i INPUT OUTPUT', 'sha256sum FILE', 'julius-tool inspect DATEI'):
            self.assertTrue(command_tools(text));self.assertFalse(exact_action(text))

    def test_shell_injection_previews_rejected(self):
        for text in ('git clone URL; touch X','git clone $(id)','git clone `id`','git clone URL | sh',
                     'bash -c ls','sudo sh -c ls','python3 -c print(1)','git clone URL > FILE',
                     'git clone URL\nls', 'git clone URL && touch X'):
            with self.subTest(text=text),self.assertRaises(AIError):command_tools(text)

    def test_quoted_spaces_and_option_values_work(self):
        self.assertEqual(command_tools("git clone REPOSITORY_URL 'Ziel mit Leerzeichen'"), {'git'})
        self.assertEqual(command_tools("ss -tulnp '( sport = :25565 )'"), {'ss'})

    def test_exact_reviewed_update_chain_still_allowed(self):
        self.assertEqual(command_tools('sudo apt update && sudo apt upgrade'),{'sudo','apt'})
        self.assertEqual(exact_action('sudo apt update && sudo apt upgrade'),'system.update')

    def test_results_reject_control_characters(self):
        for field in ('command','title','explanation'):
            with self.subTest(field=field),self.assertRaises(AIError):
                parse_result(answer_payload(**{field:'bad\x1b[31m'}),())

    def test_truncated_model_output_rejected(self):
        c=OllamaClient();c.request=Mock(return_value={**chat('{}'),'done_reason':'length'})
        with self.assertRaises(AIError):
            CommandResearch(c)._chat('test:small','test',{},PLAN_SCHEMA,threading.Event())


class ResearchUITests(unittest.TestCase):
    def test_evidence_is_visible_then_invalidated_when_typing(self):
        from auralyn_terminal.smart_search import Answer
        Popover, worker, _=load_ui_class('SmartPopover')
        view=Popover(owner(),W());view.open();view.entry.set_text(QUESTION);view._search()
        a=Answer('Git','Ein Projekt herunterladen.',command='git clone REPOSITORY_URL',
                 evidence='git: im Suchpfad gefunden; Handbuch git-clone(1) gelesen.',source='Lokale KI · Befehlsrecherche')
        view._receive(view._serial,a)
        self.assertTrue(view.evidence_label.visible)
        self.assertIn('git-clone(1)',view.evidence_label.label)
        self.assertFalse(view.execute_button.visible)
        view.entry.set_text('Etwas anderes')
        self.assertFalse(view.evidence_label.visible)
        view.destroy()

    def test_loading_state_describes_research_when_ai_enabled(self):
        Popover,worker,_=load_ui_class('SmartPopover');host=owner();host.settings['smart_ai_enabled']=True
        view=Popover(host,W());view.open();view.entry.set_text(QUESTION);view._search()
        self.assertIn('KI recherchiert',view.result_title.label)
        self.assertIn('Handbücher',view.answer_label.label)
        host.launch_smart_action.assert_not_called();view.destroy()
