import asyncio
import random
import re
import time

import discord
from discord.ext import commands
from discord import app_commands

import database as db
from cogs.permissions import is_event_admin, event_admin_check, giveaway_host_check, log_app_command_error
from utils import parse_duration, format_duration


def parse_role_list(guild: discord.Guild, text: str) -> list[int]:
    """Parses a comma/space separated list of role mentions, IDs, or names."""
    if not text:
        return []
    ids = []
    for chunk in re.split(r"[,\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"<@&(\d+)>", chunk)
        if m:
            ids.append(int(m.group(1)))
            continue
        if chunk.isdigit():
            ids.append(int(chunk))
            continue
        role = discord.utils.get(guild.roles, name=chunk)
        if role:
            ids.append(role.id)
    return ids


def build_giveaway_embed(guild: discord.Guild, giveaway: dict, template: dict, status: str, winners: list[int] | None = None) -> discord.Embed:
    color = discord.Color.gold() if status == "running" else discord.Color.dark_gray()
    title = f"🎁 {template['top_message'] or 'GIVEAWAY'} 🎁" if status == "running" else f"Giveaway — {status.title()}"
    embed = discord.Embed(title=title, color=color)

    host = guild.get_member(giveaway["host_id"])
    host_mention = host.mention if host else f"<@{giveaway['host_id']}>"

    prize_text = db.apply_emoji_shortcuts(guild.id, giveaway["prize"])
    body_text = db.apply_emoji_shortcuts(guild.id, giveaway.get("body_text") or "")

    # Built as separate blocks joined with blank lines in between, so the embed
    # has real breathing room instead of everything crammed together.
    blocks = []

    if body_text:
        blocks.append(body_text)

    blocks.append(f"🎗️ **Hosted By:** {host_mention}")
    blocks.append(f"🏆 **Number of Winners:** {giveaway['winner_count']}")
    blocks.append(f"🎁 **Prize:**\n{prize_text}")

    if status == "running":
        end_ts = int(giveaway["end_time"])
        blocks.append(f"⏳ **Ends:** <t:{end_ts}:R>")
    else:
        blocks.append("⏳ **Ended**")

    if template["blacklisted_roles"]:
        names = []
        for rid in template["blacklisted_roles"]:
            role = guild.get_role(rid)
            names.append(role.mention if role else f"<@&{rid}>")
        blocks.append("🚫 **Blacklisted roles:**\n" + ", ".join(names))

    if template["extra_entry_roles"]:
        names = []
        for rid in template["extra_entry_roles"]:
            role = guild.get_role(rid)
            names.append((role.mention if role else f"<@&{rid}>") + " +1")
        blocks.append("✨ **Extra Entries:**\n" + ", ".join(names))

    if winners is not None:
        if winners:
            blocks.append("🎊 **Winners**\n" + "\n".join(f"<@{w}>" for w in winners))
        else:
            blocks.append("🎊 **Winners**\nNo valid entries — no winner could be chosen.")

    embed.description = "\n\n".join(blocks)

    if template.get("icon_url"):
        embed.set_thumbnail(url=template["icon_url"])

    if giveaway.get("id"):
        embed.set_footer(text=f"Giveaway ID: {giveaway['id']}")

    return embed


def build_ended_announcement(guild: discord.Guild, giveaway: dict, winners: list[int], rerolled: bool = False) -> tuple[str, discord.Embed]:
    """Builds the 'Giveaway Ended!' congrats message + embed shown in the channel."""
    host = guild.get_member(giveaway["host_id"])
    host_mention = host.mention if host else f"<@{giveaway['host_id']}>"
    prize_text = db.apply_emoji_shortcuts(guild.id, giveaway["prize"])

    verb = "Rerolled" if rerolled else "Ended"
    if winners:
        mentions = ", ".join(f"<@{w}>" for w in winners)
        content = f"🎉 Congratulations {mentions} for winning {host_mention}'s giveaway!"
        winners_value = "\n".join(f"<@{w}>" for w in winners)
    else:
        content = f"😔 {host_mention}'s giveaway ended with no eligible winner."
        winners_value = "No valid entries."

    embed = discord.Embed(
        title=f"🎉 Giveaway {verb}!",
        description="Congratulations to the winners!" if winners else "No one was eligible to win.",
        color=discord.Color.green() if winners else discord.Color.dark_gray(),
    )
    embed.add_field(name="🎁 Prize", value=prize_text, inline=False)
    embed.add_field(name="🏆 Winners", value=winners_value, inline=False)
    embed.set_footer(text=f"Giveaway ID: {giveaway['id']}")
    return content, embed


class GiveawayEditModal(discord.ui.Modal, title="Edit Giveaway"):
    def __init__(self, view: "GiveawayPreviewView"):
        super().__init__()
        self.view_ref = view
        g = view.giveaway
        self.prize = discord.ui.TextInput(label="Prize", default=g["prize"], max_length=200)
        self.winners = discord.ui.TextInput(label="Number of Winners", default=str(g["winner_count"]), max_length=3)
        self.duration = discord.ui.TextInput(
            label="Duration (e.g. 1h, 30m, 2d)", default=format_duration(g["end_time"] - g.get("_created_at", g["end_time"])), max_length=20
        )
        self.body_text = discord.ui.TextInput(
            label="Giveaway Message", style=discord.TextStyle.paragraph,
            default=g.get("body_text") or "", required=False, max_length=1000,
        )
        self.add_item(self.prize)
        self.add_item(self.winners)
        self.add_item(self.duration)
        self.add_item(self.body_text)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            winner_count = max(1, int(self.winners.value.strip()))
        except ValueError:
            await interaction.response.send_message("Number of winners must be a whole number.", ephemeral=True)
            return
        seconds = parse_duration(self.duration.value)
        if not seconds:
            await interaction.response.send_message("Couldn't parse that duration. Try things like `1h`, `30m`, `2d`.", ephemeral=True)
            return

        g = self.view_ref.giveaway
        g["prize"] = self.prize.value.strip()
        g["winner_count"] = winner_count
        g["end_time"] = time.time() + seconds
        g["body_text"] = self.body_text.value.strip()

        await interaction.response.edit_message(embed=self.view_ref.build_preview_embed(), view=self.view_ref)


class GiveawayPreviewView(discord.ui.View):
    """Shown to the host before the giveaway goes live: edit fields, or hit Start."""

    def __init__(self, cog: "GiveawayCog", guild: discord.Guild, template: dict, giveaway: dict):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.template = template
        self.giveaway = giveaway
        self.giveaway["_created_at"] = time.time()

    def build_preview_embed(self) -> discord.Embed:
        fake = dict(self.giveaway)
        fake["host_id"] = self.giveaway["host_id"]
        embed = build_giveaway_embed(self.guild, fake, self.template, status="running")
        embed.set_footer(text="Preview — not posted yet. Edit or hit Start when ready.")
        return embed

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.giveaway["host_id"]:
            await interaction.response.send_message("Only the host can edit this giveaway.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveawayEditModal(self))

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="🚀")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.giveaway["host_id"]:
            await interaction.response.send_message("Only the host can start this giveaway.", ephemeral=True)
            return
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        await self.cog.launch_giveaway(interaction, self.template, self.giveaway)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.giveaway["host_id"]:
            await interaction.response.send_message("Only the host can cancel this giveaway.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Giveaway cancelled — not posted.", embed=None, view=self)


class GiveawayJoinView(discord.ui.View):
    """Persistent-ish view attached to a live giveaway message."""

    def __init__(self, cog: "GiveawayCog", giveaway_id: int, blacklisted_roles: list[int], entry_count: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id
        self.blacklisted_roles = set(blacklisted_roles)
        self.join_button.label = f"🎉{entry_count}"

    @discord.ui.button(label="🎉0", style=discord.ButtonStyle.blurple, custom_id="giveaway_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_role_ids = {r.id for r in interaction.user.roles} if hasattr(interaction.user, "roles") else set()
        if user_role_ids & self.blacklisted_roles:
            await interaction.response.send_message("🚫 You're not eligible to enter this giveaway.", ephemeral=True)
            return

        if db.has_entry(self.giveaway_id, interaction.user.id):
            db.remove_entry(self.giveaway_id, interaction.user.id)
            joined = False
        else:
            db.add_entry(self.giveaway_id, interaction.user.id)
            joined = True

        count = db.count_entries(self.giveaway_id)
        button.label = f"🎉{count}"
        await interaction.response.edit_message(view=self)
        msg = "✅ You joined the giveaway! Good luck." if joined else "You left the giveaway."
        await interaction.followup.send(msg, ephemeral=True)


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        # Reschedule any giveaways that were still running when the bot restarted.
        for g in db.get_running_giveaways():
            self._schedule_end(g["id"], g["end_time"])

    # ---------------- /default-template ----------------

    @app_commands.command(name="default-template", description="Create or update a giveaway template.")
    @event_admin_check()
    async def default_template(self, interaction: discord.Interaction, name: str):
        modal = TemplateModal(interaction.guild.id, name)
        await interaction.response.send_modal(modal)

    # ---------------- /ga ----------------

    @app_commands.command(name="ga", description="Create a giveaway from a saved template.")
    @giveaway_host_check()
    async def ga(self, interaction: discord.Interaction, template: str, prize: str, winners: int, duration: str):
        tmpl = db.get_template(interaction.guild.id, template)
        if not tmpl:
            names = ", ".join(db.list_templates(interaction.guild.id)) or "none yet — use /default-template first"
            await interaction.response.send_message(
                f"No template named `{template}` found. Available: {names}", ephemeral=True
            )
            return
        seconds = parse_duration(duration)
        if not seconds:
            await interaction.response.send_message(
                "Couldn't parse that duration. Try things like `1h`, `30m`, `2d`, `1d12h`.", ephemeral=True
            )
            return
        if winners < 1:
            await interaction.response.send_message("Number of winners must be at least 1.", ephemeral=True)
            return

        modal = GiveawayBodyModal(self, interaction.channel, tmpl, prize, winners, seconds)
        await interaction.response.send_modal(modal)

    @ga.autocomplete("template")
    async def ga_template_autocomplete(self, interaction: discord.Interaction, current: str):
        names = db.list_templates(interaction.guild.id)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    # ---------------- launch / end ----------------

    async def launch_giveaway(self, interaction: discord.Interaction, template: dict, giveaway: dict):
        guild = interaction.guild
        channel = interaction.channel

        giveaway_id = db.create_giveaway(
            guild_id=guild.id,
            channel_id=channel.id,
            template_id=template["id"],
            prize=giveaway["prize"],
            winner_count=giveaway["winner_count"],
            host_id=giveaway["host_id"],
            body_text=giveaway.get("body_text") or "",
            end_time=giveaway["end_time"],
        )
        row = db.get_giveaway(giveaway_id)

        embed = build_giveaway_embed(guild, row, template, status="running")
        view = GiveawayJoinView(self, giveaway_id, template["blacklisted_roles"], 0)

        msg = await channel.send(embed=embed, view=view)
        thread = None
        try:
            thread = await msg.create_thread(name=f"🎉 {giveaway['prize'][:80]}")
        except discord.HTTPException:
            pass

        db.set_giveaway_message(giveaway_id, msg.id, thread.id if thread else None)

        # Ping the server's configured giveaway-ping role (set via /giveaway-ping-role),
        # not the template's blacklisted/extra-entry roles.
        settings = db.get_guild_settings(guild.id)
        ping_role_id = settings.get("giveaway_ping_role_id")
        if ping_role_id:
            role = guild.get_role(ping_role_id)
            mention = role.mention if role else f"<@&{ping_role_id}>"
            await channel.send(
                f"{mention}\n🎁 A new giveaway just started: **{giveaway['prize']}**!",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

        if thread:
            host = guild.get_member(giveaway["host_id"])
            host_mention = host.mention if host else f"<@{giveaway['host_id']}>"
            await thread.send(
                f"🎉 Giveaway hosted by {host_mention} — good luck everyone!",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        await interaction.followup.send(f"✅ Giveaway posted in {channel.mention}!", ephemeral=True)

        self._schedule_end(giveaway_id, giveaway["end_time"])

    def _schedule_end(self, giveaway_id: int, end_time: float):
        delay = max(0, end_time - time.time())
        task = asyncio.create_task(self._end_after_delay(giveaway_id, delay))
        self.tasks[giveaway_id] = task

    async def _end_after_delay(self, giveaway_id: int, delay: float):
        await asyncio.sleep(delay)
        await self.end_giveaway(giveaway_id)

    async def end_giveaway(self, giveaway_id: int):
        g = db.get_giveaway(giveaway_id)
        if not g or g["status"] != "running":
            return
        guild = self.bot.get_guild(g["guild_id"])
        if not guild:
            return
        template = db.get_template(guild.id, self._template_name_by_id(g["template_id"]))
        if template is None:
            # Fall back to raw row if the name-based lookup path above fails.
            template = self._template_by_id(g["template_id"])

        entries = db.list_entries(giveaway_id)
        winners = self._pick_winners(guild, entries, template, g["winner_count"])

        db.update_giveaway(giveaway_id, status="ended")
        db.record_winners(giveaway_id, winners)

        channel = guild.get_channel(g["channel_id"])
        g["id"] = giveaway_id
        embed = build_giveaway_embed(guild, g, template, status="ended", winners=winners)

        try:
            msg = await channel.fetch_message(g["message_id"])
            await msg.edit(embed=embed, view=None)
        except (discord.NotFound, discord.HTTPException):
            pass

        content, announce_embed = build_ended_announcement(guild, g, winners)
        await channel.send(content, embed=announce_embed, allowed_mentions=discord.AllowedMentions(users=True))

        if g["thread_id"]:
            thread = guild.get_channel(g["thread_id"]) or guild.get_thread(g["thread_id"])
            if thread and winners:
                mentions = " ".join(f"<@{w}>" for w in winners)
                await thread.send(f"🎊 Congrats {mentions}! Winners were announced in {channel.mention}.")

        self.tasks.pop(giveaway_id, None)

    # ---------------- /giveaway-reroll ----------------

    @app_commands.command(name="giveaway-reroll", description="Reroll an ended giveaway's winner(s), excluding previous winners. One-time only.")
    @giveaway_host_check()
    async def giveaway_reroll(self, interaction: discord.Interaction, giveaway_id: int):
        g = db.get_giveaway(giveaway_id)
        if not g or g["guild_id"] != interaction.guild.id:
            await interaction.response.send_message(f"No giveaway found with ID `{giveaway_id}` in this server.", ephemeral=True)
            return
        if g["status"] != "ended":
            await interaction.response.send_message("That giveaway hasn't ended yet.", ephemeral=True)
            return
        if g["rerolled"]:
            await interaction.response.send_message("That giveaway has already been rerolled once.", ephemeral=True)
            return

        template = self._template_by_id(g["template_id"])
        previous_winners = set(db.get_winners(giveaway_id))
        entries = [uid for uid in db.list_entries(giveaway_id) if uid not in previous_winners]

        new_winners = self._pick_winners(interaction.guild, entries, template, g["winner_count"])
        if not new_winners:
            await interaction.response.send_message(
                "No eligible entrants left to reroll (everyone who entered already won).", ephemeral=True
            )
            return

        db.mark_rerolled(giveaway_id)
        db.record_winners(giveaway_id, new_winners)

        channel = interaction.guild.get_channel(g["channel_id"])
        all_winners = list(previous_winners) + new_winners
        embed = build_giveaway_embed(interaction.guild, g, template, status="ended", winners=all_winners)
        try:
            msg = await channel.fetch_message(g["message_id"])
            await msg.edit(embed=embed, view=None)
        except (discord.NotFound, discord.HTTPException):
            pass

        content, announce_embed = build_ended_announcement(interaction.guild, g, new_winners, rerolled=True)
        await interaction.response.send_message("✅ Rerolled.", ephemeral=True)
        await channel.send(content, embed=announce_embed, allowed_mentions=discord.AllowedMentions(users=True))

    def _template_by_id(self, template_id: int) -> dict:
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM giveaway_templates WHERE id = ?", (template_id,)).fetchone()
        d = dict(row)
        import json as _json
        d["blacklisted_roles"] = _json.loads(d["blacklisted_roles"])
        d["extra_entry_roles"] = _json.loads(d["extra_entry_roles"])
        return d

    def _template_name_by_id(self, template_id: int) -> str:
        with db.get_conn() as conn:
            row = conn.execute("SELECT name, guild_id FROM giveaway_templates WHERE id = ?", (template_id,)).fetchone()
        return row["name"] if row else None

    def _pick_winners(self, guild: discord.Guild, entries: list[int], template: dict, winner_count: int) -> list[int]:
        if not entries:
            return []
        extra_role_ids = set(template["extra_entry_roles"])
        weighted = []
        for user_id in entries:
            member = guild.get_member(user_id)
            tickets = 1
            if member and extra_role_ids:
                member_role_ids = {r.id for r in member.roles}
                tickets += len(member_role_ids & extra_role_ids)
            weighted.extend([user_id] * tickets)

        winners = []
        pool = list(weighted)
        seen = set()
        random.shuffle(pool)
        for user_id in pool:
            if user_id not in seen:
                seen.add(user_id)
                winners.append(user_id)
            if len(winners) >= winner_count:
                break
        return winners

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            log_app_command_error("Giveaway", interaction, error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


class TemplateModal(discord.ui.Modal, title="Giveaway Template"):
    def __init__(self, guild_id: int, name: str):
        super().__init__()
        self.guild_id = guild_id
        self.name = name
        self.top_message = discord.ui.TextInput(label="Top Message", max_length=100, placeholder="GENERAL GIVEAWAY")
        self.icon_url = discord.ui.TextInput(label="Icon URL (top-right image)", required=False, max_length=300)
        self.blacklisted = discord.ui.TextInput(
            label="Blacklisted Roles (mentions/IDs, comma sep.)", required=False, style=discord.TextStyle.paragraph
        )
        self.extra_entries = discord.ui.TextInput(
            label="Extra Entry Roles (mentions/IDs, comma sep.)", required=False, style=discord.TextStyle.paragraph
        )
        self.add_item(self.top_message)
        self.add_item(self.icon_url)
        self.add_item(self.blacklisted)
        self.add_item(self.extra_entries)

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.giveaway_cog import parse_role_list  # local import avoids circularity at module load
        blacklisted_ids = parse_role_list(interaction.guild, self.blacklisted.value)
        extra_ids = parse_role_list(interaction.guild, self.extra_entries.value)
        db.create_template(
            self.guild_id, self.name, self.top_message.value.strip(),
            self.icon_url.value.strip() or None, blacklisted_ids, extra_ids,
        )
        await interaction.response.send_message(f"✅ Template **{self.name}** saved.", ephemeral=True)


class GiveawayBodyModal(discord.ui.Modal, title="Giveaway Message"):
    def __init__(self, cog: GiveawayCog, channel, template: dict, prize: str, winners: int, seconds: int):
        super().__init__()
        self.cog = cog
        self.channel = channel
        self.template = template
        self.prize = prize
        self.winners = winners
        self.seconds = seconds
        self.body_text = discord.ui.TextInput(
            label="Giveaway message (shown in the embed)", style=discord.TextStyle.paragraph,
            required=False, max_length=1000,
            placeholder="e.g. decided to stop waiting for kingdom anime and started manga...",
        )
        self.add_item(self.body_text)

    async def on_submit(self, interaction: discord.Interaction):
        giveaway = {
            "prize": self.prize,
            "winner_count": self.winners,
            "host_id": interaction.user.id,
            "body_text": self.body_text.value.strip(),
            "end_time": time.time() + self.seconds,
        }
        view = GiveawayPreviewView(self.cog, interaction.guild, self.template, giveaway)
        await interaction.response.send_message(embed=view.build_preview_embed(), view=view)


async def setup(bot: commands.Bot):
    cog = GiveawayCog(bot)
    await bot.add_cog(cog)
