"""Tests of run/kill catalogue, completion and read-only metadata handling."""
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from auralyn_terminal.programs import (Program, ProgramIndex, AmbiguousProgram, desktop_dirs,
                                       desktop_unescape, locale_keys, executable_tokens, find_executable)
from auralyn_terminal.completion import Engine, Candidate, parse_context, replacement, custom_action
from auralyn_terminal.command_help import describe
from auralyn_terminal.processes import Process, ProcessIndex

ROOT = Path(__file__).resolve().parent.parent
NAMES = ['run', 'kill', 'auralyn-run', 'auralyn-kill', '__auralyn_run_enabled', '__auralyn_kill_enabled']


def context(line):
    value = parse_context(line, len(line.encode()))
    assert value is not None, line
    return value


class CatalogueFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='auralyn-program-test-')
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.user = self.root / 'user'; self.user.mkdir()
        self.system = self.root / 'system'; self.system.mkdir()
        self.env = {'HOME': str(self.root), 'LANG': 'de_DE.UTF-8', 'XDG_CURRENT_DESKTOP': 'ubuntu:GNOME'}
        self.index = ProgramIndex(self.env, [self.user, self.system])

    def tearDown(self):
        self.temp.cleanup()

    def executable(self, name, text='#!/bin/sh\nexit 0\n'):
        p = self.bin / name
        p.write_text(text); p.chmod(0o755)
        return p

    def desktop(self, filename='demo.desktop', name='Demo Editor', extra='', root=None, command='/bin/true %U'):
        p = (root or self.user) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'[Desktop Entry]\nType=Application\nName={name}\nExec={command}\n{extra}', encoding='utf-8')
        return p

    def apps(self):
        self.index._cache_time = 0
        return self.index.applications(str(self.bin), str(self.root))

