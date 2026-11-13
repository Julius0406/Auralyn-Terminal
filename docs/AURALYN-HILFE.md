# Auralyn-Programmhilfe v1.0.0 Stable

## Faceman-Kommandos

`face`, `gondelface` und `luiswiththegondelface` schreiben alle fortlaufend
„Faceman is here“. Du kannst sie mit **Strg+C** jederzeit stoppen. Die
Ausgabe wird leicht gebremst, damit das Terminal nicht einfriert. Die Befehle
erscheinen als Auralyn-Bash-Funktionen in den Live-Vorschlägen (H für Hilfe).
Sie werden nicht in dein normales Ubuntu-Terminal oder `~/.bashrc` installiert.

## Systemupdate-Button

Pfeilkreis links neben der Lupe → neuer Update-Tab: sudo apt update → sudo apt full-upgrade -y → flatpak update --assumeyes. Paketfragen werden standardmäßig automatisch bestätigt, auch mögliche Paketentfernungen durch full-upgrade. Abschalten: Zahnrad → Update-Button → Optionen & Passwort… → Paketfragen automatisch bestätigen. Konfigurations-/Berechtigungsfragen können bleiben. Bei Fehlern wird angehalten, fehlendes Flatpak übersprungen. sudo -K löscht am Schluss und bei behandelten Abbrüchen die sudo-Anmeldung. Danach normale Benutzer-Bash, keine Root-Shell.

## Paketfragen automatisch bestätigen

Zahnrad → „Update-Button“ → „Optionen & Passwort…“ → „Paketfragen automatisch bestätigen“. Standard: eingeschaltet, auch nach einem Programmupdate. APT full-upgrade verwendet -y und flatpak update --assumeyes; Ja/Nein und Yes/No hängen dadurch nicht von der Sprache ab. Gilt nur für den nächsten Button-Start, nicht für laufende Updates, eigene Befehle oder Smart Search. Ausgeschaltet wird wieder gefragt. full-upgrade kann auch Pakete entfernen. Konfigurationsfragen und separate Berechtigungsabfragen bleiben möglich; kein automatischer Neustart. Das sudo-Passwort und das Löschen der sudo-Anmeldung bleiben getrennt davon.

## Passwort nur für den Update-Button

Zahnrad → „Update-Button“ → „Optionen & Passwort…“. Gib dein Linux-/sudo-Passwort ein und wähle „Im Schlüsselbund speichern“. Der Schalter „Passwort für Update-Button verwenden“ aktiviert die Übernahme nur für dessen zwei sudo-Aufrufe. Eigene Befehle und die KI erhalten es nicht. Nach dem Ablauf löscht sudo -K die sudo-Zwischenspeicher. „Gespeichertes Passwort löschen“ entfernt den Eintrag. Kein Klartext in settings.json, keine NOPASSWD-Regel. Ein gesperrter Schlüsselbund kann nachfragen; nur im vertrauenswürdigen Benutzerkonto verwenden.

## Web-Recherche einschalten

Lupe → „Lokale KI…“ → „Web-Recherche erlauben“. Die lokale KI muss ebenfalls aktiviert sein. Dann sucht Auralyn zuerst nach Online-Dokumentation und prüft danach den lokalen Suchpfad. Standardanbieter: DuckDuckGo ohne Schlüssel, mit direkter Online-Doku als Rückfall. Für Ollama Web Search ist ein separater API-Schlüssel nötig. Ohne Freigabe bleibt die Recherche rein lokal.

## Webprüfung und Installationsvorschläge

Im Ergebnis stehen „1/2 Web“ und „2/2 Lokal“ sowie die tatsächlich abgerufenen Quellen. Fehlt ein Befehl, recherchiert Auralyn eine Installationsquelle und prüft vorgeschlagene APT-Pakete lokal. Neue Installationsbefehle sind nur kopierbar, nie automatisch ausführbar. Danach „Nach Installation erneut prüfen“. Fehlende Webquellen oder Modellfehler werden nicht als Beweis ausgegeben, dass es keinen Befehl gibt. Bei internen Fehlern zeigt „Fehlerdetails kopieren“ Version, Prüfschritt und Codefehler; keine Suchfrage, Modelltexte oder Schlüssel. Der technische Bericht bleibt lokal.

