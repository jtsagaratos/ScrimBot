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

    @config_group.command(name="manager_role", description="Set the role allowed to manage bot commands")
    async def config_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        try:
            ensure_manager(interaction, self.db)
            await interaction.response.defer(ephemeral=True)
            self.db.update_guild_settings(interaction.guild.id, manager_role_id=role.id)
            await interaction.followup.send(f"Manager role set to {role.mention}.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="clear_manager_role", description="Clear the configured manager role")
    async def config_clear_manager_role(self, interaction: discord.Interaction):
        try:
            ensure_manager(interaction, self.db)
            await interaction.response.defer(ephemeral=True)
            self.db.get_guild_settings(interaction.guild.id)
            self.db.update_guild_settings(interaction.guild.id, manager_role_id=0)
            await interaction.followup.send("Manager role cleared.", ephemeral=True)
        except Exception as exc:
            await self.send_error(interaction, exc)

    @config_group.command(name="status", description="Show shared bot configuration")
    async def config_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        settings = self.db.get_guild_settings(interaction.guild.id)
        manager_role = interaction.guild.get_role(settings["manager_role_id"]) if settings["manager_role_id"] else None
        reminder_channel = (
            interaction.guild.get_channel(settings["reminder_channel_id"])
            if settings["reminder_channel_id"]
            else None
        )

        response = "**Bot Config**\n"
        response += f"**Manager Role:** {manager_role.mention if manager_role else 'Not set'}\n"
        response += f"**Default Timezone:** {settings['timezone']}\n"
        response += f"**MRC Reminder Channel:** {reminder_channel.mention if reminder_channel else 'Auto'}"
        await interaction.followup.send(response, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
