import asyncio
import random
import re
import time

import discord
from discord.ext import commands
from discord import app_commands

import config
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


def parse_role_weight_list(guild: discord.Guild, text: str) -> dict[str, int]:
    """Parses entries like '<@&123>:2, <@&456>' into {role_id_str: weight}.
    A missing ':weight' defaults to 1. Keys are strings so this matches the JSON
    shape stored in the database (JSON object keys are always strings)."""
    if not text:
        return {}
    result = {}
    for chunk in re.split(r"[,\n]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        weight = 1
        if ":" in chunk:
            role_part, weight_part = chunk.rsplit(":", 1)
            role_part = role_part.strip()
            weight_part = weight_part.strip()
            if weight_part.isdigit():
                weight = max(1, int(weight_part))
                chunk = role_part
        m = re.match(r"<@&(\d+)>", chunk)
        if m:
            result[m.group(1)] = weight
            continue
        if chunk.isdigit():
            result[chunk] = weight
            continue
        role = discord.utils.get(guild.roles, name=chunk)
        if role:
            result[str(role.id)] = weight
    return result


def build_giveaway_embed(guild: discord.Guild, giveaway: dict, template: dict, status: str, winners: list[int] | None = None) -> discord.Embed:
    color = discord.Color(config.EMBED_COLOR_HEX)
    top_message = template["top_message"] or "GIVEAWAY"
    title = f":party: {top_message}" if status == "running" else f"Giveaway — {status.title()}"
    embed = discord.Embed(title=db.apply_emoji_shortcuts(title), color=color)

    host = guild.get_member(giveaway["host_id"])
    host_mention = host.mention if host else f"<@{giveaway['host_id']}>"

    # Built as separate blocks joined with blank lines in between, so the embed
    # has real breathing room instead of everything crammed together. Icon tokens
    # (:name:) are resolved to the bot's own uploaded emojis in one pass at the end.
    blocks = []

    blocks.append(f":prize: **Prize:** {giveaway['prize']}")
    blocks.append(f":winner: **Number of Winners:** {giveaway['winner_count']}")
    blocks.append(f":pray: **Hosted By:** {host_mention}")

    if giveaway.get("body_text"):
        blocks.append(giveaway["body_text"])

    if status == "running":
        end_ts = int(giveaway["end_time"])
        blocks.append(f":hourglass: **Ends:** <t:{end_ts}:R>")
    else:
        blocks.append(":hourglass: **Ended**")

    if template["blacklisted_roles"]:
        names = []
        for rid in template["blacklisted_roles"]:
            role = guild.get_role(rid)
            names.append(role.mention if role else f"<@&{rid}>")
        blocks.append(":blacklist: **Blacklisted Roles:**\n" + "\n".join(names))

    if template.get("required_roles"):
        names = []
        for rid in template["required_roles"]:
            role = guild.get_role(rid)
            names.append(role.mention if role else f"<@&{rid}>")
        blocks.append(":musthave: **Required Roles:**\n" + "\n".join(names))

    if template["extra_entry_roles"]:
        names = []
        for rid_str, weight in template["extra_entry_roles"].items():
            rid = int(rid_str)
            role = guild.get_role(rid)
            names.append((role.mention if role else f"<@&{rid}>") + f" +{weight}")
        blocks.append(":extraentries: **Extra Entries:**\n" + "\n".join(names))

    if template.get("bypass_roles"):
        names = []
        for rid in template["bypass_roles"]:
            role = guild.get_role(rid)
            names.append(role.mention if role else f"<@&{rid}>")
        blocks.append(":bypass2: **Bypass Roles:**\n" + "\n".join(names))

    if winners is not None:
        if winners:
            blocks.append(":winner: **Winners:** " + " ".join(f"<@{w}>" for w in winners))
        else:
            blocks.append(":winner: **Winners:** No valid entries — no winner could be chosen.")

    embed.description = db.apply_emoji_shortcuts("\n\n".join(blocks))

    if template.get("icon_url"):
        embed.set_thumbnail(url=template["icon_url"])

    if giveaway.get("id"):
        embed.set_footer(text=f"Giveaway ID: {giveaway['id']}")

    return embed


def build_ended_announcement(guild: discord.Guild, giveaway: dict, winners: list[int], rerolled: bool = False) -> tuple[str, discord.Embed]:
    """Builds the 'Giveaway Ended!' congrats message + embed shown in the channel."""
    host = guild.get_member(giveaway["host_id"])
    host_mention = host.mention if host else f"<@{giveaway['host_id']}>"

    verb = "rerolled" if rerolled else "ended"
    if winners:
        mentions = ", ".join(f"<@{w}>" for w in winners)
        content = db.apply_emoji_shortcuts(f":congrats: Congratulations {mentions} for winning {host_mention}'s giveaway!")
        winners_block = ":winner: **Winners:** " + " ".join(f"<@{w}>" for w in winners)
    else:
        content = f"😔 {host_mention}'s giveaway ended with no eligible winner."
        winners_block = ":winner: **Winners:** No valid entries."

    top_block = ""
    if giveaway.get("body_text"):
        top_block += giveaway["body_text"] + "\n"
    top_block += f":prize: **Prize:** {giveaway['prize']}"

    blocks = [top_block, winners_block, f"Giveaway ID: {giveaway['id']}"]

    embed = discord.Embed(
        title=db.apply_emoji_shortcuts(f":congrats: Giveaway {verb}!"),
        description=db.apply_emoji_shortcuts("\n\n".join(blocks)),
        color=discord.Color(config.EMBED_COLOR_HEX),
    )
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

    def __init__(self, cog: "GiveawayCog", guild: discord.Guild, template: dict, giveaway: dict, target_channel: discord.TextChannel):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.template = template
        self.giveaway = giveaway
        self.target_channel = target_channel
        self.giveaway["_created_at"] = time.time()
        self.edit_button.emoji = db.get_emoji_mention("edit") or "✏️"
        self.start_button.emoji = db.get_emoji_mention("start") or "🚀"
        self.cancel_button.emoji = db.get_emoji_mention("cancel") or "🗑️"

    def build_preview_embed(self) -> discord.Embed:
        fake = dict(self.giveaway)
        fake["host_id"] = self.giveaway["host_id"]
        embed = build_giveaway_embed(self.guild, fake, self.template, status="running")
        embed.set_footer(text=f"Preview — will post in #{self.target_channel.name} when started.")
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
        await self.cog.launch_giveaway(interaction, self.template, self.giveaway, self.target_channel)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.giveaway["host_id"]:
            await interaction.response.send_message("Only the host can cancel this giveaway.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Giveaway cancelled — not posted.", embed=None, view=self)


class GiveawayJoinView(discord.ui.View):
    """Persistent view attached to a live giveaway message. custom_id is namespaced
    per giveaway so multiple concurrent giveaways (and restarts) don't collide."""

    def __init__(
        self, cog: "GiveawayCog", giveaway_id: int, blacklisted_roles: list[int],
        entry_count: int, required_roles: list[int] = None, bypass_roles: list[int] = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id
        self.blacklisted_roles = set(blacklisted_roles)
        self.required_roles = set(required_roles or [])
        self.bypass_roles = set(bypass_roles or [])
        self.join_button.custom_id = f"giveaway_join_{giveaway_id}"
        self.join_button.emoji = db.get_emoji_mention("party") or "🎉"
        self.join_button.label = str(entry_count)

    @discord.ui.button(label="0", style=discord.ButtonStyle.blurple, custom_id="giveaway_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_role_ids = {r.id for r in interaction.user.roles} if hasattr(interaction.user, "roles") else set()

        if not (user_role_ids & self.bypass_roles):
            if user_role_ids & self.blacklisted_roles:
                await interaction.response.send_message("🚫 You're not eligible to enter this giveaway.", ephemeral=True)
                return
            if self.required_roles and not (user_role_ids & self.required_roles):
                await interaction.response.send_message(
                    "🔒 You need one of the required roles to enter this giveaway.", ephemeral=True
                )
                return

        if db.has_entry(self.giveaway_id, interaction.user.id):
            db.remove_entry(self.giveaway_id, interaction.user.id)
            joined = False
        else:
            db.add_entry(self.giveaway_id, interaction.user.id)
            joined = True

        count = db.count_entries(self.giveaway_id)
        button.label = str(count)
        await interaction.response.edit_message(view=self)
        msg = "✅ You joined the giveaway! Good luck." if joined else "You left the giveaway."
        await interaction.followup.send(msg, ephemeral=True)


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        # Reschedule any giveaways that were still running when the bot restarted,
        # and re-attach their join-button views (otherwise clicking them after a
        # restart would silently fail).
        for g in db.get_running_giveaways():
            self._schedule_end(g["id"], g["end_time"])
            if not g.get("message_id"):
                continue
            try:
                template = self._template_by_id(g["template_id"])
                count = db.count_entries(g["id"])
                view = GiveawayJoinView(self, g["id"], template["blacklisted_roles"], count, template.get("required_roles"), template.get("bypass_roles"))
                self.bot.add_view(view, message_id=g["message_id"])
            except Exception as e:
                print(f"[Giveaway] couldn't re-attach view for giveaway {g['id']}: {e}")

    # ---------------- /default-template ----------------

    @app_commands.command(name="default-template", description="Create, or edit an existing, giveaway template.")
    @event_admin_check()
    async def default_template(self, interaction: discord.Interaction, name: str):
        existing = db.get_template(interaction.guild.id, name)
        modal = TemplateModal(interaction.guild.id, name, existing)
        await interaction.response.send_modal(modal)

    # ---------------- /ga ----------------

    @app_commands.command(name="ga", description="Create a giveaway from a saved template.")
    @app_commands.describe(channel="Channel to post the giveaway in")
    @giveaway_host_check()
    async def ga(self, interaction: discord.Interaction, template: str, prize: str, winners: int, duration: str, channel: discord.TextChannel = None):
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

        target_channel = channel or interaction.channel
        giveaway = {
            "prize": prize,
            "winner_count": winners,
            "host_id": interaction.user.id,
            "body_text": "",
            "end_time": time.time() + seconds,
        }
        view = GiveawayPreviewView(self, interaction.guild, tmpl, giveaway, target_channel)
        await interaction.response.send_message(embed=view.build_preview_embed(), view=view)

    @ga.autocomplete("template")
    async def ga_template_autocomplete(self, interaction: discord.Interaction, current: str):
        names = db.list_templates(interaction.guild.id)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    # ---------------- launch / end ----------------

    async def launch_giveaway(self, interaction: discord.Interaction, template: dict, giveaway: dict, target_channel: discord.TextChannel):
        guild = interaction.guild
        channel = target_channel

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
        view = GiveawayJoinView(self, giveaway_id, template["blacklisted_roles"], 0, template.get("required_roles"), template.get("bypass_roles"))

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
                db.apply_emoji_shortcuts(f":party: A new giveaway just started: **{giveaway['prize']}**!\n{mention}"),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )

        if thread:
            host = guild.get_member(giveaway["host_id"])
            host_mention = host.mention if host else f"<@{giveaway['host_id']}>"
            await thread.send(
                db.apply_emoji_shortcuts(f":party: Giveaway hosted by {host_mention} — good luck everyone!"),
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
                await thread.send(db.apply_emoji_shortcuts(f":hype: Congrats {mentions}! Winners were announced in {channel.mention}."))

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

    # ---------------- participant management (admin only) ----------------

    @app_commands.command(name="giveaway-participants", description="ADMIN: View who has entered a giveaway.")
    @app_commands.describe(giveaway_id="The giveaway's ID, shown in its embed footer")
    @event_admin_check()
    async def giveaway_participants(self, interaction: discord.Interaction, giveaway_id: int):
        g = db.get_giveaway(giveaway_id)
        if not g or g["guild_id"] != interaction.guild.id:
            await interaction.response.send_message(f"No giveaway found with ID `{giveaway_id}` in this server.", ephemeral=True)
            return

        entries = db.list_entries(giveaway_id)
        if not entries:
            await interaction.response.send_message(f"No participants in giveaway **#{giveaway_id}** yet.", ephemeral=True)
            return

        lines = [f"<@{uid}>" for uid in entries]
        header = f"**Participants for giveaway #{giveaway_id}** ({len(entries)} total):\n"
        body = "\n".join(lines)
        if len(header) + len(body) > 1900:
            # Trim to fit one message rather than crash on Discord's 2000-char cap.
            keep = []
            total = len(header)
            for line in lines:
                if total + len(line) + 1 > 1880:
                    break
                keep.append(line)
                total += len(line) + 1
            body = "\n".join(keep) + f"\n… and {len(entries) - len(keep)} more"

        await interaction.response.send_message(
            header + body, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @app_commands.command(name="giveaway-remove-participant", description="ADMIN: Remove a participant from a giveaway.")
    @app_commands.describe(giveaway_id="The giveaway's ID, shown in its embed footer", user="The participant to remove")
    @event_admin_check()
    async def giveaway_remove_participant(self, interaction: discord.Interaction, giveaway_id: int, user: discord.Member):
        g = db.get_giveaway(giveaway_id)
        if not g or g["guild_id"] != interaction.guild.id:
            await interaction.response.send_message(f"No giveaway found with ID `{giveaway_id}` in this server.", ephemeral=True)
            return
        if not db.has_entry(giveaway_id, user.id):
            await interaction.response.send_message(f"{user.mention} isn't entered in giveaway **#{giveaway_id}**.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return

        db.remove_entry(giveaway_id, user.id)
        count = db.count_entries(giveaway_id)

        # Keep the live join button's count in sync if the giveaway is still running.
        if g["status"] == "running" and g.get("message_id"):
            try:
                channel = interaction.guild.get_channel(g["channel_id"])
                msg = await channel.fetch_message(g["message_id"])
                template = self._template_by_id(g["template_id"])
                view = GiveawayJoinView(self, giveaway_id, template["blacklisted_roles"], count, template.get("required_roles"), template.get("bypass_roles"))
                await msg.edit(view=view)
            except (discord.NotFound, discord.HTTPException, AttributeError):
                pass

        await interaction.response.send_message(
            f"✅ Removed {user.mention} from giveaway **#{giveaway_id}**. Now **{count}** participant(s).",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    def _template_by_id(self, template_id: int) -> dict:
        return db.get_template_by_id(template_id)

    def _template_name_by_id(self, template_id: int) -> str:
        with db.get_conn() as conn:
            row = conn.execute("SELECT name, guild_id FROM giveaway_templates WHERE id = ?", (template_id,)).fetchone()
        return row["name"] if row else None

    def _pick_winners(self, guild: discord.Guild, entries: list[int], template: dict, winner_count: int) -> list[int]:
        if not entries:
            return []
        extra_weights = {int(k): v for k, v in (template.get("extra_entry_roles") or {}).items()}
        weighted = []
        for user_id in entries:
            member = guild.get_member(user_id)
            tickets = 1
            if member and extra_weights:
                member_role_ids = {r.id for r in member.roles}
                for rid, weight in extra_weights.items():
                    if rid in member_role_ids:
                        tickets += weight
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


def _role_weights_to_text(weights: dict | None) -> str:
    return ", ".join(f"<@&{rid}>:{w}" for rid, w in (weights or {}).items())


def _roles_to_text(ids: list[int]) -> str:
    return ", ".join(f"<@&{rid}>" for rid in (ids or []))


class TemplateModal(discord.ui.Modal, title="Giveaway Template (1/2)"):
    """First of two chained modals (Discord caps modals at 5 fields each)."""

    def __init__(self, guild_id: int, name: str, existing: dict | None = None):
        super().__init__()
        self.guild_id = guild_id
        self.name = name
        existing = existing or {}
        self.top_message = discord.ui.TextInput(
            label="Top Message", max_length=100, placeholder="GENERAL GIVEAWAY",
            default=existing.get("top_message") or "",
        )
        self.icon_url = discord.ui.TextInput(
            label="Icon URL (top-right image)", required=False, max_length=300,
            default=existing.get("icon_url") or "",
        )
        self.blacklisted = discord.ui.TextInput(
            label="Blacklisted Roles (mentions/IDs, comma sep.)", required=False, style=discord.TextStyle.paragraph,
            default=_roles_to_text(existing.get("blacklisted_roles")),
        )
        self.required = discord.ui.TextInput(
            label="Must-Have Roles (mentions/IDs, comma sep.)", required=False, style=discord.TextStyle.paragraph,
            default=_roles_to_text(existing.get("required_roles")),
        )
        self.add_item(self.top_message)
        self.add_item(self.icon_url)
        self.add_item(self.blacklisted)
        self.add_item(self.required)

    async def on_submit(self, interaction: discord.Interaction):
        existing = db.get_template(self.guild_id, self.name) or {}
        modal2 = TemplateModal2(
            self.guild_id, self.name,
            top_message=self.top_message.value.strip(),
            icon_url=self.icon_url.value.strip() or None,
            blacklisted_text=self.blacklisted.value,
            required_text=self.required.value,
            existing=existing,
        )
        # Chaining a modal directly from another modal's on_submit is unreliable on
        # some discord.py/API combinations (fails with a cryptic "Invalid Form Body"
        # error). Routing the second modal through a button click instead avoids that.
        await interaction.response.send_message(
            "Step 1 saved. Click below to continue with extra-entry and bypass roles.",
            view=ContinueToStep2View(modal2), ephemeral=True,
        )


class ContinueToStep2View(discord.ui.View):
    def __init__(self, modal2: "TemplateModal2"):
        super().__init__(timeout=300)
        self.modal2 = modal2

    @discord.ui.button(label="Continue (Step 2/2)", style=discord.ButtonStyle.primary, emoji="➡️")
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.send_modal(self.modal2)
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass


class TemplateModal2(discord.ui.Modal, title="Giveaway Template (2/2)"):
    """Second modal: extra-entry and bypass roles, then actually saves the template."""

    def __init__(self, guild_id: int, name: str, top_message: str, icon_url: str | None,
                 blacklisted_text: str, required_text: str, existing: dict):
        super().__init__()
        self.guild_id = guild_id
        self.name = name
        self.top_message_value = top_message
        self.icon_url_value = icon_url
        self.blacklisted_text = blacklisted_text
        self.required_text = required_text
        self.extra_entries = discord.ui.TextInput(
            label="Extra Entry Roles (role:extra, e.g. @VIP:3)", required=False, style=discord.TextStyle.paragraph,
            placeholder="@Booster:3, @Donator:2, @Member (no number = +1)",
            default=_role_weights_to_text(existing.get("extra_entry_roles")),
        )
        self.bypass = discord.ui.TextInput(
            label="Requirements Bypass Roles (comma sep.)", required=False, style=discord.TextStyle.paragraph,
            default=_roles_to_text(existing.get("bypass_roles")),
        )
        self.add_item(self.extra_entries)
        self.add_item(self.bypass)

    async def on_submit(self, interaction: discord.Interaction):
        blacklisted_ids = parse_role_list(interaction.guild, self.blacklisted_text)
        required_ids = parse_role_list(interaction.guild, self.required_text)
        extra_ids = parse_role_weight_list(interaction.guild, self.extra_entries.value)
        bypass_ids = parse_role_list(interaction.guild, self.bypass.value)
        db.create_template(
            self.guild_id, self.name, self.top_message_value, self.icon_url_value,
            blacklisted_ids, extra_ids, required_ids, bypass_ids,
        )
        await interaction.response.send_message(f"✅ Template **{self.name}** saved.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = GiveawayCog(bot)
    await bot.add_cog(cog)
