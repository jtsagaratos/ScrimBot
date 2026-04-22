import discord
from dateutil import parser as date_parser
from discord import app_commands
from discord.ext import commands
from typing import Optional

from models.database import DatabaseManager
from models.permissions import ensure_manager
from models.time_utils import (
    COMMON_TIMEZONES,
    discord_time_display,
    localize_datetime,
    normalize_timezone,
    split_trailing_timezone,
    to_utc_iso,
)


class ScrimCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    def ensure_manager(self, interaction: discord.Interaction):
        ensure_manager(interaction, self.db)

    def parse_datetime_string(self, datetime_str: str, timezone_name: str) -> tuple:
        """
        Parse datetime string with timezone support.
        Examples: "4/22/26 4pm EST", "2026-04-22 16:00", "April 22 4 PM America/Denver"
        """
        try:
            datetime_part, trailing_timezone = split_trailing_timezone(datetime_str)
            used_timezone = normalize_timezone(trailing_timezone, timezone_name)
            dt = date_parser.parse(datetime_part, dayfirst=False)
            return localize_datetime(dt, used_timezone), used_timezone
        except Exception as e:
            raise ValueError(f"Could not parse datetime string: {datetime_str}. Error: {str(e)}")

    def get_team_role(self, guild: discord.Guild, team_name: str) -> discord.Role:
        """
        Find a role matching the team name.
        Searches for role names containing the team name, case-insensitively.
        """
        team_name_lower = team_name.lower()

        for role in guild.roles:
            if team_name_lower in role.name.lower() or role.name.lower() == team_name_lower:
                return role

        available_roles = ", ".join([r.name for r in guild.roles if not r.is_bot_managed()])
        raise ValueError(f"Team role '{team_name}' not found. Available roles: {available_roles}")

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

    @app_commands.command(name="scrim", description="Create a scrim event against another team")
    @app_commands.describe(
        team_name="Name of the opposing team",
        event_datetime="Date and time of the scrim (e.g., 4/22/26 4pm EST)",
        timezone_name="Timezone abbreviation or IANA name",
    )
    async def scrim(
        self,
        interaction: discord.Interaction,
        team_name: str,
        event_datetime: str,
        timezone_name: Optional[str] = None,
    ):
        """Create a scrim event and tag the team role."""
        try:
            self.ensure_manager(interaction)
            await interaction.response.defer()

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return

            default_timezone = self.db.get_guild_settings(guild.id)["timezone"]
            timezone_name = normalize_timezone(timezone_name, default_timezone)
            event_dt, used_timezone = self.parse_datetime_string(event_datetime, timezone_name)
            team_role = self.get_team_role(guild, team_name)
            event_name = f"Scrim vs {team_role.name}"

            scheduled_event = await guild.create_scheduled_event(
                name=event_name,
                description=f"Team scrim against {team_role.mention}",
                start_time=event_dt,
                end_time=None,
                location="Online",
                privacy_level=discord.PrivacyLevel.guild_only,
                entity_type=discord.ScheduledEventEntityType.external,
            )

            self.db.add_scrim(
                guild.id,
                team_role.name,
                team_role.id,
                to_utc_iso(event_dt),
                used_timezone,
                str(scheduled_event.id),
            )

            confirmation = "Scrim event created!\n"
            confirmation += f"**Event:** {event_name}\n"
            confirmation += f"**Time:** {discord_time_display(to_utc_iso(event_dt), used_timezone)}\n"
            confirmation += f"**Against:** {team_role.mention}\n"
            confirmation += f"**Event Link:** {scheduled_event.url}"

            await interaction.followup.send(confirmation)
        except ValueError as e:
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
        except PermissionError as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "Error: Bot does not have permission to create events. "
                "Make sure the bot has the Manage Events permission.",
                ephemeral=True,
            )
        except Exception as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

    @scrim.autocomplete("timezone_name")
    async def scrim_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(ScrimCog(bot))
