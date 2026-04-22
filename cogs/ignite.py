from datetime import datetime, timezone
import hashlib
import sqlite3
from typing import Dict, List, Optional
from urllib.parse import urlparse

import discord
import requests
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands, tasks

from models.database import DatabaseManager
from models.permissions import ensure_manager
from models.time_utils import discord_timestamp


DEFAULT_IGNITE_URL = "https://liquipedia.net/marvelrivals/MR_Ignite/2026/Preseason/Americas"
USER_AGENT = "ScrimBot/1.0 (Discord bot Ignite result checker)"


def validate_source_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Source URL must start with http:// or https://")
    if parsed.netloc.lower() != "liquipedia.net":
        raise ValueError("Source URL must be on liquipedia.net")
    if not parsed.path.startswith("/marvelrivals/"):
        raise ValueError("Source URL must be a Liquipedia Marvel Rivals page")
    return url.strip()


def build_match_key(source_url: str, team1: str, team2: str, score: str, timestamp: Optional[str], row_index: int) -> str:
    """Build a stable key that distinguishes rematches with the same score."""
    raw = f"{source_url}|{team1}|{team2}|{score}|{timestamp or 'no-time'}|row-{row_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_ignite_results_html(source_url: str, html: str) -> List[Dict]:
    """Parse completed Ignite match results from a Liquipedia HTML document."""
    source_url = validate_source_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for row_index, match in enumerate(soup.select(".brkts-match")):
        try:
            opponents = match.select(".brkts-opponent-entry")
            if len(opponents) < 2:
                continue

            team1 = opponents[0].get("aria-label", "").strip()
            team2 = opponents[1].get("aria-label", "").strip()
            if not team1 or not team2:
                continue
            if team1.upper() in {"TBD", "BYE"} or team2.upper() in {"TBD", "BYE"}:
                continue

            score_cells = match.select(".brkts-opponent-score-inner")
            if len(score_cells) < 2:
                continue

            score1 = score_cells[0].get_text(" ", strip=True)
            score2 = score_cells[1].get_text(" ", strip=True)
            if not score1.isdigit() or not score2.isdigit():
                continue

            timestamp = None
            timer = match.select_one(".timer-object[data-timestamp]")
            if timer and timer.get("data-timestamp"):
                try:
                    unix_time = int(timer["data-timestamp"])
                    timestamp = datetime.fromtimestamp(unix_time, tz=timezone.utc).isoformat()
                except (TypeError, ValueError):
                    timestamp = None

            score = f"{score1}-{score2}"
            match_key = build_match_key(source_url, team1, team2, score, timestamp, row_index)
            if match_key in seen:
                continue
            seen.add(match_key)

            results.append({
                "team1": team1,
                "team2": team2,
                "score": score,
                "match_key": match_key,
                "datetime": timestamp,
                "source_url": source_url,
            })
        except Exception as exc:
            print(f"Error parsing Ignite match row: {exc}")

    return results


def scrape_ignite_results(source_url: str = DEFAULT_IGNITE_URL) -> List[Dict]:
    """
    Fetch Liquipedia and return completed Ignite match results.
    Returns dicts with team1, team2, score, match_key, and optional datetime.
    """
    source_url = validate_source_url(source_url)
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(source_url, headers=headers, timeout=20)
    response.raise_for_status()
    return parse_ignite_results_html(source_url, response.text)


