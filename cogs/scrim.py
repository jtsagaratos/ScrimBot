from typing import Optional

import discord
from dateutil import parser as date_parser
from discord import app_commands
from discord.ext import commands

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

    def get_scrim_ping_mentions(self, guild: discord.Guild) -> str:
        mentions = []
        for role_id in self.db.get_scrim_ping_roles(guild.id):
            role = guild.get_role(role_id)
            if role:
                mentions.append(role.mention)
        return " ".join(mentions)

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

    scrim_group = app_commands.Group(name="scrim", description="Scrim scheduling and settings")

    @scrim_group.command(name="create", description="Create a scrim event against another team")
    @app_commands.describe(
        team_name="Name of the opposing team",
        event_datetime="Date and time of the scrim (e.g., 4/22/26 4pm EST)",
        timezone_name="Timezone abbreviation or IANA name",
    )
    async def scrim_create(
        self,
        interaction: discord.Interaction,
        team_name: str,
        event_datetime: str,
        timezone_name: Optional[str] = None,
    ):
        """Create a scrim event and ping configured scrim roles."""
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
            event_dt, used_timezone = self.parse_datetime_string(event_datetime, timezone_name)
            event_name = f"Scrim vs {opponent_name}"

            scheduled_event = await guild.create_scheduled_event(
                name=event_name,
                description=f"Team scrim against {opponent_name}",
                start_time=event_dt,
                end_time=None,
                location="Online",
                privacy_level=discord.PrivacyLevel.guild_only,
                entity_type=discord.EntityType.external,
            )

            self.db.add_scrim(
                guild.id,
                opponent_name,
                None,
                to_utc_iso(event_dt),
                used_timezone,
                str(scheduled_event.id),
            )

            pings = self.get_scrim_ping_mentions(guild)
            confirmation = ""
            if pings:
                confirmation += f"{pings}\n"
            confirmation += "Scrim event created!\n"
            confirmation += f"**Event:** {event_name}\n"
            confirmation += f"**Time:** {discord_time_display(to_utc_iso(event_dt), used_timezone)}\n"
            confirmation += f"**Against:** {opponent_name}\n"
            confirmation += f"**Event Link:** {scheduled_event.url}"

            await interaction.followup.send(
                confirmation,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
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

    @scrim_create.autocomplete("timezone_name")
    async def scrim_timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.timezone_autocomplete(interaction, current)

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
