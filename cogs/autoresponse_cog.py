import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check, log_app_command_error


class AutoresponseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip().lower()
        if not content:
            return
        row = db.get_autoresponse(message.guild.id, content)
        if row:
            await message.channel.send(row["response"])

    @app_commands.command(name="autoresponse-add", description="Add an exact-match autoresponse trigger.")
    @event_admin_check()
    async def autoresponse_add(self, interaction: discord.Interaction, trigger: str, response: str):
        db.add_autoresponse(interaction.guild.id, trigger, response)
        await interaction.response.send_message(
            f"✅ When someone types exactly `{trigger.strip()}`, I'll reply with:\n> {response}",
            ephemeral=True,
        )

    @app_commands.command(name="autoresponse-remove", description="Remove an autoresponse trigger.")
    @event_admin_check()
    async def autoresponse_remove(self, interaction: discord.Interaction, trigger: str):
        removed = db.remove_autoresponse(interaction.guild.id, trigger)
        if removed:
            await interaction.response.send_message(f"🗑️ Removed trigger `{trigger.strip()}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No trigger found matching `{trigger.strip()}`.", ephemeral=True)

    @app_commands.command(name="autoresponse-list", description="List all autoresponse triggers in this server.")
    @event_admin_check()
    async def autoresponse_list(self, interaction: discord.Interaction):
        rows = db.list_autoresponses(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("No autoresponses set up yet.", ephemeral=True)
            return
        lines = [f"`{r['trigger']}` → {r['response'][:60]}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @autoresponse_remove.autocomplete("trigger")
    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = db.list_autoresponses(interaction.guild.id)
        return [
            app_commands.Choice(name=r["trigger"], value=r["trigger"])
            for r in rows if current.lower() in r["trigger"]
        ][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Autoresponse", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoresponseCog(bot))
