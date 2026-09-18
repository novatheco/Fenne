import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import event_admin_check, log_app_command_error


class InvitesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return
        data = [(inv.code, inv.uses or 0, inv.inviter.id if inv.inviter else None) for inv in invites]
        db.cache_invites(guild.id, data)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        db.cache_invites(invite.guild.id, [(invite.code, invite.uses or 0, invite.inviter.id if invite.inviter else None)])

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        # Leave the cached row as-is; it's still useful for matching the last use
        # that consumed the invite (e.g. single-use invites that get auto-deleted).
        pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        settings = db.get_guild_settings(guild.id)
        log_channel_id = settings.get("invite_log_channel_id")
        if not log_channel_id:
            return
        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        try:
            fresh_invites = await guild.invites()
        except discord.Forbidden:
            return
        cached = db.get_cached_invites(guild.id)

        used_invite = None
        for inv in fresh_invites:
            old = cached.get(inv.code)
            old_uses = old["uses"] if old else 0
            if (inv.uses or 0) > old_uses:
                used_invite = inv
                break

        # Re-cache current state regardless of whether we found a match.
        db.cache_invites(guild.id, [(i.code, i.uses or 0, i.inviter.id if i.inviter else None) for i in fresh_invites])

        embed = discord.Embed(title="📥 Member Joined", color=discord.Color.green())
        embed.add_field(name="Invited", value=member.mention, inline=True)

        if used_invite and used_invite.inviter:
            embed.add_field(name="Invited by", value=used_invite.inviter.mention, inline=True)
            embed.add_field(name="Invite", value=f"`discord.gg/{used_invite.code}`", inline=True)
            total = db.count_invites_by_user(guild.id, used_invite.inviter.id)
            embed.set_footer(text=f"{used_invite.inviter.display_name} has {total} total invite use(s)")
        else:
            embed.add_field(name="Invited by", value="Unknown (vanity URL, widget, or bot invite)", inline=True)

        embed.set_thumbnail(url=member.display_avatar.url)
        embed.timestamp = discord.utils.utcnow()

        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=False))

    @app_commands.command(name="tracker-to", description="Set the channel where invite-tracking logs are posted.")
    @event_admin_check()
    async def tracker_to(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.set_invite_log_channel(interaction.guild.id, channel.id)
        await self._cache_guild_invites(interaction.guild)
        await interaction.response.send_message(
            f"✅ Invite logs will now be posted in {channel.mention}.", ephemeral=True
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Invites", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InvitesCog(bot))
