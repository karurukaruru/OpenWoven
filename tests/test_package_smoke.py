from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.package_smoke import validate_wheel


class PackageSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wheel = Path(self.tmp.name) / 'synthetic.whl'

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, holder='[COPYRIGHT HOLDER]', extra=None, omit_license=False,
                metadata_extra='', name='openwoven', omit_module=''):
        prefix = 'openwoven-0.1.0.dist-info/'
        with ZipFile(self.wheel, 'w') as archive:
            archive.writestr(prefix + 'METADATA', f'Metadata-Version: 2.4\nName: {name}\nVersion: 0.1.0\nLicense-Expression: MIT\n' + metadata_extra)
            if not omit_license:
                archive.writestr(prefix + 'licenses/LICENSE', 'MIT License\nCopyright (c) 2026 ' + holder)
            for module in ('core', 'retrieval', 'android_bridge', 'onboarding', 'character_interview', 'character_book'):
                if module == omit_module:
                    continue
                archive.writestr('adaptive_companion/' + module + '.py', '# synthetic fixture\n')
            for module in ('__init__', '__main__'):
                if module != omit_module:
                    archive.writestr('openwoven/' + module + '.py', '# synthetic public fixture\n')
            if extra:
                archive.writestr(extra, 'synthetic, not user data')

    def test_draft_license_allowed_locally_but_not_for_publication(self):
        self.fixture()
        validate_wheel(self.wheel)
        with self.assertRaisesRegex(ValueError, 'copyright-holder'):
            validate_wheel(self.wheel, for_publication=True)
        self.fixture(holder='Synthetic fixture holder')
        validate_wheel(self.wheel, for_publication=True)

    def test_missing_license_and_unexpected_payload_are_rejected(self):
        self.fixture(omit_license=True)
        with self.assertRaisesRegex(ValueError, 'LICENSE'):
            validate_wheel(self.wheel)
        self.fixture(extra='tests/example.py')
        with self.assertRaisesRegex(ValueError, 'unexpected payload'):
            validate_wheel(self.wheel)

    def test_wrong_distribution_and_runtime_dependency_are_rejected(self):
        self.fixture(name='other-project')
        with self.assertRaisesRegex(ValueError, 'distribution name'):
            validate_wheel(self.wheel)
        self.fixture(metadata_extra='Requires-Dist: unnecessary-dependency\n')
        with self.assertRaisesRegex(ValueError, 'runtime dependencies'):
            validate_wheel(self.wheel)

    def test_missing_character_book_is_rejected(self):
        self.fixture(omit_module='character_book')
        with self.assertRaisesRegex(ValueError, 'required module missing: character_book'):
            validate_wheel(self.wheel)

    def test_missing_public_entry_points_are_rejected(self):
        for module in ('__init__', '__main__'):
            with self.subTest(module=module):
                self.fixture(omit_module=module)
                with self.assertRaisesRegex(ValueError, 'required public module missing: ' + module):
                    validate_wheel(self.wheel)


if __name__ == '__main__':
    unittest.main()