class CatalogueTests(CatalogueFixture):
    def test_installed_executable_and_user_script_detected_without_running(self):
        marker = self.root/'must-not-exist'
        self.executable('ThirdParty', f'#!/bin/sh\ntouch {shlex.quote(str(marker))}\n')
        self.assertIn('ThirdParty', [p.name for p in self.apps()])
        self.assertFalse(marker.exists())

    def test_nonexecutable_and_directory_not_listed(self):
        (self.bin/'not-program').write_text('text')
        (self.bin/'directory').mkdir()
        self.assertEqual(self.apps(), ())

    def test_path_precedence_and_relative_path(self):
        one = self.executable('demo')
        other = self.root/'other';other.mkdir(); (other/'demo').symlink_to('/bin/false')
        p = self.index.resolve('demo', f'bin:{other}', str(self.root))
        self.assertEqual(p.path, str(one))

    def test_menu_display_name_and_description(self):
        p=self.desktop(extra='Comment=Bearbeitet Texte.\n')
        app=self.apps()[0]
        self.assertEqual((app.name,app.path,app.description),('Demo Editor',str(p),'Bearbeitet Texte.'))
        self.assertEqual(app.kind,'desktop')

    def test_localized_name_and_comment(self):
        self.desktop(extra='Name[de]=Mein Editor\nComment[de_DE]=Ein Testeditor\n')
        app=self.apps()[0]
        self.assertEqual((app.name,app.description),('Mein Editor','Ein Testeditor'))

    def test_hidden_user_entry_masks_system_launcher(self):
        self.desktop(root=self.system)
        (self.user/'demo.desktop').write_text('[Desktop Entry]\nHidden=true\n')
        self.assertEqual(self.apps(),())

    def test_nodisplay_is_not_in_suggestions(self):
        self.desktop(extra='NoDisplay=true\n')
        self.assertEqual(self.apps(),())

    def test_onlyshowin_and_notshowin(self):
        self.desktop('kde.desktop','KDE Tool','OnlyShowIn=KDE;\n')
        self.desktop('excluded.desktop','Excluded','NotShowIn=GNOME;\n')
        self.desktop('gnome.desktop','GNOME Tool','OnlyShowIn=GNOME;\n')
        self.assertEqual([p.name for p in self.apps()],['GNOME Tool'])

    def test_missing_tryexec_and_missing_exec_skipped(self):
        self.desktop(extra='TryExec=does-not-exist-auralyn\n')
        self.desktop('other.desktop','Other',command='/does/not/exist')
        self.assertEqual(self.apps(),())

    def test_dbus_application_can_omit_exec(self):
        self.desktop(extra='DBusActivatable=true\n',command='')
        self.assertEqual(len(self.apps()),1)

    def test_malformed_and_oversized_files_ignored(self):
        (self.user/'bad.desktop').write_text('wrong format')
        (self.user/'big.desktop').write_text('x'*262145)
        self.assertEqual(self.apps(),())

    def test_subdirectories_use_desktop_ids(self):
        self.desktop('sub/demo.desktop')
        self.assertEqual(self.apps()[0].desktop_id,'sub-demo.desktop')

    def test_duplicate_display_names_disambiguated(self):
        self.desktop('one.desktop','Editor')
        self.desktop('two.desktop','Editor')
        self.assertEqual({p.name for p in self.index.choices(str(self.bin),str(self.root))},{'one.desktop','two.desktop'})
        with self.assertRaises(AmbiguousProgram):
            self.index.resolve('Editor',str(self.bin),str(self.root))
        self.assertTrue(self.index.resolve('one.desktop',str(self.bin),str(self.root)).path.endswith('one.desktop'))

    def test_executable_wins_over_same_name_desktop(self):
        exe=self.executable('demo');self.desktop(name='demo')
        self.assertEqual(self.index.resolve('demo',str(self.bin),str(self.root)).path,str(exe))
        self.assertIn('demo.desktop',[p.name for p in self.index.choices(str(self.bin),str(self.root))])

    def test_case_insensitive_desktop_resolution(self):
        self.desktop(name='Fancy Editor')
        self.assertEqual(self.index.resolve('fancy editor',str(self.bin),str(self.root)).name,'Fancy Editor')

    def test_refresh_after_install(self):
        self.assertEqual(self.apps(),())
        self.executable('newtool')
        self.assertIn('newtool',[p.name for p in self.apps()])

    def test_xdg_snap_and_flatpak_directories(self):
        paths = desktop_dirs({'HOME':'/home/test','XDG_DATA_HOME':'/custom','XDG_DATA_DIRS':'/one:/two'})
        self.assertEqual(paths[0],Path('/custom/applications'))
        self.assertIn(Path('/var/lib/flatpak/exports/share/applications'),paths)
        self.assertIn(Path('/var/lib/snapd/desktop/applications'),paths)
        self.assertIn(Path('/home/test/.local/share/flatpak/exports/share/applications'),paths)

    def test_quoted_exec_is_parsed_only_as_a_hint(self):
        self.assertEqual(executable_tokens('env FOO=bar "/opt/My App/bin" %U'),('/opt/My App/bin','%U'))
        self.assertEqual(executable_tokens('env -S something'),())
        self.assertEqual(executable_tokens('"unterminated'),())

    def test_plain_appimage_path_resolves(self):
        p=self.executable('My App.AppImage')
        self.assertEqual(find_executable('./bin/My App.AppImage','',str(self.root)),str(p))

    def test_control_characters_in_name_are_rejected(self):
        self.desktop(name='Bad\\nName')
        self.assertEqual(self.apps(),())

    def test_name_shell_metacharacters_never_execute_on_discovery(self):
        marker=self.root/'NEVER'
        name=f'Editor $(touch {marker})'
        self.desktop(name=name)
        self.assertEqual(self.apps()[0].name,name)
        self.assertFalse(marker.exists())
        line,_=replacement(context('run Ed'),Candidate(name))
        self.assertEqual(shlex.split(line),['run',name])


