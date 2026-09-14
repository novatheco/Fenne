import discord

import config
import database as db


def is_event_admin(interaction: discord.Interaction) -> bool:
    """True if the user can run management commands: server owner, configured
    admin role, real Administrator permission, or a bot owner."""
    user = interaction.user
    if user.id in config.OWNER_IDS:
        return True
    if interaction.guild is None:
        return False
    if interaction.guild.owner_id == user.id:
        return True
    perms = getattr(user, "guild_permissions", None)
    if perms and perms.administrator:
        return True
    settings = db.get_guild_settings(interaction.guild.id)
    admin_role_id = settings.get("admin_role_id")
    if admin_role_id:
        role_ids = {r.id for r in getattr(user, "roles", [])}
        if admin_role_id in role_ids:
            return True
    return False


def event_admin_check():
    """app_commands check decorator using is_event_admin."""
    from discord import app_commands

    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_event_admin(interaction):
            raise app_commands.CheckFailure(
                "You need the configured admin role (or Administrator) to use this command."
            )
        return True

    return app_commands.check(predicate)
