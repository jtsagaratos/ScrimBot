import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


class DatabaseManager:
    """Manages SQLite database for MRC matches, scrims, and server settings."""

    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def init_database(self):
        """Initialize database tables if they don't exist."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mrc_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                datetime TEXT NOT NULL,
                round_group TEXT NOT NULL,
                bracket TEXT NOT NULL,
                opponent TEXT,
                discord_event_id TEXT,
                reminder_sent_30 INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT 'US/Eastern',
                status TEXT NOT NULL DEFAULT 'Scheduled',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scrim_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                role_id INTEGER,
                datetime TEXT NOT NULL,
                timezone TEXT NOT NULL,
                discord_event_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                reminder_channel_id INTEGER,
                manager_role_id INTEGER,
                timezone TEXT NOT NULL DEFAULT 'US/Eastern',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminder_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
        ''')

        self._ensure_column(cursor, "mrc_matches", "discord_event_id", "TEXT")
        self._ensure_column(cursor, "mrc_matches", "reminder_sent_30", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(cursor, "mrc_matches", "timezone", "TEXT NOT NULL DEFAULT 'US/Eastern'")
        self._ensure_column(cursor, "mrc_matches", "status", "TEXT NOT NULL DEFAULT 'Scheduled'")
        self._ensure_column(cursor, "mrc_matches", "archived", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(cursor, "guild_settings", "manager_role_id", "INTEGER")

        conn.commit()
        conn.close()

    def _ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str):
        """Add a column when an existing database was created by an older version."""
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _parse_stored_datetime(self, value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _row_to_match(self, row) -> Dict:
        """Convert an mrc_matches row into the dict shape used by the cogs."""
        return {
            'id': row[0],
            'guild_id': row[1],
            'datetime': row[2],
            'round_group': row[3],
            'bracket': row[4],
            'opponent': row[5],
            'discord_event_id': row[6],
            'reminder_sent_30': row[7],
            'timezone': row[8],
            'status': row[9],
            'archived': row[10],
            'created_at': row[11],
            'updated_at': row[12]
        }

    def _row_to_scrim(self, row) -> Dict:
        return {
            'id': row[0],
            'guild_id': row[1],
            'team_name': row[2],
            'role_id': row[3],
            'datetime': row[4],
            'timezone': row[5],
            'discord_event_id': row[6],
            'created_at': row[7],
            'updated_at': row[8],
        }

    # ==================== SETTINGS ====================

    def get_guild_settings(self, guild_id: int) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT guild_id, reminder_channel_id, manager_role_id, timezone, created_at, updated_at
                FROM guild_settings
                WHERE guild_id = ?
            ''', (guild_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'guild_id': row[0],
                    'reminder_channel_id': row[1],
                    'manager_role_id': row[2],
                    'timezone': row[3],
                    'created_at': row[4],
                    'updated_at': row[5],
                }

            now = self._utc_now_iso()
            cursor.execute('''
                INSERT INTO guild_settings (guild_id, timezone, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (guild_id, "US/Eastern", now, now))
            conn.commit()
            return {
                'guild_id': guild_id,
                'reminder_channel_id': None,
                'manager_role_id': None,
                'timezone': "US/Eastern",
                'created_at': now,
                'updated_at': now,
            }
        finally:
            conn.close()

    def update_guild_settings(self, guild_id: int, **kwargs) -> bool:
        allowed_fields = {'reminder_channel_id', 'manager_role_id', 'timezone'}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}
        if not update_fields:
            return False

        self.get_guild_settings(guild_id)
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            set_clause = ', '.join([f"{field} = ?" for field in update_fields.keys()])
            update_fields['updated_at'] = self._utc_now_iso()
            set_clause += ", updated_at = ?"
            values = list(update_fields.values()) + [guild_id]

            cursor.execute(f'''
                UPDATE guild_settings
                SET {set_clause}
                WHERE guild_id = ?
            ''', values)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def add_reminder_role(self, guild_id: int, role_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT OR IGNORE INTO reminder_roles (guild_id, role_id, created_at)
                VALUES (?, ?, ?)
            ''', (guild_id, role_id, self._utc_now_iso()))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def remove_reminder_role(self, guild_id: int, role_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                DELETE FROM reminder_roles
                WHERE guild_id = ? AND role_id = ?
            ''', (guild_id, role_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_reminder_roles(self, guild_id: int) -> List[int]:
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT role_id
                FROM reminder_roles
                WHERE guild_id = ?
                ORDER BY role_id ASC
            ''', (guild_id,))
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== MRC MATCH OPERATIONS ====================

    def add_mrc_match(self, guild_id: int, datetime_str: str, round_group: str,
                      bracket: str, opponent: Optional[str] = None,
                      discord_event_id: Optional[str] = None,
                      timezone_name: str = "US/Eastern",
                      status: str = "Scheduled") -> int:
        """Add a new MRC match to database. Returns the match ID."""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = self._utc_now_iso()

        try:
            cursor.execute('''
                INSERT INTO mrc_matches
                (guild_id, datetime, round_group, bracket, opponent, discord_event_id,
                 timezone, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (guild_id, datetime_str, round_group, bracket, opponent, discord_event_id,
                  timezone_name, status, now, now))

            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_mrc_match(self, guild_id: int, match_id: int) -> Optional[Dict]:
        """Get a specific MRC match by ID."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT id, guild_id, datetime, round_group, bracket, opponent, discord_event_id,
                       reminder_sent_30, timezone, status, archived, created_at, updated_at
                FROM mrc_matches
                WHERE id = ? AND guild_id = ?
            ''', (match_id, guild_id))

            row = cursor.fetchone()
            if row:
                return self._row_to_match(row)
            return None
        finally:
            conn.close()

    def get_all_mrc_matches(
        self,
        guild_id: int,
        include_completed: bool = True,
        include_archived: bool = False,
    ) -> List[Dict]:
        """Get all MRC matches for a guild, ordered by datetime."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            where_clauses = ["guild_id = ?"]
            values = [guild_id]
            if not include_archived:
                where_clauses.append("archived = 0")
            if not include_completed:
                where_clauses.append("status NOT IN ('Completed', 'Cancelled')")

            cursor.execute('''
                SELECT id, guild_id, datetime, round_group, bracket, opponent, discord_event_id,
                       reminder_sent_30, timezone, status, archived, created_at, updated_at
                FROM mrc_matches
                WHERE ''' + " AND ".join(where_clauses) + '''
                ORDER BY datetime ASC
            ''', values)

            return [self._row_to_match(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_upcoming_mrc_matches(
        self,
        guild_id: int,
        days: int = 14,
        include_completed: bool = False,
        include_archived: bool = False,
    ) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) + timedelta(days=days)
        matches = []
        for match in self.get_all_mrc_matches(
            guild_id,
            include_completed=include_completed,
            include_archived=include_archived,
        ):
            dt = self._parse_stored_datetime(match['datetime'])
            if datetime.now(timezone.utc) <= dt <= cutoff:
                matches.append(match)
        return matches

    def update_mrc_match(self, guild_id: int, match_id: int, **kwargs) -> bool:
        """
        Update an MRC match with provided fields.
        Allowed fields: datetime, round_group, bracket, opponent, discord_event_id,
        reminder_sent_30, timezone, status, archived
        """
        allowed_fields = {
            'datetime',
            'round_group',
            'bracket',
            'opponent',
            'discord_event_id',
            'reminder_sent_30',
            'timezone',
            'status',
            'archived',
        }
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not update_fields:
            return False

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            set_clause = ', '.join([f"{field} = ?" for field in update_fields.keys()])
            update_fields['updated_at'] = self._utc_now_iso()
            set_clause += ", updated_at = ?"
            values = list(update_fields.values()) + [match_id, guild_id]

            cursor.execute(f'''
                UPDATE mrc_matches
                SET {set_clause}
                WHERE id = ? AND guild_id = ?
            ''', values)

            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_mrc_match(self, guild_id: int, match_id: int) -> bool:
        """Delete an MRC match from database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                DELETE FROM mrc_matches
                WHERE id = ? AND guild_id = ?
            ''', (match_id, guild_id))

            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_upcoming_matches(self, guild_id: int, seconds_from_now: int) -> List[Dict]:
        """Get matches happening within the specified seconds from now."""
        cutoff = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
        matches = []
        for match in self.get_all_mrc_matches(guild_id):
            dt = self._parse_stored_datetime(match['datetime'])
            if datetime.now(timezone.utc) <= dt <= cutoff:
                matches.append(match)
        return matches

    def get_matches_needing_30_minute_reminder(self) -> List[Dict]:
        """Get future matches due for a one-time 30-minute reminder."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT id, guild_id, datetime, round_group, bracket, opponent, discord_event_id,
                       reminder_sent_30, timezone, status, archived, created_at, updated_at
                FROM mrc_matches
                WHERE reminder_sent_30 = 0
                  AND archived = 0
                ORDER BY datetime ASC
            ''')
            rows = cursor.fetchall()
        finally:
            conn.close()

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(minutes=30)
        matches = []
        for row in rows:
            match = self._row_to_match(row)
            dt = self._parse_stored_datetime(match['datetime'])
            if now < dt <= cutoff:
                matches.append(match)
        return matches

    def mark_30_minute_reminder_sent(self, guild_id: int, match_id: int) -> bool:
        """Mark a match so the 30-minute reminder is not sent again."""
        return self.update_mrc_match(guild_id, match_id, reminder_sent_30=1)

    def archive_completed_mrc_matches(self, guild_id: int) -> int:
        """Archive completed or cancelled matches. Returns number of rows changed."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE mrc_matches
                SET archived = 1, updated_at = ?
                WHERE guild_id = ?
                  AND archived = 0
                  AND status IN ('Completed', 'Cancelled')
            ''', (self._utc_now_iso(), guild_id))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    # ==================== SCRIM OPERATIONS ====================

    def add_scrim(self, guild_id: int, team_name: str, role_id: Optional[int],
                  datetime_str: str, timezone_name: str,
                  discord_event_id: Optional[str]) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        now = self._utc_now_iso()

        try:
            cursor.execute('''
                INSERT INTO scrim_events
                (guild_id, team_name, role_id, datetime, timezone, discord_event_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (guild_id, team_name, role_id, datetime_str, timezone_name, discord_event_id, now, now))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_upcoming_scrims(self, guild_id: int, days: int = 14) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                SELECT id, guild_id, team_name, role_id, datetime, timezone, discord_event_id,
                       created_at, updated_at
                FROM scrim_events
                WHERE guild_id = ?
                ORDER BY datetime ASC
            ''', (guild_id,))
            rows = cursor.fetchall()
        finally:
            conn.close()

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)
        scrims = []
        for row in rows:
            scrim = self._row_to_scrim(row)
            dt = self._parse_stored_datetime(scrim['datetime'])
            if now <= dt <= cutoff:
                scrims.append(scrim)
        return scrims
