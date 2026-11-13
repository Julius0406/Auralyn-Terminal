import json
import os
from pathlib import Path
import shlex
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from auralyn_terminal.completion import Candidate, Engine, PathIndex, files, lex, parse_context, replacement
from auralyn_terminal.protocol import Decoder, SessionIPC
from auralyn_terminal.settings import Settings, validate

ROOT = Path(__file__).resolve().parent.parent


def context(text, point=None):
    return parse_context(text, len(text.encode()) if point is None else point)


class SettingsTests(unittest.TestCase):
    def test_default_75_transparent_not_opacity(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp) / "settings.json")
            self.assertEqual(settings["transparency"], 75)
            self.assertEqual(settings.alpha, .25)

    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp) / "settings.json")
            settings.set("transparency", 0)
            self.assertEqual(settings.alpha, 1.0)
            settings.set("transparency", 100)
            self.assertEqual(settings.alpha, 0.0)

    def test_roundtrip_private_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config" / "settings.json"
            settings = Settings(path)
            settings.set("transparency", 42)
            self.assertEqual(Settings(path)["transparency"], 42)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_validate_bad_values(self):
        data = validate({"transparency": 200, "suggestion_rows": 400, "font": "bad\nfont", "suggestions": "true"})
        self.assertEqual(data["transparency"], 100)
        self.assertEqual(data["suggestion_rows"], 3)
        self.assertEqual(data["font"], "Monospace 13")
        self.assertTrue(data["suggestions"])
        self.assertEqual(validate({"suggestion_rows": 0})["suggestion_rows"], 2)

    def test_temporary_override_not_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings = Settings(path)
            settings.runtime_overrides["suggestions"] = False
            self.assertFalse(settings["suggestions"])
            settings.save()
            self.assertTrue(Settings(path)["suggestions"])

    def test_corrupt_json_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text("{not json")
            settings = Settings(path)
            self.assertEqual(settings["transparency"], 75)
            self.assertTrue(settings.error)


class ProtocolTests(unittest.TestCase):
    def test_fragments_and_newline(self):
        decoder = Decoder()
        data = b'B\0S\0' + b'5\0/tmp\0/bin\0a\nb\0P\0123\0/tmp\0/bin\0test\nalias\05.2\0'
        # Avoid octal escape ambiguity in the actual frame.
        data = b'B\0' + b'\0'.join([b'S', b'5', b'/tmp', b'/bin', b'a\nb']) + b'\0' + b'\0'.join([b'P', b'123', b'/tmp', b'/bin', b'test\nalias', b'5.2']) + b'\0'
        events = []
        for byte in data:
            events += decoder.feed(bytes([byte]))
        self.assertEqual(events, [('B', []), ('S', ['5', '/tmp', '/bin', 'a\nb']), ('P', ['123', '/tmp', '/bin', 'test\nalias', '5.2'])])

    def test_unknown_tag(self):
        self.assertEqual(Decoder().feed(b'nonsense\0B\0'), [('B', [])])

    def test_fifo_permissions_and_cleanup(self):
        ipc = SessionIPC()
        directory = ipc.directory
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(ipc.fifo.stat().st_mode), 0o600)
        writer = os.open(ipc.fifo, os.O_WRONLY)
        os.write(writer, b'B\0')
        os.close(writer)
        self.assertEqual(ipc.receive(), [('B', [])])
        ipc.close()
        self.assertFalse(directory.exists())

    def test_replacement_is_data(self):
        ipc = SessionIPC()
        try:
            dangerous = "$(touch /tmp/should-not-exist); \"hi\"\nnext"
            ipc.write_replacement('s', 1, dangerous, len(dangerous))
            self.assertEqual(ipc.replacement.read_bytes().split(b'\0')[2], dangerous.encode())
            self.assertEqual(stat.S_IMODE(ipc.replacement.stat().st_mode), 0o600)
            with self.assertRaises(ValueError):
                ipc.write_replacement('s', 1, 'bad\0data', 1)
        finally:
            ipc.close()


