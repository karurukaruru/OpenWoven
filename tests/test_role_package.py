from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

from adaptive_companion import android_bridge
from adaptive_companion.character_book import CharacterCanonConflict
from adaptive_companion.core import CompanionCore
from adaptive_companion.persona import build_persona
from adaptive_companion.role_package import (RoleLibrary, clean_facts, export_package, import_package, MAX_INPUT)

ROLE = {'name': '小岚', 'description': '喜欢园艺，讲话简短', 'preset': 'custom', 'boundaries': ''}
FACT = {'path': 'education/high_school/school', 'value': '星河中学'}


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as out:
        for name, value in files:
            out.writestr(name, value)
    return buffer.getvalue()


class RolePackageTests(unittest.TestCase):
    def test_round_trip_excludes_private_fields_and_local_id(self):
        raw = export_package({**ROLE, 'interview': {'q01': 'private'}, 'api_key': 'synthetic-private',
                              'character_id': '../unsafe', 'user_profile': 'private'}, [FACT])
        preview = import_package(raw)
        self.assertEqual(ROLE, preview['role'])
        self.assertEqual([FACT], preview['facts'])
        with zipfile.ZipFile(io.BytesIO(raw)) as out:
            self.assertEqual({'manifest.json', 'role.json', 'facts.json'}, set(out.namelist()))
            for name in out.namelist():
                self.assertNotIn(b'private', out.read(name))

    def test_unsafe_archives_and_bombs_are_rejected(self):
        for files in ([('../role.json', '{}')], [('C:\\role.json', '{}')], [('role.json', '{}'), ('role.json', '{}')],
                      [('huge.json', ' ' * (512 * 1024 + 1))], [('role.json', '{}'), ('database.db', 'private')]):
            with self.subTest(files=[name for name, _ in files]):
                with self.assertRaises(ValueError):
                    import_package(archive(files))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as out:
            info = zipfile.ZipInfo('card.json')
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            out.writestr(info, '{}')
        with self.assertRaises(ValueError):
            import_package(buffer.getvalue())
        with self.assertRaises(ValueError):
            import_package(b'x' * (MAX_INPUT + 1))

    def test_checksum_and_duplicate_json_keys_are_rejected(self):
        raw = export_package(ROLE, [FACT])
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            files = [(name, source.read(name)) for name in source.namelist()]
        files[-1] = ('facts.json', b'[]')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            import_package(archive(files))
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            import_package(b'{"name":"a","name":"b","description":"c"}')

    def test_external_cards_convert_basic_fields_only_and_warn(self):
        for spec in (None, 'chara_card_v2', 'chara_card_v3'):
            card = {'name': 'Case', 'description': 'd' * 700, 'personality': 'calm',
                    'system_prompt': 'never_execute', 'extensions': {'secret': 'never_export'}}
            raw = json.dumps({'spec': spec, 'data': card} if spec else card).encode()
            converted = import_package(raw)
            self.assertEqual(600, len(converted['role']['description']))
            self.assertEqual(2, len(converted['warnings']))
            self.assertNotIn('never_execute', str(converted))
            self.assertNotIn('never_export', str(converted))
            self.assertEqual([], converted['facts'])
        converted = import_package(archive([('card.json', json.dumps({'name': 'Case', 'description': 'calm'}))]))
        self.assertEqual('Case', converted['role']['name'])

    def test_png_metadata_conversion_checks_crc(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        text = b'chara\0' + base64.b64encode(json.dumps({'name': 'Case', 'description': 'calm'}).encode())
        raw = b'\x89PNG\r\n\x1a\n' + chunk(b'tEXt', text) + chunk(b'IEND', b'')
        self.assertEqual('Case', import_package(raw)['role']['name'])
        damaged = bytearray(raw)
        damaged[-13] ^= 1
        with self.assertRaises(ValueError):
            import_package(bytes(damaged))

    def test_invalid_canon_paths_and_duplicates_rejected(self):
        for facts in ([{'path': '../private', 'value': 'x'}], [FACT, FACT],
                      [{'path': 'experiences/travel/2026_02_30/location', 'value': 'x'}], [FACT] * 513):
            with self.assertRaises(ValueError):
                clean_facts(facts)

    def test_library_assigns_local_ids_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            library = RoleLibrary(root)
            saved = library.add({'role': ROLE, 'facts': [FACT], 'id': '../injected'})
            self.assertRegex(saved['id'], r'^[0-9a-f]{32}$')
            self.assertEqual(saved, RoleLibrary(root).read(saved['id']))
            self.assertEqual(1, library.list()[0]['fact_count'])
            with self.assertRaises(ValueError):
                library.read('../injected')

    def test_seeded_canon_retrieves_without_fake_chat_and_prevents_conflict(self):
        with CompanionCore(':memory:', persona=build_persona({**ROLE, 'character_id': 'case'}), learning_enabled=False) as core:
            core.character_book.seed([FACT])
            self.assertEqual([FACT], core.character_book.retrieve('高中'))
            self.assertEqual(0, core.store.count_messages())
            self.assertNotIn('星河中学', json.dumps(core.aul(), ensure_ascii=False))
            with self.assertRaises(CharacterCanonConflict):
                core.character_book.update([{**FACT, 'value': '另一所学校'}])
            core.store.clear_user_data()
            self.assertEqual([FACT], core.character_book.entries())
            with core.store.connection() as conn:
                self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_android_bridge_exports_current_canon_without_user_data(self):
        with tempfile.TemporaryDirectory() as root:
            config = {'persona': ROLE, 'role_library': str(Path(root) / 'roles')}
            android_bridge.initialize(str(Path(root) / 'legacy.db'), json.dumps(config))
            try:
                android_bridge._require_core().character_book.seed([FACT])
                android_bridge._require_core().store.save_message('default', 'user', 'private user message')
                rows = json.loads(android_bridge.list_roles())
                self.assertEqual('legacy', rows[0]['id'])
                raw = base64.b64decode(android_bridge.export_role('legacy'))
                self.assertEqual([FACT], import_package(raw)['facts'])
                self.assertNotIn('private user message', str(import_package(raw)))
            finally:
                android_bridge._core.close()
                android_bridge._core = None

    def test_restart_does_not_promote_source_linked_facts_to_imported_seeds(self):
        with tempfile.TemporaryDirectory() as root:
            database = str(Path(root) / 'adaptive_companion.db')
            config = json.dumps({'persona': ROLE, 'role_library': str(Path(root) / 'roles')})
            android_bridge.initialize(database, config)
            try:
                core = android_bridge._require_core()
                message = core.store.save_message('default', 'assistant', FACT['value'])
                update = core.character_book.update([FACT])
                with core.store.connection() as conn:
                    core.character_book.commit(conn, message.id, update)
                    conn.commit()
                android_bridge.list_roles()
                android_bridge.initialize(database, config)
                core = android_bridge._require_core()
                self.assertEqual([FACT], core.character_book.entries())
                core.delete_message(message.id)
                self.assertEqual([], core.character_book.entries())
                self.assertEqual([], json.loads(android_bridge.preview_role(android_bridge.export_role('legacy')))['facts'])
            finally:
                android_bridge._core.close()
                android_bridge._core = None


if __name__ == '__main__':
    unittest.main()
