import os
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import mkstemp
from types import SimpleNamespace

from cogs.ignite import DEFAULT_IGNITE_URL, parse_ignite_results_html
from models.database import DatabaseManager
from models.permissions import is_manager
from models.time_utils import discord_timestamp, to_utc_iso


class TempDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = mkstemp(suffix=".db")
        os.close(fd)
        self.db = DatabaseManager(self.path)

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)


class DatabaseTests(TempDatabaseTestCase):
    def test_archive_completed_hides_from_default_queries(self):
        now = datetime.now(timezone.utc)
        scheduled_id = self.db.add_mrc_match(
            100,
            to_utc_iso(now + timedelta(days=1)),
            "Rounds 1-3",
            "Upper",
            status="Scheduled",
        )
        completed_id = self.db.add_mrc_match(
            100,
            to_utc_iso(now + timedelta(days=2)),
            "Rounds 4-6",
            "Lower",
            status="Completed",
        )

        visible = self.db.get_all_mrc_matches(100, include_completed=False)
        self.assertEqual([match["id"] for match in visible], [scheduled_id])

        archived_count = self.db.archive_completed_mrc_matches(100)
        self.assertEqual(archived_count, 1)

        all_unarchived = self.db.get_all_mrc_matches(100, include_completed=True)
        self.assertEqual([match["id"] for match in all_unarchived], [scheduled_id])

        all_with_archived = self.db.get_all_mrc_matches(100, include_completed=True, include_archived=True)
        self.assertEqual({match["id"] for match in all_with_archived}, {scheduled_id, completed_id})

    def test_manager_roles_can_store_multiple_roles(self):
        self.assertTrue(self.db.add_manager_role(200, 12345))
        self.assertTrue(self.db.add_manager_role(200, 67890))
        self.assertFalse(self.db.add_manager_role(200, 12345))
        self.assertEqual(set(self.db.get_manager_roles(200)), {12345, 67890})

    def test_scrim_ping_roles_can_store_multiple_roles(self):
        self.assertTrue(self.db.add_scrim_ping_role(201, 111))
        self.assertTrue(self.db.add_scrim_ping_role(201, 222))
        self.assertFalse(self.db.add_scrim_ping_role(201, 111))
        self.assertEqual(set(self.db.get_scrim_ping_roles(201)), {111, 222})
        self.assertTrue(self.db.remove_scrim_ping_role(201, 111))
        self.assertEqual(self.db.get_scrim_ping_roles(201), [222])


class IgniteParserTests(unittest.TestCase):
    def test_parse_ignite_results_html(self):
        html = """
        <div class="brkts-match">
          <div class="brkts-opponent-entry" aria-label="Vengeful">
            <div class="brkts-opponent-score-inner"><b>2</b></div>
          </div>
          <div class="brkts-opponent-entry" aria-label="Other Team">
            <div class="brkts-opponent-score-inner">1</div>
          </div>
          <span class="timer-object" data-timestamp="1777143600"></span>
        </div>
        """
        results = parse_ignite_results_html(DEFAULT_IGNITE_URL, html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["team1"], "Vengeful")
        self.assertEqual(results[0]["team2"], "Other Team")
        self.assertEqual(results[0]["score"], "2-1")
        self.assertEqual(len(results[0]["match_key"]), 64)
        self.assertEqual(results[0]["datetime"], "2026-04-25T19:00:00+00:00")


class TimeTests(unittest.TestCase):
    def test_discord_timestamp(self):
        value = to_utc_iso(datetime(2026, 4, 25, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(discord_timestamp(value, "F"), "<t:1777143600:F>")


class PermissionTests(TempDatabaseTestCase):
    def test_configured_manager_role_is_allowed(self):
        self.db.add_manager_role(300, 999)
        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=300),
            user=SimpleNamespace(
                guild_permissions=SimpleNamespace(
                    administrator=False,
                    manage_guild=False,
                    manage_events=False,
                ),
                roles=[SimpleNamespace(id=999)],
            ),
        )
        self.assertTrue(is_manager(interaction, self.db))


if __name__ == "__main__":
    unittest.main()
