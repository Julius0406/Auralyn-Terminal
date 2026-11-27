import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "orbit-global-menu"
MAPPING_FILE = INTEGRATION / "auralyn-terminal.json"
INSTALLER = INTEGRATION / "install.sh"


class OrbitGlobalMenuTests(unittest.TestCase):
    def test_mapping_matches_orbit_schema_and_auralyn_actions(self):
        mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
        self.assertEqual(mapping["format"], 1)
        self.assertEqual(mapping["app"], "auralyn-terminal")
        self.assertIn("auralyn-terminal", mapping["identifiers"])
        self.assertGreaterEqual(len(mapping["menus"]), 6)
        app_source = (ROOT / "auralyn_terminal" / "app.py").read_text(encoding="utf-8")
        for menu in mapping["menus"]:
            self.assertIsInstance(menu["label"], str)
            for item in menu["items"]:
                if item.get("separator"):
                    continue
                self.assertIn("shortcut", item)
                self.assertRegex(item["shortcut"], r"^<Ctrl>.*")
        for key in ("Gdk.KEY_u", "Gdk.KEY_i", "Gdk.KEY_n", "Gdk.KEY_q",
                    "Gdk.KEY_t", "Gdk.KEY_w", "Gdk.KEY_f", "Gdk.KEY_comma",
                    "Gdk.KEY_Page_Up", "Gdk.KEY_Page_Down", "Gdk.KEY_plus",
                    "Gdk.KEY_minus", "Gdk.KEY_0", "Gdk.KEY_space"):
            self.assertIn(key, app_source)

    def test_installer_installs_mapping_and_reloads_enabled_orbit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fakebin = root / "bin"
            fakebin.mkdir()
            log = root / "orbit.log"
            fake = fakebin / "gnome-extensions"
            fake.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = list ]; then echo global-menu@unmade.space; "
                "else echo \"$1\" >> \"$ORBIT_LOG\"; fi\n"
            )
            fake.chmod(0o755)
            env = os.environ.copy()
            env["XDG_CONFIG_HOME"] = str(root / "config")
            env["ORBIT_LOG"] = str(log)
            env["PATH"] = str(fakebin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                ["bash", str(INSTALLER)], env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            dest = root / "config/global-menu/shortcuts/apps/auralyn-terminal.json"
            self.assertEqual(json.loads(dest.read_text()), json.loads(MAPPING_FILE.read_text()))
            self.assertEqual(log.read_text().splitlines(), ["disable", "enable"])
            self.assertIn("neu geladen", result.stdout)

            dest.write_text('{"app":"my-custom-menu"}\n')
            subprocess.run(
                ["bash", str(INSTALLER)], env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            backups = list(dest.parent.glob("auralyn-terminal.json.backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), {"app": "my-custom-menu"})
            self.assertEqual(json.loads(dest.read_text()), json.loads(MAPPING_FILE.read_text()))


if __name__ == "__main__":
    unittest.main()
