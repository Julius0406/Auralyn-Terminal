"""Optional update-button credential: Secret Service only, never a JSON/file fallback.

All methods may block (desktop keyring unlock), so the GUI calls them in a worker.
The exact same Linux password is still sensitive to other code in the login
session. This is convenience storage, NOT a new restricted administrator account.
"""
from __future__ import annotations
import os
import socket
import threading
from contextlib import contextmanager

SCHEMA_NAME = 'de.julius.AuralynTerminal.UpdatePassword'
MAX_PASSWORD_BYTES = 1024


class SecretError(RuntimeError):
    pass


def validate_password(password: str) -> str:
    if (not isinstance(password, str) or not password or
            any(c in password for c in ('\x00', '\r', '\n')) or
            len(password.encode('utf-8')) > MAX_PASSWORD_BYTES):
        raise SecretError('Bitte ein nicht leeres Passwort ohne Zeilenumbrüche eingeben (höchstens 1024 UTF-8-Bytes).')
    return password


def attributes() -> dict[str, str]:
    # Metadata is not encrypted: never put a password in attributes/labels.
    return {'uid': str(os.getuid()), 'host': socket.gethostname(), 'purpose': 'update-button'}


class UpdateSecretStore:
    def _api(self):
        try:
            import gi
            gi.require_version('Secret', '1')
            from gi.repository import Secret, Gio
            schema = Secret.Schema.new(SCHEMA_NAME, Secret.SchemaFlags.NONE,
                {key: Secret.SchemaAttributeType.STRING for key in attributes()})
            return Secret, Gio, schema
        except (ImportError, ValueError):
            raise SecretError('Schlüsselbund-Unterstützung fehlt. Benötigt wird gir1.2-secret-1 mit einem laufenden Secret-Service, z. B. GNOME-Schlüsselbund.') from None

    @contextmanager
    def _session(self, *, timeout=120):
        Secret, Gio, schema = self._api()
        cancel = Gio.Cancellable()
        timer = threading.Timer(timeout, cancel.cancel)
        timer.daemon = True
        timer.start()
        try:
            # Explicit D-Bus Service, NOT the generic backend that may fall back
            # to a file backend. No file/keyring-fallback credential is created.
            service = Secret.Service.get_sync(Secret.ServiceFlags.OPEN_SESSION, cancel)
            if service is None:
                raise SecretError('Kein System-Schlüsselbund erreichbar.')
            yield Secret, service, schema, cancel
        except SecretError:
            raise
        except Exception:
            # A backend's exception text is not safe for logging/display.
            raise SecretError('Schlüsselbund nicht erreichbar, gesperrt oder Anfrage abgebrochen. Bitte den Ubuntu-Schlüsselbund entsperren und erneut versuchen. Es gibt keinen Klartext-Fallback.') from None
        finally:
            timer.cancel()

    def exists(self) -> bool:
        with self._session(timeout=15) as (Secret, service, schema, cancel):
            # Metadata only: opening Settings must NOT retrieve/unlock a secret.
            items = service.search_sync(schema, attributes(), Secret.SearchFlags.NONE, cancel)
            return bool(items)

    def save(self, password: str) -> None:
        validate_password(password)
        with self._session() as (Secret, service, schema, cancel):
            value = Secret.Value.new(password, -1, 'text/plain')
            try:
                ok = service.store_sync(schema, attributes(), Secret.COLLECTION_DEFAULT,
                    'Auralyn Terminal · Passwort für den Update-Button', value, cancel)
                if not ok:
                    raise SecretError('Das Passwort wurde nicht gespeichert.')
            finally:
                # PyGObject owns/free's SecretValue. Python str copies cannot be
                # reliably wiped; do not promise immunity to a memory inspection.
                del value

    def lookup(self) -> bytearray:
        with self._session() as (Secret, service, schema, cancel):
            items = service.search_sync(schema, attributes(),
                Secret.SearchFlags.UNLOCK | Secret.SearchFlags.LOAD_SECRETS, cancel)
            if not items:
                raise SecretError('Kein Update-Passwort gespeichert. Zahnrad → Update-Button → Optionen & Passwort….')
            value = items[0].get_secret()
            if value is None:
                raise SecretError('Der Schlüsselbund wurde nicht entsperrt. Update ohne Passwortübernahme abgebrochen.')
            text = value.get_text()
            try:
                return bytearray(validate_password(text), 'utf-8')
            finally:
                del text, value

    def delete(self) -> None:
        with self._session() as (Secret, service, schema, cancel):
            # clear_sync alone ignores locked items. Explicitly unlock/delete
            # ONLY our matching items, then verify there is no item left.
            items = service.search_sync(schema, attributes(),
                Secret.SearchFlags.ALL | Secret.SearchFlags.UNLOCK, cancel)
            for item in items:
                if item.get_locked() or not item.delete_sync(cancel):
                    raise SecretError('Passwort nicht gelöscht: Bitte den Schlüsselbund entsperren und erneut versuchen.')
            if service.search_sync(schema, attributes(), Secret.SearchFlags.NONE, cancel):
                raise SecretError('Der Schlüsselbund enthält noch einen passenden Eintrag.')
