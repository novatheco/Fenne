import time

import discord
from discord.ext import commands
from discord import app_commands

import config
import database as db
from cogs.permissions import log_app_command_error


class AfkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="afk", description="Set yourself as AFK. Clears automatically next time you send a message.")
    @app_commands.describe(reason="Why you're AFK (optional)")
    async def afk(self, interaction: discord.Interaction, reason: str = "AFK"):
        db.set_afk(interaction.guild.id, interaction.user.id, reason.strip() or "AFK", time.time())
        await interaction.response.send_message(
            f"💤 {interaction.user.mention} is now AFK: {reason.strip() or 'AFK'}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # If the author was AFK, welcome them back and clear it.
        row = db.get_afk(message.guild.id, message.author.id)
        if row:
            db.clear_afk(message.guild.id, message.author.id)
            away_seconds = int(time.time() - row["started_at"])
            try:
                await message.channel.send(
                    f"👋 Welcome back {message.author.mention}, I've removed your AFK status "
                    f"(you were away for <t:{int(row['started_at'])}:R>).",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

        # Notify about any mentioned users who are AFK.
        if not message.mentions:
            return
        seen = set()
        for member in message.mentions:
            if member.id in seen or member.bot:
                continue
            seen.add(member.id)
            afk_row = db.get_afk(message.guild.id, member.id)
            if not afk_row:
                continue
            embed = discord.Embed(
                description=db.apply_emoji_shortcuts(
                    f"🔴 {member.mention} is currently AFK.\n"
                    f":reason: **Reason:** {afk_row['reason']}\n"
                    f":afktime: **Started at:** <t:{int(afk_row['started_at'])}:R>"
                ),
                color=discord.Color(config.EMBED_COLOR_HEX),
            )
            try:
                await message.reply(embed=embed, mention_author=False)
            except discord.HTTPException:
                pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Afk", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AfkCog(bot))
