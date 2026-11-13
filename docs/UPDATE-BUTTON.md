# Update-Button · v1.0.0 Stable

## Bedienung und Umfang

Pfeilkreis links neben der Lupe → neuer Tab → `sudo apt update`, danach
`sudo apt full-upgrade -y`, danach `flatpak update --assumeyes`. Jeder Schritt muss
erfolgreich enden, bevor der nächste beginnt. Flatpak fehlt: ausdrücklicher
Hinweis und Überspringen, keine automatische Installation.

Der neue Schalter **„Paketfragen automatisch bestätigen“** ist standardmäßig
aktiv, auch bei bisherigen Einstellungen ohne diesen Eintrag. Er steht unter
**Zahnrad → Update-Button → Optionen & Passwort…**. APT und Flatpak verwenden
in diesem Ablauf ihre dokumentierten Ja-Optionen. Es gibt keine Suche nach
Prompt-Text, kein `yes | ...`, kein Einfügen von J/Y ins VTE und keine globale
APT- oder Umgebungsänderung. Die angezeigte Befehlsvorschau zeigt den gewählten
Modus. Ausschalten entfernt die Ja-Optionen beim nächsten Button-Start; bereits
laufende Prozesse, normale Shellbefehle und Smart Search bleiben unverändert.

**`full-upgrade` kann auch Pakete entfernen; die normale Paketbestätigung dafür
ist im Auto-Ja-Modus ebenfalls beantwortet.** Sonderfragen von dpkg/debconf,
Konfigurationsdatei-Konflikte, Schlüsselbund- und Polkit-Abfragen können trotzdem
eine manuelle Entscheidung erfordern. Es gibt weder `--force-yes` noch
`--allow-unauthenticated`, `--allow-downgrades`, `--allow-remove-essential`,
`--allow-change-held-packages`, globale `DEBIAN_FRONTEND`-Änderungen oder
`Dpkg::Options::=--force-conf...`. Die Standardschutzfunktionen werden nicht
abgeschaltet; APT kann bei problematischen Änderungen weiterhin abbrechen.
Kein automatischer Neustart, Entfernen von Sperrdateien oder Distributionswechsel.
Ein Fehler hält den Ablauf an, ohne eine Wiederholung mit stärkeren Flags.
Flatpak läuft bewusst als normaler Benutzer, nicht als root.

Der GUI-Button startet nicht in einer vorhandenen Shell/SSH-/Editor-Sitzung,
sondern in einem eigenen VTE-Pseudoterminal. Ein Benutzer kann nur einen solchen
Ablauf gleichzeitig starten; eine Dateisperre deckt weitere Auralyn-Fenster ab.
Die Sperrdatei ist leer und enthält nie ein Geheimnis.

Zahnrad → Update-Button → Optionen & Passwort… → verdecktes Feld →
„Im Schlüsselbund speichern“. Dieser Klick aktiviert die Übernahme. Der Schalter
kann sie jederzeit abschalten, ohne den Eintrag zu löschen. „Gespeichertes Passwort
löschen“ deaktiviert die Funktion sofort und versucht nur den passenden
Schlüsselbund-Eintrag zu entfernen. Kann ein gesperrter Eintrag nicht gelöscht
werden, wird der Fehler gezeigt, nicht Erfolg behauptet.

Bei einer Deinstallation bleibt der persönliche Schlüsselbund getrennt vom
Programmpaket. Zum vollständigen Entfernen des Geheimnisses vorab den
Löschen-Button benutzen oder den Eintrag „Auralyn Terminal · Passwort für den
Update-Button“ im Programm „Passwörter und Schlüssel“ entfernen.

## Passwortpfad

1. Das Feld wird vor dem Hintergrund-Speichern geleert. Es gibt kein
   vorausgefülltes oder sichtbares Passwort beim späteren Öffnen des Dialogs.
2. `update_secrets.py` nutzt ausdrücklich `Secret.Service`, nicht ein generisches
   Backend mit einem möglichen Dateispeicher als Rückfall. Gespeichert wird der
   `Secret.Value` mit Inhaltstyp `text/plain` über D-Bus in der Standard-Collection.
   Nur UID/Host/Zweck werden unverschlüsselte Suchattribute; nie das Passwort.
3. Die Updater-Einstellungen enthalten nur die booleschen Werte
   `update_use_keyring` und `update_auto_confirm`, keine Passwortkopie. Beim Öffnen der Einstellungen werden
   nur Metadaten abgefragt, nicht der Passwortinhalt.
4. Nur der neue Update-Prozess lädt bei eingeschalteter Option den Eintrag. Er
   erzeugt einen kurzlebigen Unix-Socket: Verzeichnis 0700, Socket 0600. Ein
   `SO_PEERCRED`-Abgleich und PPid-Prüfung erlauben den direkten Askpass-Kindprozess
   des gerade aktivierten sudo-Prozesses, einmal je APT-Befehl. Ein direkter
   Aufruf des Helfers erhält keinen Schlüsselbund-Zugriff.
