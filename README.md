<div align="center">

# Schrödinger aka CodeVerse Bot

**Enterprise-grade Discord bot for programming communities with comprehensive management tools**

![Status](https://img.shields.io/badge/status-active-success) ![License](https://img.shields.io/badge/license-MIT-blue) ![Python](https://img.shields.io/badge/python-3.12-blue)

*Professional Staff Management • Advanced Moderation • Support Ticket System • Data Persistence • Programming Utilities • Community Engagement*

</div>

## Features Overview

- **Moderation suite** -> purge, kick, ban, softban, timeout (`?mute` works as a prefix alias), slowmode, locks/lockdowns, tempban, and more, with permit-based delegation for staff. Mutes can be marked non-appealable via `?a` tag (prefix) or `appeal:False` (slash).
- **Warning system** -> issue, revoke, and review warnings (`/warn`, `/warnings view|modify|clear`).
- **Support tickets** -> persistent, thread-based ticket system with category routing, transcripts, and logging.
- **Permit system** -> create named permission groups (roles), assign them to members, and let staff act without native Discord permissions. Full lifecycle: `new`, `add`, `list`, `check`, `delete`, `rename`, `check-all`.
- **Reaction roles** -> automatic role assignment through emoji reactions.
- **Sticky messages** -> keep important announcements pinned in channels.
- **Appeals** -> ban/mute appeals with DM workflow and staff review.
- **Centralized logging** -> webhook-based event logging with per-guild channel configuration.
- **Thread management** -> close/archive, pin, and unpin threads.
- **Embed builder & server tooling** -> interactive embed creator plus `?ls` channel/role/permission auditing tools, including `?ls channels ?v` (view permissions) and `?ls noroles` (members with no roles).
- **Rules & community** -> quick rule-reference commands (`?r1`…`?r13`, `?r34`, `?tldr`). Rules commands are usable by anyone via prefix, no authorized role needed.
- **Welcome system** -> Components V2 welcome DM sent to new members with Quick Links, How to Verify (ephemeral guide), Website, and GitHub buttons. `?sendwm` for testing.
- **Welcome system** -> Components V2 welcome DM with Quick Links, How to Verify button (ephemeral guide), Website and GitHub links.
- **Protection** -> protected-channel auto-timeout, authorized-server enforcement, and more.

> **Prefix:** `?` (per-guild override via `/prefix`) • **Slash:** `/` • **Access:** Authorized role or bot owner only

## Recent Changes

- **Anti-ping overhaul** -> every `.mention` in embeds replaced with `display_name`/`role.name` across 24 files, plus `allowed_mentions=AllowedMentions.none()` on all 100+ `send()` calls. No more accidental `@user`, `@role`, or `@everyone` pings from bot embeds.
- **`?nuke` rewrite** -> reaction-based confirmation (green tick / red cross), detailed channel stats embed, 30-second timeout, nuclear bomb GIF success embed in the recreated channel. Protected channel names and announcement channels are blocked.
- **Authorized role gate** -> only users with the `AUTHORISED_ROLE_ID` role (or the bot owner) can use bot commands. Unauthorized prefix commands are silently ignored; slash commands show a "Not Permitted" card.
- **Permit system works everywhere** -> all moderation commands (kick, ban, timeout, warn, lock, unlock, purge, clean, slowmode, nickname, softban, unban, untimeout) now respect the custom permit system, not just native Discord permissions.
- **Non-appealable mutes** -> `/timeout appeal:False` (slash) or `?mute @user 10m reason ?a` (prefix) marks a timeout as non-appealable. The appeals system skips the DM for non-appealable mutes.
- **Components V2 moderation cards** -> all moderation confirmations (kick, ban, softban, timeout, untimeout, warn, unwarn, lock, unlock, slowmode, nickname) now render as clean Components V2 containers with accent colors and no emojis.
- **Specific error messages** -> every error message now names the exact permission needed, tells the user to ask an admin, and explains where to fix it.
- **`?ls channels ?v`** -> audit which roles/users can view a specific channel via permission overwrites.
- **`?ls noroles`** -> list all members who have no roles (only @everyone).
- **Warn logging** -> warnings are now logged to `LOG_CHANNEL_WARNINGS_ID` via the centralized logging system.
- **Components V2 dashboards** -> major surfaces now render with Discord's new Components V2 (containers, text displays, sections) instead of classic embeds: the `/help` menu (categories fit on one page, command detail cards), all `?ls` auditing tools (no more 4000-char truncation hacks), the `?appeals` admin list (one Section per appeal with colored status badges + avatar thumbnails), moderation log cards (ban/unban/kick/timeout/warn entries with user-avatar accessories), and `?diag` (a color-coded health dashboard, green/red per subsystem).
- **Embed builder overhaul** -> `/embed` is now an interactive Components V2 builder: an ephemeral dashboard where every section (title, description, color, footer, pre-message, author, media, webhook, link button, target channel) has an Edit button that opens a modal, plus Save & Cancel. Title is optional, you can set the webhook name/avatar the embed is sent as, add a bottom link button, and `/editembed` re-opens the same builder pre-filled for in-place edits.
- **Appeals** -> accepting an appeal whose timeout already expired (or whose member left) no longer approves a dead punishment: the accept is blocked, the appeal is auto-resolved, and it's logged to the appeals channel. Tempbans are also persisted to the database so they survive bot restarts.
- **Channel update logging** -> permission change entries no longer use check/cross emojis; each change is now shown as inline code (`added: send_messages`, `removed: view_channel`, `reset: read_messages`).
- **Custom Discord emojis** -> bot messages now use `<:greentick:1529045309081256026>` and `<:redtick:1529045360742502481>` instead of Unicode emojis.
- **Updated server rules** -> R1-R12 updated with new wording, R13 (Use Common Sense) added, R34 removed.
- **Permit management commands** -> added `/permit delete`, `/permit rename`, and `/permit check-all` (paginated view of every user with permits).
- **Environment-based configuration** -> all Discord channel/category/user/role/guild IDs moved out of the code into a single `.env` file (fallback defaults live in `config.py`).

## Quick Start

### Prerequisites
- Python 3.12+
- Discord bot token
- Server/Guild ID

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/youngcoder45/codeverse-bot.git
   cd codeverse-bot
   ```

2. **Set up environment**
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   Copy `.env.example` to `.env` and fill in the values:
   ```env
   # Required
   DISCORD_TOKEN=your_bot_token_here
   GUILD_ID=your_server_id_here

   # Authorized guilds (comma-separated) the bot only operates here
   AUTHORIZED_GUILD_IDS=your_server_id_here
   ```

   Every Discord ID the bot uses (channels, roles, users, guilds) is configured through `.env`.
   See [Configuration](#configuration) and `.env.example` for the full list.

5. **Run the bot**
   ```bash
   python main.py
   ```

### Windows One-Liner
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; python main.py
```

## Command Reference

A full, maintained reference lives in [`docs/COMMAND_REFERENCE.md`](docs/COMMAND_REFERENCE.md). Quick overview by category:

### Core
| Command | Description |
|---------|-------------|
| `/help` • `?help` | Interactive Components V2 help menu |
| `/ping` | Bot latency check |
| `/info` • `?info` | Detailed user information (alias `userinfo`) |
| `/get-user-id` | Get a Discord ID from a mention |
| `/prefix` | View or change the per-guild prefix |
| `/report` | Report a message to moderators |
| `/diag` • `?diag` | Color-coded health dashboard (prefix only) |

### Moderation
| Command | Description |
|---------|-------------|
| `/purge` • `/clean` | Delete messages / clean bot messages |
| `/kick` • `/ban` • `/unban` • `/softban` | Member removal |
| `/timeout` (alias `?mute`) • `/untimeout` (alias `?unmute`) • `/tempban` | Temporary actions (`?a` tag or `appeal:False` for non-appealable) |
| `/slowmode` • `/lock` • `/unlock` • `/lockdown` • `/unlockdown` | Channel control |
| `/nuke` • `/massban` | Owner-only destructive tools |
| `/role` • `/addmod` • `/nickname` | Role & nickname management |
| `/verify` | Verification panel with role selection |
| `/serverinfo` • `/roleinfo` • `/avatar` | Information commands |
| `?hide` • `?unhide` | Channel visibility (prefix only) |

### Warnings
| Command | Description |
|---------|-------------|
| `/warn` | Issue a warning |
| `/unwarn` | Remove a warning by ID |
| `/warnings view` | View a user's warning history |
| `/warnings modify` | Revoke a warning by case ID |
| `/warnings clear` | Clear all warnings for a user |

### Permits
| Command | Description |
|---------|-------------|
| `/permit new` | Create a permit role and pick permissions |
| `/permit add` | Assign a permit role to a member |
| `/permit list` | List all permit roles |
| `/permit check` | Check a member's permits |
| `/permit delete` | Delete a permit role (with confirmation) |
| `/permit rename` | Rename a permit role |
| `/permit check-all` | Show every user with permits (paginated) |

### Tickets
| Command | Description |
|---------|-------------|
| `/ticket panel` | Create a persistent ticket panel |
| `/ticket list` • `/ticket stats` | View tickets / statistics |
| `/ticket forceclose` | Force-close a ticket |
| `/ticket log` • `/ticket support` • `/ticket report` • `/ticket partner` • `/ticket category` | Configure roles/channels/categories |

### Reaction Roles & Sticky Messages
| Command | Description |
|---------|-------------|
| `/rr` | Create a reaction-role message |
| `/rrlist` • `/rrremove` | List / remove reaction-role setups |
| `/stickymessage` | Set a sticky message in a channel |
| `/removesticky` • `/liststicky` | Remove / list sticky messages |

### Threads, Appeals & Logging
| Command | Description |
|---------|-------------|
| `?close` • `?pin` • `?unpin` | Thread management (prefix only) |
| `/appeals` • `/appealinfo` • `/appealcancel` | Appeal workflow |
| `/setlogchannels` | Configure per-guild log channels |

### Utility & Rules
| Command | Description |
|---------|-------------|
| `/embed` • `/editembed` | Interactive Components V2 embed builder (author, webhook identity, link button) |
| `?ls role/perms/perm/noperms/noroles/members/channels/categories/bots/boosters` | Server auditing tools (prefix only, `?ls channels ?v` for view audit) |
| `?r1`…`?r13` • `?r34` • `?tldr` | Quick rule reference (prefix only) |
| `?permits` | Show all available permits with permissions |
| `?sendwm` | Send the welcome DM to a user for testing (prefix only) |

## Project Structure

```
codeverse-bot/
├── main.py                      # Production entrypoint
├── config.py                    # Central configuration (reads .env)
├── .env.example                 # Environment variable template
├── src/
│   ├── bot.py                   # Bot initialization & cog loading
│   ├── commands/
│   │   ├── core.py              # Core commands (ping, info, help, report, prefix)
│   │   ├── diagnostics.py       # ?diag
│   │   ├── modcog.py            # Main moderation commands
│   │   ├── advanced_moderation.py # tempban, hide/unhide
│   │   ├── appeals.py           # Appeal workflow
│   │   ├── tickets.py           # Ticket system
│   │   ├── permits.py           # Permit permission groups
│   │   ├── reaction_roles.py    # Reaction-role assignment
│   │   ├── sticky_message.py    # Sticky messages
│   │   ├── spam_catch.py        # Protected-channel auto-timeout
│   │   ├── thread.py            # Thread close/pin/unpin
│   │   ├── help_thread_notification.py # ?needhelp (staff)
│   │   ├── rules.py             # ?r1…?r12, ?tldr
│   │   ├── utility.py           # /embed, /editembed, ?ls tools
│   │   ├── help_menu.py         # Dynamic /help menu
│   │   ├── logging/             # Webhook-based logging system
│   │   └── modules/sam/         # Warning system (SAM module)
│   ├── events/
│   │   ├── member_events.py     # Welcome DMs on join
│   │   └── message_handler.py   # Intro reactions + error handling
│   ├── utils/                   # Database, embeds, helpers, webhooks, keep-alive
│   └── data/                    # JSON data (quotes, questions, challenges)
├── data/                        # SQLite database files
├── requirements.txt             # Python dependencies
└── runtime.txt                  # Python version for hosting
```

## Configuration

The bot reads all configuration from `.env` via `config.py`. Copy `.env.example` → `.env`.

### Required
- `DISCORD_TOKEN` -> your bot token
- `GUILD_ID` -> your main server ID
- `AUTHORIZED_GUILD_IDS` -> comma-separated guilds the bot is allowed to operate in

### Discord IDs (all optional -> code falls back to defaults)

**Guilds:** `AUTHORIZED_GUILD_IDS`, `MAIN_GUILD_ID`

**Roles:** `MODERATION_ROLE_ID`, `STAFF_ROLE_ID`, `ADMIN_BYPASS_ROLE_ID`, `HELP_MODERATOR_ROLE_ID`, `VERIFY_STREAM_ROLE_ID`, `VERIFY_VOICE_ROLE_ID`, `VERIFY_EMBED_ROLE_ID`, `VERIFY_JOIN_VC_ROLE_ID`

**Users:** `BOT_OWNER_ID`, `APPEALS_MODERATOR_USER_ID`, `AUTHORISED_ROLE_ID` (role required to use the bot)

**Channels:** `INTRODUCTION_CHANNEL_ID`, `WELCOME_ROLES_CHANNEL_ID`, `WELCOME_GENERAL_CHANNEL_ID`, `WELCOME_IDEAS_CHANNEL_ID`, `HELP_FORUM_ID`, `WELCOME_TICKET_CHANNEL_ID`, `HELP_NOTIFY_TARGET_CHANNEL_ID`, `HELP_GUIDE_CHANNEL_ID`, `REPORT_CHANNEL_ID`, `PROTECTED_CHANNEL_ID`, `TICKET_LOGS_CHANNEL_ID`, `APPEALS_LOG_CHANNEL_ID`

**Logging channels:** `LOG_CHANNEL_MEMBERS_ID`, `LOG_CHANNEL_ROLES_ID`, `LOG_CHANNEL_CHANNELS_ID`, `LOG_CHANNEL_TIMEOUTS_ID`, `LOG_CHANNEL_VOICE_ID`, `LOG_CHANNEL_WARNINGS_ID`, `LOG_CHANNEL_MEMBER_ROLE_CHANGES_ID`, `LOG_CHANNEL_MODERATION_ID`, `LOG_CHANNEL_TICKETS_ID`, `LOG_CHANNEL_STAFF_POINTS_ID`

**Other:** `APPEALS_LOG_CHANNEL_IDS`, `DATABASE_NAME`, `LOG_CHANNEL_NAME`, `STATUS_MESSAGE`, `PORT`, `HOSTING_PLATFORM`, `INSTANCE_ID`, `BOT_LOCK_FILE`, `ALLOW_MULTIPLE_INSTANCES`

### Required Bot Permissions

- **View Channels**, **Send Messages**, **Embed Links**, **Add Reactions**, **Use Slash Commands**, **Read Message History**
- **Moderation:** Manage Messages, Kick Members, Ban Members, Moderate Members, Manage Channels, Manage Nicknames, Manage Roles
- **Advanced:** Create Public Threads, Manage Threads, Manage Webhooks (for webhook logging)

## Development

### Adding New Commands

1. Create or edit a cog file in `src/commands/`
2. Add a command with the appropriate decorator:
   ```python
   @commands.hybrid_command(name="mycommand", help="Description")
   async def my_command(self, ctx):
       await ctx.send("Hello!")
   ```
3. Add the cog to `COGS_TO_LOAD` in `src/bot.py`

### Testing Changes

```bash
python -m py_compile src/commands/your_cog.py
```

## Deployment

### Railway / Heroku
1. Connect your GitHub repository
2. Set environment variables in the platform dashboard (token, guild IDs)
3. Deploy automatically on push

### VPS / Self-Hosted
1. Clone the repository on the server
2. Create `.env` with your configuration
3. Run with a process manager (systemd / PM2)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes
4. Push to the branch and open a Pull Request

## License

This project is licensed under the MIT License see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: Report bugs via GitHub Issues
- **Discord**: https://discord.gg/3xKFvKhuGR
- **Email**: contact@aditya-verma.me