## Auralyn Terminal – Programmhilfe

Auralyn ist ein echtes Bash-Terminal mit Tabs, einstellbarer Transparenz, kleinen Live-Vorschlägen, H-Kurzhilfe, run/kill, Smart Search und einem separaten Systemupdate-Button. Frage nach einer Funktion, zum Beispiel „Wie stelle ich die Transparenz ein?“.

## Transparenz einstellen

Klicke oben auf das Zahnrad → „Hintergrund-Transparenz“ und verschiebe den Regler. 0 % = undurchsichtig, 100 % = Hintergrund unsichtbar. Standard: 75 %. Schrift und Cursor bleiben sichtbar; die Änderung wird automatisch gespeichert.

## Transparenz und Unschärfe

Auralyn kann den Hintergrund durchsichtig machen, erzeugt aber selbst keinen Blur-/Unschärfeeffekt. Dafür gibt es keinen Schalter. Das Zahnrad enthält nur den Transparenzregler; es wird keine GNOME-Erweiterung installiert.

## Terminal-Einstellungen öffnen

Klicke oben auf das Zahnrad oder drücke Strg+,. Dort findest du Hintergrund-Transparenz, Terminal-Schrift, Live-Befehlsvorschläge, 2–3 sichtbare Vorschläge, Bash-Completions, Cursor-Blinken, Cursor-Form sowie „Update-Button → Optionen & Passwort…“.

## Einstellungen speichern

Änderungen im Zahnrad-Menü werden sofort angewendet und automatisch gespeichert. Für normale Einstellungen brauchst du keinen Speichern-Button; „Fertig“ schließt das Fenster. Die gespeicherten Werte werden beim nächsten Start wieder geladen. Ausnahme: Das optionale Update-Passwort wird erst durch „Im Schlüsselbund speichern“ hinterlegt.

## Schriftart und Schriftgröße ändern

Zahnrad → „Terminal-Schrift“. Wähle dort Schriftart und Größe. Standard: Monospace 13. Das wird gespeichert. Nur vorübergehend im aktuellen Tab vergrößern: Strg++; verkleinern: Strg+−; Zoom zurücksetzen: Strg+0.

## Terminal-Zoom

Strg++ vergrößert die Schrift im aktuellen Tab, Strg+− verkleinert sie und Strg+0 setzt den Zoom zurück. Für eine dauerhaft gespeicherte Schriftgröße: Zahnrad → „Terminal-Schrift“.

## Cursor-Form ändern

Zahnrad → „Cursor-Form“. Du kannst Block, Strich oder Unterstrich auswählen. Die Form wird direkt übernommen und gespeichert.

## Cursor-Blinken einstellen

Zahnrad → „Cursor blinkt“. Schalte den Schalter aus für einen unbewegten Cursor oder an für Blinken. Die Einstellung wird gespeichert.

## Kleine Befehlsvorschläge

Tippe einen Befehlsanfang: s zeigt passende Namen, sud filtert weiter. Tab markiert und wechselt, Umschalt+Tab geht zurück. Enter oder Pfeil rechts setzt die Auswahl ein; erst ein weiteres Enter führt sie aus. Höchstens 2–3 Treffer sind gleichzeitig sichtbar.

## Befehlsvorschläge an- und ausschalten

Zahnrad → „Live-Befehlsvorschläge“. Dort schaltest du die kleine Vorschlagsbox an oder aus. Esc blendet nur die aktuelle Box aus; Strg+Leertaste fragt die Vorschläge erneut ab.

## Anzahl sichtbarer Vorschläge

Zahnrad → „Sichtbare Vorschläge“. Wähle 2 oder 3 Zeilen; Standard: 3. Mit Tab erreichst du auch die weiteren Treffer. Mehr als drei gleichzeitig sichtbare Einträge sind in dieser Version nicht vorgesehen.

## Unterbefehle und Bash-Completions

Zahnrad → „Installierte Bash-Completions nutzen“. Auralyn nutzt vorhandene Completion-Dateien für Unterbefehle und Optionen, etwa sudo apt i → install. Eine CLI ohne solche Definitionen hat nicht automatisch Vorschläge für alle Unterbefehle.

