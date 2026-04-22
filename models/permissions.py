import discord

from models.database import DatabaseManager


def is_manager(interaction: discord.Interaction, db: DatabaseManager) -> bool:
    """Return whether a user can manage bot scheduling/configuration."""
    if not interaction.guild:
        return False

    permissions = interaction.user.guild_permissions
    if permissions.administrator or permissions.manage_guild or permissions.manage_events:
        return True

    settings = db.get_guild_settings(interaction.guild.id)
    manager_role_id = settings.get("manager_role_id")
    if not manager_role_id:
        return False

    return any(role.id == manager_role_id for role in getattr(interaction.user, "roles", []))


def ensure_manager(interaction: discord.Interaction, db: DatabaseManager):
    if is_manager(interaction, db):
        return
    raise PermissionError(
        "You need Administrator, Manage Server, Manage Events, or the configured manager role to use this command."
    )
