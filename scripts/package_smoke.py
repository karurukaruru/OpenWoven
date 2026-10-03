"""Check a built wheel in an isolated temporary environment, without a provider.

Build first: python -m pip wheel --no-deps --wheel-dir dist .
Use --for-publication to also reject an unfinished copyright notice.
This checks a Python wheel, not a signed Android release or a security audit.
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
import venv
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


def validate_wheel(wheel: Path, for_publication=False):
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_files = [n for n in names if n.endswith('.dist-info/METADATA')]
        license_files = [n for n in names if n.endswith('.dist-info/licenses/LICENSE')]
        if len(metadata_files) != 1 or len(license_files) != 1:
            raise ValueError('wheel must include one package metadata file and its MIT LICENSE')
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        if metadata['Name'] != 'openwoven':
            raise ValueError('unexpected distribution name')
        if metadata['License-Expression'] != 'MIT' or metadata.get_all('Requires-Dist'):
            raise ValueError('expected MIT metadata and no third-party runtime dependencies')
        license_text = archive.read(license_files[0]).decode('utf-8')
        if not license_text.startswith('MIT License'):
            raise ValueError('unexpected license text')
        if for_publication and '[COPYRIGHT HOLDER]' in license_text:
            raise ValueError('fill the copyright-holder placeholder before publication')
        for name in names:
            root = name.split('/', 1)[0]
            if root not in {'adaptive_companion', 'openwoven'} and not root.endswith('.dist-info'):
                raise ValueError('unexpected payload outside the Core package: ' + name)
        for required in ('core', 'retrieval', 'android_bridge', 'onboarding', 'character_interview', 'character_book', 'role_package'):
            if f'adaptive_companion/{required}.py' not in names:
                raise ValueError('required module missing: ' + required)

        for required in ('__init__', '__main__', 'web'):
            if f'openwoven/{required}.py' not in names:
                raise ValueError('required public module missing: ' + required)
        for required in ('index.html', 'style.css', 'app.js'):
            if f'openwoven/static/{required}' not in names:
                raise ValueError('required Web asset missing: ' + required)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', nargs='?', type=Path)
    parser.add_argument('--for-publication', action='store_true')
    args = parser.parse_args()
    if args.wheel is None:
        wheels = list(Path('dist').glob('openwoven-*.whl'))
        if len(wheels) != 1:
            parser.error('provide one wheel path, or build exactly one matching wheel in dist/')
        args.wheel = wheels[0]
    wheel = args.wheel.resolve(strict=True)
    validate_wheel(wheel, args.for_publication)
    with tempfile.TemporaryDirectory(prefix='companion-package-smoke-') as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root)
        python = root / ('Scripts/python.exe' if (root / 'Scripts').exists() else 'bin/python')
        subprocess.run([str(python), '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', str(wheel)],
                       cwd=root, check=True)
        # Isolated mode ignores PYTHONPATH and current-directory imports. Running
        # outside the checkout verifies the distribution, not an editable link.
        # -I ignores PYTHONUTF8, so pass UTF-8 explicitly for Windows CI/logs.
        subprocess.run([str(python), '-I', '-X', 'utf8', '-m', 'openwoven', '--db', ':memory:', 'demo'],
                       cwd=root, check=True)
        subprocess.run([str(python), '-I', '-X', 'utf8', '-m', 'adaptive_companion', '--help'],
                       cwd=root, check=True)
        subprocess.run([str(python), '-I', '-X', 'utf8', '-m', 'openwoven.web', '--help'],
                       cwd=root, check=True)
        subprocess.run([str(python), '-I', '-c',
                        'from openwoven import CompanionCore; from adaptive_companion import CompanionCore as Legacy; assert CompanionCore is Legacy'],
                       cwd=root, check=True)
        scripts = python.parent
        for command in ('openwoven', 'companion'):
            executable = scripts / (command + '.exe' if (root / 'Scripts').exists() else command)
            subprocess.run([str(executable), '--help'], cwd=root, check=True)
    print('PASS: packaged modules, MIT metadata/license, offline demo and compatible entry points.')
    print('Not an APK, provider-quality test, secret scan or GitHub publication.')


if __name__ == '__main__':
    main()
