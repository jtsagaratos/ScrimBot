import discord
from discord import app_commands
from discord.ext import commands

from models.database import DatabaseManager
from models.permissions import ensure_manager


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    config_group = app_commands.Group(name="config", description="Shared bot configuration")

    async def send_error(self, interaction: discord.Interaction, error: Exception):
        message = f"Error: {str(error)}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @config_group.command(name="manager_role", description="Add a role allowed to manage bot commands")
    async def config_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        try:
            ensure_manager(interaction, self.db)
            await interaction.response.defer(ephemeral=True)
            self.db.add_manager_role(interaction.guild.id, role.id)
            await interaction.followup.send(f"Added manager role {role.mention}.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="remove_manager_role", description="Remove a configured manager role")
    async def config_remove_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        try:
            ensure_manager(interaction, self.db)
            await interaction.response.defer(ephemeral=True)
            removed = self.db.remove_manager_role(interaction.guild.id, role.id)
            if removed:
                await interaction.followup.send(f"Removed manager role {role.mention}.", ephemeral=True)
            else:
                await interaction.followup.send(f"{role.mention} was not configured as a manager role.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="clear_manager_role", description="Clear all configured manager roles")
    async def config_clear_manager_role(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, self.db)
            await interaction.response.defer(ephemeral=True)
            removed = self.db.clear_manager_roles(interaction.guild.id)
            self.db.update_guild_settings(interaction.guild.id, manager_role_id=0)
            await interaction.followup.send(f"Cleared {removed} manager role(s).", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="manager_roles", description="List configured manager roles")
    async def config_manager_roles(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            if not interaction.guild:
                await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
                return
            roles = [interaction.guild.get_role(role_id) for role_id in self.db.get_manager_roles(interaction.guild.id)]
            role_mentions = [role.mention for role in roles if role]
            await interaction.followup.send(
                f"Manager roles: {', '.join(role_mentions) if role_mentions else 'None'}",
                ephemeral=True,
            )
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="status", description="Show shared bot configuration")
    async def config_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        settings = self.db.get_guild_settings(interaction.guild.id)
        manager_roles = [interaction.guild.get_role(role_id) for role_id in self.db.get_manager_roles(interaction.guild.id)]
        manager_role_mentions = [role.mention for role in manager_roles if role]
        reminder_channel = (
            interaction.guild.get_channel(settings["reminder_channel_id"])
            if settings["reminder_channel_id"]
            else None
        )

        response = "**Bot Config**\n"
        response += f"**Manager Roles:** {', '.join(manager_role_mentions) if manager_role_mentions else 'Not set'}\n"
        response += f"**Default Timezone:** {settings['timezone']}\n"
        response += f"**MRC Reminder Channel:** {reminder_channel.mention if reminder_channel else 'Auto'}"
        await interaction.followup.send(response, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
