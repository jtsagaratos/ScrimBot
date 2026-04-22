import sqlite3

import discord
import requests
from discord import app_commands
from discord.ext import commands

from cogs.ignite import USER_AGENT
from models.database import DatabaseManager


class HealthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    @app_commands.command(name="health", description="Check bot health and key integrations")
    async def health(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        checks = []

        try:
            conn = sqlite3.connect("bot_data.db")
            conn.execute("SELECT 1")
            conn.close()
            checks.append("Database: OK")
        except Exception as exc:
            checks.append(f"Database: FAIL ({str(exc)[:120]})")

        mrc = self.bot.get_cog("MRCCog")
        if mrc and getattr(mrc, "reminder_task", None):
            checks.append(f"MRC reminder task: {'running' if mrc.reminder_task.is_running() else 'stopped'}")
        scrim = self.bot.get_cog("ScrimCog")
        if scrim and getattr(scrim, "scrim_reminder_task", None):
            checks.append(f"Scrim reminder task: {'running' if scrim.scrim_reminder_task.is_running() else 'stopped'}")
        else:
            checks.append("Scrim reminder task: not loaded")
        tournament = self.bot.get_cog("TournamentCog")
        if tournament and getattr(tournament, "tournament_reminder_task", None):
            checks.append(
                f"Tournament reminder task: {'running' if tournament.tournament_reminder_task.is_running() else 'stopped'}"
            )
        else:
            checks.append("Tournament reminder task: not loaded")

        ignite = self.bot.get_cog("IgniteCog")
        if ignite and getattr(ignite, "check_ignite_results", None):
            checks.append(f"Ignite auto-check task: {'running' if ignite.check_ignite_results.is_running() else 'stopped'}")
        else:
            checks.append("Ignite auto-check task: not loaded")

        if interaction.guild and ignite:
            settings = ignite.get_settings(interaction.guild.id)
            channel = self.bot.get_channel(int(settings["channel_id"])) if settings["channel_id"] else None
            checks.append(f"Ignite enabled: {'yes' if settings['enabled'] else 'no'}")
            checks.append(f"Ignite channel: {channel.mention if channel else 'not set'}")
            checks.append(f"Ignite failures: {settings['failure_count']}")

            try:
                response = requests.get(
                    settings["source_url"],
                    headers={"User-Agent": USER_AGENT},
                    timeout=10,
                )
                checks.append(f"Ignite source: HTTP {response.status_code}")
            except Exception as exc:
                checks.append(f"Ignite source: FAIL ({str(exc)[:120]})")

        latency_ms = round(self.bot.latency * 1000)
        checks.append(f"Discord latency: {latency_ms} ms")

        await interaction.followup.send("**Bot Health**\n" + "\n".join(f"- {check}" for check in checks), ephemeral=True)


async def setup(bot):
    await bot.add_cog(HealthCog(bot))
