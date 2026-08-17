"""Interactive Components V2 embed builder used by ``/embed`` and ``/editembed``.

The builder is an ephemeral dashboard where every embed section (title,
description, author, webhook identity, link button, ...) has an Edit button
on its right that opens a modal. **Save** posts the finished embed through a
webhook with the chosen identity; **Cancel** discards everything.
"""

import functools
import re
from typing import Any, Optional

import discord  # type: ignore[import-not-found]

from utils.helpers import sanitize_mentions

EMBED_BUILDER_COLOR = 0x5865F2


class EmbedSectionModal(discord.ui.Modal):
    """Small modal that edits a single section of the embed builder."""

    def __init__(
        self,
        builder: "EmbedBuilderDashboard",
        section: str,
        title: str,
        fields: list[tuple[str, dict[str, Any]]],
    ):
        super().__init__(title=title, timeout=300)
        self.builder = builder
        self.section = section
        self.inputs: list[tuple[str, discord.ui.TextInput]] = []
        for key, kwargs in fields:
            text_input = discord.ui.TextInput(**kwargs)
            self.inputs.append((key, text_input))
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.builder.user_id:
            await interaction.response.send_message(
                "This embed builder is not for you.", ephemeral=True
            )
            return
        values: dict[str, Optional[str]] = {}
        for key, text_input in self.inputs:
            value = text_input.value
            values[key] = value.strip() if value else None
        await self.builder.apply_section(interaction, self.section, values)