## Drittanbieterprogramme erkennen

Befehlsnamen kommen aus deinem PATH sowie lokalen Bash-Aliasen und -Funktionen. run berücksichtigt zusätzlich App-Menü-Einträge. Für fremde Unterbefehle helfen installierte Bash-Completions; unbekannte Möglichkeiten werden nicht erfunden.

## H-Kurzhilfe

Markiere einen Vorschlag mit Tab und drücke H für eine kurze Erklärung. Tab wechselt samt Erklärung zum nächsten Eintrag. H oder Esc schließt die Erklärung. Ohne Auswahl schreibt h ganz normal einen Buchstaben.

## Woher die Befehlserklärungen kommen

H nutzt eingebaute deutsche Kurztexte und, falls vorhanden, lokale Handbuchbeschreibungen (whatis). Diese können Englisch sein. Ohne Beschreibung wird das angezeigt. Der ausgewählte Befehl wird zum Erklären nicht gestartet.

## Terminal-Tabs verwenden

Oben links auf das Tab-Plus klicken oder Strg+Umschalt+T drücken öffnet einen neuen Tab. Strg+Bild auf/ab wechselt zwischen Tabs; Strg+Umschalt+W schließt den aktuellen Tab. Jeder Tab hat eine eigene Shell.

## Zwischen Tabs wechseln

Klicke auf den gewünschten Tab oder drücke Strg+Bild auf beziehungsweise Strg+Bild ab. Alt+1 bis Alt+9 wählt einen der ersten neun Tabs direkt.

## Tab oder Fenster schließen

Das X am Tab oder Strg+Umschalt+W schließt den aktuellen Tab. Das X am Fenster schließt Auralyn. Bei erkannten laufenden Vordergrundprogrammen fragt Auralyn vorher nach. Sichere deine Arbeit zuerst; das Schließen ersetzt nicht das Speichern im Programm.

## Alles markieren mit Strg+Umschalt+A

Drücke Strg+Umschalt+A im aktiven Auralyn-Terminal-Tab, um den Terminaltext einschließlich vorhandener Scrollback-Ausgabe zu markieren. Strg+Umschalt+C kopiert die Auswahl. Alternativ: Rechtsklick → „Alles markieren (Strg+Umschalt+A)“. Es wird kein Befehl gestartet oder Text automatisch kopiert. Strg+A geht im Terminal wieder zum Anfang der Bash-Eingabezeile; auch Home funktioniert. In Eingabefeldern von Einstellungen und Smart Search bleibt Strg+A das normale Alles-markieren des jeweiligen Felds.

## Kopieren und Einfügen

Strg+Umschalt+A markiert den gesamten Terminaltext einschließlich Scrollback. Strg+Umschalt+C kopiert die Auswahl und Strg+Umschalt+V fügt direkt aus der Zwischenablage ein – auch mehrere Zeilen ohne Bestätigungsdialog. Alternativ gibt es Rechtsklick → „Kopieren (Strg+Umschalt+C)“ oder „Einfügen (Strg+Umschalt+V)“. Strg+A bewegt den Bash-Cursor zum Zeilenanfang. Strg+C ohne Umschalt kann laufende Befehle abbrechen. Prüfe kopierte Mehrzeilen-Befehle vor dem Einfügen.

## Mehrere Zeilen ohne Nachfrage einfügen

Mit Strg+Umschalt+V oder Rechtsklick → „Einfügen (Strg+Umschalt+V)“ fügt Auralyn auch mehrere Zeilen sofort ein, ohne die bisherige Warnung „Mehrere Zeilen einfügen?“ anzuzeigen. Zeilenumbrüche innerhalb des Texts bleiben erhalten; abschließende Leerzeilen werden entfernt. VTE nutzt Bracketed Paste, wenn das laufende Programm diesen Modus unterstützt. In anderen Shells/Programmen können Zeilenumbrüche Befehle auslösen: vor dem Einfügen prüfen.

## Programm starten

Tippe run und ein Leerzeichen; Tab wählt einen Programmnamen. Enter setzt ihn ein, ein weiteres Enter startet ihn im Hintergrund. Erkannt werden PATH-Programme und App-Menü-Einträge. Für interaktive Terminalprogramme: run --foreground NAME.

