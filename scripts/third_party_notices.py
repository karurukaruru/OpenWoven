"""Generate a reviewed redistribution notice from runtime POMs and upstream licenses.

Writes only generated build output. This preparation step needs network access;
normal APK builds use the checked-in notice and remain usable offline.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import tomllib


LICENSES = {
    'Chaquopy 17.0.0 — MIT': 'https://raw.githubusercontent.com/chaquo/chaquopy/17.0.0/LICENSE.txt',
    'CPython 3.13.9 — PSF and historical licenses': 'https://raw.githubusercontent.com/python/cpython/v3.13.9/LICENSE',
    'CPython incorporated components and acknowledgements': 'https://raw.githubusercontent.com/python/cpython/v3.13.9/Doc/license.rst',
    'Apache License 2.0 — AndroidX, Kotlin, Okio, Guava and JSpecify': 'https://www.apache.org/licenses/LICENSE-2.0.txt',
    'OpenSSL 3.0.18 — Apache License 2.0': 'https://raw.githubusercontent.com/openssl/openssl/openssl-3.0.18/LICENSE.txt',
    'libffi 3.4.4 — MIT': 'https://raw.githubusercontent.com/libffi/libffi/v3.4.4/LICENSE',
    'bzip2 1.0.8 — BSD-style license': 'https://raw.githubusercontent.com/libarchive/bzip2/bzip2-1.0.8/LICENSE',
    'XZ 5.4.6 — liblzma is public domain; xz command-line utilities are NOT included': 'https://raw.githubusercontent.com/tukaani-project/xz/v5.4.6/COPYING',
}


def fetch_license(item, proxy):
    title, url = item
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy} if proxy else {}))
    with opener.open(url, timeout=30) as response:
        text = response.read(250_000).decode('utf-8')
    if len(text) < 100 or '<html' in text.lower():
        raise ValueError('invalid upstream license: ' + title)
    return title, url, text


def generate(root, cache, proxy):
    result = subprocess.run([str(root / 'android/gradlew.bat'), ':app:printRuntimeInventory', '--offline', '--no-daemon'],
        cwd=root / 'android', capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
    coordinates = sorted({line.removeprefix('RUNTIME ').strip() for line in result.stdout.splitlines() if line.startswith('RUNTIME ')})
    if len(coordinates) < 20:
        raise ValueError('incomplete runtime inventory')
    version = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    sections = [f'OpenWoven {version} — third-party notices\n\n'
        'Project source: MIT, Copyright (c) 2026 karurukaruru. Dependencies retain their own licenses.\n'
        'Runtime inventory: fullDebugRuntimeClasspath. Test-only and host build tools are excluded.\n'
        'Python is the Chaquopy 3.13.9-0 Android distribution; this app makes no additional CPython changes.\n'
        'Native versions follow CPython 3.13.9/Android/android.py. SQLite 3.50.4 is public domain:\n'
        'https://sqlite.org/copyright.html . liblzma is included, not the GPL xz command-line program.\n'
        'System Android libraries are supplied by the device, not redistributed in this APK.\n']
    notices = {}
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    def read_pom(coordinate):
        group, artifact, version = coordinate.split(':')
        poms = list((cache / group / artifact / version).glob('*/*.pom'))
        if poms:
            return coordinate, poms[0].read_bytes()
        base = 'https://dl.google.com/dl/android/maven2/' if group.startswith('androidx.') else 'https://repo.maven.apache.org/maven2/'
        url = base + group.replace('.', '/') + f'/{artifact}/{version}/{artifact}-{version}.pom'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy} if proxy else {}))
        with opener.open(url, timeout=30) as response:
            return coordinate, response.read(250_000)
    with ThreadPoolExecutor(max_workers=12) as workers:
        pom_data = dict(workers.map(read_pom, coordinates))
    for coordinate in coordinates:
        group, artifact, version = coordinate.split(':')
        directory = cache / group / artifact / version
        pom = ET.fromstring(pom_data[coordinate])
        licenses = [' | '.join(filter(None, [node.findtext('m:name', namespaces=ns), node.findtext('m:url', namespaces=ns)]))
                    for node in pom.findall('m:licenses/m:license', ns)]
        parent = pom.find('m:parent', ns)
        if not licenses and parent is not None:
            parent_id = ':'.join(parent.findtext('m:' + field, namespaces=ns) for field in ('groupId', 'artifactId', 'version'))
            parent_pom = ET.fromstring(read_pom(parent_id)[1])
            licenses = [' | '.join(filter(None, [node.findtext('m:name', namespaces=ns), node.findtext('m:url', namespaces=ns)]))
                        for node in parent_pom.findall('m:licenses/m:license', ns)]
        if not licenses:
            raise ValueError('missing runtime license declaration: ' + coordinate)
        sections.append(coordinate + '\n  ' + '; '.join(licenses) + '\n')
        for archive in (*directory.glob('*/*.jar'), *directory.glob('*/*.aar')):
            with zipfile.ZipFile(archive) as package:
                packages = [package]
                if 'classes.jar' in package.namelist():
                    packages.append(zipfile.ZipFile(io.BytesIO(package.read('classes.jar'))))
                for nested in packages:
                    for name in nested.namelist():
                        if any(word in Path(name).name.lower() for word in ('license', 'notice', 'copying')) and not name.endswith('/'):
                            data = nested.read(name)
                            try:
                                text = data.decode('utf-8')
                            except UnicodeDecodeError:
                                continue
                            if len(text) > 100:
                                notices.setdefault(hashlib.sha256(data).hexdigest(), (coordinate + ' / ' + name, text))
    with ThreadPoolExecutor(max_workers=8) as workers:
        for title, url, text in workers.map(lambda item: fetch_license(item, proxy), LICENSES.items()):
            sections.append('\n' + '=' * 70 + '\n' + title + '\nSource: ' + url + '\n\n' + text)
    # Preserve license/NOTICE texts shipped in resolved JVM artifacts.
    for title, text in notices.values():
        sections.append('\n' + '=' * 70 + '\n' + title + '\n\n' + text)
    # Chaquopy bootstrap includes setuptools and pyelftools, with their own notices.
    with zipfile.ZipFile(root / 'android/app/build/outputs/apk/full/debug/app-full-debug.apk') as package:
        with zipfile.ZipFile(io.BytesIO(package.read('assets/chaquopy/bootstrap.imy'))) as bootstrap:
            included = 0
            for path in bootstrap.namelist():
                if 'license' in path.lower() and not path.endswith('/'):
                    sections.append('\n' + '=' * 70 + '\n' + path + '\n\n' + bootstrap.read(path).decode('utf-8'))
                    included += 1
            if included < 2:
                raise ValueError('incomplete bootstrap license inventory')
    output = root / 'build/release-tools/THIRD_PARTY_NOTICES.txt'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(sections), encoding='utf-8')
    print(f'Generated {output.name}: {len(coordinates)} JVM dependencies; {len(notices)} embedded license texts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--proxy', default='')
    args = parser.parse_args()
    generate(Path(__file__).resolve().parents[1], args.cache, args.proxy)