5. Der Helper schreibt das Passwort ausschließlich in sudos Askpass-Ausgabepipe.
   Weder Passwort noch `echo PASSWORD | sudo` werden ins Terminal eingetippt.
   Argumente/Environment enthalten lediglich Helperpfad und Socketmetadaten,
   keine Passwortdaten. Der Helper nimmt keine beliebigen auszuführenden
   Befehle entgegen.
6. Bereits vor Flatpak werden Socket und Passwortbroker geschlossen. Veränderbare
   Passwortpuffer werden überschrieben. Die Anmeldung wird danach und im
   abschließenden Fehler-/Abbruchpfad mit `sudo -K` zurückgesetzt.

Es wird **keine** Root-Shell gestartet, kein sudoers-Eintrag installiert und
kein zusätzlicher Update-Ablauf durch ein Installationsskript dieser `.deb` ausgeführt.
APT darf beim Installieren der `.deb` natürlich deren benötigte Abhängigkeiten installieren.

## Grenzen und ehrliche Sicherheitsannahmen

Dies ist Komfortspeicherung eines echten Kontopassworts, keine neue
Berechtigungsart. Ein entsperrter Desktop-Schlüsselbund sowie Prozesse desselben
Benutzers sind keine harte Grenze gegen bereits ausgeführten Schadcode. Das
Passwort kann kurz in Python-/GTK-Arbeitsspeicher liegen; unveränderliche
Python-Zeichenketten lassen sich nicht garantiert aus dem Speicher löschen.
Auralyn kontrolliert nicht die Verschlüsselungseinstellungen eines vom Nutzer
selbst veränderten Schlüsselbunds. Niemals ein Root-Passwort in ein fremdes oder
nicht vertrauenswürdiges Benutzerkonto speichern.

Die App verwendet den gespeicherten Eintrag nur für ihren festen Update-Ablauf.
Das ist keine kryptografische Garantie, dass kein anderes Programm des Benutzers
den entsperrten Schlüsselbund lesen kann. Normale Shell-/Smart-Search-Befehle
bekommen keine automatische Übergabe durch Auralyn.

Ein gesperrter Schlüsselbund kann ein eigenes Entsperrfenster anzeigen. Flatpaks
Polkit-Regeln bleiben erhalten; Auralyn setzt das gespeicherte sudo-Passwort dort
nicht ein. Ein fehlendes/ungültiges Passwort stoppt die APT-Schritte, ohne
unbegrenzt neu zu versuchen. Keine Authentifizierungsregeln werden abgeschaltet.

`sudo -K` entfernt alle sudo-Authentifizierungszeitstempel des Benutzers, auch
solche anderer Terminals. Das beeinflusst dort die nächste Passwortabfrage,
beendet aber keine bereits laufenden Root-Prozesse. Bestehende NOPASSWD-/andere
Systemrichtlinien bleiben gültig; die App erzwingt keine neue globale Passwortregel.

Der Wrapper behandelt Strg+C, SIGHUP und SIGTERM und räumt nach Rückkehr der
Kindprozesse auf. SIGKILL, Stromausfall, Kernelabsturz oder gezielt manipulierte
sudo-Konfigurationen können nicht mit einer garantiert ausgeführten
Abschlussfunktion beantwortet werden. Die APT-Aufrufe benutzen zusätzlich
`sudo -k`, um vorhandene Zeitstempel nicht zu übernehmen und beim getesteten
GNU sudo keinen wiederverwendbaren Zeitstempel zu erzeugen. Auf der tatsächlichen
Ubuntu-sudo-rs-Version wurde das hier nicht live geprüft.

## Abhängigkeiten und Diagnose

Das Paket benötigt `gir1.2-secret-1`; ein Secret-Service wie GNOME Keyring muss
in der eigenen D-Bus-Benutzersitzung laufen. Bei fehlendem Dienst gibt es keinen
Klartext-Rückfall. Ohne gespeicherten Eintrag kann man die Funktion abschalten
und normale sudo-Passworteingabe im Update-Tab verwenden. Unterstützt das lokale
sudo kein `--askpass`, wird die Speicherung im Ablauf nicht benutzt und ein
Hinweis zum Abschalten angezeigt; Auralyn verändert die installierte sudo-Version
nicht eigenständig.

Die sichtbaren Befehle sind die vom Nutzer gewünschten drei Schritte; intern
werden nur feste Programme in Systempfaden und feste Parameter aufgerufen, für
APT ergänzt um `sudo -k -A --` im gespeicherten Modus. Lokale Aliase, PATH-
Skripte, fremde `APT_CONFIG`, `SUDO_ASKPASS` oder BASH_ENV werden nicht übernommen.

Nach erfolgreicher Bereinigung meldet der Tab:

> sudo-Anmeldung gelöscht · normale Passwortabfrage wieder aktiv

Wenn das Löschen scheitert, erscheint eine deutliche Warnung mit `sudo -K`;
der Vorgang wird nicht als erfolgreich gewertet. Der folgende Tab ist eine
gewöhnliche Benutzer-Bash, nie eine beibehaltene Root-Shell.

Tests, Reproduktionsskript und genaue Einschränkungen: [Testbericht](../TESTBERICHT.md).
Primärdokumentation: [Quellen](QUELLEN.md).
