"""Harmless checks against an already extracted package, NOT an update run."""
from pathlib import Path
import hashlib, os, stat, subprocess, sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
root=Path(sys.argv[1]).resolve()
app=root/'usr/share/auralyn-terminal'
sys.path.insert(0,str(app))
from auralyn_terminal import __version__
from auralyn_terminal.settings import validate
from auralyn_terminal.update_session import DISPLAY_COMMANDS, update_environment, shell_environment, display_commands, UpdateRunner
from auralyn_terminal.update_auth import PasswordBroker, wipe
assert __version__=='1.0.0'
assert DISPLAY_COMMANDS==('sudo apt update','sudo apt full-upgrade','flatpak update')
assert display_commands(True)==('sudo apt update','sudo apt full-upgrade -y','flatpak update --assumeyes')
assert validate({})['update_auto_confirm'] is True
assert validate({'update_auto_confirm': False})['update_auto_confirm'] is False
for auto in (False, True):
    child=Mock(pid=9000);child.wait.return_value=0
    popen=Mock(return_value=child)
    control=Mock(return_value=NS(returncode=0))
    runner=UpdateRunner(saved_password=False,assume_yes=auto,resolver=lambda n:'/usr/bin/'+n,
                        popen=popen,run=control,emit=lambda _:None)
    result=runner.execute()
    assert result.code==0 and result.completed==3 and result.revoked
    assert [c.args[0] for c in popen.call_args_list]==[
        ['/usr/bin/sudo','-k','--','/usr/bin/apt','update'],
        ['/usr/bin/sudo','-k','--','/usr/bin/apt','full-upgrade']+(['-y'] if auto else []),
        ['/usr/bin/flatpak','update']+(['--assumeyes'] if auto else [])]
    assert [c.args[0] for c in control.call_args_list]==[['/usr/bin/sudo','-K']]*3
print('PASS: extracted automatic/manual flags and sudo cleanup (controlled children, no updates)')
settings=validate({'update_use_keyring': True, 'sudo_password': 'TEST-PLACEHOLDER', 'update_password': 'TEST-PLACEHOLDER'})
assert settings['update_use_keyring'] is True
assert 'sudo_password' not in settings and 'update_password' not in settings
assert validate({})['update_use_keyring'] is False
help_result=subprocess.run([sys.executable,'-I',str(app/'update_launcher.py'),'--help'],
                           capture_output=True,text=True,timeout=5)
assert help_result.returncode==0 and '--assume-yes' in help_result.stdout
print('PASS: isolated packaged update launcher accepts --assume-yes (help only)')
helper=app/'update_askpass.py'
assert stat.S_IMODE(helper.stat().st_mode)==0o755
assert helper.read_text().splitlines()[0]=='#!/usr/bin/python3 -I'
secret=bytearray(b'DUMMY-PACKAGE-PROBE-NOT-A-REAL-CREDENTIAL')
try:
    with PasswordBroker(secret) as broker:
        env=broker.environment(update_environment(),str(helper))
        assert secret.decode() not in repr(env)
        broker.prepare()
        denied=subprocess.run([str(helper)],env=env,capture_output=True,timeout=8)
        assert denied.returncode!=0 and not denied.stdout
        broker.arm(os.getpid())
        allowed=subprocess.run([str(helper)],env=env,capture_output=True,timeout=8)
        assert allowed.returncode==0 and allowed.stdout==secret+b'\n' and not allowed.stderr
        second=subprocess.run([str(helper)],env=env,capture_output=True,timeout=8)
        assert second.returncode!=0 and not second.stdout
        path=Path(broker.path)
    assert not path.exists() and not path.parent.exists()
finally:
    wipe(secret)
count=0
for line in (root/'DEBIAN/md5sums').read_text().splitlines():
    md5,name=line.split('  ',1)
    assert hashlib.md5((root/name).read_bytes()).hexdigest()==md5,name
    count+=1
assert not any((root/'DEBIAN'/name).exists() for name in ('postinst','preinst','postrm','prerm'))
print('PASS: extracted version and exact fixed update commands')
print('PASS: opt-in bool setting only; password fields not serialized')
print('PASS: isolated helper mode 755 and trusted Python shebang')
print('PASS: real extracted helper denies unarmed parent and repeat request')
print('PASS: authorized dummy broker round-trip via pipe, no secret in env')
print('PASS: broker/socket removed and mutable test password buffer cleared')
print(f'PASS: all {count} packaged file hashes verified; no maintainer scripts')
print('No package update, real secret-service operation or GUI was executed.')
