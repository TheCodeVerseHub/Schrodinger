import discord  # type: ignore[import-not-found]
from discord.ext import commands  # type: ignore[import-not-found]
from discord import app_commands  # type: ignore[import-not-found]
from typing import Optional

from utils.helpers import safe_interaction_reply
from .embed_builder import EmbedBuilderDashboard


class EmbedBuilder(commands.Cog):
    """Advanced embed creation and management commands"""

    def __init__(self, bot):
        self.bot = bot
        # Store some preset colors for easy access
        self.colors = {
            "red": discord.Color.red(),
            "blue": discord.Color.blue(),
            "green": discord.Color.green(),
            "gold": discord.Color.gold(),
            "purple": discord.Color.purple(),
            "orange": discord.Color.orange(),
            "teal": discord.Color.teal(),
            "magenta": discord.Color.magenta(),
        }

    @app_commands.command(
        name="embed",
        description="Build a custom embed with an interactive builder"
    )
    async def create_embed_interactive(self, interaction: discord.Interaction):
        """Open the interactive Components V2 embed builder."""
        try:
            view = EmbedBuilderDashboard(
                self,
                user_id=interaction.user.id,
                channel_id=interaction.channel_id,
                mode="create",
            )
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error Opening Embed Builder",
                description=f"Error: {str(e)}",
                color=discord.Color.red()
            )
            # Safe: handles already-responded/expired interactions (10062).
            await safe_interaction_reply(interaction, embed=error_embed, ephemeral=True)

    @app_commands.command(
        name="editembed",
        description="Edit an existing embed made by the bot"
    )
    @app_commands.describe(
        message_id="The ID of the message containing the embed to edit",
        message_url="Alternative: Paste the message URL instead of ID"
    )
    async def edit_embed(
        self,
        interaction: discord.Interaction,
        message_id: Optional[str] = None,
        message_url: Optional[str] = None
    ):
        """Open the embed builder pre-filled with an existing embed and edit it in place."""
        try:
            # Extract message ID from URL if provided
            target_message_id = None
            target_channel_id = None

            if message_url:
                # Parse Discord message URL: https://discord.com/channels/guild_id/channel_id/message_id
                import re
                url_pattern = r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)'
                match = re.match(url_pattern, message_url.strip())
                if match:
                    guild_id, channel_id, msg_id = match.groups()
                    target_message_id = int(msg_id)
                    target_channel_id = int(channel_id)
                else:
                    raise ValueError("Invalid message URL format")
            elif message_id:
                try:
                    target_message_id = int(message_id.strip())
                    target_channel_id = interaction.channel_id
                except ValueError:
                    raise ValueError("Invalid message ID format")
            else:
                raise ValueError("Please provide either message_id or message_url")

            # Get the channel and message
            if target_channel_id and target_channel_id != interaction.channel_id:
                # Message is in a different channel
                if not interaction.guild:
                    raise ValueError("This command can only be used in a server")
                target_channel = interaction.guild.get_channel(target_channel_id)
                if not target_channel:
                    raise ValueError("Channel not found or not accessible")
                if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
                    raise ValueError("Can only edit embeds in text channels or threads")
            else:
                target_channel = interaction.channel
                if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
                    raise ValueError("Can only edit embeds in text channels or threads")

            if not target_message_id:
                raise ValueError("Message ID is required")

            # Fetch the message
            try:
                target_message = await target_channel.fetch_message(target_message_id)
            except discord.NotFound:
                raise ValueError("Message not found")
            except discord.Forbidden:
                raise ValueError("No permission to access that message")

            # Check if the message was sent by the bot (id) or by a webhook (no user id checks for webhooks)
            # Fetch webhook if it's a webhook message
            is_webhook = bool(target_message.webhook_id)
            webhook = None

            if is_webhook:
                if isinstance(target_channel, discord.TextChannel) and interaction.guild and target_channel.permissions_for(interaction.guild.me).manage_webhooks:
                     webhooks = await target_channel.webhooks()
                     # Check if we own the webhook (it's one of ours)
                     webhook = next((w for w in webhooks if w.id == target_message.webhook_id and (w.user and w.user.id == interaction.client.user.id)), None) if interaction.client.user else None

            if not is_webhook and (not interaction.client.user or target_message.author.id != interaction.client.user.id):
                error_embed = discord.Embed(
                    title="❌ Cannot Edit Message",
                    description="I can only edit messages that I sent myself.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
                return

            if is_webhook and not webhook:
                 error_embed = discord.Embed(
                    title="❌ Cannot Edit Message",
                    description="This webhook message doesn't seem to belong to me or I don't have access to it.",
                    color=discord.Color.red()
                )
                 await interaction.response.send_message(embed=error_embed, ephemeral=True)
                 return

            # Check if the message has an embed
            if not target_message.embeds:
                error_embed = discord.Embed(
                    title="❌ No Embed Found",
                    description="The specified message doesn't contain any embeds to edit.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
                return

            # Get the first embed from the message
            original_embed = target_message.embeds[0]

            builder = EmbedBuilderDashboard(
                self,
                user_id=interaction.user.id,
                channel_id=target_channel.id,
                mode="edit",
                edit_target=(target_channel.id, target_message.id, webhook),
            )
            self._prefill_embed_builder(builder, target_message, original_embed)
            await interaction.response.send_message(view=builder, ephemeral=True)

        except ValueError as e:
            error_embed = discord.Embed(
                title="❌ Invalid Input",
                description=f"Error: {str(e)}\n\n**Usage Examples:**\n"
                           f"• `/editembed message_id:123456789`\n"
                           f"• `/editembed message_url:https://discord.com/channels/.../.../.../`\n"
                           f"• Right-click message → Copy Message Link",
                color=discord.Color.red()
            )
            # Safe: handles already-responded/expired interactions (10062).
            await safe_interaction_reply(interaction, embed=error_embed, ephemeral=True)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Error Opening Embed Editor",
                description=f"Error: {str(e)}",
                color=discord.Color.red()
            )
            await safe_interaction_reply(interaction, embed=error_embed, ephemeral=True)

    def _prefill_embed_builder(self, builder, message, embed):
        """Pre-fill a builder with the contents of an existing embed/message."""
        builder.data["title"] = embed.title or None
        builder.data["description"] = embed.description or None
        if embed.color:
            builder.data["color"] = f"#{embed.color.value:06x}"
        if embed.footer and embed.footer.text:
            builder.data["footer"] = embed.footer.text
        builder.data["premessage"] = message.content or None
        if embed.image:
            builder.data["image_url"] = embed.image.url
        if embed.thumbnail:
            builder.data["thumbnail_url"] = embed.thumbnail.url
        if embed.author and embed.author.name:
            # Round-trip the existing author; the Author modal can replace it
            # with a user ID (name + avatar are then taken from that user).
            builder.data["author_name"] = embed.author.name
            builder.data["author_icon"] = embed.author.icon_url
        link_button = self._extract_link_button(message)
        if link_button:
            builder.data["button_label"] = link_button.label
            builder.data["button_url"] = link_button.url
        builder._render()

    @staticmethod
    def _extract_link_button(message):
        """Find an existing link button on a message so the builder can prefill it."""
        try:
            for row in message.components:
                for component in getattr(row, "children", []):
                    if (
                        getattr(component, "style", None) == discord.ButtonStyle.link
                        and getattr(component, "url", None)
                    ):
                        return component
        except Exception:
            return None
        return None

    # embedrules command has been removed

    @commands.group(name="ls", invoke_without_command=True)
    async def ls_command(self, ctx):
        """List utilities for the server"""
        commands_list = [
            "`?ls channels` - List all channels (categories, text, voice)",
            "`?ls channels ?w <Target> <Perm>` - Find channels where User/Role has Permission",
            "`?ls channels ?v <channel>` - Show who can view a specific channel",
            "`?ls categories [?w ...]` - List categories (optional: filter by permission)",
            "`?ls role <role>` - View full details and permissions of a role",
            "`?ls members <role>` - List members who have a specific role",
            "`?ls perm <permission>` - See which roles have a specific permission",
            "`?ls bots` - List all bots in the server",
            "`?ls boosters` - List server boosters",
            "`?ls perms` - List roles that have permissions",
            "`?ls noperms` - List cosmetic roles (no permissions)",
            "`?ls noroles` - List users with no roles",
        ]
        await _ls_send(
            ctx,
            _ls_container(
                "Server Listing Utilities",
                "Inspect roles, channels, and permissions on this server.",
                commands_list,
                footer="Tip: Use Role ID with ?ls role <id> to avoid pinging members!",
            ),
        )

    @ls_command.command(name="role")
    async def ls_role(self, ctx, role: discord.Role):
        """View full details and permissions of a specific role"""
        perms = role.permissions

        # Key Permissions to highlight
        key_perms = []
        if perms.administrator:
            key_perms.append("Administrator")
        if perms.manage_guild:
            key_perms.append("Manage Server")
        if perms.manage_roles:
            key_perms.append("Manage Roles")
        if perms.manage_channels:
            key_perms.append("Manage Channels")
        if perms.ban_members:
            key_perms.append("Ban Members")
        if perms.kick_members:
            key_perms.append("Kick Members")
        if perms.manage_messages:
            key_perms.append("Manage Messages")
        if perms.mention_everyone:
            key_perms.append("Mention Everyone")
        if perms.view_audit_log:
            key_perms.append("View Audit Log")

        # Create list of enabled permissions
        enabled_perms = [p[0].replace('_', ' ').title() for p in perms if p[1]]

        container = discord.ui.Container(accent_color=discord.Color(LS_COLOR))
        container.add_item(discord.ui.TextDisplay(f"## Role: {role.name}"))
        container.add_item(discord.ui.Separator())

        info = [
            f"**ID:** `{role.id}`",
            f"**Color:** {role.color}",
            f"**Position:** {role.position}",
            f"**Integrated:** {role.is_integration()}",
            f"**Hoisted:** {role.hoist}",
            f"**Mentionable:** {role.mentionable}",
            f"**Members:** {len(role.members)}",
            f"**Created:** <t:{int(role.created_at.timestamp())}:R>",
        ]
        container.add_item(discord.ui.TextDisplay("### Info\n" + "\n".join(info)))
        container.add_item(discord.ui.Separator())

        if perms.administrator:
            container.add_item(
                discord.ui.TextDisplay(
                    "### ⚠️ Fatal Permission\n**ADMINISTRATOR** (bypasses all other permissions)"
                )
            )
            container.add_item(discord.ui.Separator())
        elif key_perms:
            container.add_item(
                discord.ui.TextDisplay("### Key Permissions\n" + ", ".join(key_perms))
            )
            container.add_item(discord.ui.Separator())

        if not enabled_perms:
            container.add_item(
                discord.ui.TextDisplay("### All Permissions\nNone (cosmetic role)")
            )
        else:
            perm_lines = [f"• {p}" for p in enabled_perms]
            for chunk in _ls_chunk_lines(perm_lines):
                container.add_item(
                    discord.ui.TextDisplay("### All Permissions\n" + chunk)
                )

        await _ls_send(ctx, container)

    @ls_command.command(name="members")
    async def ls_members(self, ctx, *, role: discord.Role):
        """Show how many people have a specific role and list them"""
        count = len(role.members)
        if count == 0:
            lines = []
            empty_text = "No members have this role."
        elif count <= 50:
            lines = [member.mention for member in role.members]
            empty_text = None
        else:
            lines = []
            empty_text = f"There are {count} members with this role. (List only shown if up to 50)"
        await _ls_send(
            ctx,
            _ls_container(
                f"Members in Role: {role.name}",
                f"**Total:** {count} • **Role ID:** `{role.id}`",
                lines,
                empty_text=empty_text,
            ),
        )

    @ls_command.command(name="perm")
    async def ls_perm(self, ctx, *, perm_query: str):
        """List roles that have a specific permission"""
        # Normalize query
        query = perm_query.lower().replace(" ", "_")

        # Valid permissions map
        valid_perms = dir(discord.Permissions.none())

        # Find match
        matched_perm = None
        for p in valid_perms:
            if p.startswith("_") or callable(getattr(discord.Permissions, p, None)):
                continue
            if p == query or p.replace("_", "") == query.replace("_", ""):
                matched_perm = p
                break

        if not matched_perm:
            # Fuzzy-ish fallback
            matches = [p for p in valid_perms if not p.startswith("_") and query in p]
            if matches:
                 await ctx.send(f"Permission `{perm_query}` not found. Did you mean: {', '.join(matches[:5])}?")
            else:
                 await ctx.send(f"Permission `{perm_query}` not found.")
            return

        # Find roles
        roles_with_perm = []
        for role in ctx.guild.roles:
            if role.is_default():
                continue
            # Administrator implies all permissions
            if role.permissions.administrator or getattr(role.permissions, matched_perm):
                roles_with_perm.append(role)

        roles_with_perm.sort(key=lambda r: r.position, reverse=True)

        lines = []
        for role in roles_with_perm:
            # Mark if it's via admin or direct
            note = " (Admin)" if role.permissions.administrator and matched_perm != "administrator" else ""
            lines.append(f"{role.mention}{note}")

        await _ls_send(
            ctx,
            _ls_container(
                f"Roles with '{matched_perm.replace('_', ' ').title()}'",
                f"Found {len(roles_with_perm)} roles.",
                lines,
                empty_text="No roles found.",
            ),
        )

    @ls_command.command(name="noperms")
    async def ls_noperms(self, ctx):
        """List cosmetic roles (no permissions at all)"""
        roles = []
        for role in ctx.guild.roles:
            if role.is_default():
                continue # Skip @everyone
            # Check if role has NO permissions
            if role.permissions.value == 0:
                roles.append(role)

        # Sort by position (reverse = highest first)
        roles.sort(key=lambda r: r.position, reverse=True)

        if not roles:
            await ctx.send("No cosmetic-only roles found.")
            return

        lines = [f"{r.mention} (Pos: {r.position})" for r in roles]
        await _ls_send(
            ctx,
            _ls_container(
                "Cosmetic Roles (No Permissions)",
                "These roles have 0 permission value.",
                lines,
                footer=f"Total: {len(roles)} roles",
            ),
        )

    @ls_command.command(name="perms")
    async def ls_perms(self, ctx, *, role: discord.Role = None):
        """List roles that have at least one permission or permissions for a specific role"""

        if role:
            # List permissions for the specific role
            perms = []
            for perm, value in role.permissions:
                if value:
                    perms.append(perm.replace('_', ' ').title())

            if not perms:
                await ctx.send(f"{role.mention} has no active permissions.", allowed_mentions=discord.AllowedMentions.none())
                return

            perms.sort()
            await _ls_send(
                ctx,
                _ls_container(
                    f"Permissions for {role.name}",
                    None,
                    [f"• {p}" for p in perms],
                    footer=f"Total: {len(perms)} permissions",
                ),
            )
            return

        # List all roles with permissions
        roles = []
        for r in ctx.guild.roles:
            if r.is_default():
                continue
            if r.permissions.value != 0:
                roles.append(r)

        roles.sort(key=lambda r: r.position, reverse=True)

        if not roles:
            await ctx.send("No roles with permissions found (unlikely).")
            return

        lines = [f"{r.mention} (Pos: {r.position})" for r in roles]
        await _ls_send(
            ctx,
            _ls_container(
                "Functional Roles (With Permissions)",
                "These roles have at least one permission enabled.",
                lines,
                footer=f"Total: {len(roles)} roles",
            ),
        )
    @ls_command.command(name="noroles")
    async def ls_noroles(self, ctx):
        """Show all users in the server who have no roles (no role at all)."""
        no_role_members = [
            m for m in ctx.guild.members if len(m.roles) == 1  # only @everyone
        ]

        if not no_role_members:
            await _ls_send(
                ctx,
                _ls_container(
                    "Users with No Roles",
                    None,
                    [],
                    empty_text="Every member in this server has at least one role.",
                ),
            )
            return

        lines = [f"{m.mention} ({m.id})" for m in sorted(no_role_members, key=lambda m: m.display_name.lower())]
        await _ls_send(
            ctx,
            _ls_container(
                "Users with No Roles",
                "These members only have the @everyone role.",
                lines,
                footer=f"Total: {len(no_role_members)} user{'s' if len(no_role_members) != 1 else ''}",
            ),
        )

    @ls_command.command(name="channels")
    async def ls_channels(self, ctx, *args):
        """List channels. Usage: ?ls channels [?w <Role/User> <Permission>] | ?v <channel>"""

        # Check for ?w argument for filtering
        full_args = " ".join(args)

        # ── ?v  –  show who can view a specific channel ──
        if "?v" in full_args:
            await self._ls_channels_view(ctx, full_args)
            return

        if "?w" in full_args:
            # Parse usage: ?ls channels ?w <Target> <Permission>
            try:
                # Split everything after ?w
                params = full_args.split("?w", 1)[1].strip()
                if not params:
                    raise ValueError("Missing arguments after ?w")

                # We expect the last word to be the permission, and everything before it to be the target
                # This allows targets with spaces in names if distinct enough, though mentions/IDs are safer.
                match_parts = params.rsplit(" ", 1)
                if len(match_parts) < 2:
                    raise ValueError("Please provide a Target and a Permission (e.g., Everyone SendMessage)")

                target_str = match_parts[0].strip()
                perm_str = match_parts[1].strip()

                # Resolve Target
                target = None
                if target_str.lower() in ["everyone", "@everyone", "here", "@here"]:
                    target = ctx.guild.default_role
                else:
                    # Try converting to Role first, then Member
                    try:
                        target = await commands.RoleConverter().convert(ctx, target_str)
                    except commands.BadArgument:
                        try:
                            target = await commands.MemberConverter().convert(ctx, target_str)
                        except commands.BadArgument:
                            await ctx.send(f"Could not find a role or member named `{target_str}`. Check the spelling or use a mention or ID instead.")
                            return

                # Resolve Permission
                # Map common aliases
                perm_map = {
                    'sendmessage': 'send_messages',
                    'sendmessages': 'send_messages',
                    'sendingmessages': 'send_messages',
                    'send': 'send_messages',
                    'view': 'view_channel',
                    'viewchannel': 'view_channel',
                    'viewchannels': 'view_channel',
                    'read': 'view_channel',
                    'readmessage': 'view_channel',
                    'readmessages': 'view_channel',
                    'connect': 'connect',
                    'speak': 'speak',
                    'manage': 'manage_channels',
                    'admin': 'administrator',
                    'embed': 'embed_links',
                    'embeds': 'embed_links',
                    'embedlink': 'embed_links',
                    'attach': 'attach_files',
                    'files': 'attach_files',
                    'file': 'attach_files',
                    'image': 'attach_files',
                    'addreaction': 'add_reactions',
                    'addreactions': 'add_reactions',
                    'reaction': 'add_reactions',
                    'history': 'read_message_history',
                    'managemessage': 'manage_messages',
                    'managemessages': 'manage_messages'
                }

                # Normalize input
                clean_input = perm_str.lower().replace(" ", "").replace("_", "")

                # Get all real permissions using standard iteration
                valid_perms = [name for name, value in discord.Permissions()]

                perm_attr = None

                # 1. Map Check (Trust the map)
                if clean_input in perm_map:
                    perm_attr = perm_map[clean_input]

                # 2. Direct name check (snake case normalized)
                # This covers "manage_channels" -> "manage_channels"
                if not perm_attr:
                     snake_input = perm_str.lower().replace(" ", "_")
                     if snake_input in valid_perms:
                         perm_attr = snake_input

                # 3. Stripped check (ignore underscores in real permissions)
                # This covers "managechannels" -> matches "manage_channels"
                if not perm_attr:
                    for vp in valid_perms:
                        if vp.replace("_", "") == clean_input:
                            perm_attr = vp
                            break

                # 4. Fuzzy / Substring match (DANGEROUS but helpful)
                if not perm_attr:
                    # Finds "manage" -> "manage_channels" (first match)
                    # Use a priority list if multiple match?
                    matches = [p for p in valid_perms if clean_input in p.replace("_", "")]
                    if matches:
                        # Prefer shorter matches or exact start matches
                        # e.g. "ban" matches "ban_members"
                        perm_attr = matches[0]
                    else:
                        await ctx.send(f"Invalid permission `{perm_str}`. Use ?ls perm to see available permission names.")
                        return

                # Filter Channels
                matched = []
                for channel in ctx.guild.channels:
                    # Exclude categories
                    if isinstance(channel, discord.CategoryChannel):
                        continue

                    # channel.permissions_for handles overwrites, roles, admin implications
                    perms = channel.permissions_for(target)
                    if getattr(perms, perm_attr, False):
                        matched.append(channel)

                matched.sort(key=lambda c: c.position)

                if not matched:
                    await ctx.send(f"🚫 No channels found where {target.mention} has `{perm_attr}` permission.")
                    return

                # Build list text
                lines = [f"{c.mention} (`{c.id}`)" for c in matched]
                await _ls_send(
                    ctx,
                    _ls_container(
                        f"Channel Audit: {perm_attr}",
                        f"Showing channels where **{target.mention}** can `{perm_attr}`.",
                        lines,
                        empty_text="No channels found.",
                    ),
                )

            except Exception as e:
                await ctx.send(f"Error parsing arguments: {str(e)}\nUsage: `?ls channels ?w Everyone SendMessage`")
            return

        # Default: List all channels grouped by category
        channels = sorted(ctx.guild.channels, key=lambda c: c.position)

        categories = {}
        no_category = []

        for c in channels:
            if c.category:
                if c.category not in categories:
                    categories[c.category] = []
                categories[c.category].append(c)
            elif isinstance(c, discord.CategoryChannel):
                if c not in categories:
                    categories[c] = [] # Ensure category exists even if empty
            else:
                no_category.append(c)

        container = discord.ui.Container(accent_color=discord.Color(LS_COLOR))
        container.add_item(discord.ui.TextDisplay(f"## Channels in {ctx.guild.name}"))
        container.add_item(discord.ui.Separator())

        text_lines = []
        if no_category:
            text_lines.append("### Uncategorized")
            text_lines.extend(c.mention for c in no_category)

        # Sort categories by position
        sorted_cats = sorted(categories.keys(), key=lambda x: x.position)

        for cat in sorted_cats:
            chans = categories[cat]
            text_lines.append(f"### {cat.name.upper()}")
            text_lines.extend(f"└ {c.mention}" for c in chans)

        if not text_lines:
            container.add_item(
                discord.ui.TextDisplay("*No channels in this server.*")
            )
        else:
            for chunk in _ls_chunk_lines(text_lines):
                container.add_item(discord.ui.TextDisplay(chunk))

        await _ls_send(ctx, container)

    async def _ls_channels_view(self, ctx, full_args: str):
        """Show which roles/users can view a specific channel.

        Usage: ?ls channels ?v #channel-name
        """
        # Extract channel mention or ID after ?v
        params = full_args.split("?v", 1)[1].strip()
        if not params:
            await ctx.send("Please provide a channel after ?v. Example: ?ls channels ?v #general")
            return

        channel_str = params.strip()

        # Resolve the channel
        channel = None
        # Try channel mention / ID converter
        try:
            channel = await commands.TextChannelConverter().convert(ctx, channel_str)
        except commands.BadArgument:
            await ctx.send(
                f"Could not find a text channel named `{channel_str}`. Check the channel name or use a channel mention instead."
            )
            return

        if channel is None:
            return

        # Determine who has view_channel
        # Collect roles and members with explicit view_channel=True
        view_roles: list[discord.Role] = []
        view_users: list[discord.Member] = []
        deny_roles: list[discord.Role] = []
        deny_users: list[discord.Member] = []

        # Check @everyone first
        everyone_overwrite = channel.overwrites_for(ctx.guild.default_role)
        everyone_can_view = everyone_overwrite.view_channel
        # view_channel can be None (inherits) – treat as True for @everyone
        everyone_view_allowed = everyone_can_view is not False

        # Iterate over all overwrites for the channel
        for target, overwrite in channel.overwrites.items():
            can_view = overwrite.view_channel
            if can_view is True:
                if isinstance(target, discord.Role):
                    view_roles.append(target)
                elif isinstance(target, discord.Member):
                    view_users.append(target)
            elif can_view is False:
                if isinstance(target, discord.Role):
                    deny_roles.append(target)
                elif isinstance(target, discord.Member):
                    deny_users.append(target)

        # Members who inherit view through roles
        inherited_view_members: list[discord.Member] = []
        if everyone_view_allowed:
            for member in ctx.guild.members:
                # Skip members already explicitly allowed or denied
                if member in view_users or member in deny_users:
                    continue
                # Check if any of their roles grant explicit view
                member_roles = set(member.roles)
                if any(r in view_roles for r in member_roles):
                    view_users.append(member)
                elif any(r in deny_roles for r in member_roles):
                    deny_users.append(member)
                else:
                    # Inherits from @everyone
                    inherited_view_members.append(member)

        # Combine: explicit allows + inherited (if @everyone allows)
        all_view = view_users + (
            inherited_view_members if everyone_view_allowed else []
        )

        # Build display
        title = f"Can View: {channel.name}"
        sections: list[str] = []

        if view_roles:
            sections.append("### Roles (Explicit Allow)")
            for r in sorted(view_roles, key=lambda r: r.position, reverse=True):
                sections.append(f"• {r.mention}")

        if view_users:
            # Show explicit + inherited together
            mention_list = [m.mention for m in sorted(all_view, key=lambda m: m.display_name.lower())]
            sections.append(f"### Users ({len(all_view)})")
            for chunk in _ls_chunk_lines(mention_list, max_chars=1200):
                sections.append(chunk)

        if deny_roles:
            sections.append("### Roles (Explicit Deny)")
            for r in sorted(deny_roles, key=lambda r: r.position, reverse=True):
                sections.append(f"• {r.mention}")

        if deny_users:
            sections.append("### Users (Explicit Deny)")
            for m in sorted(deny_users, key=lambda m: m.display_name.lower()):
                sections.append(f"• {m.mention}")

        if not sections:
            # Nobody has explicit overwrites; fall back to inheritance info
            if everyone_view_allowed:
                sections.append(
                    f"*No explicit overwrites. **{ctx.guild.member_count}** members can view via @everyone.*"
                )
            else:
                sections.append("*No one can view this channel (view denied at @everyone level).*")

        await _ls_send(
            ctx,
            _ls_container(
                title,
                f"Channel: {channel.mention} (`{channel.id}`)",
                sections,
            ),
        )

    @ls_command.command(name="categories", aliases=["category"])
    async def ls_categories(self, ctx, *args):
        """List categories. Usage: ?ls categories [?w <Role/User> <Permission>]"""

        # Check for ?w argument for filtering
        full_args = " ".join(args)
        if "?w" in full_args:
            # Parse usage: ?ls categories ?w <Target> <Permission>
            try:
                # Split everything after ?w
                params = full_args.split("?w", 1)[1].strip()
                if not params:
                    raise ValueError("Missing arguments after ?w")

                match_parts = params.rsplit(" ", 1)
                if len(match_parts) < 2:
                    raise ValueError("Please provide a Target and a Permission")

                target_str = match_parts[0].strip()
                perm_str = match_parts[1].strip()

                # Resolve Target
                target = None
                if target_str.lower() in ["everyone", "@everyone", "here", "@here"]:
                    target = ctx.guild.default_role
                else:
                    try:
                        target = await commands.RoleConverter().convert(ctx, target_str)
                    except commands.BadArgument:
                        try:
                            target = await commands.MemberConverter().convert(ctx, target_str)
                        except commands.BadArgument:
                            await ctx.send(f"Could not find a role or member named `{target_str}`. Check the spelling or use a mention or ID instead.")
                            return

                # Resolve Permission
                perm_map = {
                    'sendmessage': 'send_messages',
                    'sendmessages': 'send_messages',
                    'sendingmessages': 'send_messages',
                    'send': 'send_messages',
                    'view': 'view_channel',
                    'viewchannel': 'view_channel',
                    'viewchannels': 'view_channel',
                    'read': 'view_channel',
                    'readmessage': 'view_channel',
                    'readmessages': 'view_channel',
                    'connect': 'connect',
                    'speak': 'speak',
                    'manage': 'manage_channels',
                    'admin': 'administrator',
                    'embed': 'embed_links',
                    'embeds': 'embed_links',
                    'embedlink': 'embed_links',
                    'attach': 'attach_files',
                    'files': 'attach_files',
                    'file': 'attach_files',
                    'image': 'attach_files',
                    'addreaction': 'add_reactions',
                    'addreactions': 'add_reactions',
                    'reaction': 'add_reactions',
                    'history': 'read_message_history',
                    'managemessage': 'manage_messages',
                    'managemessages': 'manage_messages'
                }

                clean_input = perm_str.lower().replace(" ", "").replace("_", "")
                valid_perms = [name for name, value in discord.Permissions()]

                perm_attr = None
                if clean_input in perm_map:
                    perm_attr = perm_map[clean_input]

                if not perm_attr:
                     snake_input = perm_str.lower().replace(" ", "_")
                     if snake_input in valid_perms:
                         perm_attr = snake_input

                if not perm_attr:
                    for vp in valid_perms:
                        if vp.replace("_", "") == clean_input:
                            perm_attr = vp
                            break

                if not perm_attr:
                    matches = [p for p in valid_perms if clean_input in p.replace("_", "")]
                    if matches:
                        perm_attr = matches[0]
                    else:
                        await ctx.send(f"Invalid permission `{perm_str}`. Use ?ls perm to see available permission names.")
                        return

                # Filter Categories
                matched = []
                for channel in ctx.guild.categories:
                    perms = channel.permissions_for(target)
                    if getattr(perms, perm_attr, False):
                        matched.append(channel)

                matched.sort(key=lambda c: c.position)

                if not matched:
                    await ctx.send(f"🚫 No categories found where {target.mention} has `{perm_attr}` permission.")
                    return

                lines = [f"{c.name.upper()} (`{c.id}`)" for c in matched]
                await _ls_send(
                    ctx,
                    _ls_container(
                        f"Category Audit: {perm_attr}",
                        f"Showing categories where **{target.mention}** can `{perm_attr}`.",
                        lines,
                        empty_text="No categories found.",
                    ),
                )

            except Exception as e:
                await ctx.send(f"Error parsing arguments: {str(e)}")
            return

        # Default: List all categories
        categories = sorted(ctx.guild.categories, key=lambda c: c.position)
        lines = [f"{c.name} (`{c.id}`)" for c in categories]
        await _ls_send(
            ctx,
            _ls_container(
                f"Categories in {ctx.guild.name}",
                None,
                lines,
                empty_text="No categories found.",
            ),
        )

    @ls_command.command(name="bots")
    async def ls_bots(self, ctx):
        """List all bots in the server"""
        bots = [m for m in ctx.guild.members if m.bot]
        lines = [f"{b.mention} {b.top_role.mention if b.top_role else ''}" for b in bots]
        await _ls_send(
            ctx,
            _ls_container(
                f"Bots in {ctx.guild.name} ({len(bots)})",
                None,
                lines,
                empty_text="No bots in this server.",
            ),
        )

    @ls_command.command(name="boosters")
    async def ls_boosters(self, ctx):
        """List current server boosters"""
        boosters = ctx.guild.premium_subscribers

        if not boosters:
            await _ls_send(
                ctx,
                _ls_container(
                    f"Server Boosters (Tier {ctx.guild.premium_tier})",
                    None,
                    [],
                    empty_text="This server has no boosters yet!",
                ),
            )
            return

        lines = []
        for member in boosters:
            # Format time since boost
            if member.premium_since:
                timestamp = f"<t:{int(member.premium_since.timestamp())}:R>"
            else:
                timestamp = "Unknown time"
            lines.append(f"• {member.mention} - {timestamp}")

        await _ls_send(
            ctx,
            _ls_container(
                f"Server Boosters ({ctx.guild.premium_subscription_count} boosts)",
                f"Current Level: **Tier {ctx.guild.premium_tier}**",
                lines,
            ),
        )


LS_COLOR = 0x5865F2


def _ls_chunk_lines(lines: list[str], max_chars: int = 1500) -> list[str]:
    """Split display lines into chunks that fit a single TextDisplay safely."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _ls_container(
    title: str,
    intro: Optional[str] = None,
    lines: Optional[list[str]] = None,
    empty_text: Optional[str] = None,
    footer: Optional[str] = None,
) -> discord.ui.Container:
    """Build a Components V2 listing container.

    ``lines`` are chunked into TextDisplays so no truncation hack is needed,
    no matter how long the list is.
    """
    container = discord.ui.Container(accent_color=discord.Color(LS_COLOR))
    container.add_item(discord.ui.TextDisplay(f"## {title}"))
    if intro:
        container.add_item(discord.ui.TextDisplay(intro))
    container.add_item(discord.ui.Separator())

    if lines:
        for chunk in _ls_chunk_lines(lines):
            container.add_item(discord.ui.TextDisplay(chunk))
    else:
        container.add_item(discord.ui.TextDisplay(empty_text or "*Nothing to show.*"))

    if footer:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"*{footer}*"))
    return container


async def _ls_send(ctx, container: discord.ui.Container) -> None:
    """Send a Components V2 container as a standalone message."""
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(EmbedBuilder(bot))
