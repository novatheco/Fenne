import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import is_event_admin


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


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCog(bot))
