"""CLI actions and real Bash integration, with explicitly controlled processes.

The name-based kill end-to-end test drops to nobody when tests run as root.
It creates a uniquely named copy of sleep, starts it with run, then stops just
that test program. A separate ordinary sleep is checked to remain alive.
"""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch, Mock

from auralyn_terminal.programs import Program
from auralyn_terminal.program_cli import (main, launch_executable, launch_desktop)
from test_shell import BashSession

ROOT = Path(__file__).resolve().parent.parent


class LauncherTests(unittest.TestCase):
    def test_literal_arguments_no_shell_expansion_and_private_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);marker=root/'NEVER'
            attack=f'$(touch {marker}); echo unsafe'
            program=Program('python','executable',sys.executable)
            with patch.dict(os.environ,{'XDG_STATE_HOME':str(root)}):
                child,log=launch_executable(program,['-c','import sys;print(repr(sys.argv[1]))',attack])
            try:
                self.assertEqual(child.wait(timeout=4),0)
                self.assertIn(repr(attack),Path(log).read_text())
                self.assertFalse(marker.exists())
                self.assertEqual(Path(log).stat().st_mode & 0o777,0o600)
            finally:
                if child.poll() is None:child.kill();child.wait()

    def test_default_launch_returns_before_program_finishes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_STATE_HOME':tmp}):
            child,_=launch_executable(Program('sleep','executable','/bin/sleep'),['20'])
            try:
                self.assertIsNone(child.poll())
                self.assertEqual(os.getsid(child.pid),child.pid)
            finally:child.kill();child.wait()

    def test_launch_error_removes_unused_log(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_STATE_HOME':tmp}):
            with self.assertRaises(FileNotFoundError):
                launch_executable(Program('missing','executable','/no/such/auralyn-program'),[])
            self.assertEqual(list(Path(tmp).rglob('*.log')),[])

    def test_foreground_execs_only_helper_with_exact_arguments(self):
        with patch('auralyn_terminal.program_cli.os.execv',side_effect=RuntimeError('test-exec')) as exe:
            with self.assertRaisesRegex(RuntimeError,'test-exec'):
                launch_executable(Program('nano','executable','/usr/bin/nano'),['a b.txt'],True)
        exe.assert_called_once_with('/usr/bin/nano',['/usr/bin/nano','a b.txt'])

    def test_symlink_log_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'XDG_STATE_HOME':tmp}):
            appdir=Path(tmp)/'auralyn-terminal';appdir.mkdir()
            (appdir/'runs').symlink_to(tmp)
            with self.assertRaises(PermissionError):
                launch_executable(Program('true','executable','/bin/true'),[])

    def fake_gio(self):
        gi=types.ModuleType('gi');gi.require_version=Mock()
        repo=types.ModuleType('gi.repository')
        app=Mock();app.launch_uris.return_value=True
        app_type=types.SimpleNamespace(new_from_filename=Mock(return_value=app))
        repo.Gio=types.SimpleNamespace(DesktopAppInfo=app_type,AppLaunchContext=Mock(return_value='context'))
        repo.GioUnix=types.SimpleNamespace(DesktopAppInfo=app_type)
        return {'gi':gi,'gi.repository':repo},app,app_type

    def test_desktop_launch_delegates_to_gio_not_exec_string(self):
        modules,app,app_type=self.fake_gio()
        p=Program('Editor','desktop','/usr/share/applications/editor.desktop',exec_words=('never','eval','this'))
        with patch.dict(sys.modules,modules):launch_desktop(p,[])
        app_type.new_from_filename.assert_called_once_with(p.path)
        app.launch_uris.assert_called_once_with([],'context')

    def test_desktop_launch_passes_urls_and_files_as_data(self):
        modules,app,_=self.fake_gio()
        with patch.dict(sys.modules,modules):
            launch_desktop(Program('Editor','desktop','/tmp/editor.desktop'),['/tmp/a b.txt','https://example.org/test'])
        self.assertEqual(app.launch_uris.call_args.args[0],['file:///tmp/a%20b.txt','https://example.org/test'])

    def test_desktop_cli_options_not_misinterpreted_as_filenames(self):
        with self.assertRaisesRegex(ValueError,'Befehlsnamen'):
            launch_desktop(Program('Editor','desktop','/tmp/editor.desktop'),['--dangerous'])

    def test_invalid_desktop_entry_has_actionable_error(self):
        modules,app,app_type=self.fake_gio();app_type.new_from_filename.return_value=None
        with patch.dict(sys.modules,modules),self.assertRaisesRegex(ValueError,'ungültig'):
            launch_desktop(Program('Editor','desktop','/tmp/editor.desktop'),[])

    def test_root_force_stop_refused_before_process_lookup(self):
        with patch('auralyn_terminal.program_cli.os.geteuid',return_value=0), \
             patch('auralyn_terminal.program_cli.ProcessIndex') as index,redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(['kill','anything']),1)
        index.assert_not_called();self.assertIn('ohne sudo',error.getvalue())

    def test_help_does_not_launch_or_kill(self):
        with patch('auralyn_terminal.program_cli.launch_executable') as launch, \
             patch('auralyn_terminal.program_cli.send_force_stop') as stop,redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['run','--help']),0)
            self.assertEqual(main(['kill','--help']),0)
        launch.assert_not_called();stop.assert_not_called()
        self.assertIn('Ungespeicherte',output.getvalue())

    def test_missing_program_reports_error_without_traceback(self):
        with patch('auralyn_terminal.program_cli.os.geteuid',return_value=1000), \
             redirect_stderr(io.StringIO()) as error:
            result=main(['run','/does-not-exist/auralyn-test'])
        self.assertEqual(result,1);self.assertIn('nicht gefunden',error.getvalue())

    def test_isolated_cli_ignores_fake_module_in_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'auralyn_terminal.py').write_text('raise RuntimeError("WRONG IMPORT")')
            p=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'program_launcher.py'),'run','--help'],cwd=tmp,capture_output=True,text=True,timeout=4)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('Auralyn run',p.stdout)


