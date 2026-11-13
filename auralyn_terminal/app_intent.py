"""Local, typo-tolerant routing for Auralyn's own documented features.

Only match a help ID. No network, shell, system changes or spelling changes to
actual commands. Product help has priority over optional probabilistic AI.
Unclear product queries remain in the product-help scope, not APT actions.
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
import re

from .app_knowledge import APP_HELP
from .search_text import normalize


_ALIASES = {
    'transparenz': 'transparency', 'transparents': 'transparency',
    'transperenz': 'transparency', 'transperanz': 'transparency',
    'transperents': 'transparency', 'transparens': 'transparency',
    'transparancy': 'transparency',
    'transparent': 'transparency', 'transparente': 'transparency',
    'transparenten': 'transparency', 'transparenter': 'transparency',
    'transperent': 'transparency', 'transperente': 'transparency',
    'transparenzregler': 'transparency', 'transparenzslider': 'transparency',
    'transparentheit': 'transparency', 'transperentheit': 'transparency',
    'durchsichtig': 'transparency', 'durchsichtiger': 'transparency',
    'durchsichtigkeit': 'transparency', 'undurchsichtig': 'transparency',
    'deckend': 'transparency', 'deckkraft': 'transparency', 'opacity': 'transparency',
    'glaseffekt': 'transparency', 'glass': 'transparency',
    'unscharf': 'blur', 'unscharfe': 'blur', 'verschwommen': 'blur',
    'verschwimmen': 'blur', 'weichzeichnen': 'blur',
    'einstellungen': 'settings', 'einstellung': 'settings', 'setting': 'settings',
    'einstelungen': 'settings', 'einstellugen': 'settings', 'settings': 'settings',
    'zahnrad': 'settings', 'zahnradsymbol': 'settings',
    'einstellen': 'adjust', 'einstelle': 'adjust', 'andern': 'adjust', 'andere': 'adjust',
    'verandern': 'adjust', 'verstelle': 'adjust', 'verstellen': 'adjust',
    'anpassen': 'adjust', 'change': 'adjust', 'adjust': 'adjust',
    'farbe': 'theme', 'farben': 'theme', 'colors': 'theme', 'colours': 'theme',
    'farbthema': 'theme', 'themes': 'theme', 'design': 'theme',
    'hintergrundbild': 'wallpaper', 'hintergrundbilder': 'wallpaper',
    'hintergrund': 'background', 'fenster': 'window',
    'schrift': 'font', 'schriftart': 'font', 'schriftgrosse': 'font',
    'schriftgroesse': 'font', 'schrifft': 'font', 'schriftgrosze': 'font',
    'buchstaben': 'font', 'textgrosse': 'font', 'font': 'font',
    'zoom': 'zoom', 'zoomen': 'zoom', 'zoome': 'zoom',
    'cursorform': 'cursor', 'eingabecursor': 'cursor', 'kursor': 'cursor',
    'blink': 'blink', 'blinking': 'blink', 'blinken': 'blink', 'blinkt': 'blink', 'blinkenden': 'blink',
    'vorschlag': 'suggestions', 'vorschlage': 'suggestions', 'vorschlagen': 'suggestions',
    'vorschlagsbox': 'suggestions', 'vorschlagsliste': 'suggestions', 'vorschlagsfenster': 'suggestions',
    'vorschlagszeilen': 'suggestions', 'befehlsbox': 'suggestions',
    'autovervollstandigung': 'suggestions', 'autocomplete': 'suggestions', 'suggestion': 'suggestions',
    'kurzhilfe': 'hhelp', 'h-hilfe': 'hhelp', 'erklarung': 'explanation', 'erklarungen': 'explanation',
    'erklart': 'explanation', 'erklaren': 'explain',
    'unterbefehl': 'subcommand', 'unterbefehle': 'subcommand', 'unterbefehlen': 'subcommand',
    'completion': 'completion', 'completions': 'completion',
    'tastenkurzel': 'shortcuts', 'tastenkombinationen': 'shortcuts', 'hotkeys': 'shortcuts',
    'shortcut': 'shortcuts', 'shortcuts': 'shortcuts',
    'tabs': 'tab', 'tabwechsel': 'tab_switch',
    'neuen': 'new', 'neuer': 'new', 'neue': 'new', 'neu': 'new',
    'wechsel': 'switch', 'wechseln': 'switch', 'wechsle': 'switch', 'wechselt': 'switch',
    'schliessen': 'close', 'schliesse': 'close', 'schliesst': 'close', 'close': 'close',
    'kopieren': 'copy', 'kopiere': 'copy', 'kopiert': 'copy', 'kopie': 'copy',
    'einfugen': 'paste', 'einfuge': 'paste', 'eingefugt': 'paste',
    'zwischenablage': 'clipboard', 'mehrzeilig': 'multiline', 'mehrzeilige': 'multiline',
    'bestatigen': 'confirm', 'bestatigung': 'confirm',
    'warnung': 'warning', 'zeilen': 'lines', 'zeile': 'lines',
    'starten': 'start', 'starte': 'start', 'startet': 'start',
    'offnen': 'open', 'offne': 'open', 'stoppen': 'stop', 'stoppe': 'stop',
    'beenden': 'stop', 'beende': 'stop', 'hangt': 'hang', 'killen': 'kill', 'kille': 'kill',
    'vordergrund': 'foreground', 'hintergrundstart': 'background_run',
    'interaktiv': 'interactive', 'interaktive': 'interactive', 'interaktiven': 'interactive',
    'ausgabe': 'output', 'logdatei': 'logs', 'logdateien': 'logs', 'log': 'logs',
    'programme': 'program', 'programmen': 'program', 'programm': 'program', 'programs': 'program',
    'anwendung': 'program', 'anwendungen': 'program', 'apps': 'app',
    'drittanbieter': 'thirdparty', 'aliasen': 'aliases', 'aliase': 'aliases', 'alias': 'aliases',
    'lupe': 'smart', 'suchmenu': 'smart', 'befehlssuche': 'smart',
    'suche': 'search', 'suchen': 'search', 'suchfeld': 'search',
    'suchanfrage': 'question', 'suchanfragen': 'question', 'fragen': 'question', 'frage': 'question',
    'ausfuhren': 'execute', 'ausfuhrt': 'execute', 'ausgefuhrt': 'execute',
    'modell': 'model', 'modelle': 'model', 'modellwahl': 'model',
    'ki': 'ai', 'kunstliche': 'ai',
    'aktiviere': 'enable', 'aktivieren': 'enable', 'einschalten': 'enable',
    'deaktivieren': 'disable', 'deaktiviere': 'disable', 'ausschalten': 'disable',
    'ausstellen': 'disable', 'ausblenden': 'disable', 'abschalten': 'disable',
    'speichern': 'save', 'speichere': 'save', 'gespeichert': 'stored',
    'neustart': 'restart', 'neustarten': 'restart',
    'konfiguration': 'config', 'konfigurationsdatei': 'config',
    'einstellungsdatei': 'config', 'konfigdatei': 'config',
    'datenschutz': 'privacy', 'privatsphare': 'privacy', 'dateien': 'files',
    'senden': 'send', 'schickt': 'send', 'schicken': 'send', 'liest': 'read',
    'zugriff': 'access', 'cloud': 'cloud', 'passwort': 'password', 'passworter': 'password',
    'ausgabepuffer': 'scrollback', 'zuruckscrollen': 'scrollback',
    'verlauf': 'history', 'befehlsverlauf': 'history', 'terminalverlauf': 'history',
    'alte': 'old', 'alten': 'old', 'alter': 'old',
    'aktualisieren': 'update', 'aktualisiere': 'update', 'updaten': 'update', 'updates': 'update',
    'versionsnummer': 'version', 'versionen': 'version',
    'befehl': 'command', 'befehle': 'command', 'befehlen': 'command', 'commands': 'command',
    'infosymbol': 'info', 'funktionen': 'features', 'funktion': 'feature',
    'zwei': '2', 'drei': '3', 'anzahl': 'count', 'anzahlige': 'count',
    'weniger': 'less', 'mehr': 'more', 'maximal': 'maximum',
    'unser': 'our', 'unsere': 'our', 'unserem': 'our', 'unseren': 'our', 'unserer': 'our',
}
_FILLER = set('wie was ich du er sie es der die das den dem des ein eine einen einer einem mein meine meinen '
              'meiner mir mich bitte mal denn man kann kannst konnte kannst du sollte soll mochte will '
              'fur von vom in im am an zu zur zum damit mit und oder eigentlich einfach gerne wohl '
              'jetzt hier dort da bei diesem dieses dieser diese dem the a an i my me how what do does '
              'can could please it this that is are ist sind habe hat gibt wozu warum wieso wohin'.split())
_FUZZY_WORDS = ('transparenz', 'transparency', 'einstellungen', 'vorschlage', 'vorschlagsbox',
                'schriftgrosse', 'schriftart', 'auralyn', 'autovervollstandigung')
_UI_WORDS = {'transparency', 'settings', 'font', 'cursor', 'blur', 'theme', 'wallpaper', 'zoom'}
_FOREIGN_UI = {'firefox', 'chrome', 'chromium', 'discord', 'roblox', 'ttd', 'photoshop',
               'gimp', 'windows', 'konsole', 'kitty', 'alacritty', 'gnome', 'kde', 'png',
               'blender', 'politik', 'demokratie', 'gesellschaft', 'physik', 'chemie'}


@lru_cache(maxsize=512)
def _word(word: str) -> str:
    if word in _ALIASES:
        return _ALIASES[word]
    # Conservative correction only for long product vocabulary with the same
    # first three letters, never arbitrary words or the real command line.
    if len(word) >= 6:
        possible = [w for w in _FUZZY_WORDS if w[:3] == word[:3] and abs(len(w) - len(word)) <= 2]
        best = get_close_matches(word, possible, n=1, cutoff=0.85)
        if best:
            return _ALIASES.get(best[0], best[0])
    return word


def app_tokens(question: str) -> set[str]:
    return {_word(word) for word in normalize(question).split() if word not in _FILLER}


_EXACT = {normalize(example): entry.id for entry in APP_HELP.values()
          for example in (entry.title, *entry.examples)}
_INDEX = {entry.id: [app_tokens(example) for example in (entry.title, *entry.examples)]
          for entry in APP_HELP.values()}


@dataclass(frozen=True)
class AppMatch:
    entry_id: str = ''
    scoped: bool = False
    foreign_ui: bool = False
    ambiguous: bool = False


def exact_app_entry(question: str):
    ident = _EXACT.get(normalize(question))
    return APP_HELP.get(ident)


def _sample_match(words: set[str]) -> str:
    ranked = []
    generic = {'auralyn', 'terminal', 'program', 'app', 'command', 'our', 'help', 'version'}
    for ident, samples in _INDEX.items():
        best = 0.0
        for sample in samples:
            shared = words & sample
            if not shared or not (shared - generic):
                continue
            # No one generic token should answer a long unrelated question.
            if len(shared) == 1 and len(words) > 3:
                continue
            best = max(best, 2 * len(shared) / (len(words) + len(sample)))
        if best >= 0.70:
            ranked.append((best, ident))
    ranked.sort(reverse=True)
    if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.10):
        return ranked[0][1]
    return ''


def match_app_question(question: str) -> AppMatch:
    exact = exact_app_entry(question)
    if exact:
        return AppMatch(exact.id, True)
    w = app_tokens(question)
    named = ('auralyn' in w or ('our' in w and bool(w & {'program', 'terminal', 'app'}))
             or bool(re.search(r'\b(?:diesem|dieses|diese|unser[a-z]*) (?:programm|terminal|app)\b',
                               normalize(question))))
    implicit = bool(w & (_UI_WORDS | {'suggestions', 'hhelp', 'shortcuts', 'scrollback', 'smart'}))
    scoped = named or implicit
    if w & _UI_WORDS and w & _FOREIGN_UI and not named:
        return AppMatch(scoped=True, foreign_ui=True)
    def hit(ident):
        return AppMatch('app.' + ident, True)

    # The dedicated terminal select-all shortcut has its own explanation.
    # Never change the actual Bash command input with this text normalizer.
    if re.search(r'\b(?:strg|ctrl|steuerung)(?: (?:umschalt|shift))? a\b', normalize(question)):
        return hit('select_all')
    if scoped and 'terminal' in w and w & {'alles', 'gesamte', 'gesamten'} and w & {'markieren', 'markiere', 'auswahlen', 'auswahl'}:
        return hit('select_all')

    # Product-specific update settings must win over generic save/password help.
    update_button = bool(w & {'update-button', 'updatebutton', 'pfeilkreis'}) or (
        'update' in w and bool(w & {'button', 'knopf', 'schaltflache'}))
    if (update_button and 'password' in w) or ('password' in w and
            bool(w & {'schlusselbund', 'keyring'})) or (
            'password' in w and 'save' in w and 'sudo' in w):
        return hit('update_password')
    if update_button and w & {'confirm', 'bestatigungen', 'bestatigt',
                              'paketfragen', 'ja', 'nein', 'yes', 'no', 'automatisch', 'auto'}:
        return hit('update_confirmation')
    if update_button:
        return hit('update_button')
    # More specific combinations have priority over their shared settings words.
    if ('privacy' in w or ('question' in w and w & {'stored', 'save', 'history', 'send'})
            or (w & {'ai', 'ollama', 'search'} and
                         w & {'files', 'history', 'send', 'read', 'access', 'cloud', 'password'})):
        return hit('privacy')
    if w & {'offline'} or ('ohne' in w and w & {'ai', 'ollama', 'model'}):
        return hit('offline')
    if w & {'ai', 'ollama', 'model'}:
        return hit('ai')
    if 'settings' in w and (('wo' in w and w & {'stored', 'save'}) or w & {'datei', 'file', 'pfad', 'path'}):
        return hit('config')
    if 'config' in w or ('settings' in w and 'json' in w):
        return hit('config')
    if w & {'save', 'stored'} and (scoped or 'restart' in w):
        return hit('save')
    if 'execute' in w and (w & {'smart', 'search', 'button', 'enter'}):
        return hit('execute')
    if 'blur' in w:
        return hit('blur')
    if 'wallpaper' in w or 'split' in w or ('window' in w and w & {'teilen', 'geteilte'}) or ('theme' in w and scoped):
        return hit('limits')
    if len(w & {'transparency', 'font', 'cursor'}) > 1:
        return AppMatch(scoped=True, ambiguous=True)
    if ('transparency' in w
            or ('background' in w and w & {'weg', 'unsichtbar', 'durchsehen'})
            or (w & {'terminal', 'window', 'background'} and w & {'heller', 'dunkler', 'sichtbarer'})
            or ('window' in w and w & {'durch', 'hindurch'} and w & {'sehen', 'schauen', 'gucken'})):
        return hit('transparency')
    if 'zoom' in w:
        return hit('zoom')
    if 'font' in w:
        return hit('font')
    if 'cursor' in w:
        return hit('cursor_blink' if 'blink' in w else 'cursor')
    if w & {'thirdparty', 'aliases'} or {'third', 'party'} <= w:
        return hit('third_party')
    if w & {'subcommand', 'completion'}:
        return hit('completions')
    if 'suggestions' in w or ('command' in w and w & {'2', '3', 'count'}):
        if w & {'count', '2', '3', 'lines', 'more', 'less', 'maximum'}:
            return hit('suggestion_rows')
        if w & {'enable', 'disable', 'aus', 'an', 'nicht', 'schalte', 'schalten'}:
            return hit('suggestion_toggle')
        return hit('suggestions')
    if 'hhelp' in w or ('h' in w and w & {'help', 'hilfe', 'drucke', 'drucken', 'explanation', 'explain', 'schreiben'}):
        return hit('help')
    if ('explanation' in w and w & {'englisch', 'english', 'quelle', 'herkunft', 'woher'}) or 'whatis' in w:
        return hit('help_sources')
    if 'shortcuts' in w:
        return hit('shortcuts')
    if 'tab' in w:
        if w & {'switch', 'tab_switch', 'zwischen', 'anderen', 'andere'}:
            return hit('tab_switch')
        if 'close' in w:
            return hit('tab_close')
        return hit('tabs')
    if 'close' in w and (named or 'window' in w or 'terminal' in w):
        return hit('tab_close')
    if w & {'copy', 'paste', 'clipboard'}:
        if w & {'multiline', 'lines', 'confirm', 'warning'}:
            return hit('paste')
        return hit('clipboard')
    if 'scrollback' in w:
        return hit('scrollback')
    if 'history' in w or ('command' in w and 'old' in w):
        return hit('history')
    if 'run' in w or ('program' in w and w & {'start', 'open'} and not ('auralyn' in w and 'start' in w)):
        if w & {'logs', 'output'}:
            return hit('run_logs')
        if w & {'foreground', 'interactive', 'htop', 'nano'}:
            return hit('foreground')
        return hit('run')
    if 'kill' in w or ('program' in w and w & {'stop', 'hang'}) or {'force', 'stop'} <= w:
        if w & {'pid', 'java', 'python', 'nummer', 'gezielt'}:
            return hit('kill_pid')
        return hit('kill')
    if 'password' in w and (w & {'sudo', 'terminal', 'root'} or named):
        return hit('password')
    if 'sudo' in w and not w & {'apt', 'install', 'update', 'upgrade'}:
        return hit('sudo')
    if w & {'ssh', 'zsh', 'fish'} or ('shell' in w and (named or 'bash' in w or 'root' in w)):
        return hit('shell')
    if 'update' in w and named:
        return hit('update')
    if ('version' in w and named) or 'info' in w or ('i' in w and w & {'oben', 'symbol', 'button'}):
        return hit('version')
    if named and ('start' in w or 'startparameter' in w):
        return hit('start')
    if ('smart' in w or ('search' in w and (named or 'lupe' in w))):
        return hit('smart')
    if 'settings' in w:
        return hit('settings')
    if named and (w & {'features', 'feature', 'help', 'hilfe', 'kannst', 'konnen'} or w <= {'auralyn', 'terminal', 'about'}):
        return hit('overview')
    sample = _sample_match(w)
    if sample:
        return AppMatch(sample, True)
    return AppMatch(scoped=scoped)
