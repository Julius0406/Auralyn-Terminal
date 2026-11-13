# Primärquellen zur Implementierung

Dokumentationsprüfung: 11.10.2026. Diese Links beschreiben Schnittstellen; sie sind
kein Nachweis eines Live-Tests des fertigen Pakets. Öffentliches Netz war aus der
Build-Laufzeit nicht erreichbar. Such- und Modellabläufe wurden mit Fixtures getestet.

- Ollama lokale Chat-API / strukturierte Antworten:
  https://docs.ollama.com/capabilities/structured-outputs
- Ollama Web Search, Bearer-Key, POST /api/web_search, results/title/url/content:
  https://docs.ollama.com/capabilities/web-search
- DuckDuckGo Nicht-JavaScript-Suche (HTML/Lite, keine API-Verfügbarkeitszusage):
  https://duckduckgo.com/duckduckgo-help-pages/features/non-javascript/
- NVIDIA-SMI Herstellerhandbuch, Query-/CSV-Optionen:
  https://docs.nvidia.com/deploy/nvidia-smi/index.html
- NVIDIA Beispiele zur driver_version-Abfrage:
  https://nvidia.custhelp.com/app/answers/detail/a_id/3751/~/useful-nvidia-smi-queries
- Ubuntu NVIDIA-Installation, passende Treiber-/Utilities-Varianten:
  https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/
- NVIDIA Ubuntu-Paketnamen/Versionsbindung (Versionsschema nicht starr annehmen):
  https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/latest/ubuntu.html
- Ubuntu 26.04 apt-cache (lokale Paketmetadaten, policy/show):
  https://manpages.ubuntu.com/manpages/resolute/man8/apt-cache.8.html
- Ubuntu 26.04 NVIDIA-SMI-Manpage (als Online-Dokumentationsbeispiel):
  https://manpages.ubuntu.com/manpages/resolute/en/man1/nvidia-smi.1.html
- Git clone (Download ist nicht Installation):
  https://git-scm.com/docs/git-clone
- VTE GTK3 spawn_async (PTY-/Shell-Start):
  https://gnome.pages.gitlab.gnome.org/vte/gtk3/method.Terminal.spawn_async.html

Die Anwendung hat keine direkte Verbindung zur Websuche von ChatGPT. Ihr eigener
Webadapter ist in web_sources.py implementiert. Ein lokales Ollama-Modell bekommt
nicht von selbst Internetzugriff; die App ruft Quellen ab und liefert die Daten.


Zusätzlich bei der HTTPS-Korrektur geprüft:

- CPython 3.14, `SSLSocket.dup()` wirft `NotImplementedError`:
  https://raw.githubusercontent.com/python/cpython/3.14/Lib/ssl.py
- Python SSL-Kontext, TLS-Wrapping und Zertifikatsprüfung:
  https://docs.python.org/3.14/library/ssl.html
- Ollama Chat-API, strukturierte Antworten:
  https://docs.ollama.com/api/chat

Auralyn hat echte lokale TLS-Tests (einschließlich vertrauenswürdigem Testzertifikat
und Negativtests), aber keine erfolgreiche öffentliche Netzprobe in der Bauumgebung.


## Ergänzung für v1.0.0 Stable: Updates und Passwortspeicherung

- sudo-Handbuch: `-A`/Askpass, `-k` pro Befehl, `-K` für alle Zeitstempel
  desselben Benutzers, Grenzen der bestehenden Systemrichtlinie:
  https://manpages.debian.org/trixie/sudo/sudo.8.en.html
- sudo-rs-Handbuch: implementierte Optionen; nicht mit einer Live-Prüfung der
  tatsächlich installierten Ubuntu-Version gleichzusetzen:
  https://raw.githubusercontent.com/trifectatechfoundation/sudo-rs/main/docs/man/sudo.8.md
- APT-Handbuch: full-upgrade darf Pakete entfernen:
  https://manpages.debian.org/trixie/apt/apt.8.en.html
- Flatpak-Befehlsreferenz / update / System- und Benutzerinstallation:
  https://docs.flatpak.org/en/latest/flatpak-command-reference.html
- libsecret: Suchattribute sind keine Geheimnisspeicherung; GUI-Aufrufe asynchron:
  https://gnome.pages.gitlab.gnome.org/libsecret/libsecret-python-examples.html
- Expliziter Secret-Service, Store und Metadaten-/Secret-Suche:
  https://gnome.pages.gitlab.gnome.org/libsecret/method.Service.store_sync.html
  https://gnome.pages.gitlab.gnome.org/libsecret/method.Service.search_sync.html
- Secret.Value als Textwert:
  https://gnome.pages.gitlab.gnome.org/libsecret/ctor.Value.new.html
  https://gnome.pages.gitlab.gnome.org/libsecret/method.Value.get_text.html

Die Schnittstellen wurden anhand der Dokumentation geprüft. Zusätzlich lief ein
harmloser echter GNU-sudo-/Askpass-Test mit einem kurzzeitig angelegten isolierten
Testkonto und Dummy-Passwort. Die Ubuntu-GUI, der echte Desktop-Schlüsselbund und
reale Paketupdates bleiben nicht live geprüft.

## Ergänzung für v1.0.0 Stable: sprachunabhängige Bestätigung

- APT: `-y`/`--assume-yes`, Abbruch bei kritischen Situationen und ausdrückliche
  Warnungen zu den in Auralyn **nicht** verwendeten Force-/Allow-Optionen:
  https://manpages.debian.org/trixie/apt/apt-get.8.en.html
- `apt full-upgrade` kann vorhandene Pakete entfernen:
  https://manpages.debian.org/trixie/apt/apt.8.en.html
- Flatpak, Abschnitt `flatpak update`, `--assumeyes` (native Bestätigung; nicht
  mit `--noninteractive` oder `--force-remove` gleichzusetzen):
  https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-update

Dokumentation während dieses Builds per Webabruf geprüft. Auralyn analysiert
keine lokalisierten Prompt-Zeichenketten und injiziert keine Ja-Tastendrücke.
