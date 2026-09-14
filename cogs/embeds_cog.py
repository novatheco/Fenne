import discord
from discord.ext import commands
from discord import app_commands

import config
import database as db
from cogs.permissions import event_admin_check

BUTTON_STYLES = {
    "blurple": discord.ButtonStyle.blurple,
    "grey": discord.ButtonStyle.grey,
    "gray": discord.ButtonStyle.grey,
    "green": discord.ButtonStyle.green,
    "red": discord.ButtonStyle.red,
}


def parse_color(text: str | None) -> discord.Color:
    if not text:
        return discord.Color(int(config.DEFAULT_COLOR, 16))
    text = text.strip().lstrip("#")
    try:
        return discord.Color(int(text, 16))
    except ValueError:
        return discord.Color(int(config.DEFAULT_COLOR, 16))


def build_button_embed(button_row: dict) -> discord.Embed:
    embed = discord.Embed(
        title=button_row.get("embed_title") or None,
        description=button_row.get("embed_description") or None,
        color=parse_color(button_row.get("embed_color")),
    )
    if button_row.get("embed_image"):
        embed.set_image(url=button_row["embed_image"])
    return embed


class PanelView(discord.ui.View):
    """Persistent view: one button per row in embed_buttons for a panel."""

    def __init__(self, panel_id: int, buttons: list[dict]):
        super().__init__(timeout=None)
        for b in buttons:
            style = BUTTON_STYLES.get(b["style"], discord.ButtonStyle.blurple)
            item = discord.ui.Button(
                label=b["label"], style=style, custom_id=f"panelbtn_{b['id']}"
            )
            item.callback = self._make_callback(b["id"])
            self.add_item(item)

    def _make_callback(self, button_id: int):
        async def callback(interaction: discord.Interaction):
            row = db.get_button(button_id)
            if not row:
                await interaction.response.send_message("This button's content is missing.", ephemeral=True)
                return
            await interaction.response.send_message(embed=build_button_embed(row), ephemeral=True)
        return callback


class EmbedsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Re-attach persistent views for existing panels so buttons keep working after a restart.
        with db.get_conn() as conn:
            rows = conn.execute("SELECT id FROM embed_panels WHERE message_id IS NOT NULL").fetchall()
        for row in rows:
            buttons = db.get_buttons(row["id"])
            if buttons:
                self.bot.add_view(PanelView(row["id"], buttons))

    group = app_commands.Group(name="create-embed", description="Build multi-button info panels (perks, server info, etc.)")

    @group.command(name="panel", description="Create or update a panel (the intro message that buttons attach to).")
    @event_admin_check()
    async def panel(self, interaction: discord.Interaction, name: str):
        await interaction.response.send_modal(PanelModal(name))

    @group.command(name="button", description="Add a button + embed to an existing panel.")
    @event_admin_check()
    async def button(self, interaction: discord.Interaction, panel: str, label: str, style: str = "blurple"):
        panel_row = db.get_panel(interaction.guild.id, panel)
        if not panel_row:
            names = ", ".join(db.list_panels(interaction.guild.id)) or "none yet — use /create-embed panel first"
            await interaction.response.send_message(f"No panel named `{panel}` found. Available: {names}", ephemeral=True)
            return
        style_key = style.lower().strip()
        if style_key not in BUTTON_STYLES:
            await interaction.response.send_message(
                f"Unknown style `{style}`. Choose one of: {', '.join(BUTTON_STYLES)}.", ephemeral=True
            )
            return
        await interaction.response.send_modal(ButtonModal(self, panel_row, label, style_key))

    @group.command(name="post", description="Post (or repost) a panel with its current buttons in this channel.")
    @event_admin_check()
    async def post(self, interaction: discord.Interaction, panel: str):
        panel_row = db.get_panel(interaction.guild.id, panel)
        if not panel_row:
            names = ", ".join(db.list_panels(interaction.guild.id)) or "none yet — use /create-embed panel first"
            await interaction.response.send_message(f"No panel named `{panel}` found. Available: {names}", ephemeral=True)
            return

        buttons = db.get_buttons(panel_row["id"])
        embed = discord.Embed(
            title=panel_row["name"],
            description=panel_row.get("intro_text") or None,
            color=parse_color(config.DEFAULT_COLOR),
        )
        if panel_row.get("icon_url"):
            embed.set_thumbnail(url=panel_row["icon_url"])

        view = PanelView(panel_row["id"], buttons) if buttons else None
        if view:
            self.bot.add_view(view)

        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        db.set_panel_message(panel_row["id"], interaction.channel.id, msg.id)

    @button.autocomplete("panel")
    @post.autocomplete("panel")
    async def panel_autocomplete(self, interaction: discord.Interaction, current: str):
        names = db.list_panels(interaction.guild.id)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = str(error) if isinstance(error, app_commands.CheckFailure) else "An unexpected error occurred."
        if not isinstance(error, app_commands.CheckFailure):
            print(f"Embeds cog error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


class PanelModal(discord.ui.Modal, title="Embed Panel"):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.intro_text = discord.ui.TextInput(
            label="Intro text", style=discord.TextStyle.paragraph, required=False, max_length=1000
        )
        self.icon_url = discord.ui.TextInput(label="Icon URL (thumbnail)", required=False, max_length=300)
        self.add_item(self.intro_text)
        self.add_item(self.icon_url)

    async def on_submit(self, interaction: discord.Interaction):
        db.create_panel(interaction.guild.id, self.name, self.intro_text.value.strip(), self.icon_url.value.strip() or None)
        await interaction.response.send_message(
            f"✅ Panel **{self.name}** saved. Use `/create-embed button` to add buttons, then `/create-embed post` to publish it.",
            ephemeral=True,
        )


class ButtonModal(discord.ui.Modal, title="Button Embed Content"):
    def __init__(self, cog: EmbedsCog, panel_row: dict, label: str, style: str):
        super().__init__()
        self.cog = cog
        self.panel_row = panel_row
        self.label = label
        self.style = style
        self.embed_title = discord.ui.TextInput(label="Embed Title", required=False, max_length=200)
        self.embed_description = discord.ui.TextInput(
            label="Embed Description", style=discord.TextStyle.paragraph, required=False, max_length=2000
        )
        self.embed_color = discord.ui.TextInput(label="Color (hex, no #)", required=False, max_length=6, placeholder="5865f2")
        self.embed_image = discord.ui.TextInput(label="Image URL", required=False, max_length=300)
        self.add_item(self.embed_title)
        self.add_item(self.embed_description)
        self.add_item(self.embed_color)
        self.add_item(self.embed_image)

    async def on_submit(self, interaction: discord.Interaction):
        db.add_button(
            self.panel_row["id"], self.label, self.style,
            self.embed_title.value.strip() or None, self.embed_description.value.strip() or None,
            self.embed_color.value.strip() or None, self.embed_image.value.strip() or None,
        )
        await interaction.response.send_message(
            f"✅ Added button **{self.label}** to panel **{self.panel_row['name']}**. "
            f"Run `/create-embed post panel:{self.panel_row['name']}` to (re)publish it with this button.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedsCog(bot))
