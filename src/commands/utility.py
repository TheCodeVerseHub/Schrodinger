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
        embed = discord.Embed(
            title="Server Listing Utilities",
            description="Inspect roles, channels, and permissions on this server.",
            color=0x5865F2
        )
        embed.add_field(name="?ls channels", value="List all channels (categories, text, voice)", inline=False)
        embed.add_field(name="?ls channels ?w <Target> <Perm>", value="Find channels where User/Role has Permission", inline=False)
        embed.add_field(name="?ls categories [?w ...]", value="List categories (optional: filter by permission)", inline=False)
        embed.add_field(name="?ls role <role>", value="View full details and permissions of a role", inline=False)
        embed.add_field(name="?ls members <role>", value="List members who have a specific role", inline=False)
        embed.add_field(name="?ls perm <permission>", value="See which roles have a specific permission", inline=False)
        embed.add_field(name="?ls bots", value="List all bots in the server", inline=False)
        embed.add_field(name="?ls boosters", value="List server boosters", inline=False)
        embed.add_field(name="?ls perms", value="List roles that have permissions", inline=False)
        embed.add_field(name="?ls noperms", value="List cosmetic roles (no permissions)", inline=False)
        
        embed.set_footer(text="Tip: Use Role ID with ?ls role <id> to avoid pinging members!")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @ls_command.command(name="role")
    async def ls_role(self, ctx, role: discord.Role):
        """View full details and permissions of a specific role"""
        perms = role.permissions

        # Key Permissions to highlight
        key_perms = []
        if perms.administrator: key_perms.append("Administrator")
        if perms.manage_guild: key_perms.append("Manage Server")
        if perms.manage_roles: key_perms.append("Manage Roles")
        if perms.manage_channels: key_perms.append("Manage Channels")
        if perms.ban_members: key_perms.append("Ban Members")
        if perms.kick_members: key_perms.append("Kick Members")
        if perms.manage_messages: key_perms.append("Manage Messages")
        if perms.mention_everyone: key_perms.append("Mention Everyone")
        if perms.view_audit_log: key_perms.append("View Audit Log")

        # Create list of enabled permissions
        enabled_perms = [p[0].replace('_', ' ').title() for p in perms if p[1]]
        
        embed = discord.Embed(title=f"Role: {role.name}", color=0x5865F2)
        embed.add_field(name="ID", value=str(role.id), inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Position", value=str(role.position), inline=True)
        embed.add_field(name="Integrated", value=str(role.is_integration()), inline=True)
        embed.add_field(name="Hoisted", value=str(role.hoist), inline=True)
        embed.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
        
        embed.add_field(name="Members", value=f"{len(role.members)} members", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(role.created_at.timestamp())}:R>", inline=True)
        
        if perms.administrator:
            embed.add_field(name="Fatal Permission", value="**ADMINISTRATOR** (Bypasses all other permissions)", inline=False)
        
        if key_perms and not perms.administrator:
            embed.add_field(name="Key Permissions", value=", ".join(key_perms), inline=False)

        # Truncate full list if too long
        perm_list_str = ", ".join(enabled_perms)
        if len(perm_list_str) > 1000:
            perm_list_str = perm_list_str[:1000] + "..."
        
        if not enabled_perms:
            perm_list_str = "None (Cosmetic Role)"

        embed.add_field(name="All Permissions", value=perm_list_str, inline=False)
        
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @ls_command.command(name="members")
    async def ls_members(self, ctx, *, role: discord.Role):
        """Show how many people have a specific role and list them if < 20"""
        count = len(role.members)
        
        embed = discord.Embed(
            title=f"Members in Role: {role.name}",
            color=role.color
        )
        embed.add_field(name="Total Members", value=str(count), inline=False)
        embed.add_field(name="Role ID", value=str(role.id), inline=False)
        
        if count == 0:
            embed.description = "No members have this role."
        elif count < 20:
            member_mentions = [member.mention for member in role.members]
            # Join with a nice separator
            embed.description = "\n".join(member_mentions)
        else:
            embed.description = f"There are {count} members with this role. (List only shown if < 20)"
            
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

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
            if role.is_default(): continue
            # Administrator implies all permissions
            if role.permissions.administrator or getattr(role.permissions, matched_perm):
                roles_with_perm.append(role)
        
        roles_with_perm.sort(key=lambda r: r.position, reverse=True)
        
        embed = discord.Embed(
            title=f"Roles with '{matched_perm.replace('_', ' ').title()}'",
            description=f"Found {len(roles_with_perm)} roles.",
            color=0x5865F2
        )
        
        chunk = ""
        for role in roles_with_perm:
            # Mark if it's via admin or direct
            note = " (Admin)" if role.permissions.administrator and matched_perm != "administrator" else ""
            line = f"{role.mention}{note}\n"
            
            if len(chunk) + len(line) > 4000:
                embed.description = chunk
                await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                chunk = line
                embed = discord.Embed(title="Continued...", color=0x5865F2)
            else:
                chunk += line
                
        if chunk:
            embed.description = chunk
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        elif not roles_with_perm:
            await ctx.send(f"No roles found with `{matched_perm}`.")

    @ls_command.command(name="noperms")
    async def ls_noperms(self, ctx):
        """List cosmetic roles (no permissions at all)"""
        roles = []
        for role in ctx.guild.roles:
            if role.is_default(): continue # Skip @everyone
            # Check if role has NO permissions
            if role.permissions.value == 0:
                roles.append(role)
        
        # Sort by position (reverse = highest first)
        roles.sort(key=lambda r: r.position, reverse=True)
        
        if not roles:
            await ctx.send("No cosmetic-only roles found.")
            return

        # Create embed
        embed = discord.Embed(
            title="Cosmetic Roles (No Permissions)",
            description="These roles have 0 permission value.",
            color=0x5865F2
        )
        
        # Chunking for description limit
        chunk = ""
        count = 0
        for role in roles:
            line = f"{role.mention} (Pos: {role.position})\n"
            if len(chunk) + len(line) > 4000:
                embed.description = chunk
                await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                chunk = line
                embed = discord.Embed(title="Continued...", color=0x5865F2)
            else:
                chunk += line
            count += 1
            
        if chunk:
            embed.description = chunk
            embed.set_footer(text=f"Total: {count} roles")
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

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
            
            perms_chunked = [perms[i:i + 20] for i in range(0, len(perms), 20)]

            for i, chunk in enumerate(perms_chunked):
                embed = discord.Embed(
                    title=f"Permissions for {role.name}" if i == 0 else f"Permissions for {role.name} (Continued)",
                    description="\n".join(f"• {p}" for p in chunk),
                    color=role.color if role.color.value != 0 else 0x5865F2
                )
                if i == len(perms_chunked) - 1:
                    embed.set_footer(text=f"Total: {len(perms)} permissions")
                await ctx.send(embed=embed)
            return

        # List all roles with permissions
        roles = []
        for r in ctx.guild.roles:
            if r.is_default(): continue
            if r.permissions.value != 0:
                roles.append(r)
        
        roles.sort(key=lambda r: r.position, reverse=True)
        
        if not roles:
            await ctx.send("No roles with permissions found (unlikely).")
            return

        embed = discord.Embed(
            title="Functional Roles (With Permissions)",
            description="These roles have at least one permission enabled.",
            color=0x5865F2
        )
        
        chunk = ""
        count = 0
        
        for r in roles:
            line = f"{r.mention} (Pos: {r.position})\n"
            if len(chunk) + len(line) > 4000:
                embed.description = chunk
                await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                chunk = line
                embed = discord.Embed(title="Continued...", color=0x5865F2)
            else:
                chunk += line
            count += 1
            
        if chunk:
            embed.description = chunk
            embed.set_footer(text=f"Total: {count} roles")
            await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @ls_command.command(name="channels")
    async def ls_channels(self, ctx, *args):
        """List channels. Usage: ?ls channels [?w <Role/User> <Permission>]"""
        
        # Check for ?w argument for filtering
        full_args = " ".join(args)
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
                            await ctx.send(f"❌ Could not find Role or Member named `{target_str}`.")
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
                        await ctx.send(f"❌ Invalid permission `{perm_str}`.")
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
                
                # Build Embed
                embed = discord.Embed(
                    title=f"Channel Audit: {perm_attr}",
                    description=f"Showing channels where **{target.mention}** can `{perm_attr}`.",
                    color=0x5865F2
                )
                
                # Build list text
                lines = [f"{c.mention} (`{c.id}`)" for c in matched]
                full_text = "\n".join(lines)
                
                # Handle large output
                if len(full_text) > 4000:
                    chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
                    embed.description = chunks[0] + "..."
                    await ctx.send(embed=embed)
                    if len(chunks) > 1:
                        await ctx.send(f"... {len(matched) - len(chunks[0].splitlines())} more channels omitted.")
                else:
                    embed.description = full_text
                    await ctx.send(embed=embed)
                    
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
                # We can list categories separately or as headers. 
                # Let's verify if 'categories' dict keys cover this.
                if c not in categories:
                    categories[c] = [] # Ensure category exists even if empty
            else:
                no_category.append(c)
                
        embed = discord.Embed(title=f"Channels in {ctx.guild.name}", color=0x5865F2)
        
        description = ""
        
        # List non-categorized first
        if no_category:
            description += "**Uncategorized**\n"
            for c in no_category:
                description += f"{c.mention}\n"
            description += "\n"
            
        # Sort categories by position
        sorted_cats = sorted(categories.keys(), key=lambda x: x.position)
        
        for cat in sorted_cats:
            chans = categories[cat]
            description += f"**{cat.name.upper()}**\n"
            for c in chans:
                description += f"  └ {c.mention}\n"
            description += "\n"
            
        if len(description) > 4000:
            description = description[:4000] + "\n...(truncated)"
            
        embed.description = description
        await ctx.send(embed=embed)

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
                            await ctx.send(f"❌ Could not find Role or Member named `{target_str}`.")
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
                        await ctx.send(f"❌ Invalid permission `{perm_str}`.")
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
                
                embed = discord.Embed(
                    title=f"Category Audit: {perm_attr}",
                    description=f"Showing categories where **{target.mention}** can `{perm_attr}`.",
                    color=0x5865F2
                )
                
                lines = [f"{c.name.upper()} (`{c.id}`)" for c in matched]
                full_text = "\n".join(lines)
                
                if len(full_text) > 4000:
                    chunks = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
                    embed.description = chunks[0] + "..."
                    await ctx.send(embed=embed)
                else:
                    embed.description = full_text
                    await ctx.send(embed=embed)
                    
            except Exception as e:
                await ctx.send(f"Error parsing arguments: {str(e)}")
            return

        # Default: List all categories
        categories = sorted(ctx.guild.categories, key=lambda c: c.position)
        
        embed = discord.Embed(title=f"Categories in {ctx.guild.name}", color=0x5865F2)
        
        lines = [f"{c.name} (`{c.id}`)" for c in categories]
        full_text = "\n".join(lines)
        
        if len(full_text) > 4000:
             embed.description = full_text[:4000] + "\n...(truncated)"
        else:
             embed.description = full_text or "No categories found."
             
        await ctx.send(embed=embed)

    @ls_command.command(name="bots")
    async def ls_bots(self, ctx):
        """List all bots in the server"""
        bots = [m for m in ctx.guild.members if m.bot]
        
        embed = discord.Embed(
            title=f"Bots in {ctx.guild.name} ({len(bots)})",
            color=0x5865F2
        )
        
        description = ""
        for bot in bots:
            description += f"{bot.mention} {bot.top_role.mention if bot.top_role else ''}\n"
            
        if len(description) > 4000:
             description = description[:4000] + "..."
             
        embed.description = description
        await ctx.send(embed=embed)

    @ls_command.command(name="boosters")
    async def ls_boosters(self, ctx):
        """List current server boosters"""
        boosters = ctx.guild.premium_subscribers
        
        if not boosters:
             embed = discord.Embed(
                title=f"Server Boosters (Tier {ctx.guild.premium_tier})",
                description="This server has no boosters yet!",
                color=0x5865F2
             )
             await ctx.send(embed=embed)
             return

        embed = discord.Embed(
            title=f"Server Boosters ({ctx.guild.premium_subscription_count} boosts)",
            description=f"Current Level: **Tier {ctx.guild.premium_tier}**",
            color=0x5865F2
        )
        
        lines = []
        for member in boosters:
            # Format time since boost
            if member.premium_since:
                timestamp = f"<t:{int(member.premium_since.timestamp())}:R>"
            else:
                timestamp = "Unknown time"
            lines.append(f"• {member.mention} - {timestamp}")
            
        embed.add_field(name="Current Boosters", value="\n".join(lines) or "None", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(EmbedBuilder(bot))
