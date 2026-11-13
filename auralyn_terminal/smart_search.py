"""Smart Search: AI-first command research, product help and labelled offline fallback.

No shell is used while answering. No terminal output/history/passwords are read.
Questions remain in memory. Only reviewed actions have an execution ID.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import os
import queue
import re
import shlex
import shutil
import threading
import unicodedata
from typing import Callable

from .diagnostics import record_failure
from .command_help import HelpEngine, MAN_TOPIC, clean_text
from .help_catalog import COMMAND_HELP, SUBCOMMAND_HELP, OPTION_HELP
from .local_ai import AIError, Cancelled, OllamaClient
from .command_ai import CommandResearch, exact_action
from .web_command_ai import WebCommandResearch
from .smart_catalog import ENTRIES, Entry, get_action
from .app_intent import exact_app_entry, match_app_question
from .search_text import normalize
from .terminal_intent import (match_terminal_question, task_clarification, scope_text, task_words, exact_terminal_entry)

MAX_QUESTION = 800
OFFLINE_SOURCE = 'Offline-Suche · feste Regeln, keine KI'
APP_SOURCE = 'Auralyn-Programmhilfe · lokal, keine KI'


@dataclass(frozen=True)
class Answer:
    title: str
    text: str
    entry_id: str = ''
    command: str = ''
    warning: str = ''
    ui: str = ''
    source: str = OFFLINE_SOURCE
    note: str = ''
    state: str = 'answer'
    evidence: str = ''
    sources: tuple = ()
    install_command: str = ''
    install_note: str = ''
    diagnostic: str = ''

    @property
    def executable(self) -> bool:
        entry = get_action(self.entry_id)
        # Never trust the visible string as executable code.
        return entry is not None and entry.command == self.command and self.state == 'answer'


def from_entry(entry: Entry, source: str = OFFLINE_SOURCE, note: str = '') -> Answer:
    if entry.preview and not note:
        note = 'Anleitung / Befehlsvorlage · keine automatische Ausführung. Platzhalter und Ziel prüfen.'
    return Answer(entry.title, entry.text, entry.id, entry.command, entry.warning,
                  entry.ui, source, note)


def rejected() -> Answer:
    return Answer('Smart Search', 'Anfrage Abgelehnt', state='rejected',
                  source='Nur Linux-Befehlshilfe und Auralyn Terminal')



_STOP = set('wie was ich du mein meine meinen meinem meiner mir mich der die das den dem des ein eine einen '
            'einem einer ist sind kann kannst kanns bitte jetzt mal denn man fur mit in im auf an am '
            'es einem eines oder und so zu zum zur von vom brauche benotige mochte will bitte einfach '
            'the a an my i me you how what do does is are can to of on for in it there please show '
            'anzeige anzeigen zeige zeigen lass lassen gibt habe hat machen mache nutzen verwenden '
            'vollstandigen alle aktuellen aktueller aktuell aktuellsten neueste neuesten neusten '
            'viel viele etwas infos information informationen'.split())
_SYNONYMS = {
    'updaten': 'update', 'updatet': 'update', 'update': 'update', 'updates': 'update',
    'aktualisieren': 'update', 'aktualisiere': 'update', 'aktualisier': 'update',
    'aktualisiert': 'update', 'aktualisierung': 'update', 'upgrades': 'update',
    'aktualisierbar': 'upgradable', 'aktualisierbare': 'upgradable',
    'aktualisierbaren': 'upgradable', 'system': 'system', 'ubuntu': 'system', 'linux': 'system',
    'betriebssystem': 'system', 'computer': 'pc', 'rechner': 'pc',
    'memory': 'ram', 'arbeitsspeicher': 'ram', 'speicherauslastung': 'ram',
    'auslastung': 'usage', 'belegung': 'usage', 'belegt': 'usage',
    'speicherplatz': 'space', 'festplattenspeicher': 'space', 'platz': 'space', 'space': 'space',
    'festplatte': 'disk', 'festplatten': 'disk', 'ssd': 'disk', 'ssds': 'disk', 'disk': 'disk',
    'laufwerk': 'drive', 'laufwerke': 'drive', 'drives': 'drive', 'partitionen': 'partition',
    'laufzeit': 'uptime', 'lauft': 'running', 'laufen': 'running',
    'prozess': 'process', 'prozesse': 'process', 'prozessliste': 'process', 'processes': 'process',
    'programme': 'program', 'programm': 'program', 'programs': 'program', 'apps': 'program',
    'anwendung': 'program', 'anwendungen': 'program',
    'paket': 'package', 'pakete': 'package', 'paketen': 'package', 'packages': 'package',
    'paketlisten': 'packagelists', 'paketliste': 'packagelists', 'paketquellen': 'packagelists',
    'dateien': 'file', 'datei': 'file', 'files': 'file',
    'ordner': 'directory', 'arbeitsverzeichnis': 'directory', 'arbeitsordner': 'directory',
    'einstellungen': 'settings', 'einstellung': 'settings',
    'transparent': 'transparency', 'transparenz': 'transparency', 'durchsichtig': 'transparency',
    'glaseffekt': 'transparency', 'transperent': 'transparency',
    'grafikkarte': 'gpu', 'grafik': 'gpu', 'grafikspeicher': 'vram',
    'prozessor': 'cpu', 'processor': 'cpu', 'kerne': 'cores', 'kernen': 'cores',
    'temperaturen': 'temperature', 'temperatur': 'temperature', 'heiss': 'temperature',
    'benutzer': 'user', 'benutzername': 'user', 'benutzernamen': 'user', 'benutzerkonto': 'user',
    'gruppen': 'groups', 'benutzergruppen': 'groups',
    'offne': 'open', 'offnen': 'open', 'starten': 'start', 'starte': 'start',
    'stoppen': 'stop', 'stoppe': 'stop', 'beenden': 'stop', 'schliessen': 'stop',
    'installieren': 'install', 'installiere': 'install', 'installierte': 'installed',
    'installierten': 'installed', 'installiert': 'installed',
    'dienste': 'service', 'dienst': 'service', 'services': 'service',
    'fehler': 'error', 'fehlerlogs': 'error', 'errors': 'error',
    'vorschlage': 'suggestions', 'autovervollstandigung': 'suggestions',
    'lupe': 'smart', 'kurzhilfe': 'help', 'hilfe': 'help',
    'befehl': 'command', 'befehle': 'command', 'commands': 'command',
}
_GENERIC = set('system pc terminal command program package file directory usage start open install update '
               'version help status list available free frei current deutsch english'.split())
_DOMAIN = set('system pc terminal auralyn bash sudo command program package file directory ram disk drive '
              'space cpu gpu vram temperature uptime ip network netzwerk netzwerkadressen port ports tcp udp '
              'ssh apt snap flatpak docker git kernel update packagelists upgradable sensor sensors '
              'service error logs boot settings transparency suggestions tab tabs smart ollama ki ai '
              'user groups clipboard zwischenablage kopieren einfugen schriftgrosse cursor'.split())


def tokens(text: str) -> set[str]:
    return {_SYNONYMS.get(word, word) for word in normalize(text).split() if word not in _STOP}


_INDEX = {entry.id: [tokens(example) for example in (entry.title, *entry.examples)]
          for entry in ENTRIES.values()}
_EXACT = {normalize(example): entry.id for entry in ENTRIES.values()
          for example in (entry.title, *entry.examples)}


def question_text(question: object) -> str | None:
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        return None
    if any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in question):
        return None
    return ' '.join(question.split())


def blocked_question(question: str) -> bool:
    value = scope_text(question)
    # URLs and quoted operands do not turn a legitimate file task into trivia.
    # Actual mixed/general-knowledge and prompt-injection requests must not be
    # laundered into a task merely by appending a word like sudo or Ubuntu.
    patterns = (
        r'^(?:hallo|hello|hi|guten morgen|guten tag|guten abend)$',
        r'\b(?:elon|musk|trump|biden|taylor swift|geburtstag|sternzeichen|horoskop)\b',
        r'\b(?:wer ist|who is|wer war|who was)\b',
        r'\b(?:wetter|weather|rezept|recipe|fussball|football|bundestagswahl|president|prasident)\b',
        r'\b(?:witz|joke|gedicht|poem|liebesbrief|songtext|lyrics|hauptstadt|capital of)\b',
        r'\b(?:ignoriere|ignorier|ignore|vergiss)\b.*\b(?:regeln|regel|instructions|anweisung|prompt|vorher)\b',
        r'\b(?:system prompt|systemprompt|jailbreak|developer mode|entwicklermodus)\b',
        r'\b(?:tu so als|pretend to be|act as|du bist jetzt|you are now)\b',
    )
    if re.search(r'\b(?:wie alt|how old)\b', value) and 'file' not in task_words(question):
        return True
    return any(re.search(pattern, value) for pattern in patterns)


def rank_entries(question: str) -> list[tuple[float, str]]:
    exact = _EXACT.get(normalize(question))
    if exact:
        return [(1.0, exact)]
    words = tokens(question)
    ranked = []
    if not words:
        return []
    for ident, samples in _INDEX.items():
        best = 0.0
        for sample in samples:
            if not sample:
                continue
            shared = sample & words
            if not shared:
                continue
            # A single generic word ("System", "Dateien", "Programm") does
            # not establish what the user wants to do with it.
            if len(shared) == 1 and (len(words) > 2 or next(iter(shared)) in _GENERIC):
                continue
            precision, recall = len(shared) / len(words), len(shared) / len(sample)
            score = 2 * precision * recall / (precision + recall)
            best = max(best, score)
        if best >= 0.56:
            ranked.append((best, ident))
    return sorted(ranked, key=lambda value: (-value[0], value[1]))


def local_match(question: str) -> Entry | None:
    ranked = rank_entries(question)
    if not ranked or ranked[0][0] < 0.64:
        return None
    if len(ranked) > 1 and ranked[0][0] < 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None
    return ENTRIES[ranked[0][1]]


def _extract_command(question: str) -> tuple[list[str], bool] | None:
    text = question.strip().rstrip('?!')
    # Outer code delimiters are formatting, never executed.
    text = text.strip('`')
    explicit = False
    match = re.match(r'^(?:was macht|was kann|was bedeutet|wozu dient|erkl[aä]re(?: mir)?|'
                     r'erkl[aä]r(?: mir)?|was ist|explain|what does|help for|hilfe zu)\s+'
                     r'(?:(?:der|das|den|the)\s+)?(?:(?:befehl|command)\s+)?(.+)$', text, re.I)
    if match:
        explicit = True
        text = match.group(1).strip().strip('`"\'').rstrip('?!.')
        text = re.sub(r'\s+(?:do|machen|tun)$', '', text, flags=re.I)
    if any(char in text for char in ';|&<>$()\n\r\x00'):
        return None
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    if not words or len(words) > 12 or not MAN_TOPIC.fullmatch(words[0]):
        return None
    if not explicit and len(words) > 1 and words[0] not in COMMAND_HELP and words[0] not in ('run', 'auralyn-run', 'auralyn-kill'):
        return None
    return words, explicit


class SearchEngine:
    def __init__(self, *, client: OllamaClient | None = None, manual=None,
                 known_command: Callable[[str], bool] | None = None, research=None, capabilities=None, web_research=None):
        self.client = client or OllamaClient()
        self.manual = manual or HelpEngine()
        self.known_command = known_command or (lambda name: shutil.which(name) is not None)
        self.research = research or CommandResearch(self.client, capabilities)
        self.web_research = web_research or WebCommandResearch(self.client, capabilities)

    def cancel(self):
        self.client.cancel()
        self.manual.cancel()
        self.web_research.cancel()

    def command_help(self, question: str) -> Answer | None:
        extracted = _extract_command(question)
        if not extracted:
            return None
        words, explicit = extracted
        # A raw exact reviewed command may be executed. A request for its
        # explanation gets help without accidentally turning it into an action.
        if not explicit:
            exact = get_action(_EXACT.get(normalize(question), ''))
            if exact is not None:
                return from_entry(exact)
            for entry in ENTRIES.values():
                if entry.command and shlex.join(words) == entry.command:
                    return from_entry(entry)
        first = words[0]
        if first in ('run', 'auralyn-run'):
            topic = 'app.foreground' if len(words) > 1 and words[1] in ('--foreground', '-f') else 'app.run'
            return from_entry(ENTRIES[topic], source='Auralyn-Befehlshilfe · lokal')
        if first in ('kill', 'auralyn-kill') and (len(words) == 1 or not (words[1].startswith(('-', '%')) or words[1].isdigit())):
            return from_entry(ENTRIES['app.kill'], source='Auralyn-Befehlshilfe · lokal',
                              note='kill PID und kill -9 PID behalten die normale Bash-Semantik. Eigene run/kill-Aliase haben Vorrang.')
        if first == 'sudo' and len(words) > 1 and not words[1].startswith('-'):
            words = words[1:]
            first = words[0]
        if not (first in COMMAND_HELP or self.known_command(first)):
            # Known subcommand manuals can exist without an executable.
            return None
        key = tuple(words)
        title = clean_text(' '.join(words), 100)
        if key in SUBCOMMAND_HELP:
            return Answer(title, SUBCOMMAND_HELP[key], source='Auralyn-Befehlshilfe · lokal')
        if len(words) == 2 and (first, words[1]) in OPTION_HELP:
            return Answer(title, OPTION_HELP[(first, words[1])], source='Auralyn-Befehlshilfe · lokal')
        if len(words) == 1 and first in COMMAND_HELP:
            return Answer(title, COMMAND_HELP[first], source='Auralyn-Befehlshilfe · lokal')
        if len(words) == 2 and MAN_TOPIC.fullmatch(words[1]):
            text = self.manual.lookup_manual(first + '-' + words[1])
            if text:
                return Answer(title, clean_text(text), source='Lokales Handbuch · Originalsprache')
        description = COMMAND_HELP.get(first) or self.manual.lookup_manual(first)
        if description:
            note = 'Nur der Hauptbefehl ist beschrieben; diese Argumente sind nicht einzeln geprüft.' if len(words) > 1 else ''
            return Answer(title, clean_text(description), source='Auralyn/Handbuch · lokal', note=note)
        return Answer(title, 'Installierter Befehl, aber keine lokale Kurzbeschreibung gefunden.',
                      source='Lokale Befehlserkennung', note='Es wird keine Funktion erfunden und nichts ausgeführt.')

    def answer(self, question: object, ai_enabled: bool = False, model: str = 'qwen3:4b',
               cancelled: threading.Event | None = None, *, web_enabled=False, web_provider='duckduckgo',
               progress=None) -> Answer:
        """AI-first for terminal tasks; local versioned help for this app's UI.

        Crucially, a GitHub/download/file keyword match must NOT return early in
        AI mode. The model researches tools, regardless of the old catalogue.
        Offline rules are only used with AI off or as an explicitly labelled
        fallback after an unavailable/invalid model response.
        """
        cancel = cancelled or threading.Event()
        question = question_text(question)
        if not question:
            return rejected()
        if cancel.is_set():
            raise Cancelled('Anfrage abgebrochen.')
        self.manual.cancelled.clear()
        if not ai_enabled:
            return self._legacy_answer(question, False, model, cancel)

        # App manuals stay authoritative about actual menus/settings. They do
        # not get to override a real file/network/task question in AI mode.
        task = match_terminal_question(question)
        app = match_app_question(question)
        exact_app = exact_app_entry(question)
        direct = _extract_command(question)
        own_command = bool(direct and direct[0][0] in ('run', 'auralyn-run', 'auralyn-kill'))
        own_kill = bool(direct and direct[0][0] == 'kill' and
                       (len(direct[0]) == 1 or not direct[0][1].startswith(('-', '%'))
                        and not direct[0][1].isdigit()))
        if not blocked_question(question):
            if exact_app is not None:
                return from_entry(exact_app, source=APP_SOURCE)
            if own_command or own_kill:
                return self._legacy_answer(question, False, model, cancel)
            if (not task.domain or ('auralyn' in normalize(question).split() and not task.family)) and (app.entry_id or app.scoped or app.foreign_ui or app.ambiguous):
                return self._legacy_answer(question, True, model, cancel)

        if web_enabled and blocked_question(question):
            # Do not send a known off-topic or injection request to any public
            # provider just to rediscover that it is outside this terminal app.
            return rejected()
        stage = 'Aufgabe verstehen · lokales Modell'
        def report_progress(text):
            nonlocal stage
            stage = text
            if progress:
                progress(text)
        try:
            result = (self.web_research.answer(question, model, cancel, provider=web_provider, progress=report_progress)
                      if web_enabled else self.research.answer(question, model, cancel))
            if cancel.is_set():
                raise Cancelled('Anfrage abgebrochen.')
            if web_enabled and result.state == 'unavailable' and not result.web_checked:
                known = exact_terminal_entry(question) or ENTRIES.get(_EXACT.get(normalize(question), ''))
                if known is not None and not known.id.startswith('app.'):
                    offline = from_entry(known, source='Offline-Rückfall · Webprüfung nicht abgeschlossen',
                                         note='Keine Webbestätigung. ' + result.text + ' ' + result.web_note)
                    return offline
            source = (f'Lokale KI · {model} · Web + Lokal' if web_enabled
                      else f'Lokale KI · {model} · Befehlsrecherche')
            if not web_enabled and result.state in ('rejected', 'clarify') and not result.command:
                # A failed model match must not erase an already useful local
                # answer. This is an explicitly labelled fallback, not research.
                if not blocked_question(question):
                    local = self._legacy_answer(question, False, model, cancel)
                    if local.entry_id or (result.state == 'rejected' and task.domain):
                        return replace(local, source='Offline-Hilfe · keine KI-Antwort',
                                       note='Die KI fand keinen eindeutigen Befehl. Stattdessen: Offline-Hilfe. ' + local.note)
                if result.state == 'rejected':
                    return replace(rejected(), source=f'Lokale KI · {model} · Themenprüfung')
            if web_enabled and result.state == 'rejected':
                return replace(rejected(), source=source)
            if result.state == 'app':
                ident = self.client.choose(question, model, cancel, scope='app')
                if cancel.is_set():
                    raise Cancelled('Anfrage abgebrochen.')
                entry = ENTRIES.get(ident)
                if entry is not None and entry.id.startswith('app.'):
                    return from_entry(entry, source=f'Lokale KI · {model} · Auralyn-Programmhilfe')
                return self._app_clarification('Die KI hat die Frage als Auralyn-Bedienfrage eingeordnet.')
            inspected = tuple(e for e in result.evidence if not result.used_tools or e.command in result.used_tools)
            evidence = '\n'.join(e.description() for e in inspected)
            if web_enabled and result.web_checked:
                evidence = '1/2 Web: Quellen abgerufen und dem Befehl zugeordnet.\n2/2 Lokal: ' + (evidence or 'noch kein Befehl ausgewählt.')
            text = result.text + ('\n' + result.follow_up if result.follow_up else '')
            ident = exact_action(result.command) if result.command else ''
            # No execution for an explanation, missing input, absent commands or
            # model-generated syntax. Matching an approved ID isn't enough.
            if (result.state != 'answer' or result.follow_up or (direct and direct[1] and direct[0][0] in {e.command for e in inspected})
                    or not inspected or not all(e.available for e in inspected)):
                ident = ''
            entry = get_action(ident)
            warning = result.warning
            if entry and entry.warning:
                warning = entry.warning
            note = 'Verfügbarkeit und lokale Dokumentation abgeglichen, nicht testweise ausgeführt. '
            if not web_enabled and any(not e.text for e in inspected):
                note += 'Nicht alles ist lokal dokumentiert; Teile beruhen auf Modellwissen. '
            note += ('Prüfe Befehl und Ziel vor dem Ausführen.' if ident else
                     'KI-Vorlage nur zum Kopieren; Parameter und Platzhalter prüfen.')
            if web_enabled:
                note = ('Webquellen + lokale Verfügbarkeit abgeglichen; kein Funktionstest. '
                        'Gefunden bedeutet nicht, dass Treiber/Hardware oder alle Optionen funktionieren. ')
                note += 'Ausführen startet nur die feste geprüfte Aktion.' if ident else 'Neue KI-Vorlagen nur kopieren und prüfen.'
                if not result.web_checked:
                    source = 'Webprüfung nicht abgeschlossen · keine verifizierte Webantwort'
                if result.web_note:
                    note += '\n' + result.web_note
            if not result.command and not inspected and not web_enabled:
                note = ''
            return Answer(result.title or 'Befehlsrecherche', text, entry_id=ident,
                          command=result.command, warning=warning, source=source,
                          note=note, state=result.state, evidence=evidence,
                          sources=tuple((s.title, s.url, s.kind) for s in result.sources),
                          install_command=result.install_command, install_note=result.install_note)
        except Cancelled:
            raise
        except AIError as exc:
            if cancel.is_set():
                raise Cancelled('Anfrage abgebrochen.')
            diagnostic = record_failure(exc, stage=stage, web=web_enabled)
            if web_enabled:
                # For a *precisely* known local question, a model formatting
                # error should never hide the usable offline documentation.
                # Do not imply that the failed Web+KI check succeeded; do not
                # turn a fuzzy/unrelated question into an update action.
                exact = exact_terminal_entry(question) or ENTRIES.get(_EXACT.get(normalize(question), ''))
                if exact is not None and not exact.id.startswith('app.'):
                    answer = from_entry(exact, source='Offline-Rückfall · KEINE Web-/KI-Prüfung',
                                        note='Web-/KI-Prüfung fehlgeschlagen (' + str(exc)
                                             + '). Stattdessen eine bekannte Offline-Anleitung. '                                              + ('Ausführung nur mit deiner Bestätigung.' if exact.executable else 'Nur Vorlage, nicht automatisch ausführen.'))
                    return replace(answer, diagnostic=diagnostic.text)
                return Answer('Web-/KI-Prüfung nicht abgeschlossen',
                              'Die Prüfung ist fehlgeschlagen, nicht deine Frage. Es kann trotzdem einen passenden Befehl geben.',
                              source='KI + Web · Prüfung fehlgeschlagen, keine verifizierte Antwort',
                              note=str(exc), state='unavailable', diagnostic=diagnostic.text)
            fallback = self._legacy_answer(question, False, model, cancel)
            note = 'Keine KI-Prüfung: ' + str(exc)
            if blocked_question(question):
                return replace(rejected(), source='Offline-Themenprüfung · keine KI-Antwort', note=note)
            if fallback.state == 'clarify' and (task.clarification or task.family):
                return replace(fallback, source='Offline-Rückfall · keine KI-Antwort', note=note + ' Stattdessen: Offline-Rückfrage.')
            if fallback.state == 'rejected' or not fallback.entry_id:
                return Answer('KI-Recherche nicht verfügbar',
                              'Die Aufgabe konnte nicht mit der lokalen KI geprüft werden. '
                              'Das bedeutet nicht, dass es dafür keinen Befehl gibt.',
                              source='Offline-Rückfall · keine KI-Antwort', note=note,
                              state='unavailable', diagnostic=diagnostic.text)
            return replace(fallback, source='Offline-Rückfall · keine KI-Antwort',
                           note=note + ' Stattdessen vorhandene Offline-Hilfe. ' + fallback.note)

    def _legacy_answer(self, question: object, ai_enabled: bool = False, model: str = 'qwen3:4b',
               cancelled: threading.Event | None = None) -> Answer:
        cancel = cancelled or threading.Event()
        question = question_text(question)
        if not question or blocked_question(question):
            return rejected()
        if cancel.is_set():
            raise Cancelled('Anfrage abgebrochen.')
        self.manual.cancelled.clear()
        exact_app = exact_app_entry(question)
        if exact_app is not None:
            return from_entry(exact_app, source=APP_SOURCE)
        exact_task = exact_terminal_entry(question)
        if exact_task is not None:
            return from_entry(exact_task, source='Auralyn-Aufgabenhilfe · lokal, keine KI')
        direct = self.command_help(question)
        task = match_terminal_question(question)
        extracted = _extract_command(question) if direct is not None else None
        # Explicit 'Was macht ...?' remains explanation-only. Raw echo/cat and
        # third-party commands keep their own help, not a task from an operand.
        # Natural shorthand like 'tar xz entpacken' or 'git repo updaten' may
        # instead use the reviewed task guide.
        if direct is not None and (extracted is None or extracted[1]
                                   or extracted[0][0].lower() not in {'git', 'tar', 'zip', 'unzip'}):
            return direct
        # A specific terminal operation is not a GUI shortcut. For example,
        # copying a directory means cp -r, not Ctrl+Shift+C in Auralyn.
        if task.entry_id:
            return from_entry(ENTRIES[task.entry_id], source='Auralyn-Aufgabenhilfe · lokal, keine KI')
        if task.clarification:
            return Answer('Welche Aufgabe genau?', task.clarification, state='clarify')
        if direct is not None:
            return direct
        app = match_app_question(question)
        if app.foreign_ui:
            return Answer('Nur Auralyn-Oberfläche',
                          'Diese Einstellungs-Hilfe gilt für Auralyn Terminal, nicht für die Oberfläche anderer Apps. '
                          'Frage zum Beispiel „Wie stelle ich die Transparenz in Auralyn ein?“.',
                          source=APP_SOURCE, state='clarify')
        if app.ambiguous:
            return Answer('Welche Auralyn-Einstellung?',
                          'Nenne bitte eine Einstellung auf einmal, zum Beispiel Transparenz, Schrift oder Cursor.',
                          source=APP_SOURCE, state='clarify')
        if app.entry_id:
            return from_entry(ENTRIES[app.entry_id], source=APP_SOURCE)
        match = local_match(question)
        if match is not None and match.id.startswith('app.'):
            return from_entry(match, source=APP_SOURCE)
        if app.scoped:
            # A question about this app must never fall through to an unrelated
            # system action just because it contains "update" or "install".
            match = None
        domain = app.scoped or task.domain or match is not None or bool(tokens(question) & _DOMAIN)
        # With an opted-in local model, unfamiliar wording may still be a
        # terminal task. A missing keyword must not block the AI from deciding.
        if not domain and not ai_enabled:
            return rejected()
        if ai_enabled:
            try:
                if app.scoped:
                    ident = self.client.choose(question, model, cancel, scope='app')
                else:
                    ident = self.client.choose(question, model, cancel)
                if cancel.is_set():
                    raise Cancelled('Anfrage abgebrochen.')
                if ident in ('reject', 'clarify'):
                    if app.scoped:
                        return self._app_clarification()
                    # Uncovered != off topic. A model must not discard an
                    # already known correct answer or reject a relevant task.
                    if match:
                        return from_entry(match, note='Kein eindeutiger KI-Treffer. Stattdessen: Offline-Suche.')
                    if domain or ident == 'clarify':
                        return Answer('Welche Aufgabe genau?', task_clarification(task), state='clarify',
                                      source=f'Lokale KI · {model} · Rückfrage, kein Befehl')
                    return rejected()
                entry = ENTRIES.get(ident)
                if entry is None or (app.scoped and not entry.id.startswith('app.')):
                    raise AIError('Keine erlaubte Antwort ausgewählt.')
                if task.family == 'git' and not entry.id.startswith('git.'):
                    return Answer('Welche Git-Aufgabe?', task_clarification(task), state='clarify',
                                  note='Die KI-Zuordnung passt nicht zur erkannten Git-Frage; keine Aktion freigegeben.')
                return from_entry(entry, source=f'Lokale KI · {model} · geprüfter Katalog',
                                  note='Die KI kann die Absicht falsch zuordnen. Prüfe den angezeigten Befehl.')
            except Cancelled:
                raise
            except AIError as exc:
                note = str(exc)
                if app.scoped:
                    return self._app_clarification(note)
                if match:
                    return from_entry(match, note=note + ' Stattdessen: Offline-Suche.')
                return Answer('Lokale KI nicht verfügbar', 'Keine Aktion vorgeschlagen.',
                              source='Ollama · lokal', note=note, state='unavailable')
        if match:
            return from_entry(match)
        if app.scoped:
            return self._app_clarification()
        # In-domain but not covered/ambiguous: do not fabricate a command.
        return Answer('Welche Aufgabe genau?', task_clarification(task),
                      note='Passendes Terminal-Thema, aber noch keine eindeutige Lösung. '
                           'Lokale KI kann weitere Formulierungen erkennen; fehlende Angaben werden nicht geraten.',
                      state='clarify')


    @staticmethod
    def _app_clarification(note: str = '') -> Answer:
        return Answer('Auralyn-Programmhilfe',
                      'Dazu habe ich noch keinen eindeutigen Eintrag für diese Auralyn-Version. '
                      'Frage nach der konkreten Funktion, zum Beispiel Transparenz, Schrift, Tabs, Vorschlägen oder run/kill. '
                      'Ich erfinde keine Menüs.',
                      source=APP_SOURCE, note=note, state='clarify')


class SearchWorker:
    """One cancellable, latest-only background worker, independent of completions."""
    def __init__(self, deliver: Callable[[int, Answer], None], engine: SearchEngine | None = None, progress=None):
        self.engine = engine or SearchEngine()
        self.deliver = deliver
        self.progress = progress
        self._queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._closed = False
        self._serial = 0
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name='auralyn-smart-search')
        self._thread.start()

    def _replace(self, value):
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(value)

    def submit(self, serial: int, question: str, ai_enabled: bool, model: str, *, web_enabled=False, web_provider="duckduckgo"):
        with self._lock:
            if self._closed:
                return
            self._cancel.set()
            self.engine.cancel()
            self._cancel = threading.Event()
            self._serial = serial
            self._replace((serial, question, ai_enabled, model, self._cancel, web_enabled, web_provider))

    def cancel(self):
        with self._lock:
            self._cancel.set()
            self.engine.cancel()
            self._replace(None)

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
            self.engine.cancel()
            self._replace(None)

    def _run(self):
        while True:
            item = self._queue.get()
            if self._closed:
                return
            if item is None:
                continue
            serial, question, enabled, model, cancel, web_enabled, web_provider = item
            if cancel.is_set():
                continue
            stage = 'Aufgabe verstehen · lokales Modell' if enabled else 'Offline-Hilfe'
            try:
                if web_enabled:
                    def progress(text):
                        nonlocal stage
                        stage = text
                        if self.progress and not cancel.is_set() and not self._closed and serial == self._serial:
                            self.progress(serial, text)
                    result = self.engine.answer(question, enabled, model, cancel,
                                                web_enabled=True, web_provider=web_provider, progress=progress)
                else:
                    result = self.engine.answer(question, enabled, model, cancel)
            except Cancelled:
                continue
            except Exception as exc:
                if cancel.is_set() or self._closed:
                    continue
                diagnostic = record_failure(exc, stage=stage, web=web_enabled)
                result = Answer('Smart Search: technischer Fehler',
                                'Ein interner Fehler hat die Suche unterbrochen. Deine Frage wurde nicht abgelehnt. '
                                'Es wurde kein Befehl ausgeführt.',
                                source=('KI + Web · technischer Fehler, keine verifizierte Antwort' if enabled and web_enabled
                                        else 'Lokale KI · technischer Fehler' if enabled else 'Offline-Hilfe · technischer Fehler'),
                                note=diagnostic.summary + ' · ' + diagnostic.code,
                                state='unavailable', diagnostic=diagnostic.text)
            with self._lock:
                valid = not self._closed and not cancel.is_set() and serial == self._serial
            if valid:
                self.deliver(serial, result)
