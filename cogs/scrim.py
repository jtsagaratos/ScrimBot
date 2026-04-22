from typing import Optional

import discord
import pytz
from dateutil import parser as date_parser
from discord import app_commands
from discord.ext import commands

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


SCRIM_STATUSES = ["Scheduled", "Checked In", "In Progress", "Completed", "Cancelled"]
SCRIM_STATUS_CHOICES = [app_commands.Choice(name=status, value=status) for status in SCRIM_STATUSES]


class ScrimEditModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int, scrim: dict):
        super().__init__(title=f"Edit Scrim Event #{scrim['id']}")
        self.cog = cog
        self.guild_id = guild_id
        self.scrim = scrim

        local_dt = parse_stored_datetime(scrim["datetime"]).astimezone(pytz.timezone(scrim["timezone"]))

        self.team_input = discord.ui.TextInput(
            label="Opponent Team",
            default=scrim["team_name"],
            placeholder="Team Liquid",
            max_length=100,
        )
        self.datetime_input = discord.ui.TextInput(
            label="Date/Time",
            default=local_dt.strftime("%B %d %I:%M %p %Y"),
            placeholder="April 25 4:00 PM 2026",
            max_length=80,
        )
        self.duration_input = discord.ui.TextInput(
            label="Duration Hours",
            default=f"{scrim.get('duration_hours', 2.0):g}",
            placeholder="2 or 1.5",
            max_length=10,
        )
        self.timezone_input = discord.ui.TextInput(
            label="Timezone",
            default=scrim["timezone"],
            placeholder="America/Denver, EST, PST, UTC",
            max_length=80,
        )

        self.add_item(self.team_input)
        self.add_item(self.datetime_input)
        self.add_item(self.duration_input)
        self.add_item(self.timezone_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            scrim = self.cog.db.get_scrim(self.guild_id, self.scrim["id"])
            if not scrim:
                await interaction.response.send_message(f"Event ID {self.scrim['id']} not found.", ephemeral=True)
                return

            team_name = str(self.team_input.value).strip()
            if not team_name:
                raise ValueError("Opponent team cannot be empty.")
            timezone_name = normalize_timezone(str(self.timezone_input.value).strip(), scrim["timezone"])
            event_dt, used_timezone = self.cog.parse_datetime_string(str(self.datetime_input.value).strip(), timezone_name)
            duration_hours = validate_duration_hours(str(self.duration_input.value).strip())

            self.cog.db.update_scrim(
                self.guild_id,
                scrim["id"],
                team_name=team_name,
                datetime=to_utc_iso(event_dt),
                timezone=used_timezone,
                duration_hours=duration_hours,
            )

            if scrim["discord_event_id"]:
                await self.cog.update_discord_event(
                    guild,
                    scrim["discord_event_id"],
                    scrim["id"],
                    team_name,
                    event_dt,
                    duration_hours,
                )

            updated = self.cog.db.get_scrim(self.guild_id, scrim["id"])
            await interaction.response.send_message(f"**Scrim Event Updated**\n{self.cog.build_scrim_line(updated)}")
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class ScrimPageView(discord.ui.View):
    def __init__(self, cog, scrims: list, title: str, page_size: int = 5):
        super().__init__(timeout=300)
        self.cog = cog
        self.scrims = scrims
        self.title = title
        self.page_size = page_size
        self.page = 0
        self.update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.scrims) + self.page_size - 1) // self.page_size)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.green(),
            description=f"Page {self.page + 1}/{self.total_pages} | Total events: {len(self.scrims)}",
        )
        start = self.page * self.page_size
        end = start + self.page_size
        for scrim in self.scrims[start:end]:
            embed.add_field(name=f"Event ID {scrim['id']}", value=self.cog.build_scrim_line(scrim), inline=False)
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


class ScrimCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

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

    def get_scrim_ping_mentions(self, guild: discord.Guild) -> str:
        mentions = []
        for role_id in self.db.get_scrim_ping_roles(guild.id):
            role = guild.get_role(role_id)
            if role:
                mentions.append(role.mention)
        return " ".join(mentions)

    def scrim_event_name(self, team_name: str) -> str:
        return f"Scrim vs {team_name}"

    def scrim_event_description(self, event_id: int, team_name: str) -> str:
        return f"Team scrim against {team_name}\nEvent ID: {event_id}"

    def build_scrim_line(self, scrim: dict) -> str:
        archived = " | Archived" if scrim.get("archived") else ""
        return (
            f"`Event ID {scrim['id']}` {discord_time_display(scrim['datetime'], scrim['timezone'])}\n"
            f"{self.scrim_event_name(scrim['team_name'])} | {scrim['duration_hours']:g}h | {scrim['status']}{archived}"
        )

    def normalize_status(self, status: str) -> str:
        for allowed in SCRIM_STATUSES:
            if allowed.lower() == status.strip().lower():
                return allowed
        raise ValueError(f"Status must be one of: {', '.join(SCRIM_STATUSES)}")

    async def update_discord_event(
        self,
        guild: discord.Guild,
        discord_event_id: str,
        event_id: int,
        team_name: str,
        event_dt,
        duration_hours: float,
    ) -> bool:
        try:
            event = guild.get_scheduled_event(int(discord_event_id))
            if not event:
                return False
            await event.edit(
                name=self.scrim_event_name(team_name),
                description=self.scrim_event_description(event_id, team_name),
                start_time=event_dt,
                end_time=event_end_time(event_dt, duration_hours),
                location="Online",
            )
            return True
        except Exception as e:
            print(f"Error updating Discord scrim event {discord_event_id}: {e}")
            return False

    async def delete_discord_event(self, guild: discord.Guild, discord_event_id: str) -> bool:
        try:
            event = guild.get_scheduled_event(int(discord_event_id))
            if event:
                await event.delete()
            return True
        except Exception as e:
            print(f"Error deleting Discord scrim event {discord_event_id}: {e}")
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

    async def scrim_id_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []
        choices = []
        for scrim in self.db.get_all_scrims(interaction.guild.id, include_archived=False):
            label = f"Event ID {scrim['id']} {scrim['team_name']} {scrim['status']}"
            if current and current not in str(scrim["id"]) and current.lower() not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=scrim["id"]))
            if len(choices) == 25:
                break
        return choices

    scrim_group = app_commands.Group(name="scrim", description="Scrim scheduling and settings")

    @scrim_group.command(name="create", description="Create a scrim event against another team")
    @app_commands.describe(
        team_name="Name of the opposing team",
        event_datetime="Date and time of the scrim (e.g., 4/22/26 4pm EST)",
        duration_hours="Event duration in hours, such as 2 or 1.5",
        timezone_name="Timezone abbreviation or IANA name",
    )
    async def scrim_create(
        self,
        interaction: discord.Interaction,
        team_name: str,
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

            opponent_name = team_name.strip()
            if not opponent_name:
                raise ValueError("Team name cannot be empty.")

            default_timezone = self.db.get_guild_settings(guild.id)["timezone"]
            timezone_name = normalize_timezone(timezone_name, default_timezone)
            duration_hours = validate_duration_hours(duration_hours)
            event_dt, used_timezone = self.parse_datetime_string(event_datetime, timezone_name)
            event_name = self.scrim_event_name(opponent_name)
            event_database_id = self.db.add_scrim(
                guild.id,
                opponent_name,
                None,
                to_utc_iso(event_dt),
                used_timezone,
                None,
                duration_hours,
            )

            try:
                scheduled_event = await guild.create_scheduled_event(
                    name=event_name,
                    description=self.scrim_event_description(event_database_id, opponent_name),
                    start_time=event_dt,
                    end_time=event_end_time(event_dt, duration_hours),
                    location="Online",
                    privacy_level=discord.PrivacyLevel.guild_only,
                    entity_type=discord.EntityType.external,
                )
            except Exception:
                self.db.delete_scrim(guild.id, event_database_id)
                raise

            self.db.update_scrim(guild.id, event_database_id, discord_event_id=str(scheduled_event.id))

            pings = self.get_scrim_ping_mentions(guild)
            confirmation = ""
            if pings:
                confirmation += f"{pings}\n"
            confirmation += "Scrim event created!\n"
            confirmation += f"**Event ID:** {event_database_id}\n"
            confirmation += f"**Event:** {event_name}\n"
            confirmation += f"**Time:** {discord_time_display(to_utc_iso(event_dt), used_timezone)}\n"
            confirmation += f"**Duration:** {duration_hours:g} hour(s)\n"
            confirmation += f"**Event Link:** {scheduled_event.url}"

            await interaction.followup.send(confirmation, allowed_mentions=discord.AllowedMentions(roles=True))
        except ValueError as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except PermissionError as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
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

    @scrim_create.autocomplete("timezone_name")
    async def scrim_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

    @scrim_group.command(name="view", description="View scheduled scrim events")
    @app_commands.describe(
        include_completed="Show completed and cancelled scrims",
        include_archived="Show archived scrims",
    )
    async def scrim_view(
        self,
        interaction: discord.Interaction,
        include_completed: bool = False,
        include_archived: bool = False,
    ):
        await interaction.response.defer()
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        scrims = self.db.get_all_scrims(
            guild.id,
            include_completed=include_completed,
            include_archived=include_archived,
        )
        if not scrims:
            await interaction.followup.send("No scrim events scheduled.")
            return

        view = ScrimPageView(self, scrims, "Scrim Schedule")
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @scrim_group.command(name="upcoming", description="View upcoming scrim events")
    @app_commands.describe(
        days="Number of days to include",
        include_completed="Show completed and cancelled scrims",
        include_archived="Show archived scrims",
    )
    async def scrim_upcoming(
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
        scrims = self.db.get_upcoming_scrims(
            guild.id,
            days=days,
            include_completed=include_completed,
            include_archived=include_archived,
        )
        if not scrims:
            await interaction.followup.send(f"No scrim events scheduled in the next {days} day(s).")
            return

        view = ScrimPageView(self, scrims, f"Upcoming Scrim Events ({days} days)")
        await interaction.followup.send(embed=view.build_embed(), view=view)

    @scrim_group.command(name="edit", description="Edit a scrim event")
    @app_commands.describe(event_id="Event ID to edit")
    async def scrim_edit(self, interaction: discord.Interaction, event_id: int):
        try:
            self.ensure_manager(interaction)
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return
            scrim = self.db.get_scrim(guild.id, event_id)
            if not scrim:
                await interaction.response.send_message(f"Event ID {event_id} not found.", ephemeral=True)
                return
            await interaction.response.send_modal(ScrimEditModal(self, guild.id, scrim))
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_edit.autocomplete("event_id")
    async def scrim_edit_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.scrim_id_autocomplete(interaction, current)

    @scrim_group.command(name="status", description="Set a scrim event status")
    @app_commands.describe(event_id="Event ID to update")
    @app_commands.choices(status=SCRIM_STATUS_CHOICES)
    async def scrim_status(self, interaction: discord.Interaction, event_id: int, status: str):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            scrim = self.db.get_scrim(guild.id, event_id)
            if not scrim:
                await interaction.followup.send(f"Event ID {event_id} not found.", ephemeral=True)
                return
            status = self.normalize_status(status)
            self.db.update_scrim(guild.id, event_id, status=status)
            updated = self.db.get_scrim(guild.id, event_id)
            await interaction.followup.send(f"**Scrim Event Status Updated**\n{self.build_scrim_line(updated)}")
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_status.autocomplete("event_id")
    async def scrim_status_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.scrim_id_autocomplete(interaction, current)

    @scrim_group.command(name="archive_completed", description="Archive completed and cancelled scrim events")
    async def scrim_archive_completed(self, interaction: discord.Interaction):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            count = self.db.archive_completed_scrims(guild.id)
            await interaction.followup.send(f"Archived {count} completed/cancelled scrim event(s).", ephemeral=True)
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_group.command(name="repair_events", description="Recreate missing Discord events for scrims")
    @app_commands.describe(include_completed="Also repair completed/cancelled scrims")
    async def scrim_repair_events(self, interaction: discord.Interaction, include_completed: bool = False):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            scrims = self.db.get_all_scrims(
                guild.id,
                include_completed=include_completed,
                include_archived=False,
            )
            checked = 0
            missing = 0
            repaired = 0
            failed = []

            for scrim in scrims:
                checked += 1
                event_exists = False
                if scrim["discord_event_id"]:
                    try:
                        event_exists = guild.get_scheduled_event(int(scrim["discord_event_id"])) is not None
                    except (TypeError, ValueError):
                        event_exists = False
                if event_exists:
                    await self.update_discord_event(
                        guild,
                        scrim["discord_event_id"],
                        scrim["id"],
                        scrim["team_name"],
                        parse_stored_datetime(scrim["datetime"]),
                        scrim["duration_hours"],
                    )
                    continue

                missing += 1
                try:
                    event_dt = parse_stored_datetime(scrim["datetime"])
                    scheduled_event = await guild.create_scheduled_event(
                        name=self.scrim_event_name(scrim["team_name"]),
                        description=self.scrim_event_description(scrim["id"], scrim["team_name"]),
                        start_time=event_dt,
                        end_time=event_end_time(event_dt, scrim["duration_hours"]),
                        location="Online",
                        privacy_level=discord.PrivacyLevel.guild_only,
                        entity_type=discord.EntityType.external,
                    )
                    self.db.update_scrim(guild.id, scrim["id"], discord_event_id=str(scheduled_event.id))
                    repaired += 1
                except Exception as exc:
                    failed.append(f"Event ID {scrim['id']}: {str(exc)}")

            response = "**Scrim Event Repair Complete**\n"
            response += f"Checked: {checked}\n"
            response += f"Missing/broken: {missing}\n"
            response += f"Recreated: {repaired}"
            if failed:
                response += "\n\nFailures:\n" + "\n".join(f"- {item}" for item in failed[:5])
                if len(failed) > 5:
                    response += f"\n... and {len(failed) - 5} more"
            await interaction.followup.send(response, ephemeral=True)
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_group.command(name="delete", description="Delete a scrim event")
    @app_commands.describe(event_id="Event ID to delete")
    async def scrim_delete(self, interaction: discord.Interaction, event_id: int):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            scrim = self.db.get_scrim(guild.id, event_id)
            if not scrim:
                await interaction.followup.send(f"Event ID {event_id} not found.", ephemeral=True)
                return
            if scrim["discord_event_id"]:
                await self.delete_discord_event(guild, scrim["discord_event_id"])
            self.db.delete_scrim(guild.id, event_id)
            await interaction.followup.send(f"Scrim Event ID {event_id} deleted.")
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_delete.autocomplete("event_id")
    async def scrim_delete_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.scrim_id_autocomplete(interaction, current)

    @scrim_group.command(name="ping_role_add", description="Add a role to ping when scrims are created")
    async def scrim_ping_role_add(self, interaction: discord.Interaction, role: discord.Role):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            self.db.add_scrim_ping_role(interaction.guild.id, role.id)
            await interaction.followup.send(f"Added {role.mention} to scrim pings.", ephemeral=True)
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_group.command(name="ping_role_remove", description="Remove a role from scrim pings")
    async def scrim_ping_role_remove(self, interaction: discord.Interaction, role: discord.Role):
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            removed = self.db.remove_scrim_ping_role(interaction.guild.id, role.id)
            if removed:
                await interaction.followup.send(f"Removed {role.mention} from scrim pings.", ephemeral=True)
            else:
                await interaction.followup.send(f"{role.mention} was not configured for scrim pings.", ephemeral=True)
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim_group.command(name="ping_role_list", description="List roles pinged when scrims are created")
    async def scrim_ping_role_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        roles = [interaction.guild.get_role(role_id) for role_id in self.db.get_scrim_ping_roles(interaction.guild.id)]
        role_mentions = [role.mention for role in roles if role]
        await interaction.followup.send(
            f"Scrim ping roles: {', '.join(role_mentions) if role_mentions else 'None'}",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(ScrimCog(bot))
