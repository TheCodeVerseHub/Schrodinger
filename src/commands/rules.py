import discord
from discord.ext import commands


class RulesCog(commands.Cog):
    """Commands for displaying server rules."""

    def __init__(self, bot):
        self.bot = bot
        self.intro = "Rules may change at any time. Staff may act against behavior that harms the community even if it is not explicitly listed below."
        self.rules = {
            "r1": (
                "**R1 \u276f Follow Discord Terms & Community Guidelines**\n\n"
                "All members must follow Discord's Terms of Service and Community Guidelines. "
                "Server rules supplement Discord's rules. Approved client modifications such as "
                "Vencord or BetterDiscord are allowed if they comply with Discord ToS."
            ),
            "r2": (
                "**R2 \u276f Respect Everyone**\n\n"
                "Treat all members, staff, guests, and public figures with respect. Personal attacks, "
                "harassment, bullying, threats, intimidation, or hostile behavior are not allowed. "
                "This is NOT a Dating Server. Being a creep, DMing random members, or asking for "
                "pictures or phone numbers is strictly prohibited."
            ),
            "r3": (
                "**R3 \u276f No Hate or Discrimination**\n\n"
                "Racism, casteism, sexism, religious hatred, xenophobia, homophobia, or discrimination "
                "of any kind is prohibited. Do not use someone's identity, background, or beliefs as an insult."
            ),
            "r4": (
                "**R4 \u276f Protect Privacy**\n\n"
                "Sharing, leaking, or requesting personal information is prohibited. This includes names, "
                "phone numbers, addresses, IPs, IDs, social media accounts, and similar data. Doxxing, "
                "swatting, or related threats will result in a permanent ban."
            ),
            "r5": (
                "**R5 \u276f No Scams, Malware, or Malicious Activity**\n\n"
                "Scams, phishing, malware, viruses, IP grabbers, malicious links, and similar harmful "
                "content are prohibited. Cybersecurity discussions are allowed only in designated "
                "channels and must not promote abuse."
            ),
            "r6": (
                "**R6 \u276f Keep Content Appropriate**\n\n"
                "NSFW, pornographic, graphic, gore, shock, or illegal content is not allowed. "
                "Attempts to bypass this rule are also prohibited."
            ),
            "r7": (
                "**R7 \u276f No Extremism, Violence, or Criminal Advocacy**\n\n"
                "Do not promote or encourage violence, terrorism, drugs, weed, criminal activity, or "
                "extremist ideologies. Threats, even as jokes, may result in immediate removal."
            ),
            "r8": (
                "**R8 \u276f No Spam or Advertising**\n\n"
                "Do not spam messages, reactions, sounds, mentions, emojis, or commands. Excessive pings, "
                "unsolicited promotions, advertisements, invite links, and DM advertising are prohibited. "
                "Violations may result in an unappealable permanent ban.\n\n"
                "Low effort Spam AI-generated Content and AI Slop will be Removed! AI assisted Projects "
                "are welcomed but completely using AI for programming and Posting messages will be removed! "
                "If Vibecoded make sure to mention it."
            ),
            "r9": (
                "**R9 \u276f Use Appropriate Channels**\n\n"
                "Keep discussions in relevant channels and follow each channel's topic. Staff may move, "
                "lock, mute, or redirect discussions to maintain order.\n"
                "Use English in public channels this allows more people to participate in chat and is "
                "easy to moderate."
            ),
            "r10": (
                "**R10 \u276f Voice Channel Rules**\n\n"
                "Earrape, soundboard abuse, excessive noise, voice changer abuse, harassment, or "
                "disruption are prohibited. Do not record or share voice conversations without consent. "
                "Respect the purpose of each voice channel. Streaming content that violates server laws "
                "like nsfw and illegal content is Strictly Prohibited."
            ),
            "r11": (
                "**R11 \u276f Profiles Must Follow Server Rules**\n\n"
                "Usernames, nicknames, bios, avatars, statuses, tags, pronouns, banners, and profile "
                "content must comply with server rules and Discord ToS. Impersonation/Catfishing is "
                "prohibited.\nUsing alt accounts to evade moderation or restrictions is prohibited."
            ),
            "r12": (
                "**R12 \u276f Respect Moderation Decisions**\n\n"
                "Respect moderation decisions and use proper appeal channels.\n"
                "If you believe a mistake was made, use the proper appeal or ticket/modmail system "
                "instead of arguing publicly.\n"
                "For ban appeals check <https://thecodeversehub.tech/ban-appeal>"
            ),
            "r13": (
                "**R13 \u276f Use Common Sense**\n\n"
                "Rules cannot cover every situation; exploiting loopholes or intentionally harming the "
                "community is not allowed. Use common sense."
            ),
            "r34": (
                "**R34 \u276f Heyy That's Not Allowed!**\n\n"
                "Rule 34 content is strictly prohibited on this server.\n"
                "This includes images, videos, text, or any other media depicting explicit content of fictional characters.\n"
                "Violations will result in immediate action."
            ),
            "tldr": (
                "**TL;DR**\n"
                "Follow Discord ToS. Respect others. No hate, NSFW, scams, spam, advertising, or "
                "malicious activity. Protect privacy. Use channels correctly. Respect staff. Use common "
                "sense and no alting."
            ),
        }

    async def send_rule(self, ctx, rule_key):
        rule_content = self.rules.get(rule_key)
        if rule_content:
            # Prepend the intro text on first use or for ?tldr
            text = rule_content
            if rule_key == "tldr":
                text = f"*{self.intro}*\n\n{text}"
            embed = discord.Embed(description=text, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Rule `{rule_key}` not found.")

    @commands.command(name="r1", help="R1: Follow Discord Terms & Community Guidelines")
    async def rule1(self, ctx):
        await self.send_rule(ctx, "r1")

    @commands.command(name="r2", help="R2: Respect Everyone")
    async def rule2(self, ctx):
        await self.send_rule(ctx, "r2")

    @commands.command(name="r3", help="R3: No Hate or Discrimination")
    async def rule3(self, ctx):
        await self.send_rule(ctx, "r3")

    @commands.command(name="r4", help="R4: Protect Privacy")
    async def rule4(self, ctx):
        await self.send_rule(ctx, "r4")

    @commands.command(name="r5", help="R5: No Scams, Malware, or Malicious Activity")
    async def rule5(self, ctx):
        await self.send_rule(ctx, "r5")

    @commands.command(name="r6", help="R6: Keep Content Appropriate")
    async def rule6(self, ctx):
        await self.send_rule(ctx, "r6")

    @commands.command(
        name="r7", help="R7: No Extremism, Violence, or Criminal Advocacy"
    )
    async def rule7(self, ctx):
        await self.send_rule(ctx, "r7")

    @commands.command(name="r8", help="R8: No Spam or Advertising")
    async def rule8(self, ctx):
        await self.send_rule(ctx, "r8")

    @commands.command(name="r9", help="R9: Use Appropriate Channels")
    async def rule9(self, ctx):
        await self.send_rule(ctx, "r9")

    @commands.command(name="r10", help="R10: Voice Channel Rules")
    async def rule10(self, ctx):
        await self.send_rule(ctx, "r10")

    @commands.command(name="r11", help="R11: Profiles Must Follow Server Rules")
    async def rule11(self, ctx):
        await self.send_rule(ctx, "r11")

    @commands.command(name="r12", help="R12: Respect Moderation Decisions")
    async def rule12(self, ctx):
        await self.send_rule(ctx, "r12")

    @commands.command(name="r13", help="R13: Use Common Sense")
    async def rule13(self, ctx):
        await self.send_rule(ctx, "r13")

    @commands.command(name="r34", help="R34: Heyy That's Not Allowed!")
    async def rule34(self, ctx):
        await self.send_rule(ctx, "r34")

    @commands.command(name="tldr", help="TL;DR of the rules")
    async def tldr_rule(self, ctx):
        await self.send_rule(ctx, "tldr")


async def setup(bot):
    await bot.add_cog(RulesCog(bot))
