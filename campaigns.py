"""Transactional local storage for named scheduling campaigns."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid
from inline_availability import performer_key, performer_value, request_signature, sync_inline_performers


def default_campaign_path():
    return Path.home() / 'Library' / 'Application Support' / 'MHW Scheduler' / 'campaigns.sqlite3'


class CampaignStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_campaign_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(campaigns)')}
            if 'folder_id' not in columns:
                connection.execute('ALTER TABLE campaigns ADD COLUMN folder_id TEXT')
            connection.execute('CREATE TABLE IF NOT EXISTS folders (id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE)')
            folder_columns = {row['name'] for row in connection.execute('PRAGMA table_info(folders)')}
            if 'position' not in folder_columns:
                connection.execute('ALTER TABLE folders ADD COLUMN position INTEGER NOT NULL DEFAULT 0')
                # Preserve the alphabetical order shown by earlier versions.
                folders = connection.execute('SELECT id FROM folders ORDER BY name COLLATE NOCASE').fetchall()
                connection.executemany('UPDATE folders SET position = ? WHERE id = ?',
                                       [(index, row['id']) for index, row in enumerate(folders)])
            connection.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def get_setting(self, key, default=None):
        with self._connect() as connection:
            row = connection.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row['value'] if row is not None else default

    def set_setting(self, key, value):
        with self._connect() as connection:
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) '
                               'ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _name(name, kind='schedule'):
        name = name.strip()
        if not name:
            raise ValueError(f'Enter a {kind} name.')
        return name

    def list_campaigns(self, query='', folder_id=None):
        with self._connect() as connection:
            rows = connection.execute('''SELECT campaigns.*, folders.name AS folder_name FROM campaigns
                LEFT JOIN folders ON campaigns.folder_id = folders.id
                ORDER BY updated_at DESC, campaigns.name''').fetchall()
        schedules = []
        query = query.strip().casefold()
        for row in rows:
            schedule = dict(row)
            data = json.loads(schedule.pop('data'))
            schedule['notes'] = data.get('notes', '')
            if folder_id is not None and (schedule['folder_id'] or '') != folder_id:
                continue
            if query:
                names = [person.get('name', '') for field in ('performers', 'availability_drafts')
                         for person in data.get(field, [])]
                searchable = [schedule['name'], schedule['folder_name'] or '', schedule['notes'], *names]
                if not any(query in value.casefold() for value in searchable):
                    continue
            schedules.append(schedule)
        return schedules

    def list_folders(self):
        with self._connect() as connection:
            return [dict(row) for row in connection.execute('SELECT id, name FROM folders ORDER BY position, name COLLATE NOCASE')]

    def reorder_folders(self, folder_ids):
        folder_ids = list(folder_ids)
        with self._connect() as connection:
            current = {row['id'] for row in connection.execute('SELECT id FROM folders')}
            if len(folder_ids) != len(current) or set(folder_ids) != current:
                raise ValueError('The folder list changed. Please try reordering it again.')
            connection.executemany('UPDATE folders SET position = ? WHERE id = ?',
                                   [(index, folder_id) for index, folder_id in enumerate(folder_ids)])

    def create_folder(self, name):
        folder_id = str(uuid.uuid4())
        self._write_folder('INSERT INTO folders (id, name, position) VALUES (?, ?, '
                           '(SELECT COALESCE(MAX(position), -1) + 1 FROM folders))',
                           (folder_id, self._name(name, 'folder')))
        return folder_id

    def rename_folder(self, folder_id, name):
        self._write_folder('UPDATE folders SET name = ? WHERE id = ?', (self._name(name, 'folder'), folder_id))

    def delete_folder(self, folder_id):
        if not folder_id:
            raise ValueError('Choose a folder you created.')
        with self._connect() as connection:
            self._check_folder(connection, folder_id)
            connection.execute('UPDATE campaigns SET folder_id = NULL WHERE folder_id = ?', (folder_id,))
            connection.execute('DELETE FROM folders WHERE id = ?', (folder_id,))

    def _write_folder(self, sql, values):
        try:
            with self._connect() as connection:
                if connection.execute(sql, values).rowcount != 1:
                    raise ValueError('This folder no longer exists.')
        except sqlite3.IntegrityError:
            raise ValueError('A folder with that name already exists.') from None

    @staticmethod
    def _check_folder(connection, folder_id):
        if folder_id and connection.execute('SELECT id FROM folders WHERE id = ?', (folder_id,)).fetchone() is None:
            raise ValueError('This folder no longer exists.')

    def move_to_folder(self, campaign_ids, folder_id):
        with self._connect() as connection:
            self._check_folder(connection, folder_id)
            for campaign_id in campaign_ids:
                if connection.execute('UPDATE campaigns SET folder_id = ?, updated_at = ? WHERE id = ?',
                                      (folder_id or None, self._now(), campaign_id)).rowcount != 1:
                    raise ValueError('This schedule no longer exists.')

    def set_notes(self, campaign_id, notes):
        self.update_fields(campaign_id, {'notes': notes})

    def create(self, name, folder_id=None):
        campaign_id = str(uuid.uuid4())
        with self._connect() as connection:
            self._check_folder(connection, folder_id)
            connection.execute('INSERT INTO campaigns (id, name, data, updated_at, folder_id) VALUES (?, ?, ?, ?, ?)',
                               (campaign_id, self._name(name), '{}', self._now(), folder_id or None))
        return campaign_id

    def load(self, campaign_id):
        with self._connect() as connection:
            row = connection.execute('SELECT * FROM campaigns WHERE id = ?', (campaign_id,)).fetchone()
        if row is None:
            raise ValueError('This schedule no longer exists.')
        result = dict(row)
        result['data'] = json.loads(result['data'])
        return result

    def save(self, campaign_id, data):
        serialized = json.dumps(data, ensure_ascii=False)
        self._update('UPDATE campaigns SET data = ?, updated_at = ? WHERE id = ?',
                     (serialized, self._now(), campaign_id))

    def _mutate_data(self, campaign_id, change):
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT data FROM campaigns WHERE id = ?', (campaign_id,)).fetchone()
            if row is None:
                raise ValueError('This schedule no longer exists.')
            data = json.loads(row['data'])
            result = change(data)
            if result is not False:
                connection.execute('UPDATE campaigns SET data = ?, updated_at = ? WHERE id = ?',
                                   (json.dumps(data, ensure_ascii=False), self._now(), campaign_id))
            return result

    def update_fields(self, campaign_id, fields):
        self._mutate_data(campaign_id, lambda data: data.update(fields))

    def save_inline_drafts(self, campaign_id, drafts):
        self.save_inline_editor(campaign_id, drafts)

    def save_inline_editor(self, campaign_id, drafts, open_dates=None):
        def change(data):
            sync_inline_performers(data, drafts)
            if open_dates is not None and open_dates != data.get('open_dates', ''):
                data['open_dates'] = open_dates
                data['rows'] = []
        self._mutate_data(campaign_id, change)

    def set_inline_status(self, campaign_id, row_id, status, expected=None):
        def change(data):
            draft = next((item for item in data.get('availability_drafts', []) if item['id'] == row_id), None)
            if draft is None or (expected is not None and request_signature(draft, data) != expected):
                return False
            draft['status'] = status
            return True
        return self._mutate_data(campaign_id, change)

    def apply_inline_result(self, campaign_id, row_id, snapshot, dates, explanation=''):
        def change(data):
            draft = next((item for item in data.get('availability_drafts', []) if item['id'] == row_id), None)
            if (draft is None or request_signature(draft, data) != snapshot['signature']
                    or performer_value(data, snapshot['name']) != snapshot['previous_availability']):
                return False
            if any(date not in snapshot['dates'] for date in dates):
                raise ValueError('Formatter returned a date outside this schedule’s open dates.')
            formatted = ', '.join(f'{date.month}/{date.day}/{date.year:04d}' for date in sorted(set(dates)))
            people = data.setdefault('performers', [])
            person = next((person for person in people if performer_key(person['name']) == performer_key(snapshot['name'])), None)
            if person is None:
                person = {'name': snapshot['name'], 'availability': ''}
                people.append(person)
                changed = True
            else:
                changed = person['availability'] != formatted
            person['availability'] = formatted
            if changed:
                data['rows'] = []
            draft.update(last_applied=snapshot['signature'], formatted=formatted,
                         status='Updated · ' + (formatted or 'No matching open dates'), review_notes=explanation)
            return True
        return self._mutate_data(campaign_id, change)

    def rename(self, campaign_id, name):
        self._update('UPDATE campaigns SET name = ?, updated_at = ? WHERE id = ?',
                     (self._name(name), self._now(), campaign_id))

    def delete(self, campaign_id):
        self._update('DELETE FROM campaigns WHERE id = ?', (campaign_id,))

    def _update(self, sql, parameters):
        with self._connect() as connection:
            if connection.execute(sql, parameters).rowcount != 1:
                raise ValueError('This schedule no longer exists.')

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()