class IgniteCog(commands.Cog):
    """Automatically posts new Ignite match results from Liquipedia."""

    def __init__(self, bot):
        self.bot = bot
        self.db_path = "bot_data.db"
        self.init_database()
        self.check_ignite_results.start()

    def cog_unload(self):
        self.check_ignite_results.cancel()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ignite_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                team1 TEXT,
                team2 TEXT,
                score TEXT,
                match_key TEXT UNIQUE,
                datetime TEXT,
                source_url TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ignite_settings (
                id INTEGER PRIMARY KEY,
                channel_id TEXT,
                enabled INTEGER,
                tracked_team TEXT,
                source_url TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
        ''')

        self.ensure_column(cursor, "ignite_results", "guild_id", "INTEGER")
        self.ensure_column(cursor, "ignite_results", "source_url", "TEXT")
        self.ensure_column(cursor, "ignite_settings", "tracked_team", "TEXT")
        self.ensure_column(cursor, "ignite_settings", "source_url", "TEXT")
        self.ensure_column(cursor, "ignite_settings", "failure_count", "INTEGER NOT NULL DEFAULT 0")
        self.ensure_column(cursor, "ignite_settings", "last_error", "TEXT")

        conn.commit()
        conn.close()

    def ensure_column(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    async def send_error(self, interaction: discord.Interaction, error: Exception):
        message = f"Error: {str(error)}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def get_settings(self, guild_id: int) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, channel_id, enabled, tracked_team, source_url, failure_count, last_error
                FROM ignite_settings
                WHERE id = ?
            ''', (guild_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "guild_id": row[0],
                    "channel_id": row[1],
                    "enabled": row[2] or 0,
                    "tracked_team": row[3],
                    "source_url": row[4] or DEFAULT_IGNITE_URL,
                    "failure_count": row[5] or 0,
                    "last_error": row[6],
                }

            cursor.execute('''
                INSERT INTO ignite_settings
                (id, channel_id, enabled, tracked_team, source_url, failure_count, last_error)
                VALUES (?, NULL, 0, NULL, ?, 0, NULL)
            ''', (guild_id, DEFAULT_IGNITE_URL))
            conn.commit()
            return {
                "guild_id": guild_id,
                "channel_id": None,
                "enabled": 0,
                "tracked_team": None,
                "source_url": DEFAULT_IGNITE_URL,
                "failure_count": 0,
                "last_error": None,
            }
        finally:
            conn.close()

    def list_enabled_settings(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id, channel_id, enabled, tracked_team, source_url, failure_count, last_error
                FROM ignite_settings
                WHERE enabled = 1
            ''')
            return [
                {
                    "guild_id": row[0],
                    "channel_id": row[1],
                    "enabled": row[2] or 0,
                    "tracked_team": row[3],
                    "source_url": row[4] or DEFAULT_IGNITE_URL,
                    "failure_count": row[5] or 0,
                    "last_error": row[6],
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    def update_settings(
        self,
        guild_id: int,
        channel_id: Optional[str] = None,
        enabled: Optional[int] = None,
        tracked_team: Optional[str] = None,
        source_url: Optional[str] = None,
        failure_count: Optional[int] = None,
        last_error: Optional[str] = None,
        clear_tracked_team: bool = False,
        clear_error: bool = False,
    ):
        self.get_settings(guild_id)
        updates = {}
        if channel_id is not None:
            updates["channel_id"] = channel_id
        if enabled is not None:
            updates["enabled"] = enabled
        if tracked_team is not None:
            updates["tracked_team"] = tracked_team
        if source_url is not None:
            updates["source_url"] = source_url
        if failure_count is not None:
            updates["failure_count"] = failure_count
        if last_error is not None:
            updates["last_error"] = last_error
        if clear_tracked_team:
            updates["tracked_team"] = None
        if clear_error:
            updates["last_error"] = None
        if not updates:
            return

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            set_clause = ", ".join([f"{field} = ?" for field in updates])
            values = list(updates.values())
            values.append(guild_id)
            cursor.execute(f"UPDATE ignite_settings SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def guild_match_key(self, guild_id: int, match_key: str) -> str:
        # The legacy table had match_key globally unique. Prefixing preserves per-server behavior.
        return f"{guild_id}:{match_key}"

    def insert_result(self, guild_id: int, result: Dict) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO ignite_results
                (guild_id, team1, team2, score, match_key, datetime, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                guild_id,
                result["team1"],
                result["team2"],
                result["score"],
                self.guild_match_key(guild_id, result["match_key"]),
                result.get("datetime"),
                result.get("source_url"),
            ))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def matches_tracked_team(self, result: Dict, tracked_team: Optional[str]) -> bool:
        if not tracked_team:
            return True
        needle = tracked_team.strip().lower()
        return needle in result["team1"].lower() or needle in result["team2"].lower()

    def build_result_message(self, result: Dict, source_url: str) -> str:
        score1, score2 = result["score"].split("-", 1)
        message = "\N{FIRE} **Ignite Result**\n\n"
        message += f"**{result['team1']}** {score1} - {score2} **{result['team2']}**"
        if result.get("datetime"):
            message += f"\n{discord_timestamp(result['datetime'], 'F')}"
        message += f"\n<{source_url}>"
        return message

    async def alert_failure(self, settings: Dict, error: str):
        failure_count = settings["failure_count"] + 1
        self.update_settings(
            settings["guild_id"],
            failure_count=failure_count,
            last_error=error[:500],
        )

        if failure_count < 3 or failure_count % 3 != 0:
            return
        if not settings["channel_id"]:
            return

        channel = self.bot.get_channel(int(settings["channel_id"]))
        if not channel:
            return

        await channel.send(
            "**Ignite scraper alert**\n"
            f"Failed {failure_count} checks in a row.\n"
            f"Source: <{settings['source_url']}>\n"
            f"Error: `{error[:180]}`"
        )

    ignite_group = app_commands.Group(name="ignite", description="Ignite Liquipedia result tracking")

    @ignite_group.command(name="set_channel", description="Set the channel where Ignite results are posted")
    async def ignite_set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            self.update_settings(interaction.guild.id, channel_id=str(channel.id))
            await interaction.followup.send(f"Ignite result channel set to {channel.mention}.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="set_source", description="Set the Liquipedia source URL for Ignite results")
    async def ignite_set_source(self, interaction: discord.Interaction, url: str):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            source_url = validate_source_url(url)
            self.update_settings(interaction.guild.id, source_url=source_url, failure_count=0, clear_error=True)
            await interaction.followup.send(f"Ignite source set to <{source_url}>.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="enable_auto", description="Enable automatic Ignite result posting")
    async def ignite_enable_auto(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            self.update_settings(interaction.guild.id, enabled=1)
            await interaction.followup.send("Ignite auto-posting enabled.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="disable_auto", description="Disable automatic Ignite result posting")
    async def ignite_disable_auto(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            self.update_settings(interaction.guild.id, enabled=0)
            await interaction.followup.send("Ignite auto-posting disabled.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="status", description="Show Ignite result tracking status")
    async def ignite_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        settings = self.get_settings(interaction.guild.id)
        channel = self.bot.get_channel(int(settings["channel_id"])) if settings["channel_id"] else None
        response = "**Ignite Status**\n"
        response += f"**Auto-posting:** {'Enabled' if settings['enabled'] else 'Disabled'}\n"
        response += f"**Channel:** {channel.mention if channel else 'Not set'}\n"
        response += f"**Tracked team:** {settings['tracked_team'] or 'All teams'}\n"
        response += f"**Source:** <{settings['source_url']}>\n"
        response += f"**Failure count:** {settings['failure_count']}"
        if settings["last_error"]:
            response += f"\n**Last error:** `{settings['last_error'][:180]}`"
        await interaction.followup.send(response, ephemeral=True)

    @ignite_group.command(name="set_tracked_team", description="Only post Ignite results involving this team")
    async def ignite_set_tracked_team(self, interaction: discord.Interaction, team_name: str):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            self.update_settings(interaction.guild.id, tracked_team=team_name.strip())
            await interaction.followup.send(f"Ignite tracked team set to `{team_name.strip()}`.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="clear_tracked_team", description="Post Ignite results for all teams")
    async def ignite_clear_tracked_team(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            self.update_settings(interaction.guild.id, clear_tracked_team=True)
            await interaction.followup.send("Ignite tracked team filter cleared.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @ignite_group.command(name="check_now", description="Check Liquipedia for Ignite results now")
    async def ignite_check_now(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, DatabaseManager("bot_data.db"))
            await interaction.response.defer(ephemeral=True)
            settings = self.get_settings(interaction.guild.id)
            posted = await self.process_ignite_results(settings, post_to_discord=True)
            await interaction.followup.send(f"Ignite check complete. Posted {posted} new result(s).", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    async def process_ignite_results(
        self,
        settings: Dict,
        post_to_discord: bool,
        scrape_cache: Optional[Dict[str, List[Dict]]] = None,
    ) -> int:
        if not settings["enabled"] and post_to_discord:
            return 0

        channel = None
        if post_to_discord:
            if not settings["channel_id"]:
                print(f"Ignite auto-post skipped for guild {settings['guild_id']}: no channel configured")
                return 0
            channel = self.bot.get_channel(int(settings["channel_id"]))
            if not channel:
                print(f"Ignite auto-post skipped for guild {settings['guild_id']}: invalid channel {settings['channel_id']}")
                return 0

        try:
            if scrape_cache is not None and settings["source_url"] in scrape_cache:
                results = scrape_cache[settings["source_url"]]
            else:
                results = scrape_ignite_results(settings["source_url"])
                if scrape_cache is not None:
                    scrape_cache[settings["source_url"]] = results
            self.update_settings(settings["guild_id"], failure_count=0, clear_error=True)
        except requests.HTTPError as exc:
            error = f"HTTP error: {exc}"
            print(f"Ignite scrape {error}")
            await self.alert_failure(settings, error)
            return 0
        except requests.RequestException as exc:
            error = f"Request error: {exc}"
            print(f"Ignite scrape {error}")
            await self.alert_failure(settings, error)
            return 0
        except Exception as exc:
            error = f"Scrape error: {exc}"
            print(f"Ignite scrape {error}")
            await self.alert_failure(settings, error)
            return 0

        posted = 0
        for result in results:
            if not self.matches_tracked_team(result, settings["tracked_team"]):
                continue
            if not self.insert_result(settings["guild_id"], result):
                continue
            if post_to_discord and channel:
                try:
                    await channel.send(self.build_result_message(result, settings["source_url"]))
                    posted += 1
                except Exception as exc:
                    print(f"Failed to post Ignite result {result['match_key']}: {exc}")

        return posted

    @tasks.loop(minutes=5)
    async def check_ignite_results(self):
        scrape_cache = {}
        for settings in self.list_enabled_settings():
            await self.process_ignite_results(settings, post_to_discord=True, scrape_cache=scrape_cache)

    @check_ignite_results.before_loop
    async def before_check_ignite_results(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(IgniteCog(bot))