class EmbedBuilderDashboard(discord.ui.LayoutView):
    """Ephemeral Components V2 dashboard used to build or edit an embed.

    ``mode="create"`` sends a brand new embed to the target channel on Save;
    ``mode="edit"`` edits the original message in place instead.
    """

    # section -> (display label, modal title, [(data_key, TextInput kwargs), ...])
    # Sections with several inputs (media, webhook, button) still get a single
    # Edit button; the modal just collects all of their fields at once.
    SECTIONS: dict[str, tuple[str, str, list[tuple[str, dict[str, Any]]]]] = {
        "title": (
            "Title",
            "Edit Title",
            [
                (
                    "title",
                    {
                        "label": "Embed Title",
                        "placeholder": "Optional title for the embed...",
                        "required": False,
                        "max_length": 256,
                    },
                )
            ],
        ),
        "description": (
            "Description",
            "Edit Description",
            [
                (
                    "description",
                    {
                        "label": "Description",
                        "placeholder": "Main content of the embed...",
                        "style": discord.TextStyle.paragraph,
                        "required": True,
                        "max_length": 4000,
                    },
                )
            ],
        ),
        "color": (
            "Color",
            "Edit Color",
            [
                (
                    "color",
                    {
                        "label": "Color",
                        "placeholder": "red, blue, green, gold, purple, orange, teal, #FF0000",
                        "required": False,
                        "max_length": 50,
                    },
                )
            ],
        ),
        "footer": (
            "Footer",
            "Edit Footer",
            [
                (
                    "footer",
                    {
                        "label": "Footer Text",
                        "placeholder": "Small text at the bottom of the embed...",
                        "required": False,
                        "max_length": 2048,
                    },
                )
            ],
        ),
        "premessage": (
            "Pre-Message",
            "Edit Pre-Message",
            [
                (
                    "premessage",
                    {
                        "label": "Pre-Message",
                        "placeholder": "Plain text before the embed (can @mention people or roles)...",
                        "style": discord.TextStyle.paragraph,
                        "required": False,
                        "max_length": 2000,
                    },
                )
            ],
        ),
        "author": (
            "Author",
            "Edit Author",
            [
                (
                    "author_id",
                    {
                        "label": "User ID",
                        "placeholder": "Paste a user ID - their name & avatar are used automatically",
                        "required": False,
                        "max_length": 30,
                    },
                )
            ],
        ),
        "media": (
            "Media",
            "Edit Media",
            [
                (
                    "image_url",
                    {
                        "label": "Image URL",
                        "placeholder": "https://... (large image at the bottom)",
                        "required": False,
                        "max_length": 1024,
                    },
                ),
                (
                    "thumbnail_url",
                    {
                        "label": "Thumbnail URL",
                        "placeholder": "https://... (small image at the top right)",
                        "required": False,
                        "max_length": 1024,
                    },
                ),
            ],
        ),
        "webhook": (
            "Webhook",
            "Edit Webhook",
            [
                (
                    "webhook_name",
                    {
                        "label": "Webhook Name",
                        "placeholder": "Name the embed appears to be sent by",
                        "required": False,
                        "max_length": 80,
                    },
                ),
                (
                    "webhook_avatar",
                    {
                        "label": "Avatar URL",
                        "placeholder": "https://... profile picture for the webhook",
                        "required": False,
                        "max_length": 1024,
                    },
                ),
            ],
        ),
        "button": (
            "Link Button",
            "Edit Link Button",
            [
                (
                    "button_label",
                    {
                        "label": "Button Label",
                        "placeholder": "Text shown on the button (e.g. Read More)",
                        "required": False,
                        "max_length": 80,
                    },
                ),
                (
                    "button_url",
                    {
                        "label": "Button Link URL",
                        "placeholder": "https://... opened when the button is clicked",
                        "required": False,
                        "max_length": 1024,
                    },
                ),
            ],
        ),
        "channel": (
            "Target Channel",
            "Edit Target Channel",
            [
                (
                    "channel_id",
                    {
                        "label": "Channel",
                        "placeholder": "Channel ID or #mention (default: current channel)",
                        "required": False,
                        "max_length": 100,
                    },
                )
            ],
        ),
    }

    def __init__(
        self,
        cog,
        *,
        user_id: int,
        channel_id: Optional[int] = None,
        mode: str = "create",
        edit_target: Optional[tuple[int, int, Any]] = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.mode = mode
        # edit_target: (channel_id, message_id, webhook_or_None) when editing
        self.edit_target = edit_target
        self.done = False
        self.data: dict[str, Any] = {
            "title": None,
            "description": None,
            "color": None,
            "footer": None,
            "premessage": None,
            "author_id": None,
            "author_name": None,
            "author_icon": None,
            "image_url": None,
            "thumbnail_url": None,
            "webhook_name": None,
            "webhook_avatar": None,
            "button_label": None,
            "button_url": None,
            "channel_id": str(channel_id) if channel_id else None,
        }
        self._render()

    # ------------------------------------------------------------------ render

    def _render(self) -> None:
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Color(EMBED_BUILDER_COLOR)
        )
        container.add_item(
            discord.ui.TextDisplay(
                "## Embed Builder\n"
                "Use the buttons to edit each section, then "
                "**Save & Send** or **Cancel**."
            )
        )
        container.add_item(discord.ui.Separator())

        for section, (label, _modal_title, _fields) in self.SECTIONS.items():
            edit_button = discord.ui.Button(
                label="Edit",
                style=discord.ButtonStyle.secondary,
                custom_id=f"embed:edit:{section}",
            )
            edit_button.callback = functools.partial(  # type: ignore[assignment]
                self._edit_section, section
            )
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        f"### {label}\n{self._truncate_display(self._display_value(section))}"
                    ),
                    accessory=edit_button,
                )
            )

        self.add_item(container)

        actions = discord.ui.ActionRow()
        save = discord.ui.Button(
            label="Save Changes" if self.mode == "edit" else "Save & Send",
            style=discord.ButtonStyle.success,
            custom_id="embed:save",
        )
        save.callback = self._save  # type: ignore[assignment]
        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="embed:cancel",
        )
        cancel.callback = self._cancel  # type: ignore[assignment]
        actions.add_item(save)
        actions.add_item(cancel)
        self.add_item(actions)

    def _render_done(self, jump_url: str) -> None:
        self.clear_items()
        container = discord.ui.Container(accent_color=discord.Color.green())
        if self.mode == "edit":
            text = "## ✅ Embed Updated\n[Jump to message]({0})".format(jump_url)
        else:
            text = "## ✅ Embed Sent\n[Jump to message]({0})".format(jump_url)
        container.add_item(discord.ui.TextDisplay(text))
        self.add_item(container)

    def _display_value(self, section: str) -> str:
        if section == "description":
            # Descriptions can be up to 4000 chars, which would overflow the
            # TextDisplay limit once the section header is added. Show whether
            # one is set instead of the raw content.
            return "Set" if (self.data.get("description") or "").strip() else "*Not set*"
        if section == "button":
            label = self.data.get("button_label")
            url = self.data.get("button_url")
            if label or url:
                return f"`{label or 'Unnamed'}` → {url or 'no link'}"
            return "*Not set*"
        if section == "channel":
            raw = self.data.get("channel_id")
            if not raw:
                return "*Not set*"
            channel = self.cog.bot.get_channel(self._parse_channel_id(raw))
            if channel is not None:
                return channel.mention
            return f"ID `{raw}`"
        if section == "author":
            author_id = self.data.get("author_id")
            if author_id:
                return f"User ID `{author_id}`"
            if self.data.get("author_name"):
                return self.data["author_name"]
            return "*Not set*"
        if section == "media":
            image = self.data.get("image_url")
            thumbnail = self.data.get("thumbnail_url")
            if not image and not thumbnail:
                return "*Not set*"
            lines = []
            if image:
                lines.append(f"• Image: {image}")
            if thumbnail:
                lines.append(f"• Thumbnail: {thumbnail}")
            return "\n".join(lines)
        if section == "webhook":
            name = self.data.get("webhook_name")
            avatar = self.data.get("webhook_avatar")
            if not name and not avatar:
                return "*Not set*"
            lines = []
            if name:
                lines.append(f"• Name: {name}")
            if avatar:
                lines.append(f"• Avatar: {avatar}")
            return "\n".join(lines)
        value = self.data.get(section)
        if not value:
            return "*Not set*"
        return str(value)

    @staticmethod
    def _error_embed(title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=f"❌ {title}", description=description, color=discord.Color.red()
        )

    @staticmethod
    def _truncate_display(text: str, limit: int = 3500) -> str:
        """Keep section previews safely under Discord's TextDisplay limit."""
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    @staticmethod
    def _parse_channel_id(raw: Optional[str]) -> Optional[int]:
        if not raw:
            return None
        raw = raw.strip()
        match = re.fullmatch(r"<#(\d+)>", raw)
        if match:
            return int(match.group(1))
        if raw.isdigit():
            return int(raw)
        return None

    # ------------------------------------------------------------ interactions

    async def _edit_section(self, section: str, interaction: discord.Interaction):
        if self.done:
            return
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This embed builder is not for you.", ephemeral=True
            )
            return
        _label, modal_title, fields = self.SECTIONS[section]
        spec = []
        for key, kwargs in fields:
            kwargs = dict(kwargs)
            current = self.data.get(key)
            if current is not None:
                kwargs["default"] = str(current)
            spec.append((key, kwargs))
        await interaction.response.send_modal(
            EmbedSectionModal(self, section, modal_title, spec)
        )

    async def apply_section(
        self,
        interaction: discord.Interaction,
        section: str,
        values: dict[str, Optional[str]],
    ) -> None:
        if interaction.user.id != self.user_id:
            return
        if section == "button":
            self.data["button_label"] = values.get("button_label")
            self.data["button_url"] = values.get("button_url")
        elif section == "webhook":
            self.data["webhook_name"] = values.get("webhook_name")
            self.data["webhook_avatar"] = values.get("webhook_avatar")
        elif section == "media":
            self.data["image_url"] = values.get("image_url")
            self.data["thumbnail_url"] = values.get("thumbnail_url")
        elif section == "channel":
            raw = values.get("channel_id")
            parsed = self._parse_channel_id(raw)
            if raw and parsed is None:
                await interaction.response.send_message(
                    "❌ Couldn't parse that channel. Use a channel ID or a #mention.",
                    ephemeral=True,
                )
                return
            self.data["channel_id"] = str(parsed) if parsed else None
        elif section == "author":
            raw = values.get("author_id")
            if raw:
                try:
                    int(raw)
                except ValueError:
                    await interaction.response.send_message(
                        "❌ That doesn't look like a user ID.", ephemeral=True
                    )
                    return
                self.data["author_id"] = raw
            else:
                self.data["author_id"] = None
        else:
            self.data[section] = values.get(section)
        await interaction.response.defer()
        self._render()
        await interaction.edit_original_response(view=self)

    async def _cancel(self, interaction: discord.Interaction):
        if self.done:
            return
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This embed builder is not for you.", ephemeral=True
            )
            return
        self.done = True
        self.clear_items()
        container = discord.ui.Container(accent_color=discord.Color(EMBED_BUILDER_COLOR))
        container.add_item(
            discord.ui.TextDisplay("## Embed Builder\nCancelled - nothing was sent.")
        )
        self.add_item(container)
        await interaction.response.edit_message(view=self)

    # -------------------------------------------------------------------- save

    async def _save(self, interaction: discord.Interaction):
        if self.done:
            return
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This embed builder is not for you.", ephemeral=True
            )
            return
        await interaction.response.defer()

        if not (self.data.get("description") or "").strip():
            await interaction.followup.send(
                embed=self._error_embed(
                    "Description Required",
                    "The embed needs a description. Edit the **Description** "
                    "section and try again.",
                ),
                ephemeral=True,
            )
            return

        button_label = (self.data.get("button_label") or "").strip()
        button_url = (self.data.get("button_url") or "").strip()
        if button_label and not button_url:
            await interaction.followup.send(
                embed=self._error_embed(
                    "Button Needs a Link",
                    "The link button has a label but no URL. Edit the "
                    "**Link Button** section and add the URL it should open.",
                ),
                ephemeral=True,
            )
            return

        channel = await self._resolve_target_channel(interaction)
        if channel is None:
            await interaction.followup.send(
                embed=self._error_embed(
                    "Channel Not Found",
                    "The target channel couldn't be found. Edit the "
                    "**Target Channel** section.",
                ),
                ephemeral=True,
            )
            return

        embed = await self._build_embed(interaction)
        view = self._build_button_view()

        if self.mode == "edit" and self.edit_target is not None:
            jump_url = await self._save_edit(interaction, channel, embed, view)
        else:
            jump_url = await self._save_create(interaction, channel, embed, view)

        if jump_url is None:
            return  # an error was already reported to the user

        self.done = True
        self._render_done(jump_url)
        await interaction.edit_original_response(view=self)

    async def _save_create(
        self,
        interaction: discord.Interaction,
        channel,
        embed: discord.Embed,
        view: Optional[discord.ui.LayoutView],
    ) -> Optional[str]:
        guild = interaction.guild
        content = (self.data.get("premessage") or "").strip() or discord.utils.MISSING
        if (
            isinstance(channel, discord.TextChannel)
            and guild is not None
            and channel.permissions_for(guild.me).manage_webhooks
        ):
            try:
                webhooks = await channel.webhooks()
                webhook = next(
                    (
                        w
                        for w in webhooks
                        if w.user and w.user.id == self.cog.bot.user.id
                    ),
                    None,
                )
                if not webhook:
                    webhook = await channel.create_webhook(name="Embed Bot helper")
                username = (
                    (self.data.get("webhook_name") or "").strip()
                    or "The Codeverse Hub"
                )
                avatar_url = (
                    (self.data.get("webhook_avatar") or "").strip()
                    or self.cog.bot.user.display_avatar.url
                )
                message = await webhook.send(
                    content=content,
                    embed=embed,
                    view=view or discord.utils.MISSING,
                    username=username,
                    avatar_url=avatar_url,
                    allowed_mentions=discord.AllowedMentions.none(),
                    wait=True,
                )
                return message.jump_url
            except discord.Forbidden:
                pass  # fall through to the webhook-unavailable warning
            except Exception as e:
                await interaction.followup.send(
                    embed=self._error_embed(
                        "Embed Send Failed", f"Could not send the embed: {e}"
                    ),
                    ephemeral=True,
                )
                return None
        await interaction.followup.send(
            embed=self._error_embed(
                "Webhook Unavailable",
                f"I need **Manage Webhooks** permission in {channel.mention} to "
                "send this embed with the chosen identity. Nothing was sent.",
            ),
            ephemeral=True,
        )
        return None

    async def _save_edit(
        self,
        interaction: discord.Interaction,
        channel,
        embed: discord.Embed,
        view: Optional[discord.ui.LayoutView],
    ) -> Optional[str]:
        _target_channel_id, target_message_id, webhook = self.edit_target
        content = (self.data.get("premessage") or "").strip() or discord.utils.MISSING
        try:
            if webhook is not None:
                await webhook.edit_message(
                    target_message_id,
                    content=content,
                    embed=embed,
                    view=view or None,
                )
            else:
                message = await channel.fetch_message(target_message_id)
                await message.edit(
                    content=content,
                    embed=embed,
                    view=view or None,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            message = await channel.fetch_message(target_message_id)
            return message.jump_url
        except discord.Forbidden:
            await interaction.followup.send(
                embed=self._error_embed(
                    "Cannot Edit Message",
                    "I don't have permission to edit that message. For webhook "
                    "messages I need **Manage Webhooks** in that channel.",
                ),
                ephemeral=True,
            )
            return None
        except Exception as e:
            await interaction.followup.send(
                embed=self._error_embed(
                    "Embed Edit Failed", f"Could not update the embed: {e}"
                ),
                ephemeral=True,
            )
            return None

    async def _resolve_target_channel(self, interaction: discord.Interaction):
        raw = self.data.get("channel_id")
        parsed = self._parse_channel_id(raw)
        channel_id = parsed if parsed is not None else interaction.channel_id
        channel = self.cog.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.cog.bot.fetch_channel(channel_id)
            except Exception:
                return None
        return channel

    async def _build_embed(self, interaction: discord.Interaction) -> discord.Embed:
        title = (self.data.get("title") or "").strip()
        description = (self.data.get("description") or "").strip()
        embed = discord.Embed(
            title=sanitize_mentions(title) if title else None,
            description=sanitize_mentions(description),
        )
        color = self._parse_color(self.data.get("color"))
        if color is not None:
            embed.color = color
        footer = (self.data.get("footer") or "").strip()
        if footer:
            embed.set_footer(text=sanitize_mentions(footer))
        image_url = (self.data.get("image_url") or "").strip()
        if image_url:
            embed.set_image(url=image_url)
        thumbnail_url = (self.data.get("thumbnail_url") or "").strip()
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        author = await self._resolve_author(interaction)
        if author:
            embed.set_author(name=author[0], icon_url=author[1])
        return embed

    def _parse_color(self, raw: Optional[str]) -> Optional[discord.Color]:
        if not raw:
            return None
        raw = raw.strip().lower()
        if raw.startswith("#"):
            try:
                return discord.Color(int(raw[1:], 16))
            except ValueError:
                return None
        return self.cog.colors.get(raw)

    async def _resolve_author(
        self, interaction: discord.Interaction
    ) -> Optional[tuple[str, Optional[str]]]:
        author_id = (self.data.get("author_id") or "").strip()
        if author_id:
            try:
                user_id = int(author_id)
            except ValueError:
                return None
            guild = interaction.guild
            member = guild.get_member(user_id) if guild is not None else None
            if member is not None:
                return member.display_name, member.display_avatar.url
            try:
                user = await self.cog.bot.fetch_user(user_id)
                return user.display_name, user.display_avatar.url
            except Exception:
                return None
        if self.data.get("author_name"):
            return self.data["author_name"], self.data.get("author_icon") or None
        return None

    def _build_button_view(self) -> Optional[discord.ui.View]:
        """Classic (non-V2) view for the link button.

        Components V2 views set ``MessageFlags.IS_COMPONENTS_V2``, and Discord
        rejects embeds/content in the same message as a V2 view. The link
        button therefore uses a classic :class:`discord.ui.View` so it can be
        sent together with the embed.
        """
        label = (self.data.get("button_label") or "").strip()
        url = (self.data.get("button_url") or "").strip()
        if not label and not url:
            return None
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label=label or "Open Link",
            style=discord.ButtonStyle.link,
            url=url or "https://discord.com",
        )
        view.add_item(button)
        return view
