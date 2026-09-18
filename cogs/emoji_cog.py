import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check, log_app_command_error


class EmojiCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="addemoji", description="Register a named emoji shortcut (use :name: in giveaway text/prizes).")
    @event_admin_check()
    async def addemoji(self, interaction: discord.Interaction, name: str, emoji: str):
        clean_name = name.strip().lower().strip(":")
        if not clean_name:
            await interaction.response.send_message("Give the shortcut a name.", ephemeral=True)
            return
        db.add_emoji_shortcut(interaction.guild.id, clean_name, emoji.strip())
        await interaction.response.send_message(
            f"✅ Registered `:{clean_name}:` → {emoji.strip()}. Use `:{clean_name}:` anywhere in giveaway "
            f"prize/body text and it'll be swapped in automatically.",
            ephemeral=True,
        )

    @app_commands.command(name="removeemoji", description="Remove a registered emoji shortcut.")
    @event_admin_check()
    async def removeemoji(self, interaction: discord.Interaction, name: str):
        removed = db.remove_emoji_shortcut(interaction.guild.id, name)
        if removed:
            await interaction.response.send_message(f"🗑️ Removed shortcut `:{name.strip().lower()}:`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No shortcut found named `:{name.strip().lower()}:`.", ephemeral=True)

    @app_commands.command(name="listemojis", description="List all registered emoji shortcuts.")
    async def listemojis(self, interaction: discord.Interaction):
        rows = db.list_emoji_shortcuts(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("No emoji shortcuts registered yet.", ephemeral=True)
            return
        lines = [f"`:{r['name']}:` → {r['emoji']}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @removeemoji.autocomplete("name")
    async def removeemoji_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = db.list_emoji_shortcuts(interaction.guild.id)
        return [
            app_commands.Choice(name=r["name"], value=r["name"])
            for r in rows if current.lower() in r["name"]
        ][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Emoji", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiCog(bot))
