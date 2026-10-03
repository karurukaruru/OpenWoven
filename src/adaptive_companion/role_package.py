"""Portable, role-only packages. No archive member is extracted to disk."""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import sqlite3
import uuid
import zipfile
import zlib

from .character_book import MAX_FACTS, _validated_facts

MAX_INPUT = 8 * 1024 * 1024
MAX_JSON = 512 * 1024
ROLE_KEYS = {'preset', 'name', 'description', 'boundaries'}


def _json(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def clean_role(role):
    if not isinstance(role, dict):
        raise ValueError('Invalid role')
    result = {}
    for key, limit in (('name', 40), ('description', 600), ('boundaries', 300)):
        value = role.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Role field too long: ' + key)
        result[key] = value.strip()
    result['preset'] = role.get('preset', 'custom')
    if result['preset'] not in ('companion', 'listener', 'playful', 'coach', 'custom'):
        raise ValueError('Invalid role preset')
    return result


def clean_facts(facts):
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        raise ValueError('Too many character facts')
    result, seen = [], set()
    for item in facts:
        if not isinstance(item, dict) or not isinstance(item.get('value'), str):
            raise ValueError('Invalid character fact')
        validated = _validated_facts([item], item['value'])[0]
        if validated['path'] in seen:
            raise ValueError('Duplicate character chapter')
        seen.add(validated['path'])
        if validated['path'] != 'identity/name':
            result.append(validated)
    return result


def export_package(role, facts=()):
    files = {'role.json': _json(clean_role(role)), 'facts.json': _json(clean_facts(list(facts)))}
    manifest = {'format': 'openwoven-role', 'version': 1,
                'sha256': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', _json(manifest))
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def _load(raw):
    if len(raw) > MAX_JSON:
        raise ValueError('Role JSON too large')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid role JSON') from exc


def _card(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid character card')
    if data.get('spec') not in (None, 'chara_card_v2', 'chara_card_v3'):
        raise ValueError('Unsupported character card')
    card = data.get('data') if data.get('spec') else data
    if not isinstance(card, dict) or not all(isinstance(card.get(k), str) for k in ('name', 'description')):
        raise ValueError('Expected a character card with name and description')
    text = '\n'.join(card[k] for k in ('description', 'personality', 'scenario')
                     if isinstance(card.get(k), str) and card[k].strip())
    warnings = ['Card conversion imports basic role text only; greetings, prompt overrides, scripts and lorebooks are not executed or imported.']
    if len(text) > 600 or len(card['name']) > 40:
        warnings.append('Role text is shortened to the app limits (name 40, description 600 characters).')
    return {'role': clean_role({'name': card['name'][:40], 'description': text[:600]}),
            'facts': [], 'warnings': warnings}


def _png(raw):
    offset = 8
    cards = []
    while offset + 12 <= len(raw):
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError('Truncated PNG')
        chunk = raw[offset + 8:end - 4]
        if kind == b'tEXt' and chunk.split(b'\0', 1)[0] in (b'chara', b'ccv3'):
            if length > MAX_JSON * 2 or zlib.crc32(kind + chunk) != struct.unpack('>I', raw[end - 4:end])[0]:
                raise ValueError('Invalid character PNG metadata')
            try:
                cards.append((chunk.split(b'\0', 1)[0], base64.b64decode(chunk.split(b'\0', 1)[1], validate=True)))
            except (ValueError, IndexError) as exc:
                raise ValueError('Invalid character PNG encoding') from exc
        offset = end
        if kind == b'IEND':
            break
    if not cards or len(cards) > 2 or len({key for key, _ in cards}) != len(cards):
        raise ValueError('No supported character metadata in PNG')
    return _card(_load(dict(cards).get(b'ccv3', cards[0][1])))


def import_package(raw: bytes):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_INPUT:
        raise ValueError('Role file exceeds 8 MiB or is empty')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return _png(raw)
    if raw.startswith(b'PK'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                names = [x.filename for x in infos]
                if len(infos) > 4 or len(set(names)) != len(names):
                    raise ValueError('Invalid role archive members')
                for item in infos:
                    if not re.fullmatch(r'[A-Za-z0-9_-]+\.json', item.filename) or item.flag_bits & 1 or (
                        item.external_attr >> 16 & 0o170000) == 0o120000 or item.file_size > MAX_JSON:
                        raise ValueError('Unsafe role archive member')
                if sum(x.file_size for x in infos) > MAX_JSON * 3:
                    raise ValueError('Role archive too large')
                if set(names) == {'manifest.json', 'role.json', 'facts.json'}:
                    manifest = _load(archive.read('manifest.json'))
                    if not isinstance(manifest, dict) or manifest.get('format') != 'openwoven-role' or manifest.get('version') != 1:
                        raise ValueError('Unsupported role package version')
                    contents = {name: archive.read(name) for name in ('role.json', 'facts.json')}
                    if manifest.get('sha256') != {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}:
                        raise ValueError('Role package checksum mismatch')
                    role = _load(contents['role.json'])
                    if not isinstance(role, dict) or set(role) - ROLE_KEYS:
                        raise ValueError('Unexpected private data in role package')
                    return {'role': clean_role(role), 'facts': clean_facts(_load(contents['facts.json'])), 'warnings': []}
                if len(names) == 1 and names[0] != 'manifest.json':
                    return _card(_load(archive.read(names[0])))
                raise ValueError('Expected an OpenWoven role ZIP or a single character-card JSON')
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error) as exc:
            raise ValueError('Invalid role ZIP') from exc
    return _card(_load(raw))


class RoleLibrary:
    """Private local library. Imported IDs/paths are never used as filenames."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def valid_id(role_id):
        if not isinstance(role_id, str) or not re.fullmatch(r'legacy|[0-9a-f]{32}', role_id):
            raise ValueError('Invalid local role ID')
        return role_id

    def path(self, role_id):
        return self.root / (self.valid_id(role_id) + '.json')

    def read(self, role_id):
        data = _load(self.path(role_id).read_bytes())
        return {'id': role_id, 'role': clean_role(data['role']), 'facts': clean_facts(data['facts']),
                'canon_id': str(data.get('canon_id', role_id))[:80]}

    def save(self, role_id, role, facts, canon_id=None):
        path = self.path(role_id)
        data = {'role': clean_role(role), 'facts': clean_facts(facts)}
        if canon_id:
            data['canon_id'] = str(canon_id)[:80]
        temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(_json(data))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.read(role_id)

    def add(self, preview):
        if len(self.list()) >= 32:
            raise ValueError('Role library is full (32 roles)')
        return self.save(uuid.uuid4().hex, preview['role'], preview.get('facts', []))

    def list(self):
        result = []
        for path in sorted(self.root.glob('*.json')):
            try:
                if not path.is_symlink():
                    item = self.read(path.stem)
                    result.append({'id': item['id'], 'role': item['role'], 'fact_count': len(item['facts'])})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result


def stored_role_facts(library, role_id, database_root):
    """Read inactive canon without starting a Core or copying source-linked facts."""
    item = library.read(role_id)
    name = 'adaptive_companion.db' if role_id == 'legacy' else f'role_{role_id}.db'
    path = Path(database_root) / name
    if not path.exists():
        return item['facts']
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        facts = {x['path']: x['value'] for x in item['facts']}
        for table in ('character_facts', 'imported_character_facts'):
            if table in tables:
                for key, value in conn.execute(f'SELECT path,value FROM {table} WHERE character_id=? LIMIT 512',
                                               (item['canon_id'],)):
                    facts[key] = value
    return clean_facts([{'path': key, 'value': value} for key, value in sorted(facts.items())])
