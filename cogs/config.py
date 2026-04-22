import discord
from discord import app_commands
from discord.ext import commands

from cogs.ignite import validate_source_url
from models.database import DatabaseManager
from models.permissions import ensure_manager
from models.time_utils import COMMON_TIMEZONES, normalize_timezone


class TimezoneSetupModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int, current_timezone: str):
        super().__init__(title="Set Default Timezone")
        self.cog = cog
        self.guild_id = guild_id
        self.timezone_input = discord.ui.TextInput(
            label="Timezone",
            default=current_timezone,
            placeholder="America/Denver, EST, PST, UTC",
            max_length=80,
        )
        self.add_item(self.timezone_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            timezone_name = normalize_timezone(str(self.timezone_input.value).strip())
            self.cog.db.update_guild_settings(self.guild_id, timezone=timezone_name)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupHomeView(self.cog),
            )
        except Exception as exc:
            await interaction.response.send_message(f"Error: {str(exc)}", ephemeral=True)


class IgniteSetupModal(discord.ui.Modal):
    def __init__(self, cog, guild_id: int):
        super().__init__(title="Set Ignite Options")
        self.cog = cog
        self.guild_id = guild_id
        ignite_settings = cog.get_ignite_cog().get_settings(guild_id)

        self.source_input = discord.ui.TextInput(
            label="Liquipedia Source URL",
            default=ignite_settings["source_url"],
            required=False,
            max_length=300,
        )
        self.team_input = discord.ui.TextInput(
            label="Tracked Team",
            default=ignite_settings["tracked_team"] or "",
            placeholder="Leave blank to post all teams",
            required=False,
            max_length=100,
        )
        self.add_item(self.source_input)
        self.add_item(self.team_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            ignite = self.cog.get_ignite_cog()
            source_url = str(self.source_input.value).strip()
            tracked_team = str(self.team_input.value).strip()
            if source_url:
                source_url = validate_source_url(source_url)
                ignite.update_settings(self.guild_id, source_url=source_url, failure_count=0, clear_error=True)
            if tracked_team:
                ignite.update_settings(self.guild_id, tracked_team=tracked_team)
            else:
                ignite.update_settings(self.guild_id, clear_tracked_team=True)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupHomeView(self.cog),
            )
        except Exception as exc:
            await interaction.response.send_message(f"Error: {str(exc)}", ephemeral=True)


def build_role_toggle_options(guild: discord.Guild, selected_ids, placeholder_label: str):
    selected_ids = set(selected_ids)
    roles_by_id = {role.id: role for role in guild.roles if role.name != "@everyone"}
    ordered_roles = []

    for role_id in selected_ids:
        role = roles_by_id.get(role_id)
        if role:
            ordered_roles.append(role)

    for role in sorted(roles_by_id.values(), key=lambda item: item.position, reverse=True):
        if role.id not in selected_ids and not role.managed:
            ordered_roles.append(role)

    options = []
    for role in ordered_roles[:25]:
        options.append(discord.SelectOption(
            label=role.name[:100],
            value=str(role.id),
            default=role.id in selected_ids,
        ))

    if not options:
        options.append(discord.SelectOption(label=f"No roles available for {placeholder_label}", value="none"))
    return options


