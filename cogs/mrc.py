import re
from datetime import datetime
from typing import Optional, Tuple

import discord
import pytz
from dateutil import parser as date_parser
from discord import app_commands
from discord.ext import commands, tasks

from models.database import DatabaseManager
from models.permissions import ensure_manager
from models.time_utils import (
    COMMON_TIMEZONES,
    discord_time_display,
    event_end_time,
    localize_datetime,
    normalize_timezone,
    parse_stored_datetime,
    split_trailing_timezone,
    to_utc_iso,
    validate_duration_hours,
)


MATCH_STATUSES = ["Scheduled", "Checked In", "In Progress", "Completed", "Cancelled"]
BRACKET_CHOICES = [
    app_commands.Choice(name="Upper", value="Upper"),
    app_commands.Choice(name="Lower", value="Lower"),
]
STATUS_CHOICES = [app_commands.Choice(name=status, value=status) for status in MATCH_STATUSES]


class MRCEditModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int, match: dict):
        super().__init__(title=f"Edit MRC Event M{match['id']}")
        self.cog = cog
        self.guild_id = guild_id
        self.match = match

        local_dt = parse_stored_datetime(match["datetime"]).astimezone(pytz.timezone(match["timezone"]))
        datetime_default = local_dt.strftime("%B %d %I:%M %p %Y")

        self.datetime_input = discord.ui.TextInput(
            label="Date/Time",
            default=datetime_default,
            placeholder="April 25 1:00 PM 2026",
            max_length=80,
        )
        self.timezone_input = discord.ui.TextInput(
            label="Timezone",
            default=match["timezone"],
            placeholder="America/Denver, EST, PST, UTC",
            max_length=80,
        )
        self.duration_input = discord.ui.TextInput(
            label="Duration Hours",
            default=f"{match.get('duration_hours', 2.0):g}",
            placeholder="2 or 1.5",
            max_length=10,
        )
        self.rounds_input = discord.ui.TextInput(
            label="Title",
            default=match["round_group"],
            placeholder="Rounds 1-3 or Grand Finals",
            max_length=80,
        )
        self.bracket_input = discord.ui.TextInput(
            label="Bracket (optional)",
            default=match["bracket"],
            placeholder="Upper, Lower, or blank",
            max_length=20,
        )
        self.add_item(self.datetime_input)
        self.add_item(self.timezone_input)
        self.add_item(self.duration_input)
        self.add_item(self.rounds_input)
        self.add_item(self.bracket_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            match = self.cog.db.get_mrc_match(self.guild_id, self.match["id"])
            if not match:
                await interaction.response.send_message(f"Event ID M{self.match['id']} not found.", ephemeral=True)
                return

            timezone_name = normalize_timezone(str(self.timezone_input.value).strip(), match["timezone"])
            new_datetime = self.cog.parse_mrc_datetime(str(self.datetime_input.value).strip(), timezone_name)
            round_group = self.cog.normalize_mrc_title(str(self.rounds_input.value).strip())
            bracket = str(self.bracket_input.value).strip().capitalize()
            if bracket and bracket not in {"Upper", "Lower"}:
                raise ValueError("Bracket must be 'Upper', 'Lower', or blank")
            duration_hours = validate_duration_hours(str(self.duration_input.value).strip())

            self.cog.db.update_mrc_match(
                self.guild_id,
                match["id"],
                datetime=to_utc_iso(new_datetime),
                round_group=round_group,
                bracket=bracket,
                timezone=timezone_name,
                duration_hours=duration_hours,
                reminder_sent_30=0,
            )

            if match["discord_event_id"]:
                await self.cog.update_discord_event(
                    guild,
                    match["discord_event_id"],
                    new_datetime,
                    round_group,
                    bracket,
                    duration_hours,
                    match["id"],
                    match.get("season", 7),
                )

            updated = self.cog.db.get_mrc_match(self.guild_id, match["id"])
            await interaction.response.send_message(
                f"**Event Updated**\n{self.cog.build_match_line(updated)}"
            )
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class MRCMatchPageView(discord.ui.View):
    def __init__(self, cog, matches: list, title: str, page_size: int = 5):
        super().__init__(timeout=300)
        self.cog = cog
        self.matches = matches
        self.title = title
        self.page_size = page_size
        self.page = 0
        self.update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.matches) + self.page_size - 1) // self.page_size)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.blue(),
            description=f"Page {self.page + 1}/{self.total_pages} | Total matches: {len(self.matches)}",
        )
        start = self.page * self.page_size
        end = start + self.page_size
        for match in self.matches[start:end]:
            embed.add_field(name=f"Event ID {self.cog.format_public_id(match)}", value=self.cog.build_match_line(match), inline=False)
        return embed

    def update_buttons(self):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class MRCCog(commands.Cog):
    """MRC (Tournament) match scheduling and management."""

    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")
        self.reminder_task.start()

    def cog_unload(self):
        """Clean up when cog is unloaded."""
        self.reminder_task.cancel()

    # ==================== PERMISSIONS ====================

    def ensure_manager(self, interaction: discord.Interaction):
        ensure_manager(interaction, self.db)

    async def send_error(self, interaction: discord.Interaction, error: Exception):
        message = f"Error: {str(error)}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ==================== PARSING LOGIC ====================

    def parse_mrc_line(
        self,
        line: str,
        default_timezone: str,
        year: int = 2026,
    ) -> Optional[Tuple[datetime, str, str, str]]:
        """Parse a single MRC schedule line into datetime, title, optional bracket, and timezone."""
        line = line.strip()
        if not line:
            return None

        try:
            tokens = line.split()
            for split_index in range(len(tokens) - 1, 0, -1):
                datetime_part = " ".join(tokens[:split_index])
                title_part = " ".join(tokens[split_index:]).strip()
                if not title_part:
                    continue

                datetime_without_timezone, trailing_timezone = split_trailing_timezone(datetime_part)
                timezone_name = normalize_timezone(trailing_timezone, default_timezone)
                try:
                    aware_dt = self.parse_mrc_datetime(datetime_without_timezone, timezone_name, year=year)
                except ValueError:
                    continue

                title_without_timezone, title_trailing_timezone = split_trailing_timezone(title_part)
                if title_trailing_timezone:
                    timezone_name = normalize_timezone(title_trailing_timezone, timezone_name)
                    aware_dt = self.parse_mrc_datetime(datetime_without_timezone, timezone_name, year=year)
                    title_part = title_without_timezone

                title, bracket = self.extract_optional_bracket(title_part)
                return (aware_dt, title, bracket, timezone_name)

            return None
        except Exception as e:
            print(f"Error parsing line '{line}': {e}")
            return None

    def parse_mrc_datetime(
        self,
        datetime_str: str,
        timezone_name: str,
        year: int = 2026,
    ) -> datetime:
        """Parse MRC command datetimes and attach the selected timezone."""
        datetime_part, trailing_timezone = split_trailing_timezone(datetime_str)
        timezone_name = normalize_timezone(trailing_timezone, timezone_name)

        formats = [
            ("%B %d %I:%M %p %Y", datetime_part),
            ("%b %d %I:%M %p %Y", datetime_part),
            ("%B %d %Y %I:%M %p", datetime_part),
            ("%b %d %Y %I:%M %p", datetime_part),
            ("%B %d %I:%M %p %Y", f"{datetime_part} {year}"),
            ("%b %d %I:%M %p %Y", f"{datetime_part} {year}"),
        ]

        for fmt, value in formats:
            try:
                return localize_datetime(datetime.strptime(value, fmt), timezone_name)
            except ValueError:
                continue

        try:
            default_dt = datetime(year, 1, 1)
            return localize_datetime(date_parser.parse(datetime_part, default=default_dt), timezone_name)
        except (ValueError, OverflowError) as exc:
            raise ValueError(
                "Date must look like 'April 25 1:00 PM' or '4/20/26 3PM', optionally with a timezone."
            ) from exc

    def normalize_round_group(self, rounds: str) -> str:
        """Return a consistent 'Rounds X-Y' label from user input."""
        rounds = rounds.strip()
        if re.match(r"^rounds?\b", rounds, re.IGNORECASE):
            return rounds[0].upper() + rounds[1:]
        return f"Rounds {rounds}"

    def normalize_mrc_title(self, title: str) -> str:
        """Normalize a user-supplied MRC event title without forcing a bracket."""
        title = re.sub(r"\s+", " ", title.strip())
        if not title:
            raise ValueError("MRC title cannot be blank")
        if re.match(r"^rounds?\b", title, re.IGNORECASE):
            return title[0].upper() + title[1:]
        return title

    def extract_optional_bracket(self, title: str) -> Tuple[str, str]:
        title = self.normalize_mrc_title(title)
        match = re.search(r"\s+(Upper|Lower)$", title, re.IGNORECASE)
        if not match:
            return title, ""
        bracket = match.group(1).capitalize()
        title_without_bracket = self.normalize_mrc_title(title[:match.start()].strip())
        return title_without_bracket, bracket

    def build_event_name(self, season: int, round_group: str, bracket: Optional[str] = None) -> str:
        bracket_text = f" ({bracket})" if bracket else ""
        return f"MRC S{season} - {round_group}{bracket_text}"

    def normalize_status(self, status: str) -> str:
        for allowed in MATCH_STATUSES:
            if allowed.lower() == status.strip().lower():
                return allowed
        raise ValueError(f"Status must be one of: {', '.join(MATCH_STATUSES)}")

    def get_default_timezone(self, guild_id: int) -> str:
        return self.db.get_guild_settings(guild_id)["timezone"]

    async def cleanup_session_messages(self, messages: list):
        for message in messages:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                continue

    # ==================== DISCORD HELPERS ====================

    def get_reminder_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Pick the configured reminder channel, or a writable fallback."""
        settings = self.db.get_guild_settings(guild.id)
        configured_channel_id = settings.get("reminder_channel_id") or settings.get("scrim_reminder_channel_id")
        if configured_channel_id:
            channel = guild.get_channel(configured_channel_id)
            if isinstance(channel, discord.TextChannel):
                permissions = channel.permissions_for(guild.me)
                if permissions.view_channel and permissions.send_messages:
                    return channel

        channels = []
        if guild.system_channel:
            channels.append(guild.system_channel)
        channels.extend(channel for channel in guild.text_channels if channel != guild.system_channel)

        for channel in channels:
            permissions = channel.permissions_for(guild.me)
            if permissions.view_channel and permissions.send_messages:
                return channel
        return None

    def get_mrc_event_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        settings = self.db.get_guild_settings(guild.id)
        configured_channel_id = settings.get("mrc_event_channel_id")
        if configured_channel_id:
            channel = guild.get_channel(configured_channel_id)
            if isinstance(channel, discord.TextChannel):
                permissions = channel.permissions_for(guild.me)
                if permissions.view_channel and permissions.send_messages:
                    return channel
        return None

    def get_reminder_role_mentions(self, guild: discord.Guild) -> str:
        mentions = []
        for role_id in self.db.get_reminder_roles(guild.id):
            role = guild.get_role(role_id)
            if role:
                mentions.append(role.mention)
        return " ".join(mentions)

    async def create_discord_event(
        self,
        guild: discord.Guild,
        match_datetime: datetime,
        round_group: str,
        bracket: str,
        duration_hours: float,
        event_id: int,
        season: int = 7,
    ) -> Optional[str]:
        """Create a Discord Scheduled Event and return its ID."""
        try:
            event_name = self.build_event_name(season, round_group, bracket)
            event = await guild.create_scheduled_event(
                name=event_name,
                description=f"Vengeful MRC Match\nEvent ID: {self.format_public_id(event_id)}",
                start_time=match_datetime,
                end_time=event_end_time(match_datetime, duration_hours),
                privacy_level=discord.PrivacyLevel.guild_only,
                entity_type=discord.EntityType.external,
                location="Online",
            )
            return str(event.id)
        except discord.Forbidden:
            raise Exception("Bot does not have permission to create scheduled events")
        except Exception as e:
            raise Exception(f"Failed to create Discord event: {str(e)}")

    async def update_discord_event(
        self,
        guild: discord.Guild,
        event_id: str,
        match_datetime: Optional[datetime] = None,
        round_group: Optional[str] = None,
        bracket: Optional[str] = None,
        duration_hours: Optional[float] = None,
        event_database_id: Optional[int] = None,
        season: Optional[int] = None,
    ) -> bool:
        """Update an existing Discord Scheduled Event."""
        try:
            event = guild.get_scheduled_event(int(event_id))
            if not event:
                return False

            update_kwargs = {}
            if match_datetime:
                update_kwargs["start_time"] = match_datetime
            if match_datetime and duration_hours is not None:
                update_kwargs["end_time"] = event_end_time(match_datetime, duration_hours)
            if round_group is not None:
                update_kwargs["name"] = self.build_event_name(season or 7, round_group, bracket)
            if event_database_id is not None:
                update_kwargs["description"] = f"Vengeful MRC Match\nEvent ID: {self.format_public_id(event_database_id)}"

            if update_kwargs:
                await event.edit(**update_kwargs)
            return True
        except Exception as e:
            print(f"Error updating Discord event {event_id}: {e}")
            return False

    async def delete_discord_event(self, guild: discord.Guild, event_id: str) -> bool:
        """Delete a Discord Scheduled Event."""
        try:
            event = guild.get_scheduled_event(int(event_id))
            if event:
                await event.delete()
            return True
        except Exception as e:
            print(f"Error deleting Discord event {event_id}: {e}")
            return False

    def build_mrc_display_title(self, match: dict) -> str:
        return self.build_event_name(match.get("season", 7), match["round_group"], match.get("bracket"))

    def format_public_id(self, match_or_id) -> str:
        if isinstance(match_or_id, dict):
            match_id = match_or_id["id"]
        else:
            match_id = match_or_id
        return f"M{match_id}"

    def parse_public_id(self, event_id) -> int:
        value = str(event_id).strip().upper()
        if value.startswith("M"):
            value = value[1:]
        if not value.isdigit():
            raise ValueError("MRC Event ID must look like M1")
        return int(value)

    def build_discord_event_url(self, guild: discord.Guild, event_id: Optional[str]) -> Optional[str]:
        if not event_id:
            return None
        return f"https://discord.com/events/{guild.id}/{event_id}"

    def build_match_line(self, match: dict) -> str:
        archived = " | Archived" if match.get("archived") else ""
        return (
            f"`Event ID {self.format_public_id(match)}` {discord_time_display(match['datetime'], match['timezone'])}\n"
            f"{self.build_mrc_display_title(match)} | {match['duration_hours']:g}h | {match['status']}{archived}"
        )

    def build_mrc_created_message(self, match: dict, event_url: Optional[str] = None) -> str:
        message = f"**{self.build_mrc_display_title(match)}**\n"
        message += f"**Event ID:** {self.format_public_id(match)}\n"
        message += f"**Time:** {discord_time_display(match['datetime'], match['timezone'])}\n"
        message += f"**Duration:** {match['duration_hours']:g} hour(s)"
        if event_url:
            message += f"\n**Event Link:** {event_url}"
        return message

    async def post_mrc_created_message(
        self,
        guild: discord.Guild,
        fallback_channel,
        match: dict,
        event_url: Optional[str] = None,
    ):
        channel = self.get_mrc_event_channel(guild) or fallback_channel
        message = self.build_mrc_created_message(match, event_url)
        if channel:
            await channel.send(message)
        return channel

    # ==================== AUTOCOMPLETE ====================

    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        current_lower = current.lower()
        matches = [tz for tz in COMMON_TIMEZONES if current_lower in tz.lower()]
        if current and len(matches) < 25:
            try:
                normalized = normalize_timezone(current)
                if normalized not in matches:
                    matches.insert(0, normalized)
            except ValueError:
                pass
        return [app_commands.Choice(name=tz, value=tz) for tz in matches[:25]]

    async def match_id_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        matches = self.db.get_all_mrc_matches(interaction.guild.id)
        choices = []
        for match in matches:
            bracket = f" {match['bracket']}" if match.get("bracket") else ""
            public_id = self.format_public_id(match)
            label = f"Event ID {public_id} S{match.get('season', 7)} {match['round_group']}{bracket} {match['status']}"
            if current and current.lower() not in public_id.lower() and current.lower() not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=public_id))
            if len(choices) == 25:
                break
        return choices

    # ==================== COMMANDS ====================

    mrc_group = app_commands.Group(name="mrc", description="MRC schedule management commands")

    @mrc_group.command(name="import", description="Bulk import MRC schedule from multiline text")
    @app_commands.rename(
        duration_hours="duration_hrs",
        timezone_name="timezone",
    )
    @app_commands.describe(
        schedule="Multiline schedule text. Format: April 25 1:00 PM Rounds 1-3 Upper",
        duration_hours="Duration (hrs) for every imported event, such as 2 or 1.5",
        timezone_name="Default timezone for lines without a trailing timezone",
    )
    async def mrc_import(
        self,
        interaction: discord.Interaction,
        schedule: str,
        duration_hours: float,
        timezone_name: Optional[str] = None,
    ):
        """Import multiple MRC matches from bulk text."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            default_timezone = normalize_timezone(timezone_name, self.get_default_timezone(guild.id))
            duration_hours = validate_duration_hours(duration_hours)
            lines = schedule.strip().split("\n")
            imported = 0
            failed = []

            for line in lines:
                parsed = self.parse_mrc_line(line, default_timezone)
                if parsed:
                    dt, round_group, bracket, used_timezone = parsed
                    event_database_id = None
                    try:
                        event_database_id = self.db.add_mrc_match(
                            guild.id,
                            to_utc_iso(dt),
                            round_group,
                            bracket,
                            timezone_name=used_timezone,
                            duration_hours=duration_hours,
                        )
                        event_id = await self.create_discord_event(
                            guild,
                            dt,
                            round_group,
                            bracket,
                            duration_hours,
                            event_database_id,
                            7,
                        )
                        self.db.update_mrc_match(guild.id, event_database_id, discord_event_id=event_id)
                        created_match = self.db.get_mrc_match(guild.id, event_database_id)
                        await self.post_mrc_created_message(
                            guild,
                            interaction.channel,
                            created_match,
                            self.build_discord_event_url(guild, event_id),
                        )
                        imported += 1
                    except Exception as e:
                        if event_database_id is not None:
                            self.db.delete_mrc_match(guild.id, event_database_id)
                        failed.append((line, str(e)))
                else:
                    failed.append((line, "Could not parse line"))

            response = "**MRC Schedule Import Results**\n"
            response += f"Successfully imported: **{imported}** matches\n"
            response += f"Duration: **{duration_hours:g}** hour(s)\n"
            if failed:
                response += f"Failed to import: **{len(failed)}** matches\n\n"
                response += "**Failed entries:**\n"
                for line, error in failed[:5]:
                    response += f"- `{line}`: {error}\n"
                if len(failed) > 5:
                    response += f"... and {len(failed) - 5} more\n"

            await interaction.followup.send(response)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_import.autocomplete("timezone_name")
    async def mrc_import_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

    @mrc_group.command(name="add", description="Add a single MRC match")
    @app_commands.rename(
        duration_hours="duration_hrs",
        datetime_str="date_time",
    )
    @app_commands.describe(
        season="MRC season number",
        duration_hours="Duration (hrs), such as 2 or 1.5",
        datetime_str="Date & time, optionally with timezone (e.g., 4/20/26 3PM EST)",
        name="Event name, such as Rounds 7-9 or Grand Finals",
    )
    async def mrc_add(
        self,
        interaction: discord.Interaction,
        season: int,
        duration_hours: float,
        datetime_str: str,
        name: str,
    ):
        """Add a single MRC match."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            if season <= 0:
                raise ValueError("Season must be a positive number")
            used_timezone = self.get_default_timezone(guild.id)
            duration_hours = validate_duration_hours(duration_hours)
            dt = self.parse_mrc_datetime(datetime_str, used_timezone)
            _, trailing_timezone = split_trailing_timezone(datetime_str)
            used_timezone = normalize_timezone(trailing_timezone, used_timezone)
            round_group, bracket = self.extract_optional_bracket(name)

            match_id = None
            match_id = self.db.add_mrc_match(
                guild.id,
                to_utc_iso(dt),
                round_group,
                bracket,
                timezone_name=used_timezone,
                duration_hours=duration_hours,
                season=season,
            )
            try:
                event_id = await self.create_discord_event(
                    guild,
                    dt,
                    round_group,
                    bracket,
                    duration_hours,
                    match_id,
                    season,
                )
                self.db.update_mrc_match(guild.id, match_id, discord_event_id=event_id)
            except Exception:
                self.db.delete_mrc_match(guild.id, match_id)
                raise

            created_match = self.db.get_mrc_match(guild.id, match_id)
            target_channel = self.get_mrc_event_channel(guild)
            if target_channel:
                await self.post_mrc_created_message(
                    guild,
                    interaction.channel,
                    created_match,
                    self.build_discord_event_url(guild, event_id),
                )
                await interaction.followup.send(f"MRC Event ID {self.format_public_id(match_id)} posted in {target_channel.mention}.")
            else:
                await interaction.followup.send(
                    self.build_mrc_created_message(created_match, self.build_discord_event_url(guild, event_id))
                )
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="session", description="Start an interactive session to add multiple matches")
    @app_commands.rename(duration_hours="duration_hrs")
    @app_commands.describe(
        season="MRC season number for every match in this session",
        duration_hours="Duration (hrs) for every match in this session",
    )
    async def mrc_session(self, interaction: discord.Interaction, season: int, duration_hours: float):
        """Start interactive session for adding matches line by line."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            default_timezone = self.get_default_timezone(guild.id)
            if season <= 0:
                raise ValueError("Season must be a positive number")
            duration_hours = validate_duration_hours(duration_hours)
            user = interaction.user
            channel = interaction.channel

            await interaction.followup.send(
                f"**MRC Session started**\n"
                f"Default timezone: `{default_timezone}`\n"
                f"Season: `{season}`\n"
                f"Duration: `{duration_hours:g}` hour(s)\n"
                f"Enter MRC schedule lines one per message.\n"
                f"Examples: `April 25 1:00 PM Rounds 1-3`, `4/20/26 3PM EST Rounds 7-9`, "
                f"or `4/20/26 3PM EST Rounds 1-3 Upper`\n"
                f"Type `done` when finished.\n"
                f"Type `cancel` to abort.\n\n"
                f"Only you can see this instruction message.",
                ephemeral=True,
            )

            imported = 0
            session_messages = []

            def check(msg):
                return msg.author == user and msg.channel == channel

            while True:
                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=300)
                    session_messages.append(msg)
                    content = msg.content.strip()

                    if content.lower() == "done":
                        await self.cleanup_session_messages(session_messages)
                        await interaction.followup.send(
                            f"**Session ended**\nSuccessfully imported: **{imported}** matches",
                            ephemeral=True,
                        )
                        break
                    if content.lower() == "cancel":
                        await self.cleanup_session_messages(session_messages)
                        await interaction.followup.send("Session cancelled.", ephemeral=True)
                        break

                    parsed = self.parse_mrc_line(content, default_timezone)
                    if parsed:
                        dt, round_group, bracket, used_timezone = parsed
                        event_database_id = None
                        try:
                            event_database_id = self.db.add_mrc_match(
                                guild.id,
                                to_utc_iso(dt),
                                round_group,
                                bracket,
                                timezone_name=used_timezone,
                                duration_hours=duration_hours,
                                season=season,
                            )
                            event_id = await self.create_discord_event(
                                guild,
                                dt,
                                round_group,
                                bracket,
                                duration_hours,
                                event_database_id,
                                season,
                            )
                            self.db.update_mrc_match(guild.id, event_database_id, discord_event_id=event_id)
                            created_match = self.db.get_mrc_match(guild.id, event_database_id)
                            await self.post_mrc_created_message(
                                guild,
                                channel,
                                created_match,
                                self.build_discord_event_url(guild, event_id),
                            )
                            imported += 1
                            await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")
                        except Exception as e:
                            if event_database_id is not None:
                                self.db.delete_mrc_match(guild.id, event_database_id)
                            await interaction.followup.send(f"Warning: {str(e)}", ephemeral=True)
                    else:
                        await interaction.followup.send(
                            "Could not parse. Use a format like `April 25 1:00 PM Rounds 1-3` "
                            "or `4/20/26 3PM EST Rounds 7-9`.",
                            ephemeral=True,
                        )
                except discord.errors.WaitTimeoutError:
                    await self.cleanup_session_messages(session_messages)
                    await interaction.followup.send("Session timeout. Ending session.", ephemeral=True)
                    break
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="view", description="View all scheduled MRC matches")
    @app_commands.describe(
        include_completed="Show completed and cancelled matches",
        include_archived="Show archived matches",
    )
    async def mrc_view(
        self,
        interaction: discord.Interaction,
        include_completed: bool = False,
        include_archived: bool = False,
    ):
        """Display all MRC matches for the guild."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        matches = self.db.get_all_mrc_matches(
            guild.id,
            include_completed=include_completed,
            include_archived=include_archived,
        )
        if not matches:
            await interaction.followup.send("No MRC matches scheduled.")
            return

        view = MRCMatchPageView(self, matches, "MRC Schedule")
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    @mrc_group.command(name="upcoming", description="View upcoming MRC matches")
    @app_commands.describe(
        days="Number of days to include",
        include_completed="Show completed and cancelled matches",
        include_archived="Show archived matches",
    )
    async def mrc_upcoming(
        self,
        interaction: discord.Interaction,
        days: Optional[int] = 14,
        include_completed: bool = False,
        include_archived: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        days = max(1, min(days or 14, 90))
        matches = self.db.get_upcoming_mrc_matches(
            guild.id,
            days=days,
            include_completed=include_completed,
            include_archived=include_archived,
        )
        if not matches:
            await interaction.followup.send(f"No MRC matches scheduled in the next {days} day(s).")
            return

        view = MRCMatchPageView(self, matches, f"Upcoming MRC Events ({days} days)")
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    @mrc_group.command(name="status", description="Set an MRC match status")
    @app_commands.describe(event_id="Event ID to update")
    @app_commands.choices(status=STATUS_CHOICES)
    async def mrc_status(
        self,
        interaction: discord.Interaction,
        event_id: str,
        status: str,
    ):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            event_database_id = self.parse_public_id(event_id)
            match = self.db.get_mrc_match(guild.id, event_database_id)
            if not match:
                await interaction.followup.send(f"Event ID {self.format_public_id(event_database_id)} not found.", ephemeral=True)
                return
            status = self.normalize_status(status)
            self.db.update_mrc_match(guild.id, event_database_id, status=status)
            updated = self.db.get_mrc_match(guild.id, event_database_id)
            if updated["discord_event_id"]:
                await self.update_discord_event(
                    guild,
                    updated["discord_event_id"],
                    parse_stored_datetime(updated["datetime"]),
                    updated["round_group"],
                    updated["bracket"],
                    updated["duration_hours"],
                    updated["id"],
                    updated.get("season", 7),
                )
            await interaction.followup.send(f"**Event Status Updated**\n{self.build_match_line(updated)}")
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_status.autocomplete("event_id")
    async def mrc_status_match_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.match_id_autocomplete(interaction, current)

    @mrc_group.command(name="archive_completed", description="Archive completed and cancelled MRC matches")
    async def mrc_archive_completed(self, interaction: discord.Interaction):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            count = self.db.archive_completed_mrc_matches(guild.id)
            await interaction.followup.send(f"Archived {count} completed/cancelled match(es).", ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="repair_events", description="Recreate missing Discord events for MRC matches")
    @app_commands.describe(include_completed="Also repair completed/cancelled matches")
    async def mrc_repair_events(self, interaction: discord.Interaction, include_completed: bool = False):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            matches = self.db.get_all_mrc_matches(
                guild.id,
                include_completed=include_completed,
                include_archived=False,
            )
            checked = 0
            repaired = 0
            missing = 0
            failed = []

            for match in matches:
                checked += 1
                event_exists = False
                if match["discord_event_id"]:
                    try:
                        event_exists = guild.get_scheduled_event(int(match["discord_event_id"])) is not None
                    except (TypeError, ValueError):
                        event_exists = False
                if event_exists:
                    await self.update_discord_event(
                        guild,
                        match["discord_event_id"],
                        parse_stored_datetime(match["datetime"]),
                        match["round_group"],
                        match["bracket"],
                        match["duration_hours"],
                        match["id"],
                        match.get("season", 7),
                    )
                    continue

                missing += 1
                try:
                    match_dt = parse_stored_datetime(match["datetime"])
                    event_id = await self.create_discord_event(
                        guild,
                        match_dt,
                        match["round_group"],
                        match["bracket"],
                        match["duration_hours"],
                        match["id"],
                        match.get("season", 7),
                    )
                    self.db.update_mrc_match(guild.id, match["id"], discord_event_id=event_id)
                    repaired += 1
                except Exception as exc:
                    failed.append(f"Event ID {self.format_public_id(match)}: {str(exc)}")

            response = "**MRC Event Repair Complete**\n"
            response += f"Checked: {checked}\n"
            response += f"Missing/broken: {missing}\n"
            response += f"Recreated: {repaired}"
            if failed:
                response += "\n\nFailures:\n" + "\n".join(f"- {item}" for item in failed[:5])
                if len(failed) > 5:
                    response += f"\n... and {len(failed) - 5} more"
            await interaction.followup.send(response, ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="delete", description="Delete an MRC match")
    @app_commands.describe(event_id="Event ID to delete")
    async def mrc_delete(self, interaction: discord.Interaction, event_id: str):
        """Delete an MRC match and its Discord event."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            event_database_id = self.parse_public_id(event_id)
            match = self.db.get_mrc_match(guild.id, event_database_id)
            if not match:
                await interaction.followup.send(f"Event ID {self.format_public_id(event_database_id)} not found.", ephemeral=True)
                return

            if match["discord_event_id"]:
                await self.delete_discord_event(guild, match["discord_event_id"])

            self.db.delete_mrc_match(guild.id, event_database_id)
            await interaction.followup.send(f"Event ID {self.format_public_id(event_database_id)} deleted.")
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_delete.autocomplete("event_id")
    async def mrc_delete_match_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.match_id_autocomplete(interaction, current)

    # ==================== BACKGROUND TASKS ====================

    @tasks.loop(minutes=1)
    async def reminder_task(self):
        """Check for MRC matches starting within 30 minutes and send one reminder."""
        try:
            matches = self.db.get_matches_needing_30_minute_reminder()
            for match in matches:
                if match["status"] in {"Completed", "Cancelled"}:
                    self.db.mark_30_minute_reminder_sent(match["guild_id"], match["id"])
                    continue

                guild = self.bot.get_guild(match["guild_id"])
                if not guild:
                    continue

                channel = self.get_reminder_channel(guild)
                if not channel:
                    print(f"No writable reminder channel found for guild {guild.id}")
                    continue

                event_url = None
                if match["discord_event_id"]:
                    event = guild.get_scheduled_event(int(match["discord_event_id"]))
                    if event:
                        event_url = event.url

                pings = self.get_reminder_role_mentions(guild)
                message = ""
                if pings:
                    message += f"{pings}\n"
                message += (
                    f"**MRC match starts in 30 minutes**\n"
                    f"**Time:** {discord_time_display(match['datetime'], match['timezone'])}\n"
                    f"**Season:** {match.get('season', 7)}\n"
                    f"**Round:** {match['round_group']}\n"
                    f"**Duration:** {match['duration_hours']:g} hour(s)\n"
                    f"**Status:** {match['status']}"
                )
                if match.get("bracket"):
                    message += f"\n**Bracket:** {match['bracket']}"
                if event_url:
                    message += f"\n**Event:** {event_url}"

                await channel.send(message, allowed_mentions=discord.AllowedMentions(roles=True))
                self.db.mark_30_minute_reminder_sent(match["guild_id"], match["id"])
        except Exception as e:
            print(f"Error in reminder task: {e}")

    @reminder_task.before_loop
    async def before_reminder_task(self):
        """Wait for bot to be ready before starting reminder task."""
        await self.bot.wait_until_ready()


async def setup(bot):
    """Load the MRC cog."""
    await bot.add_cog(MRCCog(bot))
