import discord
from discord import app_commands
from discord.ext import commands

from models.database import DatabaseManager
from models.time_utils import discord_time_display


class UpcomingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    @app_commands.command(name="upcoming", description="View upcoming MRC matches, scrims, and tournaments")
    @app_commands.describe(days="Number of days to include, from 1 to 90")
    async def upcoming(self, interaction: discord.Interaction, days: int = 14):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        days = max(1, min(days, 90))
        matches = self.db.get_upcoming_mrc_matches(guild.id, days=days)
        scrims = self.db.get_upcoming_scrims(guild.id, days=days)
        tournaments = self.db.get_upcoming_tournaments(guild.id, days=days)

        if not matches and not scrims and not tournaments:
            await interaction.followup.send(f"No MRC matches, scrims, or tournaments scheduled in the next {days} day(s).")
            return

        embed = discord.Embed(
            title=f"Upcoming Schedule ({days} days)",
            color=discord.Color.green(),
        )

        for match in matches[:12]:
            bracket = f" ({match['bracket']})" if match.get("bracket") else ""
            value = (
                f"{discord_time_display(match['datetime'], match['timezone'])}\n"
                f"MRC S{match.get('season', 7)} - {match['round_group']}{bracket} | "
                f"{match['duration_hours']:g}h | {match['status']}"
            )
            embed.add_field(name=f"MRC Event ID M{match['id']}", value=value, inline=False)

        for scrim in scrims[:12]:
            event = guild.get_scheduled_event(int(scrim["discord_event_id"])) if scrim["discord_event_id"] else None
            value = f"{discord_time_display(scrim['datetime'], scrim['timezone'])}\n"
            value += f"Duration: {scrim['duration_hours']:g}h\n"
            value += f"Status: {scrim['status']}\n"
            value += f"Against: {scrim['team_name']}"
            if event:
                value += f"\nEvent: {event.url}"
            embed.add_field(name=f"Scrim Event ID S{scrim['id']}", value=value, inline=False)

        for tournament in tournaments[:12]:
            event = guild.get_scheduled_event(int(tournament["discord_event_id"])) if tournament["discord_event_id"] else None
            value = f"{discord_time_display(tournament['datetime'], tournament['timezone'])}\n"
            value += f"Duration: {tournament['duration_hours']:g}h\n"
            value += f"Status: {tournament['status']}"
            if event:
                value += f"\nEvent: {event.url}"
            embed.add_field(name=f"Tournament Event ID T{tournament['id']}", value=value, inline=False)

        hidden = max(0, len(matches) - 12) + max(0, len(scrims) - 12) + max(0, len(tournaments) - 12)
        if hidden:
            embed.add_field(name="More", value=f"{hidden} additional item(s) not shown.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(UpcomingCog(bot))
