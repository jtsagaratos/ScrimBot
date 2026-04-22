import discord
from discord import app_commands
from discord.ext import commands

from cogs.mrc import MRCEditModal
from cogs.scrim import ScrimEditModal
from cogs.tournaments import TournamentEditModal
from models.database import DatabaseManager
from models.permissions import ensure_manager


class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager("bot_data.db")

    def parse_event_id(self, event_id: str):
        value = event_id.strip().upper()
        if len(value) < 2:
            raise ValueError("Use a prefixed Event ID like M1, S1, or T1.")
        prefix = value[0]
        number = value[1:]
        if prefix not in {"M", "S", "T"} or not number.isdigit():
            raise ValueError("Use a prefixed Event ID like M1 for MRC, S1 for scrims, or T1 for tournaments.")
        return prefix, int(number)

    async def event_id_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild:
            return []

        current_lower = current.lower()
        choices = []

        for match in self.db.get_all_mrc_matches(interaction.guild.id, include_archived=False):
            public_id = f"M{match['id']}"
            bracket = f" {match['bracket']}" if match.get("bracket") else ""
            label = f"{public_id} MRC S{match.get('season', 7)} {match['round_group']}{bracket} {match['status']}"
            if not current or current_lower in public_id.lower() or current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=public_id))
            if len(choices) == 25:
                return choices

        for scrim in self.db.get_all_scrims(interaction.guild.id, include_archived=False):
            public_id = f"S{scrim['id']}"
            label = f"{public_id} Scrim vs {scrim['team_name']} {scrim['status']}"
            if not current or current_lower in public_id.lower() or current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=public_id))
            if len(choices) == 25:
                return choices

        for tournament in self.db.get_all_tournaments(interaction.guild.id, include_archived=False):
            public_id = f"T{tournament['id']}"
            label = f"{public_id} Tournament {tournament['tournament_name']} {tournament['status']}"
            if not current or current_lower in public_id.lower() or current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=public_id))
            if len(choices) == 25:
                return choices

        return choices

    @app_commands.command(name="edit", description="Edit an MRC, scrim, or tournament event by prefixed Event ID")
    @app_commands.describe(event_id="Event ID, such as M1, S1, or T1")
    async def edit_event(self, interaction: discord.Interaction, event_id: str):
        try:
            ensure_manager(interaction, self.db)
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Error: This command can only be used in a server.", ephemeral=True)
                return

            prefix, database_id = self.parse_event_id(event_id)
            if prefix == "M":
                mrc_cog = self.bot.get_cog("MRCCog")
                if not mrc_cog:
                    await interaction.response.send_message("Error: MRC commands are not loaded.", ephemeral=True)
                    return
                match = self.db.get_mrc_match(guild.id, database_id)
                if not match:
                    await interaction.response.send_message(f"Event ID M{database_id} not found.", ephemeral=True)
                    return
                await interaction.response.send_modal(MRCEditModal(mrc_cog, guild.id, match))
                return

            if prefix == "T":
                tournament_cog = self.bot.get_cog("TournamentCog")
                if not tournament_cog:
                    await interaction.response.send_message("Error: Tournament commands are not loaded.", ephemeral=True)
                    return
                tournament = self.db.get_tournament(guild.id, database_id)
                if not tournament:
                    await interaction.response.send_message(f"Event ID T{database_id} not found.", ephemeral=True)
                    return
                await interaction.response.send_modal(TournamentEditModal(tournament_cog, guild.id, tournament))
                return

            scrim_cog = self.bot.get_cog("ScrimCog")
            if not scrim_cog:
                await interaction.response.send_message("Error: Scrim commands are not loaded.", ephemeral=True)
                return
            scrim = self.db.get_scrim(guild.id, database_id)
            if not scrim:
                await interaction.response.send_message(f"Event ID S{database_id} not found.", ephemeral=True)
                return
            await interaction.response.send_modal(ScrimEditModal(scrim_cog, guild.id, scrim))
        except Exception as exc:
            if interaction.response.is_done():
                await interaction.followup.send(f"Error: {str(exc)}", ephemeral=True)
            else:
                await interaction.response.send_message(f"Error: {str(exc)}", ephemeral=True)

    @edit_event.autocomplete("event_id")
    async def edit_event_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self.event_id_autocomplete(interaction, current)


async def setup(bot):
    await bot.add_cog(EventCog(bot))
