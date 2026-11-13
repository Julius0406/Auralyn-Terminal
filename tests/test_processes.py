"""No signal is sent to an uncontrolled process by this test file.

Fixtures check targeting policy. The sole real SIGKILL test creates its own
private, uniquely named copy of sleep and passes only that known PID to the
pidfd sender; global process-name lookup is never used for that action.
"""
from dataclasses import replace
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from auralyn_terminal.programs import Program
from auralyn_terminal.processes import (Process, ProcessIndex, AmbiguousTarget,
    read_process, protected, send_force_stop)


def proc(pid, name='mygame', uid=1000, ppid=1, exe=None, argv=None, start=100):
    return Process(pid,ppid,uid,start,exe or '/opt/apps/'+name,tuple(argv or (name,)),name)


class TargetPolicyTests(unittest.TestCase):
    def index(self, *records, apps=()):
        return ProcessIndex({p.pid:p for p in records},1000,[],apps)

    def test_own_user_only(self):
        index=self.index(proc(100),proc(101,uid=1001),proc(102,uid=0))
        self.assertEqual([p.pid for p in index.members(index.targets()[0])],[100])

    def test_same_executable_grouped_into_one_application(self):
        index=self.index(proc(100),proc(101,ppid=100),proc(102,ppid=100))
        self.assertEqual(len(index.targets()),1)
        self.assertEqual(len(index.targets()[0].roots),3)

    def test_no_substring_or_argument_matching(self):
        index=self.index(proc(100,'longcode'),proc(101,'editor',argv=['editor','code','mygame']))
        self.assertIsNone(index.resolve('code'))
        self.assertIsNone(index.resolve('mygame'))

    def test_known_desktop_name_and_executable_alias_both_resolve(self):
        app=Program('My Game','desktop','/share/my.desktop','my.desktop','A game',('/opt/apps/mygame','%U'))
        index=self.index(proc(100),apps=[app])
        self.assertEqual(index.targets()[0].name,'My Game')
        self.assertEqual(index.resolve('mygame'),index.resolve('my game'))

    def test_shared_java_runtime_gets_pid_and_ambiguous_name_refused(self):
        index=self.index(proc(100,'java'),proc(101,'java'))
        self.assertEqual([t.name for t in index.targets()],['java [PID 100]','java [PID 101]'])
        with self.assertRaises(AmbiguousTarget):index.resolve('java')
        self.assertEqual(index.resolve('java [PID 101]').roots[0].pid,101)

    def test_jar_and_script_names_are_specific(self):
        index=self.index(proc(100,'java',argv=['java','-jar','/games/Test.jar']),
                         proc(101,'python3',argv=['python3','/tools/helper.py']))
        self.assertEqual({t.name for t in index.targets()},{'Test.jar [PID 100]','helper.py [PID 101]'})

    def test_interpreter_desktop_does_not_match_unrelated_scripts(self):
        app=Program('My Tool','desktop','/share/tool.desktop','tool.desktop',exec_words=('python3','/one.py'))
        index=self.index(proc(100,'python3',argv=['python3','/two.py']),apps=[app])
        self.assertIsNone(index.resolve('My Tool'))

    def test_steam_game_launcher_not_equated_to_steam_process(self):
        app=Program('A Game','desktop','/share/game.desktop','game.desktop',exec_words=('steam','steam://rungameid/123'))
        index=self.index(proc(100,'steam'),apps=[app])
        self.assertIsNone(index.resolve('A Game'))
        self.assertIsNotNone(index.resolve('steam'))

    def test_different_executable_paths_with_same_name_are_not_merged(self):
        index=self.index(proc(100,exe='/one/mygame'),proc(101,exe='/two/mygame'))
        self.assertEqual(len(index.targets()),2)
        with self.assertRaises(AmbiguousTarget):index.resolve('mygame')
        self.assertEqual(index.resolve('mygame [PID 100]').roots[0].exe,'/one/mygame')

    def test_descendants_included_and_unrelated_process_not_included(self):
        index=self.index(proc(100),proc(101,'helper',ppid=100),proc(102,'helper',ppid=101),proc(200,'other'))
        members=index.members(index.resolve('mygame'))
        self.assertEqual({p.pid for p in members},{100,101,102})
        self.assertEqual(members[-1].pid,100)

    def test_protected_child_is_not_killed(self):
        index=self.index(proc(100),proc(101,'gnome-shell',ppid=100))
        self.assertEqual([p.pid for p in index.members(index.resolve('mygame'))],[100])

    def test_desktop_core_and_shell_excluded(self):
        names=['gnome-shell','systemd','Xwayland','pipewire','gsd-media-keys','dbus-daemon','bash']
        index=self.index(*(proc(i+100,name) for i,name in enumerate(names)))
        self.assertEqual(index.targets(),())

    def test_auralyn_all_instances_are_protected(self):
        records=[proc(100,'python3',argv=['python3','/usr/share/auralyn-terminal/launcher.py']),
                 proc(101,'python3',argv=['python3','/usr/share/auralyn-terminal/program_launcher.py'])]
        self.assertEqual(self.index(*records).targets(),())

    def test_current_process_and_ancestor_are_protected(self):
        records=[proc(100,'term'),proc(101,'python3',ppid=100),proc(102,'mygame')]
        index=ProcessIndex({p.pid:p for p in records},1000,[101])
        self.assertEqual({p.pid for t in index.targets() for p in t.roots},{102})

    def test_pid_one_and_zombie_excluded(self):
        index=self.index(proc(1),replace(proc(100),state='Z'))
        self.assertEqual(index.targets(),())

    def test_shell_metacharacters_in_name_are_only_literal_data(self):
        p=proc(100,'bad;name')
        index=self.index(p)
        self.assertEqual(index.resolve('bad;name').roots,(p,))
        self.assertIsNone(index.resolve('bad'))

    def test_no_targets_is_normal(self):
        index=self.index()
        self.assertEqual(index.targets(),())
        self.assertIsNone(index.resolve('not-open'))


class ProcReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.base=self.root/'345';self.base.mkdir()
        fields=['S','1']+['0']*18;fields[19]='12345'
        (self.base/'stat').write_text('345 (name with ) parentheses) '+' '.join(fields))
        (self.base/'status').write_text('Name:\tdemo\nUid:\t1000\t1000\t1000\t1000\n')
        (self.base/'cmdline').write_bytes(b'/opt/demo\0file with spaces\0')
        (self.base/'exe').symlink_to('/opt/demo')

    def tearDown(self):self.temp.cleanup()

    def test_stat_parentheses_cmdline_and_starttime(self):
        p=read_process(345,self.root)
        self.assertEqual((p.start,p.ppid,p.uid,p.argv),(12345,1,1000,('/opt/demo','file with spaces')))
        self.assertEqual(p.comm,'name with ) parentheses')

    def test_setuid_transition_excluded(self):
        (self.base/'status').write_text('Uid:\t1000\t0\t0\t0\n')
        self.assertIsNone(read_process(345,self.root))

    def test_disappeared_process_is_ignored(self):
        (self.base/'stat').unlink()
        self.assertIsNone(read_process(345,self.root))

    def test_malformed_starttime_is_ignored(self):
        (self.base/'stat').write_text('not a process')
        self.assertIsNone(read_process(345,self.root))

    def test_unreadable_executable_still_allows_named_process_record(self):
        (self.base/'exe').unlink()
        self.assertEqual(read_process(345,self.root).name,'demo')


class PidfdPolicyTests(unittest.TestCase):
    def setUp(self):
        self.original=proc(1234,uid=os.getuid())

    def call(self,current=None,side_effect=None):
        with patch('auralyn_terminal.processes.os.pidfd_open',return_value=456) as opened, \
             patch('auralyn_terminal.processes.os.close') as closed, \
             patch('auralyn_terminal.processes.read_process',return_value=current) as read, \
             patch('auralyn_terminal.processes.signal.pidfd_send_signal',side_effect=side_effect) as send:
            result=send_force_stop([self.original],set())
            return result,opened,closed,read,send

    def test_validated_identity_gets_sigkill_through_fd(self):
        result,opened,closed,read,send=self.call(self.original)
        self.assertEqual(result,(1,0))
        opened.assert_called_once_with(1234,0)
        send.assert_called_once_with(456,signal.SIGKILL,None,0)
        closed.assert_called_once_with(456)

    def test_reused_pid_is_not_signalled(self):
        result,_,closed,_,send=self.call(replace(self.original,start=99999))
        self.assertEqual(result,(0,1));send.assert_not_called();closed.assert_called_once()

    def test_exec_into_another_program_is_not_signalled(self):
        result,_,_,_,send=self.call(replace(self.original,exe='/opt/other'))
        self.assertEqual(result,(0,1));send.assert_not_called()

    def test_changed_uid_is_not_signalled(self):
        result,_,_,_,send=self.call(replace(self.original,uid=os.getuid()+1))
        self.assertEqual(result,(0,1));send.assert_not_called()

    def test_exited_process_is_not_signalled(self):
        result,_,_,_,send=self.call(None)
        self.assertEqual(result,(0,1));send.assert_not_called()

    def test_permission_error_is_reported_as_skipped(self):
        result,_,closed,_,send=self.call(self.original,PermissionError())
        self.assertEqual(result,(0,1));closed.assert_called_once()

    def test_protected_process_not_even_opened(self):
        with patch('auralyn_terminal.processes.os.pidfd_open') as openfd:
            result=send_force_stop([self.original],{1234})
        self.assertEqual(result,(0,1));openfd.assert_not_called()

    @unittest.skipUnless(hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'),'Linux pidfd required')
    def test_real_pidfd_force_stops_only_created_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'auralyn-controlled-sleep'
            shutil.copy2('/bin/sleep',binary)
            child=subprocess.Popen([str(binary),'30'])
            bystander=subprocess.Popen(['/bin/sleep','30'])
            try:
                record=read_process(child.pid)
                self.assertIsNotNone(record)
                self.assertEqual(send_force_stop([record],set()),(1,0))
                self.assertEqual(child.wait(timeout=3),-signal.SIGKILL)
                self.assertIsNone(bystander.poll())
            finally:
                for p in (child,bystander):
                    if p.poll() is None:p.kill()
                    p.wait()


if __name__=='__main__':unittest.main()
