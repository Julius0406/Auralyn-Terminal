"""Reviewed guides for everyday terminal tasks, including GitHub downloads.

Templates are educational text, never executable actions. Missing URLs, package
names and paths are not filled in by an LLM. Sources: docs/QUELLEN.md.
"""
from .search_entry import Entry

TERMINAL_ENTRIES = (
    Entry('git.clone', 'Projekt von GitHub herunterladen',
          'Mit git clone lädst du ein Git-Projekt samt Versionsverlauf in einen neuen Ordner. '
          'Kopiere auf der Projektseite unter „Code → HTTPS“ den Repository-Link und ersetze REPOSITORY_URL. '
          'Das lädt Quellcode herunter, installiert oder startet die App aber nicht.',
          ('Wie kann ich Sachen von GitHub runterladen?', 'Wie lade ich etwas von Github herunter?',
           'Git Repository klonen', 'Repo runterladen', 'gitclone', 'git clone',
           'Download a project from GitHub', 'Quellcode von GitLab herunterladen'),
          warning='Vorlage: erst den echten Repository-Link einsetzen. Kein sudo nötig. '
                  'Für eine fertige App suche nach dem Release statt nach Quellcode.',
          preview='git clone REPOSITORY_URL'),
    Entry('git.release', 'Fertige App aus einem GitHub-Release laden',
          'Für eine fertige App öffne beim Projekt „Releases → Assets“ und wähle die passende Linux-Datei '
          '(zum Beispiel .deb oder .AppImage). „Source code“ ist nur Quellcode. '
          'Für einen Terminal-Download brauchst du den direkten Link zur gewünschten Datei; '
          'ersetze DOWNLOAD_URL und DATEINAME in der Vorlage.',
          ('Fertiges Programm von GitHub herunterladen', 'GitHub Release runterladen',
           'GitHub App statt Quellcode downloaden', 'Download release assets from GitHub'),
          warning='Nur herunterladen; nichts automatisch installieren oder ausführen. '
                  'Die passende Datei und Version müssen zum Projekt und zu deinem System passen.',
          preview='curl -fL --output DATEINAME -- DOWNLOAD_URL'),
    Entry('git.zip', 'GitHub-Quellcode als ZIP herunterladen',
          'Ohne Git: Projektseite → „Code → Download ZIP“. Für das Terminal kopiere den ZIP-Download-Link '
          'und ersetze ZIP_URL sowie ARCHIV.zip. Ein ZIP-Snapshot enthält keinen Git-Versionsverlauf.',
          ('GitHub als ZIP runterladen', 'Repository ohne git herunterladen', 'GitHub Download ZIP',
           'Download source archive from GitHub'),
          warning='Vorlage mit Platzhaltern. Das Archiv wird nicht automatisch entpackt oder gestartet.',
          preview='curl -fL --output ARCHIV.zip -- ZIP_URL'),
    Entry('git.file', 'Einzelne Datei von GitHub herunterladen',
          'Öffne die Datei im Repository und kopiere ihren „Raw“-Link. Ersetze RAW_DATEI_URL und DATEINAME. '
          'Ein normaler GitHub-Dateiseiten-Link kann stattdessen HTML laden.',
          ('Einzelne Datei von GitHub runterladen', 'GitHub Raw Datei herunterladen',
           'Download one file from GitHub'),
          warning='Vorlage: den direkten Datei-Link einsetzen. Kein automatisches Ausführen.',
          preview='curl -fL --output DATEINAME -- RAW_DATEI_URL'),
    Entry('git.install', 'Git unter Ubuntu installieren',
          'Installiert das Git-Paket aus deinen eingerichteten APT-Paketquellen. '
          'Danach steht git clone zur Verfügung.',
          ('Wie installiere ich git?', 'Git installieren', 'git command not found',
           'git Befehl nicht gefunden', 'Install git on Ubuntu'),
          (('sudo', 'apt', 'install', 'git'),),
          'Installiert ein Systempaket. Normale sudo- und APT-Rückfragen bleiben erhalten; kein automatisches Ja.'),
    Entry('git.pull', 'Heruntergeladenes Git-Projekt aktualisieren',
          'Wechsle zuerst in deinen vorhandenen Projektordner. git pull --ff-only lädt den neuen Stand '
          'und aktualisiert den aktuellen Branch nur, wenn kein Merge nötig ist. '
          'Bei Konflikten oder auseinanderlaufenden Branches bricht es ab; lokale Änderungen nicht blind verwerfen.',
          ('Mein geklontes GitHub Projekt aktualisieren', 'Repo updaten', 'Neuesten Git Stand holen',
           'Update a cloned repository'),
          warning='Anleitung: nur im richtigen Git-Projektordner ausführen. Kann Projektdateien ändern.',
          preview='git pull --ff-only'),
    Entry('git.push_help', 'Git-Änderungen hochladen',
          'git push überträgt vorhandene lokale Commits zum konfigurierten Remote. '
          'Es lädt nicht einfach beliebige ungespeicherte Dateien hoch. Prüfe zuerst git status und die Projektanleitung. '
          'Welches Repository und welcher Branch sind gemeint?',
          ('Änderungen zu GitHub hochladen', 'Projekt auf GitLab pushen', 'Upload commits with git'),
          warning='Nur Erklärung, kein automatisches Veröffentlichen. Keine Passwörter oder Tokens in die Suche eingeben.'),
    Entry('download.file', 'Datei über einen direkten Link herunterladen',
          'Mit curl lädst du eine Datei über ihren direkten Download-Link. Ersetze DOWNLOAD_URL durch den Link '
          'und DATEINAME durch den gewünschten lokalen Namen. Eine Webseite ist nicht automatisch ein direkter Datei-Link.',
          ('Wie kann ich eine Datei runterladen?', 'Sachen aus dem Internet herunterladen',
           'Datei mit curl downloaden', 'Download a file from a URL'),
          warning='Vorlage: vorhandene gleichnamige Dateien können überschrieben werden. '
                  'Download und Ausführen bleiben getrennt.',
          preview='curl -fL --output DATEINAME -- DOWNLOAD_URL'),
    Entry('download.wget', 'Datei mit wget herunterladen',
          'Ersetze DOWNLOAD_URL durch den direkten Download-Link und DATEINAME durch den lokalen Namen. '
          'wget -O speichert den Download unter genau diesem Namen.',
          ('Wie lade ich eine Datei mit wget runter?', 'Download file using wget'),
          warning='Vorlage: eine vorhandene Zieldatei kann überschrieben werden. '
                  'Der Download wird nicht automatisch ausgeführt.',
          preview='wget -O DATEINAME -- DOWNLOAD_URL'),
    Entry('archive.zip', 'ZIP-Datei entpacken',
          'Ersetze ARCHIV.zip durch den Pfad zu deinem ZIP-Archiv. unzip entpackt es im aktuellen Ordner. '
          'Bei fremden Archiven zuerst den Inhalt prüfen, zum Beispiel mit unzip -l ARCHIV.zip.',
          ('Wie entpacke ich eine ZIP?', 'Zip auspacken', 'ZIP Datei extrahieren', 'Unzip an archive'),
          warning='Vorlage: kein Archivpfad geraten. Dateien nur in einen passenden Zielordner entpacken.',
          preview='unzip ARCHIV.zip'),
    Entry('archive.tar', 'TAR-Archiv entpacken',
          'Ersetze ARCHIV.tar.gz durch den Archivpfad. GNU tar erkennt beim Lesen übliche Kompressionen '
          'wie gzip oder xz automatisch. Zum Prüfen des Inhalts nutze zuerst tar -tf ARCHIV.tar.gz.',
          ('Wie entpacke ich tar gz?', 'tar xz Archiv auspacken', 'TAR Archiv extrahieren',
           'Extract a tar archive'),
          warning='Vorlage: ein geeignetes Zielverzeichnis wählen; kein automatisches Entpacken.',
          preview='tar -xf ARCHIV.tar.gz'),
    Entry('files.copy', 'Datei kopieren',
          'cp kopiert Dateien. Ersetze QUELLE und ZIEL durch die Pfade. -i fragt nach, bevor eine vorhandene '
          'Zieldatei überschrieben wird. Pfade mit Leerzeichen in Anführungszeichen setzen.',
          ('Wie kopiere ich eine Datei?', 'Datei duplizieren', 'Dateien kopieren', 'Copy a file'),
          warning='Vorlage: Quelle und Ziel zuerst festlegen.', preview='cp -i -- QUELLE ZIEL'),
    Entry('files.copy_directory', 'Ordner mit Inhalt kopieren',
          'cp -r kopiert einen Ordner samt Inhalt. Ersetze QUELLORDNER und ZIELORDNER; '
          '-i fragt vor dem Überschreiben. Existiert ZIELORDNER schon, kann darin ein Unterordner entstehen.',
          ('Wie kopiere ich einen Ordner?', 'Ordner mit Inhalt duplizieren', 'Copy a directory recursively'),
          warning='Vorlage: Pfade mit Leerzeichen in Anführungszeichen setzen. Quelle und Ziel prüfen.',
          preview='cp -ri -- QUELLORDNER ZIELORDNER'),
    Entry('files.move', 'Datei oder Ordner verschieben',
          'mv verschiebt Dateien und Ordner oder benennt sie um. Ersetze QUELLE und ZIEL. '
          '-i fragt vor dem Überschreiben einer vorhandenen Zieldatei.',
          ('Datei verschieben', 'Ordner umbenennen', 'Wie benenne ich eine Datei um?', 'Move or rename a file'),
          warning='Vorlage: Quelle und Ziel nicht geraten. Nach dem Verschieben liegt die Datei am neuen Ort.',
          preview='mv -i -- QUELLE ZIEL'),
    Entry('files.mkdir', 'Neuen Ordner erstellen',
          'mkdir erstellt einen neuen Ordner. Ersetze ORDNERNAME durch den Namen oder Pfad. '
          'Namen mit Leerzeichen in Anführungszeichen setzen.',
          ('Wie erstelle ich einen Ordner?', 'Neues Verzeichnis anlegen', 'Make a new directory'),
          warning='Vorlage: Zielort zuerst wählen.', preview='mkdir -- ORDNERNAME'),
    Entry('files.cd', 'In einen anderen Ordner wechseln',
          'Mit cd wechselst du den Arbeitsordner deiner aktuellen Shell. Ersetze ORDNERPFAD; '
          'cd .. geht einen Ordner hoch, cd ohne Argument geht in deinen persönlichen Ordner.',
          ('Wie wechsle ich in einen Ordner?', 'In ein Verzeichnis gehen', 'Change directory in terminal'),
          warning='Anleitung für deine aktuelle Eingabezeile, kein Start in einem neuen Tab.',
          preview='cd -- ORDNERPFAD'),
    Entry('files.find', 'Datei nach Namen suchen',
          'find sucht ab dem aktuellen Ordner in Unterordnern. Ersetze SUCHWORT; -iname ignoriert '
          'Groß-/Kleinschreibung. Die Anführungszeichen um das Suchmuster beibehalten.',
          ('Wie finde ich eine Datei?', 'Datei nach Namen suchen', 'Dateien aufspüren', 'Find a file by name'),
          preview="find . -type f -iname '*SUCHWORT*'"),
    Entry('files.timestamps', 'Datum einer Datei prüfen',
          'stat zeigt Dateiinformationen, unter anderem Änderungs- und Zugriffszeiten. '
          'Ersetze DATEIPFAD. Ein Erstellungsdatum ist nicht bei jedem Dateisystem verfügbar.',
          ('Wie alt ist meine Datei?', 'Wann wurde eine Datei geändert?', 'Show file timestamps'),
          preview='stat -- DATEIPFAD'),
    Entry('package.install_help', 'Programm mit APT installieren',
          'Für Pakete aus deinen eingerichteten Ubuntu-Paketquellen: ersetze PAKETNAME durch den richtigen Paketnamen. '
          'Nicht jede App ist als APT-Paket verfügbar. Welche App möchtest du installieren?',
          ('Wie installiere ich ein Programm?', 'Paket installieren', 'Install an Ubuntu package'),
          warning='Vorlage: benötigt sudo und verändert installierte Pakete. Nicht unverändert ausführen.',
          preview='sudo apt install PAKETNAME'),
    Entry('package.deb_help', 'Lokale DEB-Datei installieren',
          'Öffne das Terminal im Ordner deiner heruntergeladenen .deb-Datei und ersetze PAKET.deb. '
          'APT versucht benötigte Abhängigkeiten aufzulösen. Nur Pakete aus einer vertrauenswürdigen Quelle verwenden.',
          ('Wie installiere ich eine deb Datei?', 'Lokales DEB Paket installieren', 'Install a downloaded deb file'),
          warning='Vorlage: Paketname zuerst ersetzen. Installation verwendet Administratorrechte.',
          preview='sudo apt install ./PAKET.deb'),
)

GUIDE_IDS = frozenset(e.id for e in TERMINAL_ENTRIES)
