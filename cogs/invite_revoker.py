import discord
import logging
from discord.ext import commands

INVITE = logging.getLogger("invite")


class SilentInviteRevoker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Configure which roles should not be allowed to create invites

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        """Silently revoke invites created by members with restricted roles"""
        # Skip if no inviter (like vanity URLs)
        restricted_role = invite.guild.get_role(
            1251457217576833135
        )  # Test role, replace with member role
        if invite.inviter is None:
            return

        # Get the member object to check roles

        member = invite.guild.get_member(invite.inviter.id)

        if not member:
            member = await invite.guild.fetch_member(
                invite.inviter.id
            )  # Works if member is not in cache

        if restricted_role in member.roles and member:
            try:
                await invite.delete()
                INVITE.info(
                    "Silently revoked invite %s from %s (restricted role holder)",
                    invite.code,
                    member,
                )
            except discord.HTTPException as e:
                INVITE.exception("Failed to revoke invite: ", e)


async def setup(bot):
    await bot.add_cog(SilentInviteRevoker(bot))
