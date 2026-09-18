import traceback

import discord

import config
import database as db


def log_app_command_error(label: str, interaction: discord.Interaction, error) -> None:
    """Prints the full traceback of an app command error, not just str(error),
    so failures are actually diagnosable from the console/logs."""
    original = getattr(error, "original", error)
    cmd_name = interaction.command.name if interaction.command else "?"
    print(f"[{label}] error in /{cmd_name}:")
    traceback.print_exception(type(original), original, original.__traceback__)


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


def is_giveaway_host(interaction: discord.Interaction) -> bool:
    """True if the user can host giveaways: anyone who passes is_event_admin,
    OR anyone holding the configured giveaway-host role."""
    if is_event_admin(interaction):
        return True
    if interaction.guild is None:
        return False
    settings = db.get_guild_settings(interaction.guild.id)
    host_role_id = settings.get("giveaway_host_role_id")
    if host_role_id:
        role_ids = {r.id for r in getattr(interaction.user, "roles", [])}
        if host_role_id in role_ids:
            return True
    return False


def giveaway_host_check():
    """app_commands check decorator using is_giveaway_host."""
    from discord import app_commands

    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_giveaway_host(interaction):
            raise app_commands.CheckFailure(
                "You need the configured giveaway host role (or admin role/Administrator) to use this command."
            )
        return True

    return app_commands.check(predicate)


def is_staff(interaction: discord.Interaction) -> bool:
    """True if the user can run staff-only tools like /remind-loop: anyone who
    passes is_event_admin, OR anyone holding the configured staff role."""
    if is_event_admin(interaction):
        return True
    if interaction.guild is None:
        return False
    settings = db.get_guild_settings(interaction.guild.id)
    staff_role_id = settings.get("staff_role_id")
    if staff_role_id:
        role_ids = {r.id for r in getattr(interaction.user, "roles", [])}
        if staff_role_id in role_ids:
            return True
    return False


def staff_check():
    """app_commands check decorator using is_staff."""
    from discord import app_commands

    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_staff(interaction):
            raise app_commands.CheckFailure(
                "You need the configured staff role (or admin role/Administrator) to use this command."
            )
        return True

    return app_commands.check(predicate)