class NewCompletionTests(CatalogueFixture):
    def setUp(self):
        super().setUp()
        self.engine = Engine(ROOT/'shell/native-complete.bash')
        self.engine.program_index=self.index

    def complete(self,line,names=NAMES):
        return self.engine.complete(context(line),str(self.root),str(self.bin),names,False)

    def test_run_space_shows_all_apps_then_tools(self):
        self.executable('testcli');self.desktop()
        c=self.complete('run ')
        self.assertEqual([x.value for x in c],['Demo Editor','testcli'])
        self.assertTrue(all(x.help_text for x in c))

    def test_run_casefold_prefix(self):
        self.desktop(name='Fancy Editor')
        self.assertEqual([x.value for x in self.complete('run fan')],['Fancy Editor'])
        self.assertEqual(self.complete('run fancx'),[])

    def test_run_filters_every_letter(self):
        self.executable('sober');self.executable('steam');self.executable('ssh')
        self.assertEqual({x.value for x in self.complete('run s')},{'sober','steam','ssh'})
        self.assertEqual([x.value for x in self.complete('run ste')],['steam'])

    def test_run_foreground_only_executables(self):
        self.desktop(); self.executable('testcli')
        c=self.complete('run --foreground ')
        self.assertEqual([x.value for x in c],['testcli'])
        self.assertIn('interaktiv',c[0].help_text)

    def test_run_local_executable_path(self):
        self.executable('tool')
        self.assertEqual([x.value for x in self.complete('run ./bin/to')],['./bin/tool'])

    def test_original_commands_get_special_help_only_when_our_functions_active(self):
        c=self.complete('ki')
        kill=next(x for x in c if x.value=='kill')
        self.assertEqual(kill.kind,'Auralyn');self.assertIn('sofort',kill.help_text)
        c=self.complete('ki',names=['kill'])
        self.assertFalse(next(x for x in c if x.value=='kill').help_text)

    def test_wrappers_never_intercepted(self):
        for line in ('sudo run d','sudo kill d','builtin kill d','command kill d','env run d','nohup run d','/bin/kill d'):
            with self.subTest(line=line):
                self.assertIsNone(custom_action(context(line),NAMES))

    def test_shell_assignment_and_command_separator_supported(self):
        for line in ('LANG=C run d','echo ok; run d','true && kill d'):
            self.assertIsNotNone(custom_action(context(line),NAMES))

    def test_namespace_alias_supported(self):
        self.desktop()
        self.assertEqual([x.value for x in self.complete('auralyn-run Demo')],['Demo Editor'])

    def test_user_alias_does_not_activate_our_program_completion(self):
        self.desktop()
        self.assertIsNone(custom_action(context('run D'),['run']))

    def test_underlying_subcommands_and_help(self):
        self.executable('git')
        candidates=self.complete('run git clo')
        self.assertEqual([c.value for c in candidates],['clone'])
        helptext=describe(context('run git clo'),candidates[0],str(self.root),lambda _:None)
        self.assertEqual(helptext.title,'git clone')
        self.assertNotIn('Keine',helptext.source)

    def test_help_of_desktop_name_contains_comment_without_manual_lookup(self):
        self.desktop(extra='Comment=Mein Testeditor.\n')
        c=self.complete('run Demo')[0]
        def fail(_): raise AssertionError('Must not execute a manual lookup')
        result=describe(context('run Demo'),c,str(self.root),fail)
        self.assertIn('Mein Testeditor.',result.text)

    def test_kill_suggestions_are_live_user_processes_and_have_warning(self):
        proc=Process(555,1,1000,1,'/usr/bin/mygame',('mygame',),'mygame')
        index=ProcessIndex({555:proc},1000,[],())
        with patch('auralyn_terminal.completion.ProcessIndex',return_value=index):
            candidates=self.complete('kill my')
        self.assertEqual([c.value for c in candidates],['mygame'])
        self.assertEqual(candidates[0].kind,'Sofort beenden')
        self.assertIn('Ungespeicherte',candidates[0].help_text)

    def test_kill_selection_only_inserts_literal_name(self):
        c=Candidate('java [PID 555]','Sofort beenden')
        line,point=replacement(context('kill ja'),c)
        self.assertEqual(shlex.split(line),['kill','java [PID 555]'])
        self.assertEqual(point,len(line.encode()))
        self.assertNotIn('\n',line)

    def test_numeric_kill_is_not_program_name_completion(self):
        with patch.object(self.engine,'native',return_value=[]) as native:
            self.engine.complete(context('kill 55'),str(self.root),str(self.bin),NAMES,True)
        native.assert_called_once()

    def test_kill_double_dash_keeps_numeric_semantics(self):
        with patch('auralyn_terminal.completion.ProcessIndex') as processes, \
             patch.object(self.engine,'native',return_value=[]) as native:
            self.engine.complete(context('kill -- '),str(self.root),str(self.bin),NAMES,True)
        processes.assert_not_called()
        native.assert_called_once()

    def test_run_option_help(self):
        c=self.complete('run --f')[0]
        self.assertEqual(c.value,'--foreground')
        self.assertIn('interaktiv',c.help_text)


if __name__=='__main__':unittest.main()
