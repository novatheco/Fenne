import re

import discord
from discord.ext import commands
from discord import app_commands

import config
import database as db
from cogs.permissions import event_admin_check, log_app_command_error

class AutomodCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    automod_group = app_commands.Group(name="automod-channel", description="Restrict channel messages to a pattern")

    @automod_group.command(name="set", description="Only allow messages matching a pattern in this channel; delete and notify on anything else.")
    @app_commands.describe(
        channel="The channel to restrict",
        pattern="A regex the WHOLE message must match (e.g. ^;m (?:b|buy) [0-9]+(?: all)?$)",
        title="Title shown on the rejection notice",
        message="Explanation shown on the rejection notice",
        ping_user="Also @mention the user alongside the notice? (default: no, just the embed)",
    )
    @event_admin_check()
    async def automod_set(
        self, interaction: discord.Interaction, channel: discord.TextChannel, pattern: str,
        title: str, message: str, ping_user: bool = False,
    ):
        try:
            re.compile(pattern)
        except re.error as e:
            await interaction.response.send_message(f"❌ That's not a valid regex pattern: {e}", ephemeral=True)
            return
        db.set_automod_channel(interaction.guild.id, channel.id, pattern, title, message, ping_user)
        await interaction.response.send_message(
            f"✅ {channel.mention} now only allows messages matching that pattern. "
            f"Everything else gets deleted with a notice" + (" that pings the author." if ping_user else "."),
            ephemeral=True,
        )

    @automod_group.command(name="remove", description="Stop restricting messages in a channel.")
    @app_commands.describe(channel="The channel to stop restricting")
    @event_admin_check()
    async def automod_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        removed = db.remove_automod_channel(interaction.guild.id, channel.id)
        if removed:
            await interaction.response.send_message(f"✅ {channel.mention} is no longer restricted.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} wasn't restricted.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        rule = db.get_automod_channel(message.guild.id, message.channel.id)
        if not rule:
            return

        try:
            matched = re.match(rule["pattern"], message.content, re.IGNORECASE) is not None
        except re.error:
            return  # a bad pattern shouldn't take the channel down
        if matched:
            return

        deleted_content = message.content or "*(no text content)*"
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title=db.apply_emoji_shortcuts(f":loser: {rule['title']}"),
            description=rule["message"],
            color=discord.Color(config.EMBED_COLOR_HEX),
        )
        embed.add_field(name="Deleted Message:", value=deleted_content[:1000], inline=False)

        content = message.author.mention if rule["ping_user"] else None
        try:
            await message.channel.send(
                content=content, embed=embed,
                allowed_mentions=discord.AllowedMentions(users=bool(rule["ping_user"])),
            )
        except discord.HTTPException:
            pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Automod", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutomodCog(bot))