class InteractiveFunctionTests(unittest.TestCase):
    def test_functions_and_markers_published_in_real_interactive_bash(self):
        s=BashSession()
        try:
            names=s.command('true')[3]
            for name in ('run','kill','auralyn-run','auralyn-kill','__auralyn_run_enabled','__auralyn_kill_enabled'):
                self.assertIn(name,names.splitlines())
            s.command('run --help')
            self.assertIn(b'Auralyn run',s.output)
            self.assertTrue(s.ready)
        finally:s.close()

    def test_user_aliases_not_replaced(self):
        s=BashSession("alias run='echo USER_RUN'; alias kill='echo USER_KILL'\n")
        try:
            names=s.command('run apple; kill pear')[3]
            self.assertIn(b'USER_RUN apple',s.output);self.assertIn(b'USER_KILL pear',s.output)
            self.assertNotIn('__auralyn_run_enabled',names)
            self.assertNotIn('__auralyn_kill_enabled',names)
            self.assertIn('auralyn-run',names)
        finally:s.close()

    def test_user_functions_not_replaced(self):
        s=BashSession('run() { echo USER_RUN_FUNCTION; }; kill() { echo USER_KILL_FUNCTION; }\n')
        try:
            s.command('run; kill')
            self.assertIn(b'USER_RUN_FUNCTION',s.output);self.assertIn(b'USER_KILL_FUNCTION',s.output)
        finally:s.close()

    def test_normal_numeric_signal_and_job_kill_syntax(self):
        script=f'''source {shlex.quote(str(ROOT/'shell/programs.bash'))}
/bin/sleep 30 & first=$!
kill -0 "$first" || exit 10
kill "$first" || exit 11
wait "$first"; [[ $? == 143 ]] || exit 12
/bin/sleep 30 & second=$!
kill -9 "$second" || exit 13
wait "$second"; [[ $? == 137 ]] || exit 14
/bin/sleep 30 &
kill %1 || exit 15
wait %1 2>/dev/null || :
kill -l TERM
printf 'LEGACY_OK\\n'
'''
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('LEGACY_OK',p.stdout)

    def test_regular_builtin_kill_still_explicitly_available(self):
        script=f'source {shlex.quote(str(ROOT/"shell/programs.bash"))}; builtin kill -l TERM'
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],capture_output=True,text=True,timeout=4)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'15')

    def test_name_starting_with_digit_not_mistaken_for_pid(self):
        script=f'''source {shlex.quote(str(ROOT/'shell/programs.bash'))}
__auralyn_program_helper() {{ printf '%s\\n' "$@"; }}
kill 3d-editor
'''
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],capture_output=True,text=True,timeout=4)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.splitlines(),['kill','3d-editor'])

    def test_native_readline_completion_can_insert_space_names(self):
        script=f'''source {shlex.quote(str(ROOT/'shell/programs.bash'))}
__auralyn_program_helper() {{ printf 'Fancy Editor\\0Other\\0'; }}
COMP_WORDS=(run Fa); COMP_CWORD=1
__auralyn_program_complete
printf '<%s>\\n' "${{COMPREPLY[@]}}"
'''
        p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],capture_output=True,text=True,timeout=4)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('<Fancy Editor>',p.stdout)

    def test_foreground_and_literal_arguments_in_unprivileged_shell(self):
        options={}
        if os.getuid()==0:options=dict(user=65534,group=65534,extra_groups=[])
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp,0o777)
            args='literal $HOME ; not-executed'
            script=f'''source {shlex.quote(str(ROOT/'shell/programs.bash'))}
run --foreground /usr/bin/printf '%s\\n' {shlex.quote(args)}
printf 'PROMPT_RETURNED\\n'
'''
            env=dict(os.environ,HOME=tmp,XDG_STATE_HOME=tmp)
            p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],env=env,cwd=tmp,
                             capture_output=True,text=True,timeout=6,**options)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn(args,p.stdout);self.assertIn('PROMPT_RETURNED',p.stdout)

    def test_real_unprivileged_foreground_pty_input_and_ctrl_c(self):
        options={}
        if os.getuid()==0:options=dict(user=65534,group=65534,extra_groups=[])
        script = r"""
import sys
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + '/tests')
from test_shell import BashSession
from auralyn_terminal.terminal_state import is_readline_foreground
s=BashSession()
try:
    s.write('run --foreground /bin/cat\r')
    s.wait('B');s.pump(.08)
    assert not is_readline_foreground(s.fd,s.pid,s.ready)
    s.write('AURALYN_PTY_INPUT\n');s.pump(.08)
    assert b'AURALYN_PTY_INPUT' in s.output
    s.write('\x03');s.wait('P');s.pump(.04)
    assert is_readline_foreground(s.fd,s.pid,s.ready)
    s.command("printf 'AFTER_FOREGROUND_OK\\n'")
    assert b'AFTER_FOREGROUND_OK' in s.output
    print('PTY_FOREGROUND_OK')
finally:
    s.close()
"""
        script='ROOT='+repr(str(ROOT))+'\n'+script
        p=subprocess.run(['/usr/bin/python3','-I','-c',script],capture_output=True,text=True,
                         cwd='/tmp',timeout=8,**options)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('PTY_FOREGROUND_OK',p.stdout)

    def test_real_unprivileged_run_then_name_force_stop_preserves_bystander(self):
        options={}
        if os.getuid()==0:options=dict(user=65534,group=65534,extra_groups=[])
        with tempfile.TemporaryDirectory(prefix='auralyn-e2e-') as tmp:
            os.chmod(tmp,0o777)
            binary=Path(tmp)/('auralyn-e2e-'+Path(tmp).name)
            shutil.copy2('/bin/sleep',binary)
            script=f'''source {shlex.quote(str(ROOT/'shell/programs.bash'))}
/bin/sleep 30 & bystander=$!
trap 'builtin kill -9 "$bystander" 2>/dev/null || :; wait "$bystander" 2>/dev/null || :' EXIT
run {shlex.quote(str(binary))} 30 || exit 30
kill {shlex.quote(binary.name)} || exit 31
builtin kill -0 "$bystander" || exit 32
printf 'BYSTANDER_SURVIVED\\n'
'''
            env=dict(os.environ,HOME=tmp,XDG_STATE_HOME=tmp,XDG_DATA_HOME=tmp)
            p=subprocess.run(['/bin/bash','--noprofile','--norc','-c',script],env=env,cwd=tmp,
                             capture_output=True,text=True,timeout=8,**options)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('Gestartet:',p.stdout);self.assertIn('KILL an 1 Prozess',p.stdout)
            self.assertIn('BYSTANDER_SURVIVED',p.stdout)
            pid=int(re.search(r'\(PID (\d+)\)',p.stdout)[1])
            for _ in range(100):
                status=Path(f'/proc/{pid}/stat')
                if not status.exists():break
                try:
                    if status.read_text().split(') ')[1].startswith(('Z','X')):break
                except FileNotFoundError:break
                time.sleep(.01)
            else:self.fail('Controlled process did not exit after SIGKILL')


if __name__=='__main__':unittest.main()