## Interaktive Programme mit run

Nutze run --foreground NAME, zum Beispiel run --foreground htop, damit Tastatur und Ausgabe im Terminal bleiben. Direkt htop einzugeben geht ebenfalls. Ohne --foreground startet run standardmäßig im Hintergrund.

## Ausgabe von run finden

Bei einem Hintergrundstart schreibt run die Programmausgabe in eine private Logdatei und zeigt ihren Pfad im Terminal an. App-Menü-Starts über GIO können keine eigene Logdatei liefern. Für direkt sichtbare Terminal-Ausgabe: run --foreground NAME.

## Programm sofort beenden

Tippe kill und ein Leerzeichen. Tab wählt einen eigenen laufenden Prozess. kill NAME beendet ihn sofort, ohne Speichern-Dialog. Ungespeicherte Daten können verloren gehen; mehrere Prozesse derselben App können betroffen sein.

## Gezielt beenden und normale kill-Aufrufe

Bei Java/Python und mehrdeutigen Namen wählst du den passenden Eintrag mit Prozessnummer. Es wird nicht blind geraten. kill PID, kill -9 PID und kill %1 behalten die normale Bash-Semantik; die neue Namensfunktion ist für eigene Prozesse ohne sudo gedacht.

## Smart Search

Die Lupe links neben dem Info-Symbol oder Strg+Umschalt+F öffnet Smart Search. Frage nach Auralyn oder Linux-Befehlen. Enter sucht nur. Auralyn-Bedienfragen nutzen die Programmhilfe. Bei aktivierter KI werden Terminalaufgaben zuerst vom Modell untersucht: Befehle ermitteln, mit Webfreigabe zuerst Online-Doku suchen, dann Verfügbarkeit und lokale Handbücher abgleichen und antworten. Ohne KI gibt es feste Offline-Hilfe. Unklare Aufgaben bekommen eine Rückfrage; fachfremde Fragen werden abgelehnt.

## Ausführen in Smart Search

Nur der Klick auf „Ausführen“ startet den angezeigten geprüften Befehl in einem neuen Tab. Dein bisheriger Tab bleibt unberührt. Paketänderungen benötigen vorher eine Bestätigung; sudo und APT fragen danach normal nach. Programmhilfe öffnet stattdessen bei Bedarf die Einstellungen. Befehlsvorlagen sind nur kopierbar, nicht ausführbar; Platzhalter zuerst ersetzen.

## Lokale KI einrichten

Lupe → „Lokale KI…“. Ollama muss separat laufen und ein lokales Modell bereits installiert sein. „Modelle finden“ → Modell auswählen → „Übernehmen“; danach die lokale KI aktivieren. Auralyn lädt keine Modelle automatisch herunter. Die Programmhilfe braucht kein Modell.

## Offline-Hilfe und lokale KI

Die eingebaute Programm- und Befehlshilfe funktioniert ohne KI-Modell. Sie ist regelbasiert, keine KI. Mit aktivierter KI wird für Terminalaufgaben zuerst die echte Befehlsrecherche aufgerufen, statt direkt eine feste Antwort auszuwählen. Eindeutige Auralyn-Bedienfragen bleiben lokal. Ein echter Offline-Rückfall wird so bezeichnet. Im Webmodus zeigen Verbindungs- oder interne Fehler stattdessen den fehlgeschlagenen KI-/Webschritt; sie werden nicht als Offline-Antwort ausgegeben.

## Smart Search und Datenschutz

Bekannte Auralyn-Fragen bleiben lokal. Die Suchfrage und passende Befehls-/Handbuchdaten gehen nur an Ollama auf 127.0.0.1:11434. Kein Terminalverlauf, keine privaten Dateien oder Passwortfelder. Mit Webfreigabe gehen zusätzlich generische Suchbegriffe an den Anbieter; Webseiten sehen deine IP und den Abruf. Ohne Webfreigabe keine Internetrecherche. Web-Schlüssel liegen getrennt in einer Datei mit Modus 600, nie im Modellprompt. Schreibe keine Geheimnisse in die Suche.

## sudo im Terminal

