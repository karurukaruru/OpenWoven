from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release_preflight import (REQUIRED_FILES, inspect_release, linked,
                                       source_inventory, write_report)


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        # Entire fixture is synthetic; never read the checkout's user data.
        for name in REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic fixture\n', encoding='utf-8')
        self.put('LICENSE', 'MIT License\nCopyright (c) 2026 Synthetic Test Holder\n')
        self.put('pyproject.toml', '[project]\nname="openwoven"\nversion="0.1.0"\nlicense="MIT"\n')
        self.put('android/app/build.gradle.kts', 'versionName = "0.1.0"\n')

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_draft_and_publication_modes_do_not_approve_publication(self):
        self.put('LICENSE', 'MIT License\nCopyright (c) 2026 [COPYRIGHT HOLDER]\n')
        draft = inspect_release(self.root)
        self.assertTrue(draft['automated_checks_passed'])
        self.assertTrue(any('holder' in item for item in draft['manual_checks']))
        self.assertFalse(draft['publication_approved'])
        public = inspect_release(self.root, for_publication=True)
        self.assertFalse(public['automated_checks_passed'])
        self.assertTrue(any('holder' in item for item in public['blockers']))
        self.assertFalse(inspect_release(self.root)['head_commit_is_build_provenance'])

    def test_private_and_build_files_are_not_read(self):
        names = ('.env', 'personal.db', 'personal.db-wal', 'android/local.properties',
                 'android/release.jks', 'src/adaptive_companion/.env.py',
                 'src/adaptive_companion/__pycache__/private.py',
                 'tests/build/private.py', 'release-dist/private.py',
                 'src/other_package/private.py')
        for name in names:
            self.put(name, 'synthetic private fixture')
        original = Path.read_text
        reads = []

        def observed(path, *args, **kwargs):
            reads.append(path.relative_to(self.root).as_posix())
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', observed):
            report = inspect_release(self.root)
        self.assertTrue(report['automated_checks_passed'], report['blockers'])
        self.assertTrue(set(names).isdisjoint(reads))
        self.assertTrue(set(names).isdisjoint(report['source_files']))

    def test_secret_findings_are_redacted_in_reports(self):
        token = 'sk-' + 'p' * 40  # Synthetic, assembled so source scan stays clean.
        private_header = '-----BEGIN ' + 'PRIVATE KEY-----'
        self.put('examples/key_fixture.py', token + '\n' + private_header)
        report = inspect_release(self.root)
        rendered = json.dumps(report)
        self.assertFalse(report['automated_checks_passed'])
        self.assertIn('examples/key_fixture.py:1', rendered)
        self.assertIn('examples/key_fixture.py:2', rendered)
        self.assertNotIn(token, rendered)
        self.assertNotIn(private_header, rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_required_documents_and_versions_are_checked(self):
        (self.root / 'SECURITY.md').unlink()
        self.put('android/app/build.gradle.kts', 'versionName = "9.9.9"')
        report = inspect_release(self.root)
        self.assertTrue(any('SECURITY.md' in item for item in report['blockers']))
        self.assertTrue(any('version strings' in item for item in report['blockers']))

    def test_architecture_and_shrinker_config_are_required_and_included(self):
        for name in ('ARCHITECTURE.md', 'AUL_DESIGN.md', 'android/app/proguard-rules.pro'):
            self.assertIn(name, source_inventory(self.root))
            self.assertIn(name, REQUIRED_FILES)
            original = (self.root / name).read_text(encoding='utf-8')
            (self.root / name).unlink()
            report = inspect_release(self.root)
            self.assertFalse(report['automated_checks_passed'])
            self.assertTrue(any(name in item for item in report['blockers']))
            self.put(name, original)

    def test_actual_gradle_shrinker_file_is_not_omitted_from_source_release(self):
        checkout = Path(__file__).resolve().parents[1]
        build = (checkout / 'android/app/build.gradle.kts').read_text(encoding='utf-8')
        referenced = re.findall(r'"([^"\r\n]+\.pro)"', build)
        self.assertIn('proguard-rules.pro', referenced)
        paths = source_inventory(checkout)
        for name in referenced:
            relative = 'android/app/' + name
            self.assertIn(relative, paths)
            self.assertIn(relative, REQUIRED_FILES)

    def test_architecture_contains_three_diagrams_with_valid_source_links(self):
        checkout = Path(__file__).resolve().parents[1]
        architecture = (checkout / 'ARCHITECTURE.md').read_text(encoding='utf-8')
        diagrams = re.findall(r'^```mermaid\r?\n(.*?)^```\s*$', architecture, re.MULTILINE | re.DOTALL)
        self.assertEqual(len(diagrams), 3)
        for diagram in diagrams:
            self.assertTrue(diagram.startswith('flowchart TB\n'))
            self.assertIn('-->', diagram)
        source_links = re.findall(r'\]\(((?:src/|android/)[^)]+)\)', architecture)
        self.assertGreaterEqual(len(source_links), 20)
        for name in source_links:
            self.assertTrue((checkout / name).is_file(), name)
        for name in ('README.md', 'README.en.md'):
            self.assertIn('(ARCHITECTURE.md)', (checkout / name).read_text(encoding='utf-8'))

    def test_wrong_or_invalid_python_metadata_is_blocked(self):
        self.put('pyproject.toml', '[project]\nname="other"\nlicense="wrong"\nversion="0.1.0"')
        self.assertTrue(any('name/license' in item for item in inspect_release(self.root)['blockers']))
        self.put('pyproject.toml', 'invalid [ TOML')
        self.assertFalse(inspect_release(self.root)['automated_checks_passed'])

    def test_assets_are_opt_in_hashed_and_not_asserted_to_be_build_provenance(self):
        asset = self.put('dist/example.whl', 'synthetic binary fixture')
        self.assertEqual(inspect_release(self.root)['assets'], [])
        report = inspect_release(self.root, assets=(asset,))
        self.assertTrue(report['automated_checks_passed'])
        self.assertEqual(report['assets'][0]['sha256'], hashlib.sha256(asset.read_bytes()).hexdigest())
        self.assertFalse(report['head_commit_is_build_provenance'])
        invalid = inspect_release(self.root, assets=(self.root / 'LICENSE', self.root / '../outside.apk'))
        self.assertFalse(invalid['automated_checks_passed'])
        self.assertEqual(invalid['assets'], [])

    def test_duplicate_asset_names_are_rejected(self):
        a = self.put('dist/example.apk', 'a')
        b = self.put('android/app/build/example.apk', 'b')
        report = inspect_release(self.root, assets=(a, b))
        self.assertFalse(report['automated_checks_passed'])
        self.assertTrue(any('unique' in item for item in report['blockers']))

    def test_report_is_local_metadata_only_and_cannot_overwrite_or_escape(self):
        report = inspect_release(self.root)
        write_report(self.root, Path('release-dist/review'), report)
        folder = self.root / 'release-dist/review'
        self.assertEqual({p.name for p in folder.iterdir()}, {'preflight.json', 'SOURCE_FILES.txt', 'SHA256SUMS.txt'})
        self.assertNotIn('release-dist/', (folder / 'SOURCE_FILES.txt').read_text())
        for path in (Path('release-dist/review'), Path('release-dist/../../outside'), Path('outside'), self.root.parent / 'outside'):
            with self.assertRaises((ValueError, FileExistsError)):
                write_report(self.root, path, report)

    def test_linked_source_and_asset_are_rejected_without_reading_target(self):
        outside = self.root / 'outside'
        outside.mkdir()
        target = outside / 'private.py'
        target.write_text('synthetic excluded content', encoding='utf-8')
        link = self.root / 'examples/linked.py'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Creating symlinks requires platform permission')
        self.assertNotIn('examples/linked.py', source_inventory(self.root))
        asset_link = self.root / 'dist/link.apk'
        asset_link.parent.mkdir()
        asset_link.symlink_to(target)
        self.assertFalse(inspect_release(self.root, assets=(asset_link,))['automated_checks_passed'])
        output_link = self.root / 'release-dist'
        output_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            write_report(self.root, Path('release-dist/report'), inspect_release(self.root))

    def test_missing_git_is_a_block_not_an_upload_attempt(self):
        with patch('scripts.release_preflight.subprocess.run', side_effect=FileNotFoundError):
            report = inspect_release(self.root, check_index=True)
        self.assertFalse(report['automated_checks_passed'])
        self.assertTrue(any('Git index' in item for item in report['blockers']))

    def test_link_guards_without_platform_symlink_permission(self):
        module = 'scripts.release_preflight.linked'
        def synthetic_link(path):
            return path == self.root / 'examples' or linked(path)
        with patch(module, side_effect=synthetic_link):
            self.assertNotIn('examples/calendar_memory_demo.py', source_inventory(self.root))
        with patch(module, side_effect=lambda p: p == self.root / 'release-dist'):
            with self.assertRaisesRegex(ValueError, 'linked'):
                write_report(self.root, Path('release-dist/linked-report'), inspect_release(self.root))

    def test_workflows_have_no_automatic_publication_or_write_permission(self):
        checkout = Path(__file__).resolve().parents[1]
        workflow = (checkout / '.github/workflows/release-candidate.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('--for-publication --check-index', workflow)
        self.assertNotIn('\n  push:', workflow)
        self.assertNotIn('\n  pull_request:', workflow)
        for name in ('core-tests.yml', 'android-checks.yml', 'release-candidate.yml'):
            source = (checkout / '.github/workflows' / name).read_text(encoding='utf-8')
            self.assertNotIn('contents: write', source)
            self.assertNotIn('secrets.', source)
            self.assertNotIn('gh release create', source)
            for line in source.splitlines():
                if 'uses:' in line:
                    self.assertRegex(line, r'uses: [A-Za-z0-9_/-]+@[0-9a-f]{40}\b')

    def test_android_artifacts_never_upload_locked_apks(self):
        checkout = Path(__file__).resolve().parents[1]
        workflow = (checkout / '.github/workflows/android-checks.yml').read_text(encoding='utf-8')
        self.assertIn(':app:testLockedDebugUnitTest', workflow)
        self.assertIn(':app:lintLockedDebug', workflow)
        self.assertIn(':app:assembleFullDebug', workflow)
        self.assertNotIn(':app:assembleLockedDebug', workflow)
        self.assertIn('android/app/build/outputs/apk/full/debug/*.apk', workflow)
        self.assertNotIn('android/app/build/outputs/apk/*/', workflow)
        self.assertNotIn('android/app/build/outputs/apk/locked/', workflow)

    @unittest.skipUnless(shutil.which('git'), 'Git not available')
    def test_real_synthetic_git_index_rejects_extras_and_stale_staging(self):
        def git(*arguments):
            return subprocess.run(['git', '-C', str(self.root), *arguments],
                                  capture_output=True, text=True, check=True)

        git('init', '-b', 'main')  # Disposable synthetic repo, NOT the project.
        for name in source_inventory(self.root):
            git('add', '--', name)
        self.assertTrue(inspect_release(self.root, check_index=True)['automated_checks_passed'])
        self.put('README.md', 'changed after staging')
        report = inspect_release(self.root, check_index=True)
        self.assertTrue(any('differ from the index' in item for item in report['blockers']))
        git('add', '--', 'README.md')
        self.put('private.db', 'synthetic, no real user data')
        git('add', '--', 'private.db')
        report = inspect_release(self.root, check_index=True)
        self.assertTrue(any('outside approved source inventory' in item for item in report['blockers']))
        self.put('examples/new_demo.py', '# new synthetic source')
        report = inspect_release(self.root, check_index=True)
        self.assertTrue(any('not staged/tracked: examples/new_demo.py' in item for item in report['blockers']))


if __name__ == '__main__':
    unittest.main()
