"""Conservative natural-language task routing, not a shell parser or an LLM.

Separate topical relevance from having an executable command. Everyday words,
misspellings and task objects count as scope; a missing URL is not an off-topic
request. Return only reviewed IDs or a targeted clarification. Never alter the
user's real Bash line, guess paths, execute downloads or inspect terminal output.
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
import re

from .search_text import normalize
from .terminal_knowledge import TERMINAL_ENTRIES

_EXACT = {normalize(q): e for e in TERMINAL_ENTRIES for q in (e.title, *e.examples)}

def exact_terminal_entry(question: str):
    return _EXACT.get(normalize(question))

# Only query vocabulary is corrected. Names inside quotes, paths and URLs do
# not become actions. In particular a filename containing 'github' or 'update'
# does not request a clone/system upgrade.
def scope_text(question: str) -> str:
    question = question.strip()
    if len(question) > 1 and question[0] in ('\"', "'", '`') and question[-1] == question[0]:
        question = question[1:-1]
    text = re.sub(r'https?://[^\s<>]+', lambda m: (
        ' github repository link ' if re.match(r'https?://(?:www\.)?github\.com/', m[0], re.I)
        else ' gitlab repository link ' if re.match(r'https?://(?:www\.)?gitlab\.com/', m[0], re.I)
        else ' downloadlink '), question)
    text = re.sub(r'(?<!\w)(?:"[^"\n]*"|\'[^\'\n]*\'|`[^`\n]*`)', ' operand ', text)
    text = re.sub(r'(?<!\w)(?:[~./][^\s]+|[\w.-]+\.(?:txt|log|json|py|sh|md))(?!\w)', ' file ', text)
    text = normalize(text)
    text = re.sub(r'\b(?:git hub|git hup|githup|gitthub|githib|githab)\b', 'github', text)
    text = re.sub(r'\bgitclone\b', 'git clone', text)
    text = re.sub(r'\b(?:runter|herunter) (?:laden|geladen|lade)\b', 'herunterladen', text)
    text = re.sub(r'\b(?:tar) (?:gz|xz|bz2|zst)\b', 'tar', text)
    return text

_ALIASES = {
    'repo': 'repository', 'repos': 'repository', 'repositorys': 'repository',
    'repositories': 'repository', 'repositry': 'repository', 'repository': 'repository',
    'repositorium': 'repository', 'reposetory': 'repository',
    'projekt': 'project', 'projekte': 'project', 'project': 'project',
    'quellcode': 'source', 'sourcecode': 'source', 'quelltext': 'source',
    'runterladen': 'download', 'herunterladen': 'download', 'herunterlade': 'download',
    'runterziehen': 'download', 'saugen': 'download', 'bekommen': 'get',
    'runterlade': 'download', 'runtergeladen': 'download', 'dowloaden': 'download',
    'downladen': 'download', 'downloaden': 'download', 'download': 'download', 'downloads': 'download',
    'heruntergeladen': 'download', 'laden': 'download', 'lade': 'download',
    'klonen': 'clone', 'klon': 'clone', 'klone': 'clone', 'geklont': 'clone',
    'geklontes': 'clone', 'geklonten': 'clone', 'clonen': 'clone', 'cloning': 'clone',
    'clone': 'clone', 'cloned': 'clone', 'ziehen': 'get', 'hole': 'get', 'holen': 'get',
    'bekomme': 'get', 'kriege': 'get', 'kriegen': 'get', 'get': 'get',
    'kopieren': 'copy', 'kopier': 'copy', 'kopiere': 'copy', 'kopie': 'copy',
    'duplizieren': 'copy', 'dupliziere': 'copy', 'copy': 'copy',
    'hochladen': 'upload', 'hochlade': 'upload', 'hochgeladen': 'upload',
    'push': 'upload', 'pushen': 'upload', 'uploaden': 'upload', 'upload': 'upload',
    'aktualisieren': 'update', 'aktualisiere': 'update', 'updaten': 'update',
    'update': 'update', 'updates': 'update', 'neuesten': 'latest', 'neuste': 'latest',
    'neueste': 'latest', 'neuestes': 'latest', 'neuen': 'new',
    'release': 'release', 'releases': 'release', 'asset': 'release', 'assets': 'release',
    'fertig': 'binary', 'fertige': 'binary', 'fertiges': 'binary', 'fertigen': 'binary',
    'installer': 'binary', 'installationsdatei': 'binary', 'binary': 'binary',
    'binaries': 'binary', 'appimage': 'binary',
    'programme': 'program', 'programm': 'program', 'anwendung': 'program', 'anwendungen': 'program',
    'app': 'program', 'apps': 'program', 'program': 'program',
    'datei': 'file', 'dateien': 'file', 'file': 'file', 'files': 'file',
    'einzelne': 'single', 'einzelnen': 'single', 'einzelnes': 'single', 'single': 'single',
    'ordner': 'directory', 'verzeichnis': 'directory', 'verzeichnisse': 'directory',
    'folder': 'directory', 'folders': 'directory', 'directory': 'directory',
    'archiv': 'archive', 'archive': 'archive',
    'auspacken': 'extract', 'entpacken': 'extract', 'entpacke': 'extract',
    'extrahieren': 'extract', 'entpaken': 'extract', 'unpack': 'extract',
    'extract': 'extract', 'unzip': 'extract', 'auspackt': 'extract', 'entpackt': 'extract',
    'umbenennen': 'rename', 'umbenenne': 'rename', 'rename': 'rename',
    'verschieben': 'move', 'verschiebe': 'move', 'move': 'move',
    'erstellen': 'create', 'erstell': 'create', 'erstelle': 'create',
    'anlegen': 'create', 'create': 'create', 'make': 'create', 'lege': 'place', 'leg': 'place',
    'wechseln': 'change', 'wechsle': 'change', 'wechsel': 'change', 'change': 'change',
    'gehen': 'go', 'gehe': 'go', 'go': 'go',
    'suche': 'search', 'suchen': 'search', 'finden': 'search', 'finde': 'search',
    'aufspuren': 'search', 'find': 'search', 'search': 'search',
    'zeitstempel': 'timestamps', 'timestamps': 'timestamps', 'geandert': 'modified',
    'andert': 'modified', 'modified': 'modified',
    'installieren': 'install', 'installiere': 'install', 'installier': 'install',
    'instalieren': 'install', 'install': 'install',
    'paket': 'package', 'pakete': 'package', 'package': 'package',
    'loschen': 'delete', 'losche': 'delete', 'entfernen': 'delete', 'delete': 'delete',
    'befehle': 'command', 'befehl': 'command', 'commands': 'command',
    'befehlen': 'command', 'cmd': 'command',
}
_FUZZY = ('github', 'gitlab', 'repository', 'herunterladen', 'runterladen',
          'downloaden', 'installieren', 'entpacken', 'verzeichnis', 'verschieben', 'umbenennen')

@lru_cache(maxsize=512)
def _word(word: str) -> str:
    if word in _ALIASES:
        return _ALIASES[word]
    if len(word) >= 6:
        possible = [w for w in _FUZZY if w[:2] == word[:2] and abs(len(w) - len(word)) <= 2]
        closest = get_close_matches(word, possible, n=1, cutoff=.84)
        if closest:
            return _ALIASES.get(closest[0], closest[0])
    return word


def task_words(question: str) -> set[str]:
    return {_word(word) for word in scope_text(question).split()}


@dataclass(frozen=True)
class TaskMatch:
    entry_id: str = ''
    domain: bool = False
    clarification: str = ''
    related: tuple[str, ...] = ()
    family: str = ''


def match_terminal_question(question: str) -> TaskMatch:
    text = scope_text(question)
    w = task_words(question)
    if 'hoch' in w and w & {'lade', 'download'}:
        w.add('upload')
    if 'upload' in w and not re.search(r'\b(?:herunter[a-z]*|runter[a-z]*|down[a-z]*|clone|klon[a-z]*)\b', text):
        w.discard('download')  # German separable verb: 'lade ... hoch', not a download.
    git = bool(w & {'git', 'github', 'gitlab', 'bitbucket', 'repository'})
    source = bool(w & {'source', 'project'})
    file_object = bool(w & {'file', 'directory', 'archive', 'zip', 'tar', 'deb'})
    domain = git or file_object or bool(w & {'download', 'downloadlink', 'apt', 'ssh',
        'install', 'uninstall', 'deinstallieren', 'compile',
        'sudo', 'bash', 'shell', 'terminal', 'linux', 'ubuntu', 'auralyn', 'command',
        'systemctl', 'docker', 'flatpak', 'snap', 'curl', 'wget', 'chmod', 'package',
        'permissions', 'zugriffsrechte', 'berechtigungen', 'compiler', 'kompilieren',
        'server', 'port', 'ports', 'prozess', 'prozesse', 'netzwerk', 'network',
        'ram', 'cpu', 'gpu', 'ssd', 'kernel', 'firewall', 'ip'})
    def hit(ident: str, family: str = '') -> TaskMatch:
        return TaskMatch(ident, True, family=family)
    def clarify(message: str, related: tuple[str, ...], family: str) -> TaskMatch:
        return TaskMatch(domain=True, clarification=message, related=related, family=family)

    if 'search' in w and 'file' in w and w & {'settings', 'einstellungen', 'konfiguration'}:
        return TaskMatch(domain=True)  # Auralyn's settings-file help has priority.
    if git:
        family = 'git'
        # Do not combine multiple operations or ignore a negation and then start
        # installing/cloning. Broad questions are still in scope.
        if 'upload' in w and w & {'download', 'clone'}:
            return clarify('Möchtest du ein Projekt herunterladen (git clone) oder eigene Änderungen '
                           'hochladen (git push)? Das sind unterschiedliche Schritte.',
                           ('git.clone', 'git.push_help'), family)
        if w & {'nicht', 'not', 'never'} and w & {'download', 'clone', 'upload', 'install'}:
            return clarify('Welche Git-Aufgabe möchtest du stattdessen erledigen: Quellcode laden, '
                           'einen Release laden oder ein vorhandenes Projekt aktualisieren?',
                           ('git.clone', 'git.release', 'git.pull'), family)
        if 'upload' in w:
            return hit('git.push_help', family)
        # "Git installieren" installs Git, "Programm von GitHub installieren"
        # is about the particular project's distribution, not the Git package.
        if ('git' in w and not w & {'github', 'gitlab', 'repository', 'source', 'project', 'program'}
                and ('install' in w or {'not', 'found'} <= w or {'nicht', 'gefunden'} <= w)):
            return hit('git.install', family)
        if w & {'update', 'pull'} or ('latest' in w and ('stand' in w or 'version' in w)):
            return hit('git.pull', family)
        if w & {'release', 'binary'} or ('install' in w and w & {'github', 'gitlab'}):
            return hit('git.release', family)
        if ('zip' in w or (('ohne' in w or 'without' in w) and 'git' in w)) and (w & {'download', 'archive', 'repository', 'source', 'github', 'gitlab'}):
            return hit('git.zip', family)
        if 'raw' in w or ('file' in w and (w & {'single', 'nur', 'one', '1'}) and not 'directory' in w):
            return hit('git.file', family)
        if w & {'download', 'clone', 'get', 'copy'}:
            # Don't claim a single-folder download is a full ordinary clone.
            if 'directory' in w and w & {'single', 'nur', 'one', '1'}:
                return clarify('Ein normaler git clone lädt das Repository, nicht nur einen einzelnen Unterordner. '
                               'Nenne den Repository-Link und den gewünschten Ordner; alternativ kannst du das '
                               'ganze Projekt oder einzelne Raw-Dateien herunterladen.',
                               ('git.clone', 'git.file'), family)
            return hit('git.clone', family)
        return TaskMatch(domain=True, family=family, related=('git.clone', 'git.release', 'git.pull'))

    if 'clone' in w and source:
        return hit('git.clone', 'git')
    if 'extract' in w:
        if 'zip' in w or 'unzip' in text.split():
            return hit('archive.zip', 'files')
        if 'tar' in w:
            return hit('archive.tar', 'files')
        return clarify('Welches Archiv möchtest du entpacken: .zip, .tar.gz oder etwas anderes? '
                       'Nenne die Dateiendung; der passende Befehl hängt davon ab.',
                       ('archive.zip', 'archive.tar'), 'files')
    if 'download' in w or ('downloadlink' in w and 'get' in w):
        return hit('download.wget' if 'wget' in w else 'download.file', 'download')
    if 'install' in w and 'deb' in w:
        return hit('package.deb_help', 'package')
    if 'install' in w and w & {'program', 'package', 'apt'} and not w & {'flatpak', 'snap', 'docker'}:
        return hit('package.install_help', 'package')
    if file_object:
        if 'copy' in w:
            return hit('files.copy_directory' if 'directory' in w else 'files.copy', 'files')
        if w & {'move', 'rename'}:
            return hit('files.move', 'files')
        if 'directory' in w and ('create' in w or {'place', 'an'} <= w):
            return hit('files.mkdir', 'files')
        if 'directory' in w and w & {'go', 'change'}:
            return hit('files.cd', 'files')
        if 'file' in w and 'search' in w:
            return hit('files.find', 'files')
        if 'file' in w and ('timestamps' in w or {'wie', 'alt'} <= w or {'how', 'old'} <= w
                           or ('wann' in w and 'modified' in w)):
            return hit('files.timestamps', 'files')
        if 'delete' in w:
            return clarify('Welche Datei oder welcher Ordner soll gelöscht werden? Nenne den genauen Pfad '
                           'und ob der Papierkorb oder dauerhaftes Löschen gemeint ist. '
                           'Ich starte keinen geratenen Löschbefehl.', (), 'files')
    return TaskMatch(domain=domain)


def task_clarification(task: TaskMatch) -> str:
    if task.clarification:
        return task.clarification
    if task.family == 'git':
        return ('Geht es um Quellcode herunterladen (git clone), eine fertige Release-Datei oder '
                'ein vorhandenes Repository aktualisieren (git pull)? Ein Projekt-Link hilft.')
    return ('Das klingt nach einer Terminal-Aufgabe, aber mir fehlt noch ein eindeutiger Treffer. '
            'Nenne das Ziel, die App oder den Dateityp — du musst den Befehl nicht kennen. '
            'Beispiel: „Sachen von GitHub runterladen“ oder „Eine ZIP entpacken“.')
