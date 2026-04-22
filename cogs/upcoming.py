import discord
from discord import app_commands
from discord.ext import commands

from models.database import DatabaseManager
from models.time_utils import discord_time_display


class UpcomingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    @app_commands.command(name="upcoming", description="View upcoming MRC matches and scrims")
    @app_commands.describe(days="Number of days to include, from 1 to 90")
    async def upcoming(self, interaction: discord.Interaction, days: int = 14):
        await interaction.response.defer()

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Error: This command can only be used in a server.", ephemeral=True)
            return

        days = max(1, min(days, 90))
        matches = self.db.get_upcoming_mrc_matches(guild.id, days=days)
        scrims = self.db.get_upcoming_scrims(guild.id, days=days)

        if not matches and not scrims:
            await interaction.followup.send(f"No MRC matches or scrims scheduled in the next {days} day(s).")
            return

        embed = discord.Embed(
            title=f"Upcoming Schedule ({days} days)",
            color=discord.Color.green(),
        )

        for match in matches[:12]:
            value = (
                f"{discord_time_display(match['datetime'], match['timezone'])}\n"
                f"{match['round_group']} | {match['bracket']} | {match['status']}"
            )
            embed.add_field(name=f"MRC Match #{match['id']}", value=value, inline=False)

        for scrim in scrims[:12]:
            role = guild.get_role(scrim["role_id"]) if scrim["role_id"] else None
            event = guild.get_scheduled_event(int(scrim["discord_event_id"])) if scrim["discord_event_id"] else None
            value = f"{discord_time_display(scrim['datetime'], scrim['timezone'])}\n"
            value += f"Against: {role.mention if role else scrim['team_name']}"
            if event:
                value += f"\nEvent: {event.url}"
            embed.add_field(name=f"Scrim #{scrim['id']}", value=value, inline=False)

        hidden = max(0, len(matches) - 12) + max(0, len(scrims) - 12)
        if hidden:
            embed.add_field(name="More", value=f"{hidden} additional item(s) not shown.", inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(UpcomingCog(bot))
