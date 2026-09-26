"""Rebuildable SQLite search cache for immutable history chunks, not save data."""

import json
import re
import sqlite3
import threading
from contextlib import closing

from backend.services.storage_paths import contained_path

_lock = threading.RLock()


def _query(db, character, root, before_id, limit, query):
    from backend.services.conversation_archive_service import _read, history_count
    db.executescript('''
        CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, stamp TEXT, count INTEGER);
        CREATE TABLE IF NOT EXISTS messages (chunk_id TEXT, offset INTEGER, message_id TEXT, raw TEXT, text TEXT);
        CREATE INDEX IF NOT EXISTS message_identity ON messages(message_id);
        CREATE INDEX IF NOT EXISTS message_chunk ON messages(chunk_id, offset);
        CREATE TEMP TABLE active (id TEXT, base INTEGER);
        CREATE INDEX active_id ON active(id);
        CREATE TEMP TABLE recent (position INTEGER, message_id TEXT, raw TEXT, text TEXT);
    ''')
    try:
        new_search = db.execute("SELECT 1 FROM sqlite_master WHERE name='search'").fetchone() is None
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text, tokenize='trigram')")
        if new_search:
            db.execute('INSERT INTO search(rowid,text) SELECT rowid,text FROM messages')
        fts = True
    except sqlite3.OperationalError:
        fts = False
    base = 0
    for chunk in character.get('conversation_archive', {}).get('chunks', []):
        identity = chunk.get('id', '')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
            raise ValueError('剧情档案标识无效')
        path = contained_path(root, '_history', identity + '.json')
        try:
            stat = path.stat()
        except OSError as exc:
            raise ValueError('剧情档案缺失，请恢复完整备份') from exc
        stamp = f'{stat.st_mtime_ns}:{stat.st_ctime_ns}:{stat.st_size}'
        cached = db.execute('SELECT stamp, count FROM chunks WHERE id=?', (identity,)).fetchone()
        if cached != (stamp, chunk.get('count')):
            messages = _read(chunk, root)
            if fts:
                db.execute('DELETE FROM search WHERE rowid IN (SELECT rowid FROM messages WHERE chunk_id=?)', (identity,))
            db.execute('DELETE FROM messages WHERE chunk_id=?', (identity,))
            for offset, item in enumerate(messages):
                text = (str(item.get('speaker', '')) + ' ' + str(item.get('content', ''))).casefold()
                row = db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
                                 (identity, offset, item.get('message_id'), json.dumps(item, ensure_ascii=False), text))
                if fts:
                    db.execute('INSERT INTO search(rowid,text) VALUES (?,?)', (row.lastrowid, text))
            db.execute('INSERT OR REPLACE INTO chunks VALUES (?,?,?)', (identity, stamp, len(messages)))
        db.execute('INSERT INTO active VALUES (?,?)', (identity, base))
        base += chunk['count']
    for offset, item in enumerate(character.get('conversation_history', [])):
        text = (str(item.get('speaker', '')) + ' ' + str(item.get('content', ''))).casefold()
        db.execute('INSERT INTO recent VALUES (?,?,?,?)', (base + offset, item.get('message_id'), json.dumps(item, ensure_ascii=False), text))
    db.execute('''CREATE TEMP VIEW current_messages AS
        SELECT a.base+m.offset AS position, m.message_id, m.raw, m.text, m.rowid AS row_id
        FROM messages m JOIN active a ON a.id=m.chunk_id
        UNION ALL SELECT position, message_id, raw, text, NULL FROM recent''')
    before = history_count(character)
    if before_id:
        found = db.execute('SELECT MAX(position) FROM current_messages WHERE message_id=?', (before_id,)).fetchone()[0]
        if found is None:
            raise ValueError('剧情记录已改变，请重新加载角色')
        before = found
    needle = query.strip().casefold()
    where, values = 'position < ?', [before]
    if needle:
        where += ' AND instr(text, ?) > 0'
        values.append(needle)
        if fts and len(needle) >= 3:
            where += ' AND (row_id IS NULL OR row_id IN (SELECT rowid FROM search WHERE search MATCH ?))'
            values.append('"' + needle.replace('"', '""') + '"')
    rows = db.execute(f'SELECT position,raw FROM current_messages WHERE {where} ORDER BY position DESC LIMIT ?',
                      (*values, limit + 1)).fetchall()
    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    db.commit()
    return {'messages': [json.loads(raw) for _, raw in rows], 'indices': [position for position, _ in rows],
            'start': rows[0][0] if rows else 0, 'total': history_count(character), 'has_more': has_more}


def indexed_history_page(character, root, before_id, limit, query):
    path = contained_path(root, '_history_search_v1.sqlite3')
    with _lock:
        for attempt in range(2):
            try:
                with closing(sqlite3.connect(path)) as db:
                    return _query(db, character, root, before_id, limit, query)
            except sqlite3.DatabaseError as exc:
                code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
                if attempt or code not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                    raise
                path.unlink(missing_ok=True)
