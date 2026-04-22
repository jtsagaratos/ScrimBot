import re
from datetime import datetime
from typing import Optional, Tuple

import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

from models.database import DatabaseManager
from models.permissions import ensure_manager
from models.time_utils import (
    COMMON_TIMEZONES,
    discord_time_display,
    localize_datetime,
    normalize_timezone,
    parse_stored_datetime,
    split_trailing_timezone,
    to_utc_iso,
)


MATCH_STATUSES = ["Scheduled", "Checked In", "In Progress", "Completed", "Cancelled"]
BRACKET_CHOICES = [
    app_commands.Choice(name="Upper", value="Upper"),
    app_commands.Choice(name="Lower", value="Lower"),
]
STATUS_CHOICES = [app_commands.Choice(name=status, value=status) for status in MATCH_STATUSES]


class MRCEditModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int, match: dict):
        super().__init__(title=f"Edit MRC Match #{match['id']}")
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
        self.rounds_input = discord.ui.TextInput(
            label="Rounds",
            default=match["round_group"],
            placeholder="Rounds 1-3",
            max_length=80,
        )
        self.bracket_input = discord.ui.TextInput(
            label="Bracket",
            default=match["bracket"],
            placeholder="Upper or Lower",
            max_length=20,
        )
        self.status_input = discord.ui.TextInput(
            label="Status",
            default=match["status"],
            placeholder="Scheduled, Checked In, In Progress, Completed, Cancelled",
            max_length=40,
        )

        self.add_item(self.datetime_input)
        self.add_item(self.timezone_input)
        self.add_item(self.rounds_input)
        self.add_item(self.bracket_input)
        self.add_item(self.status_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            match = self.cog.db.get_mrc_match(self.guild_id, self.match["id"])
            if not match:
                await interaction.response.send_message(f"Match with ID {self.match['id']} not found.", ephemeral=True)
                return

            timezone_name = normalize_timezone(str(self.timezone_input.value).strip(), match["timezone"])
            new_datetime = self.cog.parse_mrc_datetime(str(self.datetime_input.value).strip(), timezone_name)
            round_group = self.cog.normalize_round_group(str(self.rounds_input.value).strip())
            bracket = str(self.bracket_input.value).strip().capitalize()
            if bracket not in {"Upper", "Lower"}:
                raise ValueError("Bracket must be 'Upper' or 'Lower'")
            status = self.cog.normalize_status(str(self.status_input.value).strip())

            self.cog.db.update_mrc_match(
                self.guild_id,
                match["id"],
                datetime=to_utc_iso(new_datetime),
                round_group=round_group,
                bracket=bracket,
                timezone=timezone_name,
                status=status,
                reminder_sent_30=0,
            )

            if match["discord_event_id"]:
                await self.cog.update_discord_event(
                    guild,
                    match["discord_event_id"],
                    new_datetime,
                    round_group,
                    bracket,
                )

            updated = self.cog.db.get_mrc_match(self.guild_id, match["id"])
            await interaction.response.send_message(
                f"**Match Updated**\n{self.cog.build_match_line(updated)}"
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
            embed.add_field(name=f"Match #{match['id']}", value=self.cog.build_match_line(match), inline=False)
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
        """
        Parse a single MRC schedule line.
        Format: "April 25 1:00 PM Rounds 1-3 Upper [timezone]"
        Returns: (aware_datetime, round_group, bracket, timezone_name) or None.
        """
        line = line.strip()
        if not line:
            return None

        try:
            pattern = (
                r"(\w+)\s+(\d{1,2})\s+(\d{1,2}):(\d{2})\s+"
                r"(AM|PM)\s+Rounds?\s+([\d\s\-]+)\s+(Upper|Lower)(?:\s+(.+))?$"
            )
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                return None

            month_str, day_str, hour_str, minute_str, am_pm, rounds_str, bracket, line_timezone = match.groups()
            timezone_name = normalize_timezone(line_timezone, default_timezone)
            day = int(day_str)
            hour = int(hour_str)
            minute = int(minute_str)

            if am_pm.upper() == "PM" and hour != 12:
                hour += 12
            elif am_pm.upper() == "AM" and hour == 12:
                hour = 0

            date_str = f"{month_str} {day} {year}"
            dt = datetime.strptime(date_str, "%B %d %Y").replace(hour=hour, minute=minute)
            aware_dt = localize_datetime(dt, timezone_name)

            round_group = f"Rounds {rounds_str.strip()}"
            bracket = bracket.strip().capitalize()

            return (aware_dt, round_group, bracket, timezone_name)
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

        raise ValueError("Date must look like 'April 25 1:00 PM', optionally with a timezone.")

    def normalize_round_group(self, rounds: str) -> str:
        """Return a consistent 'Rounds X-Y' label from user input."""
        rounds = rounds.strip()
        if re.match(r"^rounds?\b", rounds, re.IGNORECASE):
            return rounds[0].upper() + rounds[1:]
        return f"Rounds {rounds}"

    def normalize_status(self, status: str) -> str:
        for allowed in MATCH_STATUSES:
            if allowed.lower() == status.strip().lower():
                return allowed
        raise ValueError(f"Status must be one of: {', '.join(MATCH_STATUSES)}")

    def get_default_timezone(self, guild_id: int) -> str:
        return self.db.get_guild_settings(guild_id)["timezone"]

    # ==================== DISCORD HELPERS ====================

    def get_reminder_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Pick the configured reminder channel, or a writable fallback."""
        settings = self.db.get_guild_settings(guild.id)
        configured_channel_id = settings.get("reminder_channel_id")
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
    ) -> Optional[str]:
        """Create a Discord Scheduled Event and return its ID."""
        try:
            event_name = f"MRC S7 - {round_group} ({bracket})"
            event = await guild.create_scheduled_event(
                name=event_name,
                description="Vengeful MRC Match",
                start_time=match_datetime,
                privacy_level=discord.PrivacyLevel.guild_only,
                entity_type=discord.ScheduledEventEntityType.external,
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
    ) -> bool:
        """Update an existing Discord Scheduled Event."""
        try:
            event = guild.get_scheduled_event(int(event_id))
            if not event:
                return False

            update_kwargs = {}
            if match_datetime:
                update_kwargs["start_time"] = match_datetime
            if round_group and bracket:
                update_kwargs["name"] = f"MRC S7 - {round_group} ({bracket})"

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

    def build_match_line(self, match: dict) -> str:
        archived = " | Archived" if match.get("archived") else ""
        return (
            f"`#{match['id']}` {discord_time_display(match['datetime'], match['timezone'])}\n"
            f"{match['round_group']} | {match['bracket']} | {match['status']}{archived}"
        )

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
            label = f"#{match['id']} {match['round_group']} {match['bracket']} {match['status']}"
            if current and current not in str(match["id"]) and current.lower() not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=match["id"]))
            if len(choices) == 25:
                break
        return choices

    # ==================== COMMANDS ====================

    mrc_group = app_commands.Group(name="mrc", description="MRC schedule management commands")

    @mrc_group.command(name="config_view", description="View MRC bot settings for this server")
    async def mrc_config_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        settings = self.db.get_guild_settings(interaction.guild.id)
        channel = interaction.guild.get_channel(settings["reminder_channel_id"]) if settings["reminder_channel_id"] else None
        roles = [interaction.guild.get_role(role_id) for role_id in self.db.get_reminder_roles(interaction.guild.id)]
        role_mentions = [role.mention for role in roles if role]

        response = "**MRC Settings**\n"
        response += f"**Timezone:** {settings['timezone']}\n"
        response += f"**Reminder Channel:** {channel.mention if channel else 'Auto'}\n"
        response += f"**Reminder Roles:** {', '.join(role_mentions) if role_mentions else 'None'}"
        await interaction.followup.send(response, ephemeral=True)

    @mrc_group.command(name="config_channel", description="Set the channel where MRC reminders are sent")
    @app_commands.describe(channel="Reminder channel")
    async def mrc_config_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            self.db.update_guild_settings(interaction.guild.id, reminder_channel_id=channel.id)
            await interaction.followup.send(f"Reminder channel set to {channel.mention}.", ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="config_timezone", description="Set the default timezone for MRC and scrim commands")
    @app_commands.describe(timezone_name="Timezone abbreviation or IANA name")
    async def mrc_config_timezone(self, interaction: discord.Interaction, timezone_name: str):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            normalized = normalize_timezone(timezone_name)
            self.db.update_guild_settings(interaction.guild.id, timezone=normalized)
            await interaction.followup.send(f"Default timezone set to `{normalized}`.", ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_config_timezone.autocomplete("timezone_name")
    async def mrc_config_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

    @mrc_group.command(name="reminder_role_add", description="Add a role to ping in MRC reminders")
    async def mrc_reminder_role_add(self, interaction: discord.Interaction, role: discord.Role):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            self.db.add_reminder_role(interaction.guild.id, role.id)
            await interaction.followup.send(f"Added {role.mention} to MRC reminder pings.", ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="reminder_role_remove", description="Remove a role from MRC reminders")
    async def mrc_reminder_role_remove(self, interaction: discord.Interaction, role: discord.Role):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            removed = self.db.remove_reminder_role(interaction.guild.id, role.id)
            if removed:
                await interaction.followup.send(f"Removed {role.mention} from MRC reminder pings.", ephemeral=True)
            else:
                await interaction.followup.send(f"{role.mention} was not configured for MRC reminders.", ephemeral=True)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_group.command(name="reminder_role_list", description="List roles pinged in MRC reminders")
    async def mrc_reminder_role_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return
        roles = [interaction.guild.get_role(role_id) for role_id in self.db.get_reminder_roles(interaction.guild.id)]
        role_mentions = [role.mention for role in roles if role]
        await interaction.followup.send(
            f"Reminder roles: {', '.join(role_mentions) if role_mentions else 'None'}",
            ephemeral=True,
        )

    @mrc_group.command(name="import", description="Bulk import MRC schedule from multiline text")
    @app_commands.describe(
        schedule="Multiline schedule text. Format: April 25 1:00 PM Rounds 1-3 Upper",
        timezone_name="Default timezone for lines without a trailing timezone",
    )
    async def mrc_import(
        self,
        interaction: discord.Interaction,
        schedule: str,
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
            lines = schedule.strip().split("\n")
            imported = 0
            failed = []

            for line in lines:
                parsed = self.parse_mrc_line(line, default_timezone)
                if parsed:
                    dt, round_group, bracket, used_timezone = parsed
                    try:
                        event_id = await self.create_discord_event(guild, dt, round_group, bracket)
                        self.db.add_mrc_match(
                            guild.id,
                            to_utc_iso(dt),
                            round_group,
                            bracket,
                            discord_event_id=event_id,
                            timezone_name=used_timezone,
                        )
                        imported += 1
                    except Exception as e:
                        failed.append((line, str(e)))
                else:
                    failed.append((line, "Could not parse line"))

            response = "**MRC Schedule Import Results**\n"
            response += f"Successfully imported: **{imported}** matches\n"
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
    @app_commands.describe(
        datetime_str="Date and time (e.g., 'April 25 1:00 PM')",
        rounds="Round group (e.g., 'Rounds 1-3' or '1-3')",
        bracket="Upper or Lower bracket",
        timezone_name="Timezone abbreviation or IANA name",
    )
    @app_commands.choices(bracket=BRACKET_CHOICES)
    async def mrc_add(
        self,
        interaction: discord.Interaction,
        datetime_str: str,
        rounds: str,
        bracket: str,
        timezone_name: Optional[str] = None,
    ):
        """Add a single MRC match."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            used_timezone = normalize_timezone(timezone_name, self.get_default_timezone(guild.id))
            dt = self.parse_mrc_datetime(datetime_str, used_timezone)
            round_group = self.normalize_round_group(rounds)

            event_id = await self.create_discord_event(guild, dt, round_group, bracket)
            match_id = self.db.add_mrc_match(
                guild.id,
                to_utc_iso(dt),
                round_group,
                bracket,
                discord_event_id=event_id,
                timezone_name=used_timezone,
            )

            response = "**MRC Match Added**\n"
            response += f"**ID:** {match_id}\n"
            response += f"**Time:** {discord_time_display(to_utc_iso(dt), used_timezone)}\n"
            response += f"**Round:** {round_group}\n"
            response += f"**Bracket:** {bracket}\n"
            response += f"**Status:** Scheduled"
            await interaction.followup.send(response)
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_add.autocomplete("timezone_name")
    async def mrc_add_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

    @mrc_group.command(name="session", description="Start an interactive session to add multiple matches")
    async def mrc_session(self, interaction: discord.Interaction):
        """Start interactive session for adding matches line by line."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            default_timezone = self.get_default_timezone(guild.id)
            user = interaction.user
            channel = interaction.channel

            await channel.send(
                f"**MRC Session started for {user.mention}**\n"
                f"Default timezone: `{default_timezone}`\n"
                f"Enter MRC schedule lines one per message (format: 'April 25 1:00 PM Rounds 1-3 Upper')\n"
                f"Type `done` when finished.\n"
                f"Type `cancel` to abort."
            )

            imported = 0

            def check(msg):
                return msg.author == user and msg.channel == channel

            while True:
                try:
                    msg = await self.bot.wait_for("message", check=check, timeout=300)
                    content = msg.content.strip()

                    if content.lower() == "done":
                        await channel.send(f"**Session ended**\nSuccessfully imported: **{imported}** matches")
                        break
                    if content.lower() == "cancel":
                        await channel.send("Session cancelled.")
                        break

                    parsed = self.parse_mrc_line(content, default_timezone)
                    if parsed:
                        dt, round_group, bracket, used_timezone = parsed
                        try:
                            event_id = await self.create_discord_event(guild, dt, round_group, bracket)
                            self.db.add_mrc_match(
                                guild.id,
                                to_utc_iso(dt),
                                round_group,
                                bracket,
                                discord_event_id=event_id,
                                timezone_name=used_timezone,
                            )
                            imported += 1
                            await msg.add_reaction("\N{WHITE HEAVY CHECK MARK}")
                        except Exception as e:
                            await msg.reply(f"Warning: {str(e)}")
                    else:
                        await msg.reply("Could not parse. Use format: 'April 25 1:00 PM Rounds 1-3 Upper'")
                except discord.errors.WaitTimeoutError:
                    await channel.send("Session timeout. Ending session.")
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
        await interaction.response.defer()
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
        await interaction.followup.send(embed=view.build_embed(), view=view)

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
        await interaction.response.defer()
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

        view = MRCMatchPageView(self, matches, f"Upcoming MRC Matches ({days} days)")
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @mrc_group.command(name="edit", description="Edit an existing MRC match")
    @app_commands.describe(
        match_id="ID of the match to edit",
    )
    async def mrc_edit(
        self,
        interaction: discord.Interaction,
        match_id: int,
    ):
        """Open a prefilled modal to edit an existing MRC match."""
        try:
            self.ensure_manager(interaction)

            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            match = self.db.get_mrc_match(guild.id, match_id)
            if not match:
                await interaction.response.send_message(f"Match with ID {match_id} not found.", ephemeral=True)
                return

            await interaction.response.send_modal(MRCEditModal(self, guild.id, match))
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_edit.autocomplete("match_id")
    async def mrc_edit_match_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.match_id_autocomplete(interaction, current)

    @mrc_group.command(name="status", description="Set an MRC match status")
    @app_commands.choices(status=STATUS_CHOICES)
    async def mrc_status(
        self,
        interaction: discord.Interaction,
        match_id: int,
        status: str,
    ):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            match = self.db.get_mrc_match(guild.id, match_id)
            if not match:
                await interaction.followup.send(f"Match with ID {match_id} not found.", ephemeral=True)
                return
            status = self.normalize_status(status)
            self.db.update_mrc_match(guild.id, match_id, status=status)
            updated = self.db.get_mrc_match(guild.id, match_id)
            await interaction.followup.send(f"**Match Status Updated**\n{self.build_match_line(updated)}")
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_status.autocomplete("match_id")
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
                    continue

                missing += 1
                try:
                    match_dt = parse_stored_datetime(match["datetime"])
                    event_id = await self.create_discord_event(
                        guild,
                        match_dt,
                        match["round_group"],
                        match["bracket"],
                    )
                    self.db.update_mrc_match(guild.id, match["id"], discord_event_id=event_id)
                    repaired += 1
                except Exception as exc:
                    failed.append(f"#{match['id']}: {str(exc)}")

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
    @app_commands.describe(match_id="ID of the match to delete")
    async def mrc_delete(self, interaction: discord.Interaction, match_id: int):
        """Delete an MRC match and its Discord event."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            match = self.db.get_mrc_match(guild.id, match_id)
            if not match:
                await interaction.followup.send(f"Match with ID {match_id} not found.", ephemeral=True)
                return

            if match["discord_event_id"]:
                await self.delete_discord_event(guild, match["discord_event_id"])

            self.db.delete_mrc_match(guild.id, match_id)
            await interaction.followup.send(f"Match {match_id} deleted.")
        except Exception as e:
            await self.send_error(interaction, e)

    @mrc_delete.autocomplete("match_id")
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
                    f"**Round:** {match['round_group']}\n"
                    f"**Bracket:** {match['bracket']}\n"
                    f"**Status:** {match['status']}"
                )
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