class ManagerRoleSelect(discord.ui.Select):
    def __init__(self, cog, guild: discord.Guild):
        self.cog = cog
        options = build_role_toggle_options(guild, cog.db.get_manager_roles(guild.id), "manager roles")
        super().__init__(
            placeholder="Check manager roles",
            min_values=0,
            max_values=min(25, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_ids = {int(value) for value in self.values if value != "none"}
        current_ids = set(self.cog.db.get_manager_roles(interaction.guild.id))
        for role_id in current_ids - selected_ids:
            self.cog.db.remove_manager_role(interaction.guild.id, role_id)
        for role_id in selected_ids - current_ids:
            self.cog.db.add_manager_role(interaction.guild.id, role_id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupRolesView(self.cog, interaction.guild),
        )


class ReminderRoleSelect(discord.ui.Select):
    def __init__(self, cog, guild: discord.Guild):
        self.cog = cog
        options = build_role_toggle_options(guild, cog.db.get_reminder_roles(guild.id), "reminder roles")
        super().__init__(
            placeholder="Check reminder roles for MRC, scrims, and tournaments",
            min_values=0,
            max_values=min(25, len(options)),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_ids = {int(value) for value in self.values if value != "none"}
        current_ids = set(self.cog.db.get_reminder_roles(interaction.guild.id))
        for role_id in current_ids - selected_ids:
            self.cog.db.remove_reminder_role(interaction.guild.id, role_id)
        for role_id in selected_ids - current_ids:
            self.cog.db.add_reminder_role(interaction.guild.id, role_id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupRolesView(self.cog, interaction.guild),
        )


class ReminderLeadSelect(discord.ui.Select):
    def __init__(self, cog, guild: discord.Guild):
        self.cog = cog
        current_minutes = cog.db.get_guild_settings(guild.id).get("reminder_minutes", 30)
        options = []
        for minutes in (15, 30, 45, 60):
            label = "1 hour" if minutes == 60 else f"{minutes} minutes"
            options.append(discord.SelectOption(
                label=label,
                value=str(minutes),
                default=minutes == current_minutes,
            ))
        super().__init__(
            placeholder="Choose reminder lead time",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        reminder_minutes = int(self.values[0])
        self.cog.db.update_guild_settings(interaction.guild.id, reminder_minutes=reminder_minutes)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupRolesView(self.cog, interaction.guild),
        )


class ReminderChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            placeholder="Choose reminder channel for MRC, scrims, and tournaments",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.db.update_guild_settings(interaction.guild.id, reminder_channel_id=channel.id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupChannelsView(self.cog),
        )


class MRCEventChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            placeholder="Choose MRC event posting channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.db.update_guild_settings(interaction.guild.id, mrc_event_channel_id=channel.id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupChannelsView(self.cog),
        )


class ScrimEventChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            placeholder="Choose scrim event posting channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.db.update_guild_settings(interaction.guild.id, scrim_event_channel_id=channel.id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupChannelsView(self.cog),
        )


class TournamentEventChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            placeholder="Choose tournament event posting channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.db.update_guild_settings(interaction.guild.id, tournament_event_channel_id=channel.id)
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupChannelsView(self.cog),
        )


class IgniteChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(
            placeholder="Choose Ignite result channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        self.cog.get_ignite_cog().update_settings(interaction.guild.id, channel_id=str(channel.id))
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupIgniteView(self.cog),
        )


class SetupHomeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog

    @discord.ui.button(label="Timezone", style=discord.ButtonStyle.primary)
    async def timezone_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            settings = self.cog.db.get_guild_settings(interaction.guild.id)
            await interaction.response.send_modal(TimezoneSetupModal(self.cog, interaction.guild.id, settings["timezone"]))
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Roles", style=discord.ButtonStyle.primary)
    async def roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupRolesView(self.cog, interaction.guild),
            )
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.primary)
    async def channels_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupChannelsView(self.cog),
            )
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Ignite", style=discord.ButtonStyle.primary)
    async def ignite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupIgniteView(self.cog),
            )
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupHomeView(self.cog),
        )

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success)
    async def done_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await close_setup_panel(interaction)


class SetupRolesView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=600)
        self.cog = cog
        self.add_item(ManagerRoleSelect(cog, guild))
        self.add_item(ReminderRoleSelect(cog, guild))
        self.add_item(ReminderLeadSelect(cog, guild))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupHomeView(self.cog),
        )

class SetupChannelsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog
        self.add_item(ReminderChannelSelect(cog))
        self.add_item(MRCEventChannelSelect(cog))
        self.add_item(ScrimEventChannelSelect(cog))
        self.add_item(TournamentEventChannelSelect(cog))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupHomeView(self.cog),
        )

class SetupIgniteView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog
        self.add_item(IgniteChannelSelect(cog))

    @discord.ui.button(label="Source / Team", style=discord.ButtonStyle.primary)
    async def ignite_options_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            await interaction.response.send_modal(IgniteSetupModal(self.cog, interaction.guild.id))
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Toggle Auto", style=discord.ButtonStyle.primary)
    async def ignite_auto_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            ignite = self.cog.get_ignite_cog()
            settings = ignite.get_settings(interaction.guild.id)
            ignite.update_settings(interaction.guild.id, enabled=0 if settings["enabled"] else 1)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupIgniteView(self.cog),
            )
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Clear Team Filter", style=discord.ButtonStyle.secondary)
    async def clear_team_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.cog.ensure_manager(interaction)
            self.cog.get_ignite_cog().update_settings(interaction.guild.id, clear_tracked_team=True)
            await interaction.response.edit_message(
                content=self.cog.build_setup_status(interaction.guild),
                view=SetupIgniteView(self.cog),
            )
        except Exception as exc:
            await self.cog.send_error(interaction, exc)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.cog.build_setup_status(interaction.guild),
            view=SetupHomeView(self.cog),
        )

