import time

import discord
from discord.ext import commands
from discord import app_commands

import config
import database as db
from cogs.permissions import event_admin_check, log_app_command_error


class AfkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    afk_group = app_commands.Group(name="afk", description="AFK status")
    channel_group = app_commands.Group(name="channel", description="Channel settings")

    @afk_group.command(name="set", description="Set yourself as AFK. Only clears when you run /afk off.")
    @app_commands.describe(reason="Why you're AFK (optional)")
    async def afk_set(self, interaction: discord.Interaction, reason: str = "AFK"):
        db.set_afk(interaction.guild.id, interaction.user.id, reason.strip() or "AFK", time.time())
        await interaction.response.send_message(
            db.apply_emoji_shortcuts(f":afk: {interaction.user.mention} is now AFK: {reason.strip() or 'AFK'}"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @afk_group.command(name="off", description="Clear your own AFK status.")
    async def afk_off(self, interaction: discord.Interaction):
        row = db.get_afk(interaction.guild.id, interaction.user.id)
        if not row:
            await interaction.response.send_message("You're not marked as AFK.", ephemeral=True)
            return
        db.clear_afk(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            db.apply_emoji_shortcuts(
                f":cat_cute: Welcome back {interaction.user.mention}, I've removed your AFK status "
                f"(you were away since <t:{int(row['started_at'])}:R>)."
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @afk_group.command(name="remove", description="ADMIN: Clear another member's AFK status.")
    @app_commands.describe(user="The member to clear AFK for")
    @event_admin_check()
    async def afk_remove(self, interaction: discord.Interaction, user: discord.Member):
        row = db.get_afk(interaction.guild.id, user.id)
        if not row:
            await interaction.response.send_message(f"{user.mention} isn't marked as AFK.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        db.clear_afk(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"✅ Cleared {user.mention}'s AFK status.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @channel_group.command(name="ignore", description="ADMIN: Stop AFK mention notices from appearing in a channel.")
    @app_commands.describe(channel="The channel to ignore")
    @event_admin_check()
    async def channel_ignore(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.add_ignored_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ AFK notices are now suppressed in {channel.mention}.", ephemeral=True)

    @channel_group.command(name="unignore", description="ADMIN: Re-allow AFK mention notices in a channel.")
    @app_commands.describe(channel="The channel to stop ignoring")
    @event_admin_check()
    async def channel_unignore(self, interaction: discord.Interaction, channel: discord.TextChannel):
        removed = db.remove_ignored_channel(interaction.guild.id, channel.id)
        if removed:
            await interaction.response.send_message(f"✅ AFK notices will show in {channel.mention} again.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} wasn't being ignored.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not message.mentions:
            return
        if db.is_channel_ignored(message.guild.id, message.channel.id):
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
                    f":name: {member.mention} is currently AFK.\n"
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
