import discord
from discord.ext import commands

from config import (
    INTRODUCTION_CHANNEL_ID,
    WELCOME_ROLES_CHANNEL_ID,
    WELCOME_GENERAL_CHANNEL_ID,
    WELCOME_IDEAS_CHANNEL_ID,
    HELP_FORUM_ID,
    WELCOME_TICKET_CHANNEL_ID,
)


WELCOME_CHANNEL_ID = 1516539384436883537
RULES_SCREENING_URL = "https://support.discord.com/hc/en-us/articles/1500000466882-Rules-Screening-FAQ"
WEBSITE_URL = "https://thecodeversehub.tech"
GITHUB_URL = "https://github.com/youngcoder45/codeverse-bot"


class VerifyView(discord.ui.LayoutView):
    """Ephemeral view shown when the How to Verify button is clicked."""

    def __init__(self, guild_icon_url=None):
        super().__init__(timeout=60)
        container = discord.ui.Container(accent_color=discord.Color.from_rgb(0, 122, 255))
        container.add_item(discord.ui.TextDisplay("## How to Verify"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Step 1:** Go to the verification channel and complete the Wick captcha.\n"
            f"> <#{WELCOME_CHANNEL_ID}>"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**Step 2:** Before verifying, make sure you have read and accepted the server rules.\n"
            f"If you are unsure how Rules Screening works, see Discord's official guide: <{RULES_SCREENING_URL}>"
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "Once both steps are complete you will have full access to the server."
        ))
        self.add_item(container)


class VerifyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="How to Verify",
            style=discord.ButtonStyle.primary,
            custom_id="welcome_verify",
        )

    async def callback(self, interaction: discord.Interaction):
        view = VerifyView()
        await interaction.response.send_message(view=view, ephemeral=True)


class WelcomeView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)


class MemberEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join: track user and send welcome DM."""
        try:
            guild = member.guild
            accent = discord.Color.from_rgb(0, 122, 255)

            container = discord.ui.Container(accent_color=accent)

            # Header
            container.add_item(discord.ui.TextDisplay("## Welcome to The CodeVerse Hub"))
            container.add_item(discord.ui.Separator())

            # Intro
            container.add_item(discord.ui.TextDisplay(
                f"Hello {member.mention}, thank you for joining. "
                f"We are a community of developers, engineers, and tech enthusiasts. "
                f"Here is everything you need to get started."
            ))

            # Channels section
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay("**Quick Links**"))
            container.add_item(discord.ui.TextDisplay(
                f"> <#{INTRODUCTION_CHANNEL_ID}> — Introduce yourself to the community\n"
                f"> <#{WELCOME_ROLES_CHANNEL_ID}> — Pick up your roles\n"
                f"> <#{WELCOME_GENERAL_CHANNEL_ID}> — Join the conversation\n"
                f"> <#{WELCOME_IDEAS_CHANNEL_ID}> — Share ideas and suggestions\n"
                f"> <#{HELP_FORUM_ID}> — Ask for help from the team or experienced members\n"
                f"> <#{WELCOME_TICKET_CHANNEL_ID}> — Contact support via a ticket"
            ))

            # Action buttons
            container.add_item(discord.ui.Separator())
            action_row = discord.ui.ActionRow(
                VerifyButton(),
                discord.ui.Button(
                    label="Website",
                    style=discord.ButtonStyle.link,
                    url=WEBSITE_URL,
                ),
                discord.ui.Button(
                    label="GitHub",
                    style=discord.ButtonStyle.link,
                    url=GITHUB_URL,
                ),
            )
            container.add_item(action_row)

            # Footer
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                f"You are member **#{guild.member_count}**. "
                f"We look forward to having you here."
            ))

            view = WelcomeView()
            view.add_item(container)

            await member.send(view=view)

        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error sending welcome DM: {e}")


async def setup(bot):
    await bot.add_cog(MemberEvents(bot))