async def close_setup_panel(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        await interaction.delete_original_response()
    except Exception:
        if not interaction.response.is_done():
            await interaction.response.edit_message(content="Setup closed.", view=None)
        else:
            await interaction.edit_original_response(content="Setup closed.", view=None)


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    async def send_error(self, interaction: discord.Interaction, error: Exception):
        message = f"Error: {str(error)}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    def ensure_manager(self, interaction: discord.Interaction):
        ensure_manager(interaction, self.db)

    def get_ignite_cog(self):
        ignite_cog = self.bot.get_cog("IgniteCog")
        if not ignite_cog:
            raise RuntimeError("Ignite cog is not loaded.")
        return ignite_cog

    def format_roles(self, guild: discord.Guild, role_ids) -> str:
        roles = [guild.get_role(role_id) for role_id in role_ids]
        role_mentions = [role.mention for role in roles if role]
        return ", ".join(role_mentions) if role_mentions else "None"

    def build_setup_status(self, guild: discord.Guild) -> str:
        settings = self.db.get_guild_settings(guild.id)
        reminder_channel_id = settings["reminder_channel_id"] or settings.get("scrim_reminder_channel_id")
        reminder_channel = guild.get_channel(reminder_channel_id) if reminder_channel_id else None
        mrc_event_channel = guild.get_channel(settings["mrc_event_channel_id"]) if settings["mrc_event_channel_id"] else None
        scrim_event_channel = guild.get_channel(settings["scrim_event_channel_id"]) if settings["scrim_event_channel_id"] else None
        tournament_event_channel = (
            guild.get_channel(settings["tournament_event_channel_id"])
            if settings["tournament_event_channel_id"]
            else None
        )
        ignite_cog = self.get_ignite_cog()
        ignite_settings = ignite_cog.get_settings(guild.id)
        ignite_channel = self.bot.get_channel(int(ignite_settings["channel_id"])) if ignite_settings["channel_id"] else None

        response = "**Bot Setup**\n"
        response += "Use the buttons and menus below to configure this server.\n\n"
        response += f"**Default Timezone:** `{settings['timezone']}`\n"
        response += f"**Manager Roles:** {self.format_roles(guild, self.db.get_manager_roles(guild.id))}\n"
        response += f"**MRC/Scrim/Tournament Reminder Channel:** {reminder_channel.mention if reminder_channel else 'Auto'}\n"
        response += f"**Reminder Lead Time:** {settings.get('reminder_minutes', 30)} minutes\n"
        response += f"**MRC Event Channel:** {mrc_event_channel.mention if mrc_event_channel else 'Command channel'}\n"
        response += f"**Scrim Event Channel:** {scrim_event_channel.mention if scrim_event_channel else 'Command channel'}\n"
        response += f"**Tournament Event Channel:** {tournament_event_channel.mention if tournament_event_channel else 'Command channel'}\n"
        response += f"**Reminder Roles:** {self.format_roles(guild, self.db.get_reminder_roles(guild.id))}\n"
        response += f"**Ignite Channel:** {ignite_channel.mention if ignite_channel else 'Not set'}\n"
        response += f"**Ignite Auto-posting:** {'Enabled' if ignite_settings['enabled'] else 'Disabled'}\n"
        response += f"**Ignite Tracked Team:** {ignite_settings['tracked_team'] or 'All teams'}\n"
        response += f"**Ignite Source:** <{ignite_settings['source_url']}>"
        return response

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

    @app_commands.command(name="setup", description="Open the interactive server setup panel")
    async def setup_panel(self, interaction: discord.Interaction):
        try:
            self.ensure_manager(interaction)
            if not interaction.guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return
            await interaction.response.send_message(
                self.build_setup_status(interaction.guild),
                view=SetupHomeView(self),
                ephemeral=True,
            )
        except Exception as exc:
            await self.send_error(interaction, exc)

async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