class ParsingTests(unittest.TestCase):
    def test_prefix(self):
        ctx = context('sud')
        self.assertEqual(ctx.prefix, 'sud')
        self.assertTrue(ctx.command_position)

    def test_sudo_command(self):
        ctx = context('sudo a')
        self.assertTrue(ctx.sudo)
        self.assertTrue(ctx.command_position)
        self.assertEqual(ctx.words, ('a',))

    def test_sudo_subcommand(self):
        ctx = context('sudo apt i')
        self.assertEqual(ctx.words, ('apt', 'i'))
        self.assertEqual(ctx.command_start, 5)
        self.assertFalse(ctx.command_position)

    def test_sudo_options(self):
        self.assertEqual(context('sudo -u root a').words, ('a',))
        self.assertEqual(context('sudo -u ro').words, ('sudo', '-u', 'ro'))
        self.assertEqual(context('sudo -- apt i').words, ('apt', 'i'))
        self.assertEqual(context('sudo --user=root apt i').words, ('apt', 'i'))
        self.assertEqual(context('sudo -').words, ('sudo', '-'))

    def test_other_wrappers_and_assignments(self):
        self.assertEqual(context('env FOO=1 sudo a').words, ('a',))
        self.assertEqual(context('FOO=1 git c').words, ('git', 'c'))
        self.assertEqual(context('command git c').words, ('git', 'c'))
        self.assertEqual(context('nice -n 3 git c').words, ('git', 'c'))

    def test_pipe_and_separators(self):
        for text in ('echo hello | sud', 'true && sud', 'false || sud', 'echo hello; sud'):
            self.assertEqual(context(text).words, ('sud',))

    def test_redirect_files(self):
        self.assertTrue(context('printf test > fo').files_only)
        self.assertTrue(context('cat < fo').files_only)

    def test_quotes_and_backslashes(self):
        self.assertEqual(context('cd "My Fol').prefix, 'My Fol')
        self.assertEqual(context("cd 'My Fol").prefix, 'My Fol')
        self.assertEqual(context('cd My\\ Fol').prefix, 'My Fol')

    def test_cursor_middle(self):
        ctx = context('sudX something', 3)
        new, point = replacement(ctx, Candidate('sudo'))
        self.assertEqual(new, 'sudo something')
        self.assertEqual(point, 4)

    def test_utf8_offsets(self):
        text = 'echo äöü fo'
        ctx = context(text)
        self.assertEqual(ctx.prefix, 'fo')
        self.assertEqual(ctx.point, len(text))
        new, point = replacement(ctx, Candidate('föö'))
        self.assertEqual(point, len(new.encode()))
        self.assertIsNone(parse_context('ä', 1))

    def test_reject_substitution_and_comments(self):
        for text in ('echo $(touch /tmp/no)', 'echo `whoami`', 'cat << END', '# sudo a', 'echo x # sudo a', 'echo\nline', 'echo ${HOME}'):
            self.assertIsNone(context(text), text)

    def test_reject_globs_and_variables(self):
        for text in ('ls $HOME', 'cat *.txt', 'ls [ab]'):
            self.assertIsNone(context(text))

    def test_filename_quoting(self):
        ctx = context('cat fo')
        for name in ('foo bar', "foo'bar", 'foo; touch /tmp/never', 'foo$(whoami)', 'foo\nbar', 'foo`id`'):
            new, point = replacement(ctx, Candidate(name, 'Datei'))
            self.assertEqual(shlex.split(new), ['cat', name])
            self.assertEqual(point, len(new.encode()))

    def test_directory_no_space(self):
        new, point = replacement(context('cd My'), Candidate('My Folder/', 'Ordner', True))
        self.assertEqual(shlex.split(new), ['cd', 'My Folder/'])
        self.assertFalse(new.endswith(' '))
        self.assertEqual(point, len(new.encode()))

    def test_home_expansion(self):
        new, _ = replacement(context('cd ~/Do'), Candidate('~/Downloads/', 'Ordner', True))
        self.assertEqual(new, 'cd ~/Downloads/')
        new, _ = replacement(context('cd ~/My'), Candidate('~/My Folder/', 'Ordner', True))
        self.assertEqual(new, "cd ~/'My Folder/'")


class FileAndCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.engine = Engine(ROOT / 'shell' / 'native-complete.bash')

    def tearDown(self):
        self.engine.cancel()
        self.temp.cleanup()

    def create_command(self, name, mode=0o755):
        target = self.bin / name
        target.write_text('#!/bin/sh\nexit 0\n')
        target.chmod(mode)
        return target

    def test_real_path_third_party_and_shell_names(self):
        self.create_command('julius-cli')
        self.create_command('julius-not-executable', 0o644)
        got = self.engine.complete(context('julius'), str(self.base), str(self.bin), ['julius-alias', 'julius-function'], False)
        self.assertEqual({c.value for c in got}, {'julius-cli', 'julius-alias', 'julius-function'})

    def test_newly_installed_and_removed(self):
        self.assertFalse(self.engine.complete(context('third'), str(self.base), str(self.bin), [], False))
        target = self.create_command('thirdparty')
        self.assertEqual(self.engine.complete(context('third'), str(self.base), str(self.bin), [], False)[0].value, 'thirdparty')
        target.unlink()
        self.assertFalse(self.engine.complete(context('third'), str(self.base), str(self.bin), [], False))

    def test_strict_prefix_not_substring(self):
        for name in ('sud', 'sudo', 'sup', 'xxsud'):
            self.create_command(name)
        got = self.engine.complete(context('sud'), str(self.base), str(self.bin), [], False)
        self.assertEqual([c.value for c in got], ['sud', 'sudo'])

    def test_no_shell_aliases_after_sudo(self):
        self.create_command('zzreal')
        got = self.engine.complete(context('sudo zz'), str(self.base), str(self.bin), ['zzalias'], False)
        self.assertIn('zzreal', [c.value for c in got])
        self.assertNotIn('zzalias', [c.value for c in got])

    def test_files_and_hidden(self):
        (self.base / 'My Folder').mkdir()
        (self.base / 'My File').touch()
        (self.base / '.hidden').touch()
        self.assertEqual({c.value for c in files('My', str(self.base))}, {'My Folder/', 'My File'})
        self.assertNotIn('.hidden', [c.value for c in files('', str(self.base))])
        self.assertIn('.hidden', [c.value for c in files('.', str(self.base))])
        self.assertEqual([c.value for c in files('My', str(self.base), True)], ['My Folder/'])

    def test_relative_executable(self):
        self.create_command('runme')
        self.create_command('readme', 0o644)
        got = self.engine.complete(context('./bin/r'), str(self.base), str(self.bin), [], False)
        self.assertEqual([c.value for c in got], ['./bin/runme'])

    def test_fallback_apt_context(self):
        got = self.engine.complete(context('sudo apt i'), str(self.base), str(self.bin), [], False)
        self.assertEqual([c.value for c in got], ['install'])


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.data = self.base / 'data'
        self.compdir = self.data / 'bash-completion' / 'completions'
        self.compdir.mkdir(parents=True)
        self.engine = Engine(ROOT / 'shell' / 'native-complete.bash')
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.data), 'HOME': str(self.base)})
        self.env.start()

    def tearDown(self):
        self.engine.cancel()
        self.env.stop()
        self.temp.cleanup()

    def native(self, text):
        self.engine.cancelled.clear()
        return self.engine.native(context(text), str(self.base), os.environ['PATH'])

    def test_custom_completion_function(self):
        (self.compdir / 'julius-cli').write_text('_jc() { COMPREPLY=(deploy describe delete); }; complete -F _jc julius-cli\n')
        got = self.native('julius-cli de')
        self.assertEqual({c.value for c in got}, {'deploy', 'describe', 'delete'})

    def test_static_wordlist(self):
        (self.compdir / 'julius-cli').write_text("complete -W 'start stop status' julius-cli\n")
        self.assertEqual({c.value for c in self.native('julius-cli st')}, {'start', 'stop', 'status'})

    def test_prefix_and_suffix(self):
        (self.compdir / 'julius-cli').write_text("complete -W 'one two' -P 'pre-' -S '=value' julius-cli\n")
        self.assertEqual({c.value for c in self.native('julius-cli ')}, {'pre-one=value', 'pre-two=value'})

    def test_quoted_wordlist(self):
        (self.compdir / 'julius-cli').write_text("complete -W '\"hello world\" hello' julius-cli\n")
        self.assertIn('hello world', [c.value for c in self.native('julius-cli he')])

    def test_git_style_explicit_completion_space(self):
        (self.compdir / 'julius-cli').write_text("_jc() { COMPREPLY=('checkout '); }; complete -o nospace -F _jc julius-cli\n")
        got = self.native('julius-cli ch')
        self.assertEqual(got[0].value, 'checkout')
        new, _ = replacement(context('julius-cli ch'), got[0])
        self.assertEqual(new, 'julius-cli checkout ')

    def test_literal_apostrophe(self):
        (self.compdir / 'julius-cli').write_text('''_jc() { COMPREPLY=("O'Brien"); }; complete -F _jc julius-cli\n''')
        got = self.native('julius-cli O')
        self.assertEqual(got[0].value, "O'Brien")
        new, _ = replacement(context('julius-cli O'), got[0])
        self.assertEqual(shlex.split(new), ['julius-cli', "O'Brien"])

    def test_completion_cannot_run_entered_input(self):
        marker = self.base / 'NOPE'
        (self.compdir / 'julius-cli').write_text('_jc() { COMPREPLY=(hello); }; complete -F _jc julius-cli\n')
        text = f'julius-cli "$(touch {marker})"'
        self.assertIsNone(context(text))
        self.assertFalse(marker.exists())
        dangerous = f'hello;touch {marker}'
        new, _ = replacement(context('julius-cli he'), Candidate(dangerous))
        self.assertEqual(shlex.split(new), ['julius-cli', dangerous])
        self.assertFalse(marker.exists())

    def test_provider_timeout(self):
        (self.compdir / 'julius-cli').write_text('_jc() { sleep 8; COMPREPLY=(slow); }; complete -F _jc julius-cli\n')
        before = time.monotonic()
        self.assertEqual(self.native('julius-cli s'), [])
        self.assertLess(time.monotonic() - before, 2.0)

    def test_no_arbitrary_help_or_actual_program_execution(self):
        marker = self.base / 'RAN'
        bindir = self.base / 'bin'
        bindir.mkdir()
        command = bindir / 'julius-cli'
        command.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
        command.chmod(0o755)
        self.engine.complete(context('julius'), str(self.base), str(bindir), [], True)
        self.engine.complete(context('julius-cli '), str(self.base), str(bindir), [], True)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
