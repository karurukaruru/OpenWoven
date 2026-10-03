"""Prepare a local, reviewable publication inventory; never commit or upload.

Only approved source files are read. Databases, local properties, credentials,
build outputs and linked paths are excluded. Pattern matching is NOT a complete
secret/privacy audit, and this does not scan Git history or validate an APK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path


ROOT_FILES = (
    '.gitignore', '.gitattributes', 'LICENSE', 'pyproject.toml', 'README.md',
    'README.en.md', 'ARCHITECTURE.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
    'GITHUB_RELEASE.md', 'RELEASE_NOTES.md', 'RELEASE_CHECKLIST.md', 'REVIEW.md',
    'MEMORY_DESIGN.md', 'PERSONA_DESIGN.md', 'AUL_DESIGN.md', 'RUNTIME_GUIDE.md', 'PERFORMANCE.md',
    'OPEN_SOURCE_PLAN.md', 'COMPETITOR_NOTES.md', 'ROLE_PACKAGES.md',
    'THIRD_PARTY_NOTICES.md', 'android/app/src/main/assets/THIRD_PARTY_NOTICES.txt',
    'android/build.gradle.kts', 'android/settings.gradle.kts',
    'android/gradle.properties', 'android/gradlew', 'android/gradlew.bat',
    'android/gradle/wrapper/gradle-wrapper.jar',
    'android/gradle/wrapper/gradle-wrapper.properties', 'android/app/build.gradle.kts',
    'android/app/proguard-rules.pro',
)
SOURCE_TREES = {
    'src/openwoven': {'.py', '.html', '.css', '.js'}, 'src/adaptive_companion': {'.py'}, 'tests': {'.py', '.cjs'}, 'examples': {'.py'},
    'scripts': {'.py'}, 'prompts': {'.md'}, '.github': {'.md', '.yml', '.yaml'},
    'android/app/src': {'.kt', '.xml'},
}
REQUIRED_FILES = (
    *ROOT_FILES,
    'src/openwoven/__init__.py', 'src/openwoven/__main__.py',
    'src/adaptive_companion/__init__.py', 'src/adaptive_companion/core.py',
    'scripts/package_smoke.py', 'scripts/release_preflight.py',
    '.github/workflows/core-tests.yml', '.github/workflows/android-checks.yml',
    '.github/workflows/release-candidate.yml',
    '.github/ISSUE_TEMPLATE/bug_report.md',
    '.github/ISSUE_TEMPLATE/feature_request.md', '.github/PULL_REQUEST_TEMPLATE.md',
)
SKIP_DIRS = {'.git', '.gradle', '.kotlin', '.java-tmp', '.idea', '.venv', 'venv',
             '__pycache__', '.pytest_cache', 'node_modules', 'build', 'dist', 'release-dist'}
SECRET_PATTERNS = {
    'private-key header': re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'OpenAI-style key': re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b'),
    'AWS access-key ID': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'Google API key': re.compile(r'\bAIza[A-Za-z0-9_-]{35}\b'),
}


def linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def safe_source(root: Path, relative: str) -> bool:
    path = root / relative
    # Check every component, including parents of the explicit Android files.
    for part in (path, *path.parents):
        if part == root:
            break
        if linked(part):
            return False
    return path.is_file() and path.resolve().is_relative_to(root)


def source_inventory(root: Path) -> list[str]:
    root = root.resolve(strict=True)
    selected = {name for name in ROOT_FILES if safe_source(root, name)}
    for directory, suffixes in SOURCE_TREES.items():
        base = root / directory
        if not base.is_dir() or any(linked(p) for p in (base, *base.parents) if p != root and root in p.parents):
            continue
        for current, directories, names in os.walk(base, followlinks=False):
            parent = Path(current)
            directories[:] = sorted(d for d in directories if d not in SKIP_DIRS
                                    and not d.endswith('.egg-info') and not linked(parent / d))
            for name in names:
                path = parent / name
                relative = path.relative_to(root).as_posix()
                if not name.startswith('.env') and path.suffix in suffixes and safe_source(root, relative):
                    selected.add(relative)
    return sorted(selected)


def git_read(root: Path, *arguments: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *arguments], capture_output=True,
                            encoding='utf-8', errors='strict', check=False)
    if result.returncode:
        # Do not echo Git's stderr (it may contain local paths or remote details).
        raise ValueError('Git index check failed; use a normal working checkout with Git installed')
    return result.stdout


def inspect_release(root: Path, *, for_publication=False, check_index=False,
                    assets: tuple[Path, ...] = ()) -> dict:
    root = root.resolve(strict=True)
    paths = source_inventory(root)
    blockers = []
    warnings = ['Manual privacy review, Git-history review, hosted CI and the private security-report channel are still required.',
                'No real model calls, device tests, APK signature/license audit or publication are performed.']
    for name in REQUIRED_FILES:
        if name not in paths:
            blockers.append('Missing or linked required source file: ' + name)
    texts = {}
    for name in paths:
        if name.endswith('.jar'):
            continue  # Gradle wrapper is a required binary; not a text secret scan.
        try:
            text = (root / name).read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            blockers.append('Cannot read approved UTF-8 source: ' + name)
            continue
        texts[name] = text
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    # Never include the matched value or original line in the report.
                    blockers.append(f'Possible {label}: {name}:{line_number}; review without posting the value')
    license_text = texts.get('LICENSE', '')
    if not license_text.startswith('MIT License'):
        blockers.append('LICENSE must contain the selected MIT license')
    notice = re.search(r'^Copyright \(c\) \d{4} (.+)$', license_text, re.MULTILINE)
    if not notice or '[COPYRIGHT HOLDER]' in license_text or not notice.group(1).strip():
        message = 'Copyright holder is not finalized in LICENSE'
        (blockers if for_publication else warnings).append(message)
    version = None
    try:
        project = tomllib.loads(texts.get('pyproject.toml', '')).get('project', {})
        version = project['version']
        if project.get('license') != 'MIT' or project.get('name') != 'openwoven':
            blockers.append('Python project name/license differs from the intended release')
        android_version = re.search(r'versionName\s*=\s*"([^"]+)"', texts.get('android/app/build.gradle.kts', ''))
        if not android_version or android_version.group(1) != version:
            blockers.append('Core and Android version strings do not match')
    except (KeyError, tomllib.TOMLDecodeError):
        blockers.append('Missing or invalid Python project version')
    commit = None
    if check_index:
        try:
            tracked = set(filter(None, git_read(root, 'ls-files', '-z').split('\0')))
            for name in sorted(tracked - set(paths)):
                blockers.append('Tracked file outside approved source inventory: ' + name)
            for name in sorted(set(paths) - tracked):
                blockers.append('Approved source is not staged/tracked: ' + name)
            # Scanning working files cannot approve a different (older) staged value.
            if git_read(root, 'diff', '--name-only', '-z', '--'):
                blockers.append('Working files differ from the index; review and stage the intended changes, then recheck')
            if git_read(root, 'ls-files', '--unmerged', '-z'):
                blockers.append('Unresolved Git index conflicts')
            result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
                                    capture_output=True, text=True, check=False)
            if result.returncode == 0 and re.fullmatch(r'[0-9a-f]{40,64}\s*', result.stdout):
                commit = result.stdout.strip()
        except (OSError, ValueError, UnicodeError):
            blockers.append('Git index could not be checked; initialize and review staging first')
    asset_records = []
    asset_names = set()
    for supplied in assets:
        candidate = supplied if supplied.is_absolute() else root / supplied
        if not candidate.is_relative_to(root):
            blockers.append('Release asset must be inside this checkout')
            continue
        relative = candidate.relative_to(root).as_posix()
        if candidate.suffix not in {'.whl', '.apk'} or not safe_source(root, relative):
            blockers.append('Release asset must be an existing, unlinked wheel or APK inside this checkout')
            continue
        if candidate.name in asset_names:
            blockers.append('Release asset basenames must be unique')
            continue
        asset_names.add(candidate.name)
        with candidate.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        asset_records.append({'name': candidate.name, 'path': relative,
                              'bytes': candidate.stat().st_size, 'sha256': digest})
    return {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'mode': 'publication' if for_publication else 'local-draft',
            'automated_checks_passed': not blockers, 'publication_approved': False,
            'version': version, 'head_commit': commit,
            'head_commit_is_build_provenance': False,
            'source_files': paths, 'assets': asset_records,
            'blockers': blockers, 'manual_checks': warnings}


def write_report(root: Path, output: Path, report: dict) -> Path:
    root = root.resolve(strict=True)
    relative = output.relative_to(root) if output.is_absolute() else output
    if not relative.parts or relative.parts[0] != 'release-dist' or '..' in relative.parts:
        raise ValueError('Report output must be under release-dist/ inside this checkout')
    destination = root / relative
    for part in (destination, *destination.parents):
        if part == root:
            break
        if linked(part):
            raise ValueError('Report output must not use linked paths')
    if not destination.resolve().is_relative_to(root):
        raise ValueError('Report output escapes the checkout')
    # No overwrite of an existing folder or a prior review snapshot.
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'SOURCE_FILES.txt').write_text(''.join(name + '\n' for name in report['source_files']), encoding='utf-8')
    (destination / 'SHA256SUMS.txt').write_text(''.join(f"{a['sha256']}  {a['name']}\n" for a in report['assets']), encoding='utf-8')
    return relative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--for-publication', action='store_true', help='reject unfinished copyright notice')
    parser.add_argument('--check-index', action='store_true', help='check Git tracked paths and working/index equality; no history scan')
    parser.add_argument('--asset', type=Path, action='append', default=[], help='hash an explicitly selected local wheel/APK; repeat as needed')
    parser.add_argument('--output', type=Path, help='write a new review snapshot under release-dist/; never overwrite')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = inspect_release(root, for_publication=args.for_publication,
                                 check_index=args.check_index, assets=tuple(args.asset))
        if args.output:
            relative = write_report(root, args.output, report)
            print('Review snapshot: ' + relative.as_posix())
        print(f"Approved source inventory: {len(report['source_files'])} files; selected assets: {len(report['assets'])}")
        for blocker in report['blockers']:
            print('BLOCK: ' + blocker)
        for warning in report['manual_checks']:
            print('REVIEW: ' + warning)
        print('Automated checks ' + ('passed' if report['automated_checks_passed'] else 'blocked') + '; nothing committed or uploaded.')
        return 0 if report['automated_checks_passed'] else 1
    except (OSError, ValueError) as exc:
        # Paths/values from OS errors are intentionally not included.
        print('BLOCK: cannot create this review snapshot; choose a new, unlinked release-dist/ subfolder and valid inputs (' + type(exc).__name__ + ')')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
