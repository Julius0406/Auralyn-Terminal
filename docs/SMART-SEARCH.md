# Smart Search – Architektur v1.0.0 Stable

Die aktuelle Bedienung steht in README.md. Diese Datei beschreibt die Datenflüsse.

## Vier Betriebsarten

1. Programmhilfe: bekannte Auralyn-Menüfragen → versionierte APP_ENTRIES, keine KI/kein Web.
2. Offline: Regeln/Completions/whatis, explizit als keine KI markiert.
3. Lokale Recherche: CommandResearch → lokale Modellplanung → CapabilityReader → Modellantwort.
4. Web + Lokal: WebCommandResearch → lokale Planung ohne PATH-Inventar → WebSearch → Modell-
   Quellenauswahl → CapabilityReader → ggf. Installationsrecherche/PackageReader → Modellantwort.

Der Webmodus erfordert beide Schalter smart_ai_enabled und smart_web_enabled.
Anbieter smart_web_provider ist duckduckgo oder ollama. Für Letzteren gibt es die
separate private Datei web-search.key; sie wird niemals in den Modellkontext geladen.

## Webbelege statt erfundener Recherche

WebSource-IDs entstehen ausschließlich aus real zurückgegebenen Seiten/Auszügen.
Die Modell-Auswahl muss eine existierende ID und einen im Auszug genannten Befehl
referenzieren. Das ist ein Beleg für den Bezug zur Quelle, kein Beweis für die volle
Semantik oder Aktualität jeder Option. Der Zweck wird weiterhin von der KI beurteilt.

DuckDuckGo HTML ist ein schlüsselfreier Adapter mit Fehler-/CAPTCHA-Erkennung. Kein
Umgehen der Sperren. Direkte Online-Doku-Adressen sind URL-Vorlagen, keine fertigen
Antworten. Bei NVIDIA existiert zusätzlich eine Hersteller-Manuallink-Vorlage.
Auch diese Quellen werden bei jeder Recherche wirklich angefragt. Ergebnisse aus
Ollama Web Search sind als Suchauszug markiert, bis ein eigener Seitenabruf gelingt.

Öffentliche HTTPS-Adressen, DNS-Prüfung und fixierte numerische Ziel-IP, TLS mit
Hostname/SNI-Prüfung; keine fremden Ports, internen Netze, URL-Credentials oder Cookies.
API-Authorization nur am exakten Endpunkt, ohne Redirect. Antworten maximal 900 KB,
Textauszüge begrenzt, maximal fünf Quellen je Suchschritt; kein Ausführen von HTML/JS.

## Lokale Prüfung und Installationsberatung

CapabilityReader inspiziert PATH-Metadaten/Bash-Builtins und begrenzte lokale man-Dateien.
Kein gefundenes Tool und kein fremdes `--help` wird beim Suchen gestartet. Optionale
Handbuchlabels werden normalisiert/fallen auf den Hauptbefehl zurück. Ein falsches Label
ist kein Grund mehr, eine gültige Aufgabe als fremden Befehl abzulehnen.

PackageReader darf nur die festen Programme /usr/bin/apt-cache und /usr/bin/dpkg-query
mit validierten Argumenten, neutraler Umgebung, Ausgabe- und Zeitgrenzen verwenden.
Keine Shell, kein sudo, kein apt install, keine Paketquellenänderung. NVIDIA-Versionen
werden gegebenenfalls aus festen Systempfaden gelesen; keinerlei Seriennummern/UUIDs.
Vor einer Utilities-Vorlage müssen Version/Variante zum geladenen Treiber passen.

Andere Manager: ausschließlich einfaches snap/flatpak-flathub/pipx/cargo/uv-tool install,
gesamte Zeile wörtlich im Auszug und Manager im PATH. Keine Store-Verifikation; sichtbar
als bloße Kopiervorlage. Fehlende Daten erzeugen keinen erfundenen Installationsweg.

## Ausführung

Answer.executable prüft unveränderliche ID, exakten String, Zustand und vorhandene
Werkzeuge. Nur 31 feste Smart-Search-Aktionen sind zugelassen. Der allgemeine Bash-
Terminal bleibt frei bedienbar. Die Installationskarte hat KEINE Ausführungsfunktion.
Ein Klick auf „Nach Installation erneut prüfen“ sucht nur neu.

Neue Fragen/Schließen/Settings-Änderungen invalidieren Serial, Ergebnis und Worker.
Fortschritt ist an dieselbe Serial gebunden. Kopieren/Quellen öffnen/echte feste Aktion
starten sind getrennte explizite Klicks. Eine fremde Modellquelle bekommt keine Shell.

## Grenzen

Keine perfekte Themen- oder Syntaxerkennung, kein garantierter semantischer Beweis,
kein Testlauf gefundener Programme. Webdienste können ausfallen; lokale Paketlisten
können veraltet sein. Ein installiertes nvidia-smi kann wegen Treiberproblemen trotzdem
fehlschlagen. Fehlerzustände behaupten deshalb nicht, die Aufgabe sei unmöglich.

Tests sind teils echte lokale I/O-/PTY-/HTTP-Tests und teils Modell/Web/GUI-Doubles.
Eine grüne Fixture-Suite ist kein Live-Ollama- oder Ubuntu-GUI-Nachweis.


## HTTPS-Verbindungsfix und Diagnose

Der HTTPS-Adapter kopiert nicht länger einen SSLSocket: das ist in CPython nicht
implementiert. Er dupliziert den zugrunde liegenden TCP-Socket vor TLS, nutzt die
Kopie nur für shutdown/close und sendet sämtliche Inhalte verschlüsselt über TLS.
Echte TLS-Tests lesen eine lokale zertifikatsgeprüfte Fixture; öffentliche Adressen
werden ausschließlich in den Tests zum Loopbackserver umgeleitet. Der Produktcode
hat keine Option, SSRF- oder Zertifikatsprüfungen dafür abzuschalten.

Unerwartete Fehler werden nicht länger still verschluckt. Answer.diagnostic enthält
kopierbare technische Metadaten; die Oberfläche zeigt einen entsprechenden Button.
Das lokale Protokoll ist auf 256 KiB begrenzt (Modus 600), ohne Suchfragen, Modell-
oder Webseiteninhalte, Terminalverlauf, Schlüssel, Variablen oder Exception-Texte.
Der letzte bekannte Schritt und Code-Datei/Zeile bleiben zur Fehlersuche erhalten.
Kein automatischer Upload. Fehler im Protokollschreiben verhindern die Anzeige nicht.
