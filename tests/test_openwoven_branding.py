"""Branding changes must not silently migrate private data or break callers."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

from adaptive_companion import CompanionCore as LegacyCore
from openwoven import CompanionCore
from scripts.release_preflight import REQUIRED_FILES, source_inventory


ROOT = Path(__file__).resolve().parents[1]


class OpenWovenBrandingTests(unittest.TestCase):
    def test_public_api_is_the_same_core_not_a_separate_data_store(self):
        self.assertIs(CompanionCore, LegacyCore)
        self.assertIs(importlib.import_module('openwoven.__main__').main,
                      importlib.import_module('adaptive_companion.cli').main)

    def test_distribution_and_both_cli_scripts_are_configured(self):
        metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertEqual('openwoven', metadata['project']['name'])
        scripts = metadata['project']['scripts']
        self.assertEqual(scripts['openwoven'], scripts['companion'])
        packages = metadata['tool']['setuptools']['packages']['find']['include']
        self.assertIn('openwoven*', packages)
        self.assertIn('adaptive_companion*', packages)

    def test_both_module_entry_points_show_openwoven_without_a_provider(self):
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'PYTHONUTF8': '1'}
        for module in ('openwoven', 'adaptive_companion'):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, '-X', 'utf8', '-m', module, '--help'],
                                        cwd=ROOT, env=env, capture_output=True,
                                        encoding='utf-8', timeout=20)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn('OpenWoven', result.stdout)

    def test_public_entry_points_are_required_in_source_releases(self):
        inventory = source_inventory(ROOT)
        for name in ('src/openwoven/__init__.py', 'src/openwoven/__main__.py'):
            self.assertIn(name, inventory)
            self.assertIn(name, REQUIRED_FILES)

    def test_android_branding_keeps_existing_installation_identity(self):
        gradle = (ROOT / 'android/app/build.gradle.kts').read_text(encoding='utf-8')
        self.assertIn('applicationId = "com.adaptive.companion"', gradle)
        self.assertIn('namespace = "com.adaptive.companion"', gradle)
        self.assertIn('"app_name", "OpenWoven Developer"', gradle)
        self.assertIn('"app_name", "OpenWoven"', gradle)
        self.assertIn('applicationIdSuffix = ".full"', gradle)
        self.assertIn('applicationIdSuffix = ".locked"', gradle)
        self.assertIn('applicationIdSuffix = ".debug"', gradle)
        manifest = (ROOT / 'android/app/src/main/AndroidManifest.xml').read_text(encoding='utf-8')
        self.assertIn('@style/Theme.OpenWoven', manifest)


if __name__ == '__main__':
    unittest.main()