Auralyn startet deine echte Bash; sudo funktioniert dort mit den normalen Ubuntu-Berechtigungen. Starte Auralyn selbst nicht mit sudo. Nur der gewünschte Befehl erhält Administratorrechte, nachdem sudo ihn erlaubt; Auralyn umgeht keine Passwortabfrage.

## Passwortabfrage im Terminal

Bei sudo wird die Passworteingabe normalerweise nicht sichtbar angezeigt, auch nicht als Sternchen. Tippe dein Passwort und drücke Enter. Live-Vorschläge werden während solcher Programme nicht eingeblendet. Normale Terminaleingaben werden nicht als Update-Passwort gespeichert. Nur für den separaten Update-Button kannst du es ausdrücklich im Schlüsselbund hinterlegen: Zahnrad → Update-Button → Optionen & Passwort….

## Bash, SSH und andere Shells

Die Live-Vorschläge gehören zur lokalen, von Auralyn gestarteten Bash. In SSH, Root-Shells, zsh/fish oder laufenden Editoren bleibt die normale Bedienung des jeweiligen Programms erhalten; dort erscheint nicht automatisch die Auralyn-Vorschlagsbox.

## Einstellungsdatei

Standardpfad: ~/.config/auralyn-terminal/settings.json. Bei gesetztem XDG_CONFIG_HOME liegt sie dort im Unterordner auralyn-terminal. Das Zahnrad speichert automatisch, die Fenstergröße wird beim Schließen gemerkt. Für manuelle Änderungen Auralyn zuerst schließen; eine offene Instanz kann die Datei sonst wieder überschreiben.

## Zurückscrollen und Ausgabepuffer

Auralyn hält standardmäßig 10000 Ausgabezeilen zum Zurückscrollen im Tab vor. Für die Größe gibt es noch keinen Regler im Zahnrad-Menü; der Schlüssel scrollback in settings.json erlaubt 1.000–100.000. Das ist nicht dasselbe wie der Befehlsverlauf deiner Bash.

## Befehlsverlauf

Auralyn verwendet den normalen Verlauf deiner Bash. Pfeil hoch/ab blättert an der Eingabezeile durch frühere Befehle, Strg+R sucht darin. Wie Bash den Verlauf speichert, hängt von deiner Bash-Konfiguration ab; Smart Search speichert keinen eigenen Fragenverlauf.

## Auralyn-Version anzeigen

Diese Hilfe gehört zu Auralyn Terminal v1.0.0 Stable. Das Info-Symbol oben öffnet „Über Auralyn“ mit der installierten Version. Im Terminal zeigt auralyn-terminal --version ebenfalls die Version.

## Auralyn selbst aktualisieren

Sichere deine Arbeit, schließe die Auralyn-Fenster und installiere die neue Auralyn-.deb mit sudo apt install ./DATEINAME.deb im Downloadordner. Ersetze DATEINAME durch den echten Paketnamen. Einstellungen bleiben erhalten. Auralyn hat noch keinen eingebauten Update-Checker.

## Auralyn starten

Öffne Auralyn Terminal im App-Menü oder mit auralyn-terminal. --working-directory ORDNER startet in einem bestimmten vorhandenen Ordner; --no-suggestions startet diesmal ohne Live-Vorschläge. Dein bisheriges Ubuntu-Terminal bleibt installiert.

## Wichtige Tastenkürzel

Strg+, = Einstellungen · Strg+Umschalt+F = Smart Search · Strg+Umschalt+T/W = Tab öffnen/schließen · Strg+Bild auf/ab = Tab wechseln · Strg+Umschalt+A = alles markieren · Strg+A = Zeilenanfang · Strg+Umschalt+C/V = kopieren/einfügen · Tab = Vorschlag markieren · H = dessen Hilfe · Strg+Leertaste = Vorschläge neu laden.

## Noch nicht eingebaute Funktionen

Diese Version bietet Tabs, aber keinen Split-Screen, keinen Theme-/Farb-Editor und keinen eigenen Hintergrundbild- oder Blur-Schalter. Das Zahnrad zeigt die tatsächlich vorhandenen Einstellungen. Ich erfinde dafür keine zusätzlichen Menüs.
