# Offline-Aufgaben und Befehlsvorlagen · v1.0.0 Stable

Mit aktivierter KI gilt stattdessen die Befehlsrecherche; diese festen
Vorlagen bleiben für den Offline-Modus und ausdrücklich beschriftete Rückfälle.

Direkt aus den verwendeten Katalogeinträgen erzeugt.

## Projekt von GitHub herunterladen

ID: `git.clone`

Mit git clone lädst du ein Git-Projekt samt Versionsverlauf in einen neuen Ordner. Kopiere auf der Projektseite unter „Code → HTTPS“ den Repository-Link und ersetze REPOSITORY_URL. Das lädt Quellcode herunter, installiert oder startet die App aber nicht.

```text
git clone REPOSITORY_URL
```

Hinweis: Vorlage: erst den echten Repository-Link einsetzen. Kein sudo nötig. Für eine fertige App suche nach dem Release statt nach Quellcode.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie kann ich Sachen von GitHub runterladen?

## Fertige App aus einem GitHub-Release laden

ID: `git.release`

Für eine fertige App öffne beim Projekt „Releases → Assets“ und wähle die passende Linux-Datei (zum Beispiel .deb oder .AppImage). „Source code“ ist nur Quellcode. Für einen Terminal-Download brauchst du den direkten Link zur gewünschten Datei; ersetze DOWNLOAD_URL und DATEINAME in der Vorlage.

```text
curl -fL --output DATEINAME -- DOWNLOAD_URL
```

Hinweis: Nur herunterladen; nichts automatisch installieren oder ausführen. Die passende Datei und Version müssen zum Projekt und zu deinem System passen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Fertiges Programm von GitHub herunterladen

## GitHub-Quellcode als ZIP herunterladen

ID: `git.zip`

Ohne Git: Projektseite → „Code → Download ZIP“. Für das Terminal kopiere den ZIP-Download-Link und ersetze ZIP_URL sowie ARCHIV.zip. Ein ZIP-Snapshot enthält keinen Git-Versionsverlauf.

```text
curl -fL --output ARCHIV.zip -- ZIP_URL
```

Hinweis: Vorlage mit Platzhaltern. Das Archiv wird nicht automatisch entpackt oder gestartet.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: GitHub als ZIP runterladen

## Einzelne Datei von GitHub herunterladen

ID: `git.file`

Öffne die Datei im Repository und kopiere ihren „Raw“-Link. Ersetze RAW_DATEI_URL und DATEINAME. Ein normaler GitHub-Dateiseiten-Link kann stattdessen HTML laden.

```text
curl -fL --output DATEINAME -- RAW_DATEI_URL
```

Hinweis: Vorlage: den direkten Datei-Link einsetzen. Kein automatisches Ausführen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Einzelne Datei von GitHub runterladen

## Git unter Ubuntu installieren

ID: `git.install`

Installiert das Git-Paket aus deinen eingerichteten APT-Paketquellen. Danach steht git clone zur Verfügung.

```text
sudo apt install git
```

Hinweis: Installiert ein Systempaket. Normale sudo- und APT-Rückfragen bleiben erhalten; kein automatisches Ja.

**Feste Aktion; Start nur nach Klick und gegebenenfalls Bestätigung.**

Beispielfrage: Wie installiere ich git?

## Heruntergeladenes Git-Projekt aktualisieren

ID: `git.pull`

Wechsle zuerst in deinen vorhandenen Projektordner. git pull --ff-only lädt den neuen Stand und aktualisiert den aktuellen Branch nur, wenn kein Merge nötig ist. Bei Konflikten oder auseinanderlaufenden Branches bricht es ab; lokale Änderungen nicht blind verwerfen.

```text
git pull --ff-only
```

Hinweis: Anleitung: nur im richtigen Git-Projektordner ausführen. Kann Projektdateien ändern.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Mein geklontes GitHub Projekt aktualisieren

## Git-Änderungen hochladen

ID: `git.push_help`

git push überträgt vorhandene lokale Commits zum konfigurierten Remote. Es lädt nicht einfach beliebige ungespeicherte Dateien hoch. Prüfe zuerst git status und die Projektanleitung. Welches Repository und welcher Branch sind gemeint?

Hinweis: Nur Erklärung, kein automatisches Veröffentlichen. Keine Passwörter oder Tokens in die Suche eingeben.

Beispielfrage: Änderungen zu GitHub hochladen

## Datei über einen direkten Link herunterladen

ID: `download.file`

Mit curl lädst du eine Datei über ihren direkten Download-Link. Ersetze DOWNLOAD_URL durch den Link und DATEINAME durch den gewünschten lokalen Namen. Eine Webseite ist nicht automatisch ein direkter Datei-Link.

```text
curl -fL --output DATEINAME -- DOWNLOAD_URL
```

Hinweis: Vorlage: vorhandene gleichnamige Dateien können überschrieben werden. Download und Ausführen bleiben getrennt.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie kann ich eine Datei runterladen?

## Datei mit wget herunterladen

ID: `download.wget`

Ersetze DOWNLOAD_URL durch den direkten Download-Link und DATEINAME durch den lokalen Namen. wget -O speichert den Download unter genau diesem Namen.

```text
wget -O DATEINAME -- DOWNLOAD_URL
```

