from typing import Optional
from datetime import datetime, timedelta, timezone

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


TOURNAMENT_STATUSES = ["Scheduled", "Checked In", "In Progress", "Completed", "Cancelled"]
TOURNAMENT_STATUS_CHOICES = [app_commands.Choice(name=status, value=status) for status in TOURNAMENT_STATUSES]


class TournamentEditModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int, tournament: dict):
        super().__init__(title=f"Edit Tournament Event T{tournament['id']}")
        self.cog = cog
        self.guild_id = guild_id
        self.tournament = tournament

        local_dt = parse_stored_datetime(tournament["datetime"]).astimezone(pytz.timezone(tournament["timezone"]))

        self.name_input = discord.ui.TextInput(
            label="Tournament Name",
            default=tournament["tournament_name"],
            placeholder="Ignite Qualifier",
            max_length=120,
        )
        self.datetime_input = discord.ui.TextInput(
            label="Date/Time",
            default=local_dt.strftime("%B %d %I:%M %p %Y"),
            placeholder="April 25 4:00 PM 2026",
            max_length=80,
        )
        self.duration_input = discord.ui.TextInput(
            label="Duration Hours",
            default=f"{tournament.get('duration_hours', 2.0):g}",
            placeholder="2 or 1.5",
            max_length=10,
        )
        self.timezone_input = discord.ui.TextInput(
            label="Timezone",
            default=tournament["timezone"],
            placeholder="America/Denver, EST, PST, UTC",
            max_length=80,
        )

        self.add_item(self.name_input)
        self.add_item(self.datetime_input)
        self.add_item(self.duration_input)
        self.add_item(self.timezone_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            tournament = self.cog.db.get_tournament(self.guild_id, self.tournament["id"])
            if not tournament:
                await interaction.response.send_message(f"Event ID T{self.tournament['id']} not found.", ephemeral=True)
                return

            tournament_name = str(self.name_input.value).strip()
            if not tournament_name:
                raise ValueError("Tournament name cannot be empty.")
            timezone_name = normalize_timezone(str(self.timezone_input.value).strip(), tournament["timezone"])
            event_dt, used_timezone = self.cog.parse_datetime_string(str(self.datetime_input.value).strip(), timezone_name)
            duration_hours = validate_duration_hours(str(self.duration_input.value).strip())

            self.cog.db.update_tournament(
                self.guild_id,
                tournament["id"],
                tournament_name=tournament_name,
                datetime=to_utc_iso(event_dt),
                timezone=used_timezone,
                duration_hours=duration_hours,
                reminder_sent_30=0,
            )

            if tournament["discord_event_id"]:
                await self.cog.update_discord_event(
                    guild,
                    tournament["discord_event_id"],
                    tournament["id"],
                    tournament_name,
                    event_dt,
                    duration_hours,
                )

            updated = self.cog.db.get_tournament(self.guild_id, tournament["id"])
            await interaction.response.send_message(f"**Tournament Event Updated**\n{self.cog.build_tournament_line(updated)}")
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class TournamentPageView(discord.ui.View):
    def __init__(self, cog, tournaments: list, title: str, page_size: int = 5):
        super().__init__(timeout=300)
        self.cog = cog
        self.tournaments = tournaments
        self.title = title
        self.page_size = page_size
        self.page = 0
        self.update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.tournaments) + self.page_size - 1) // self.page_size)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.gold(),
            description=f"Page {self.page + 1}/{self.total_pages} | Total events: {len(self.tournaments)}",
        )
        start = self.page * self.page_size
        end = start + self.page_size
        for tournament in self.tournaments[start:end]:
            embed.add_field(
                name=f"Event ID {self.cog.format_public_id(tournament)}",
                value=self.cog.build_tournament_line(tournament),
                inline=False,
            )
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


class TournamentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")
        self.tournament_reminder_task.start()

    def cog_unload(self):
        self.tournament_reminder_task.cancel()

    def ensure_manager(self, interaction: discord.Interaction):
        ensure_manager(interaction, self.db)

    def parse_datetime_string(self, datetime_str: str, timezone_name: str) -> tuple:
        try:
            datetime_part, trailing_timezone = split_trailing_timezone(datetime_str)
            used_timezone = normalize_timezone(trailing_timezone, timezone_name)
            dt = date_parser.parse(datetime_part, dayfirst=False)
            return localize_datetime(dt, used_timezone), used_timezone
        except Exception as e:
            raise ValueError(f"Could not parse datetime string: {datetime_str}. Error: {str(e)}")

    def get_reminder_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        settings = self.db.get_guild_settings(guild.id)
        configured_channel_id = settings.get("reminder_channel_id") or settings.get("scrim_reminder_channel_id")
        if configured_channel_id:
            channel = guild.get_channel(configured_channel_id)
            if isinstance(channel, discord.TextChannel):
                permissions = channel.permissions_for(guild.me)
                if permissions.view_channel and permissions.send_messages:
                    return channel

        if guild.system_channel:
            permissions = guild.system_channel.permissions_for(guild.me)
            if permissions.view_channel and permissions.send_messages:
                return guild.system_channel

        for channel in guild.text_channels:
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

    def get_tournament_event_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        settings = self.db.get_guild_settings(guild.id)
        configured_channel_id = settings.get("tournament_event_channel_id")
        if configured_channel_id:
            channel = guild.get_channel(configured_channel_id)
            if isinstance(channel, discord.TextChannel):
                permissions = channel.permissions_for(guild.me)
                if permissions.view_channel and permissions.send_messages:
                    return channel
        return None

    def tournament_event_name(self, tournament_name: str) -> str:
        return tournament_name

    def format_public_id(self, tournament_or_id) -> str:
        if isinstance(tournament_or_id, dict):
            tournament_id = tournament_or_id["id"]
        else:
            tournament_id = tournament_or_id
        return f"T{tournament_id}"

    def parse_public_id(self, event_id) -> int:
        value = str(event_id).strip().upper()
        if value.startswith("T"):
            value = value[1:]
        if not value.isdigit():
            raise ValueError("Tournament Event ID must look like T1")
        return int(value)

    def tournament_event_description(self, event_id: int, tournament_name: str) -> str:
        return f"Tournament: {tournament_name}\nEvent ID: {self.format_public_id(event_id)}"

    def build_tournament_line(self, tournament: dict) -> str:
        archived = " | Archived" if tournament.get("archived") else ""
        return (
            f"`Event ID {self.format_public_id(tournament)}` {discord_time_display(tournament['datetime'], tournament['timezone'])}\n"
            f"{self.tournament_event_name(tournament['tournament_name'])} | "
            f"{tournament['duration_hours']:g}h | {tournament['status']}{archived}"
        )

    def build_tournament_created_message(self, tournament: dict, event_url: Optional[str] = None) -> str:
        message = f"**{self.tournament_event_name(tournament['tournament_name'])}**\n"
        message += f"**Event ID:** {self.format_public_id(tournament)}\n"
        message += f"**Time:** {discord_time_display(tournament['datetime'], tournament['timezone'])}\n"
        message += f"**Duration:** {tournament['duration_hours']:g} hour(s)"
        if event_url:
            message += f"\n**Event Link:** {event_url}"
        return message

    async def post_tournament_created_message(self, guild: discord.Guild, fallback_channel, tournament: dict, event_url: Optional[str] = None):
        channel = self.get_tournament_event_channel(guild) or fallback_channel
        message = self.build_tournament_created_message(tournament, event_url)
        if channel:
            await channel.send(message)
        return channel

    def normalize_status(self, status: str) -> str:
        for allowed in TOURNAMENT_STATUSES:
            if allowed.lower() == status.strip().lower():
                return allowed
        raise ValueError(f"Status must be one of: {', '.join(TOURNAMENT_STATUSES)}")

    async def update_discord_event(
        self,
        guild: discord.Guild,
        discord_event_id: str,
        event_id: int,
        tournament_name: str,
        event_dt,
        duration_hours: float,
    ) -> bool:
        try:
            event = guild.get_scheduled_event(int(discord_event_id))
            if not event:
                return False
            await event.edit(
                name=self.tournament_event_name(tournament_name),
                description=self.tournament_event_description(event_id, tournament_name),
                start_time=event_dt,
                end_time=event_end_time(event_dt, duration_hours),
                location="Online",
            )
            return True
        except Exception as e:
            print(f"Error updating Discord tournament event {discord_event_id}: {e}")
            return False

    async def delete_discord_event(self, guild: discord.Guild, discord_event_id: str) -> bool:
        try:
            event = guild.get_scheduled_event(int(discord_event_id))
            if event:
                await event.delete()
            return True
        except Exception as e:
            print(f"Error deleting Discord tournament event {discord_event_id}: {e}")
            return False

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

    async def tournament_id_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        choices = []
        for tournament in self.db.get_all_tournaments(interaction.guild.id, include_archived=False):
            public_id = self.format_public_id(tournament)
            label = f"Event ID {public_id} {tournament['tournament_name']} {tournament['status']}"
            if current and current.lower() not in public_id.lower() and current.lower() not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=public_id))
            if len(choices) == 25:
                break
        return choices

    tournament_group = app_commands.Group(name="tournaments", description="Tournament scheduling and settings")

    @tournament_group.command(name="create", description="Create a tournament event")
    @app_commands.rename(
        tournament_name="name",
        event_datetime="date_time",
        duration_hours="duration_hrs",
        timezone_name="timezone",
    )
    @app_commands.describe(
        tournament_name="Tournament Name",
        event_datetime="Date & time, optionally with timezone (e.g., 4/22/26 4pm EST)",
        duration_hours="Duration (hrs), such as 2 or 1.5",
        timezone_name="Timezone, such as EST or America/Denver",
    )
    async def tournament_create(
        self,
        interaction: discord.Interaction,
        tournament_name: str,
        event_datetime: str,
        duration_hours: float,
        timezone_name: Optional[str] = None,
    ):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            name = tournament_name.strip()
            if not name:
                raise ValueError("Tournament name cannot be empty.")

            default_timezone = self.db.get_guild_settings(guild.id)["timezone"]
            timezone_name = normalize_timezone(timezone_name, default_timezone)
            duration_hours = validate_duration_hours(duration_hours)
            event_dt, used_timezone = self.parse_datetime_string(event_datetime, timezone_name)

            event_database_id = self.db.add_tournament(
                guild.id,
                name,
                to_utc_iso(event_dt),
                used_timezone,
                None,
                duration_hours,
            )

            try:
                scheduled_event = await guild.create_scheduled_event(
                    name=self.tournament_event_name(name),
                    description=self.tournament_event_description(event_database_id, name),
                    start_time=event_dt,
                    end_time=event_end_time(event_dt, duration_hours),
                    location="Online",
                    privacy_level=discord.PrivacyLevel.guild_only,
                    entity_type=discord.EntityType.external,
                )
            except Exception:
                self.db.delete_tournament(guild.id, event_database_id)
                raise

            self.db.update_tournament(guild.id, event_database_id, discord_event_id=str(scheduled_event.id))

            created_tournament = self.db.get_tournament(guild.id, event_database_id)
            target_channel = self.get_tournament_event_channel(guild)
            if target_channel:
                await self.post_tournament_created_message(guild, interaction.channel, created_tournament, scheduled_event.url)
                await interaction.followup.send(f"Tournament Event ID {self.format_public_id(event_database_id)} posted in {target_channel.mention}.")
            else:
                await interaction.followup.send(self.build_tournament_created_message(created_tournament, scheduled_event.url))
        except ValueError as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "Error: Bot does not have permission to create events. Make sure the bot has the Manage Events permission.",
                ephemeral=True,
            )
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @tournament_create.autocomplete("timezone_name")
    async def tournament_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

    @tournament_group.command(name="view", description="View scheduled tournament events")
    @app_commands.describe(
        include_completed="Show completed and cancelled tournaments",
        include_archived="Show archived tournaments",
    )
    async def tournament_view(self, interaction: discord.Interaction, include_completed: bool = False, include_archived: bool = False):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        tournaments = self.db.get_all_tournaments(guild.id, include_completed=include_completed, include_archived=include_archived)
        if not tournaments:
            await interaction.followup.send("No tournament events scheduled.")
            return

        view = TournamentPageView(self, tournaments, "Tournament Schedule")
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    @tournament_group.command(name="upcoming", description="View upcoming tournament events")
    @app_commands.describe(
        days="Number of days to include",
        include_completed="Show completed and cancelled tournaments",
        include_archived="Show archived tournaments",
    )
    async def tournament_upcoming(
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
        tournaments = self.db.get_upcoming_tournaments(
            guild.id,
            days=days,
            include_completed=include_completed,
            include_archived=include_archived,
        )
        if not tournaments:
            await interaction.followup.send(f"No tournament events scheduled in the next {days} day(s).")
            return

        view = TournamentPageView(self, tournaments, f"Upcoming Tournament Events ({days} days)")
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

    @tournament_group.command(name="status", description="Set a tournament event status")
    @app_commands.describe(event_id="Event ID to update")
    @app_commands.choices(status=TOURNAMENT_STATUS_CHOICES)
    async def tournament_status(self, interaction: discord.Interaction, event_id: str, status: str):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            event_database_id = self.parse_public_id(event_id)
            tournament = self.db.get_tournament(guild.id, event_database_id)
            if not tournament:
                await interaction.followup.send(f"Event ID {self.format_public_id(event_database_id)} not found.", ephemeral=True)
                return
            status = self.normalize_status(status)
            self.db.update_tournament(guild.id, event_database_id, status=status)
            updated = self.db.get_tournament(guild.id, event_database_id)
            await interaction.followup.send(f"**Tournament Event Status Updated**\n{self.build_tournament_line(updated)}")
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @tournament_status.autocomplete("event_id")
    async def tournament_status_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.tournament_id_autocomplete(interaction, current)

    @tournament_group.command(name="archive_completed", description="Archive completed and cancelled tournament events")
    async def tournament_archive_completed(self, interaction: discord.Interaction):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            count = self.db.archive_completed_tournaments(guild.id)
            await interaction.followup.send(f"Archived {count} completed/cancelled tournament event(s).", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    @tournament_group.command(name="repair_events", description="Recreate missing Discord events for tournaments")
    @app_commands.describe(include_completed="Also repair completed/cancelled tournaments")
    async def tournament_repair_events(self, interaction: discord.Interaction, include_completed: bool = False):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            tournaments = self.db.get_all_tournaments(guild.id, include_completed=include_completed, include_archived=False)
            checked = 0
            missing = 0
            repaired = 0
            failed = []

            for tournament in tournaments:
                checked += 1
                event_exists = False
                if tournament["discord_event_id"]:
                    try:
                        event_exists = guild.get_scheduled_event(int(tournament["discord_event_id"])) is not None
                    except (TypeError, ValueError):
                        event_exists = False
                if event_exists:
                    await self.update_discord_event(
                        guild,
                        tournament["discord_event_id"],
                        tournament["id"],
                        tournament["tournament_name"],
                        parse_stored_datetime(tournament["datetime"]),
                        tournament["duration_hours"],
                    )
                    continue

                missing += 1
                try:
                    event_dt = parse_stored_datetime(tournament["datetime"])
                    scheduled_event = await guild.create_scheduled_event(
                        name=self.tournament_event_name(tournament["tournament_name"]),
                        description=self.tournament_event_description(tournament["id"], tournament["tournament_name"]),
                        start_time=event_dt,
                        end_time=event_end_time(event_dt, tournament["duration_hours"]),
                        location="Online",
                        privacy_level=discord.PrivacyLevel.guild_only,
                        entity_type=discord.EntityType.external,
                    )
                    self.db.update_tournament(guild.id, tournament["id"], discord_event_id=str(scheduled_event.id))
                    repaired += 1
                except Exception as exc:
                    failed.append(f"Event ID {self.format_public_id(tournament)}: {str(exc)}")

            response = "**Tournament Event Repair Complete**\n"
            response += f"Checked: {checked}\n"
            response += f"Missing/broken: {missing}\n"
            response += f"Recreated: {repaired}"
            if failed:
                response += "\n\nFailures:\n" + "\n".join(f"- {item}" for item in failed[:5])
                if len(failed) > 5:
                    response += f"\n... and {len(failed) - 5} more"
            await interaction.followup.send(response, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

    @tournament_group.command(name="delete", description="Delete a tournament event")
    @app_commands.describe(event_id="Event ID to delete")
    async def tournament_delete(self, interaction: discord.Interaction, event_id: str):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            event_database_id = self.parse_public_id(event_id)
            tournament = self.db.get_tournament(guild.id, event_database_id)
            if not tournament:
                await interaction.followup.send(f"Event ID {self.format_public_id(event_database_id)} not found.", ephemeral=True)
                return
            if tournament["discord_event_id"]:
                await self.delete_discord_event(guild, tournament["discord_event_id"])
            self.db.delete_tournament(guild.id, event_database_id)
            await interaction.followup.send(f"Tournament Event ID {self.format_public_id(event_database_id)} deleted.")
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @tournament_delete.autocomplete("event_id")
    async def tournament_delete_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.tournament_id_autocomplete(interaction, current)

    @tasks.loop(minutes=1)
    async def tournament_reminder_task(self):
        try:
            tournaments = self.db.get_tournaments_needing_30_minute_reminder(60)
            for tournament in tournaments:
                if tournament["status"] in {"Completed", "Cancelled"}:
                    self.db.mark_tournament_30_minute_reminder_sent(tournament["guild_id"], tournament["id"])
                    continue

                guild = self.bot.get_guild(tournament["guild_id"])
                if not guild:
                    continue

                settings = self.db.get_guild_settings(guild.id)
                reminder_minutes = settings.get("reminder_minutes", 30)
                tournament_dt = parse_stored_datetime(tournament["datetime"])
                if tournament_dt > datetime.now(timezone.utc) + timedelta(minutes=reminder_minutes):
                    continue

                channel = self.get_reminder_channel(guild)
                if not channel:
                    print(f"No writable tournament reminder channel found for guild {guild.id}")
                    continue

                event_url = None
                if tournament["discord_event_id"]:
                    event = guild.get_scheduled_event(int(tournament["discord_event_id"]))
                    if event:
                        event_url = event.url

                pings = self.get_reminder_role_mentions(guild)
                message = ""
                if pings:
                    message += f"{pings}\n"
                message += (
                    f"**Tournament starts in {reminder_minutes} minutes**\n"
                    f"**Event ID:** {self.format_public_id(tournament)}\n"
                    f"**Event:** {self.tournament_event_name(tournament['tournament_name'])}\n"
                    f"**Time:** {discord_time_display(tournament['datetime'], tournament['timezone'])}\n"
                    f"**Duration:** {tournament['duration_hours']:g} hour(s)\n"
                    f"**Status:** {tournament['status']}"
                )
                if event_url:
                    message += f"\n**Event Link:** {event_url}"

                await channel.send(message, allowed_mentions=discord.AllowedMentions(roles=True))
                self.db.mark_tournament_30_minute_reminder_sent(tournament["guild_id"], tournament["id"])
        except Exception as e:
            print(f"Error in tournament reminder task: {e}")

    @tournament_reminder_task.before_loop
    async def before_tournament_reminder_task(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(TournamentCog(bot))
