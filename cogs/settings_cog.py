import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import is_event_admin, log_app_command_error


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="set-admin-role", description="Set which role can use giveaway/embed/tracker admin commands.")
    async def set_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if not is_event_admin(interaction):
            await interaction.response.send_message(
                "Only the server owner or an Administrator can set this up.", ephemeral=True
            )
            return
        db.set_admin_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} can now use admin commands (giveaways, embeds, tracker, autoresponses, leaderboards).",
            ephemeral=True,
        )


    @app_commands.command(name="giveaway-ping-role", description="Set the role pinged when a new giveaway starts.")
    async def giveaway_ping_role(self, interaction: discord.Interaction, role: discord.Role):
        if not is_event_admin(interaction):
            await interaction.response.send_message(
                "Only the server owner, an Administrator, or the admin role can set this up.", ephemeral=True
            )
            return
        db.set_giveaway_ping_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} will now be pinged whenever a new giveaway starts.", ephemeral=True
        )

    @app_commands.command(name="giveaway-host-role", description="Set which role (besides the admin role) is allowed to host giveaways.")
    async def giveaway_host_role(self, interaction: discord.Interaction, role: discord.Role):
        if not is_event_admin(interaction):
            await interaction.response.send_message(
                "Only the server owner, an Administrator, or the admin role can set this up.", ephemeral=True
            )
            return
        db.set_giveaway_host_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} can now use `/ga` and `/giveaway-reroll`, in addition to the admin role.",
            ephemeral=True,
        )

    @app_commands.command(name="set-staff-role", description="Set which role (besides the admin role) can use staff tools like /remind-loop.")
    async def set_staff_role(self, interaction: discord.Interaction, role: discord.Role):
        if not is_event_admin(interaction):
            await interaction.response.send_message(
                "Only the server owner, an Administrator, or the admin role can set this up.", ephemeral=True
            )
            return
        db.set_staff_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"✅ {role.mention} can now use staff tools (`/remind-loop`, etc.), in addition to the admin role.",
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Settings", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