Hinweis: Vorlage: eine vorhandene Zieldatei kann überschrieben werden. Der Download wird nicht automatisch ausgeführt.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie lade ich eine Datei mit wget runter?

## ZIP-Datei entpacken

ID: `archive.zip`

Ersetze ARCHIV.zip durch den Pfad zu deinem ZIP-Archiv. unzip entpackt es im aktuellen Ordner. Bei fremden Archiven zuerst den Inhalt prüfen, zum Beispiel mit unzip -l ARCHIV.zip.

```text
unzip ARCHIV.zip
```

Hinweis: Vorlage: kein Archivpfad geraten. Dateien nur in einen passenden Zielordner entpacken.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie entpacke ich eine ZIP?

## TAR-Archiv entpacken

ID: `archive.tar`

Ersetze ARCHIV.tar.gz durch den Archivpfad. GNU tar erkennt beim Lesen übliche Kompressionen wie gzip oder xz automatisch. Zum Prüfen des Inhalts nutze zuerst tar -tf ARCHIV.tar.gz.

```text
tar -xf ARCHIV.tar.gz
```

Hinweis: Vorlage: ein geeignetes Zielverzeichnis wählen; kein automatisches Entpacken.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie entpacke ich tar gz?

## Datei kopieren

ID: `files.copy`

cp kopiert Dateien. Ersetze QUELLE und ZIEL durch die Pfade. -i fragt nach, bevor eine vorhandene Zieldatei überschrieben wird. Pfade mit Leerzeichen in Anführungszeichen setzen.

```text
cp -i -- QUELLE ZIEL
```

Hinweis: Vorlage: Quelle und Ziel zuerst festlegen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie kopiere ich eine Datei?

## Ordner mit Inhalt kopieren

ID: `files.copy_directory`

cp -r kopiert einen Ordner samt Inhalt. Ersetze QUELLORDNER und ZIELORDNER; -i fragt vor dem Überschreiben. Existiert ZIELORDNER schon, kann darin ein Unterordner entstehen.

```text
cp -ri -- QUELLORDNER ZIELORDNER
```

Hinweis: Vorlage: Pfade mit Leerzeichen in Anführungszeichen setzen. Quelle und Ziel prüfen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie kopiere ich einen Ordner?

## Datei oder Ordner verschieben

ID: `files.move`

mv verschiebt Dateien und Ordner oder benennt sie um. Ersetze QUELLE und ZIEL. -i fragt vor dem Überschreiben einer vorhandenen Zieldatei.

```text
mv -i -- QUELLE ZIEL
```

Hinweis: Vorlage: Quelle und Ziel nicht geraten. Nach dem Verschieben liegt die Datei am neuen Ort.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Datei verschieben

## Neuen Ordner erstellen

ID: `files.mkdir`

mkdir erstellt einen neuen Ordner. Ersetze ORDNERNAME durch den Namen oder Pfad. Namen mit Leerzeichen in Anführungszeichen setzen.

```text
mkdir -- ORDNERNAME
```

Hinweis: Vorlage: Zielort zuerst wählen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie erstelle ich einen Ordner?

## In einen anderen Ordner wechseln

ID: `files.cd`

Mit cd wechselst du den Arbeitsordner deiner aktuellen Shell. Ersetze ORDNERPFAD; cd .. geht einen Ordner hoch, cd ohne Argument geht in deinen persönlichen Ordner.

```text
cd -- ORDNERPFAD
```

Hinweis: Anleitung für deine aktuelle Eingabezeile, kein Start in einem neuen Tab.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie wechsle ich in einen Ordner?

## Datei nach Namen suchen

ID: `files.find`

find sucht ab dem aktuellen Ordner in Unterordnern. Ersetze SUCHWORT; -iname ignoriert Groß-/Kleinschreibung. Die Anführungszeichen um das Suchmuster beibehalten.

```text
find . -type f -iname '*SUCHWORT*'
```

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie finde ich eine Datei?

## Datum einer Datei prüfen

ID: `files.timestamps`

stat zeigt Dateiinformationen, unter anderem Änderungs- und Zugriffszeiten. Ersetze DATEIPFAD. Ein Erstellungsdatum ist nicht bei jedem Dateisystem verfügbar.

```text
stat -- DATEIPFAD
```

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie alt ist meine Datei?

## Programm mit APT installieren

ID: `package.install_help`

Für Pakete aus deinen eingerichteten Ubuntu-Paketquellen: ersetze PAKETNAME durch den richtigen Paketnamen. Nicht jede App ist als APT-Paket verfügbar. Welche App möchtest du installieren?

```text
sudo apt install PAKETNAME
```

Hinweis: Vorlage: benötigt sudo und verändert installierte Pakete. Nicht unverändert ausführen.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie installiere ich ein Programm?

## Lokale DEB-Datei installieren

ID: `package.deb_help`

Öffne das Terminal im Ordner deiner heruntergeladenen .deb-Datei und ersetze PAKET.deb. APT versucht benötigte Abhängigkeiten aufzulösen. Nur Pakete aus einer vertrauenswürdigen Quelle verwenden.

```text
sudo apt install ./PAKET.deb
```

Hinweis: Vorlage: Paketname zuerst ersetzen. Installation verwendet Administratorrechte.

**Nur kopierbare Anleitung/Vorlage, keine ausführbare Aktion.**

Beispielfrage: Wie installiere ich eine deb Datei?

