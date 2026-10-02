"""Bounded, app-private JPEG attachments; never include binary data in memory."""
from __future__ import annotations

import base64
from pathlib import Path


class Attachments:
    def __init__(self, store, root: str | None = None):
        self.store = store
        self.root = Path(root).resolve() if root else None

    def checked(self, path: str) -> Path:
        target = Path(path).resolve()
        if not self.root or target.parent != self.root or target.suffix != '.jpg':
            raise ValueError('Image must be inside app-private attachments')
        if not target.is_file() or not 0 < target.stat().st_size <= 2_000_000:
            raise ValueError('Invalid or oversized image')
        with target.open('rb') as stream:
            if stream.read(3) != b'\xff\xd8\xff':
                raise ValueError('Invalid JPEG attachment')
        return target

    def save(self, message_id: str, path: str) -> None:
        if path:
            self.store.set_metadata('attachment:' + message_id, str(self.checked(path)))

    def path(self, message_id: str) -> str | None:
        return self.store.get_metadata('attachment:' + message_id)

    def for_turn(self, ids: list[str]) -> list[str]:
        paths = [self.path(key) for key in ids]
        images = [str(self.checked(path)) for path in paths if path]
        if len(images) > 4:
            raise ValueError('At most four images per turn')
        return ['data:image/jpeg;base64,' + base64.b64encode(Path(path).read_bytes()).decode('ascii') for path in images]

    def remove(self, ids: list[str]) -> None:
        # Resolve before deleting metadata; unlink only explicitly associated files.
        for key in ids:
            path = self.path(key)
            if path and self.root:
                target = Path(path).resolve()
                if target.parent == self.root and target.suffix == '.jpg':
                    target.unlink(missing_ok=True)
            with self.store.connection() as conn:
                conn.execute('DELETE FROM metadata WHERE key=?', ('attachment:' + key,))
                conn.commit()
