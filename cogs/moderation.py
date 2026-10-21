import discord
from discord.ext import commands
from discord import app_commands
import datetime

from config import CYAN
from utils import small_caps


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='kick')
    @app_commands.describe(member='Member to kick', reason='Reason for kick')
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason='No reason provided'):
        """Kick a member from the server."""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send('You cannot kick someone with an equal or higher role.', ephemeral=True)
            return
        await member.kick(reason=reason)
        embed = discord.Embed(
            title=small_caps('member kicked'),
            description=f'{member.mention} was kicked by {ctx.author.mention}',
            color=CYAN
        )
        embed.add_field(name=small_caps('reason'), value=reason)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='ban')
    @app_commands.describe(member='Member to ban', reason='Reason for ban')
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason='No reason provided'):
        """Ban a member from the server."""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send('You cannot ban someone with an equal or higher role.', ephemeral=True)
            return
        await member.ban(reason=reason)
        embed = discord.Embed(
            title=small_caps('member banned'),
            description=f'{member.mention} was banned by {ctx.author.mention}',
            color=CYAN
        )
        embed.add_field(name=small_caps('reason'), value=reason)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='unban')
    @app_commands.describe(user_id='ID of the user to unban')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str):
        """Unban a user by their ID."""
        try:
            user = await self.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user)
            embed = discord.Embed(
                title=small_caps('member unbanned'),
                description=f'{user.mention} was unbanned',
                color=CYAN
            )
            await ctx.send(embed=embed)
        except:
            await ctx.send('Invalid user ID or user not found.', ephemeral=True)

    @commands.hybrid_command(name='purge', aliases=['clear'])
    @app_commands.describe(amount='Number of messages to delete (1-100)')
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        """Bulk delete 1 to 100 messages from this channel."""
        if amount < 1 or amount > 100:
            await ctx.send('Please provide a number between 1 and 100.', ephemeral=True)
            return
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f'Deleted {len(deleted) - 1} message(s).')
        await msg.delete(delay=3)

    @commands.hybrid_command(name='slowmode', aliases=['sm'])
    @app_commands.describe(seconds='Slowmode delay in seconds (0 to disable)')
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        """Set slowmode delay on this channel (0 to disable)."""
        if seconds < 0 or seconds > 21600:
            await ctx.send('Slowmode must be between 0 and 21600 seconds.', ephemeral=True)
            return
        await ctx.channel.edit(slowmode_delay=seconds)
        msg = 'Slowmode disabled.' if seconds == 0 else f'Slowmode set to {seconds} second(s).'
        await ctx.send(msg)

    @commands.hybrid_command(name='mute', aliases=['timeout'])
    @app_commands.describe(member='Member to mute', duration='Duration (e.g. 10m, 1h, 1d)', reason='Reason')
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, duration: str = '10m', *, reason='No reason provided'):
        """Timeout a member for a duration (e.g. 10m, 1h, 1d)."""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send('You cannot mute someone with an equal or higher role.', ephemeral=True)
            return

        time_map = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
        unit = duration[-1]
        if unit not in time_map:
            await ctx.send('Invalid duration format. Use e.g. 10m, 1h, 1d.', ephemeral=True)
            return
        try:
            amount = int(duration[:-1])
        except ValueError:
            await ctx.send('Invalid duration format.', ephemeral=True)
            return

        total_seconds = amount * time_map[unit]
        if total_seconds < 1 or total_seconds > 2419200:
            await ctx.send('Duration must be between 1 second and 28 days.', ephemeral=True)
            return

        until = discord.utils.utcnow() + datetime.timedelta(seconds=total_seconds)
        await member.timeout(until, reason=reason)
        embed = discord.Embed(
            title=small_caps('member timed out'),
            description=f'{member.mention} was muted',
            color=CYAN
        )
        embed.add_field(name=small_caps('duration'), value=duration)
        embed.add_field(name=small_caps('reason'), value=reason)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='unmute')
    @app_commands.describe(member='Member to unmute')
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        """Remove timeout from a member."""
        if not member.is_timed_out():
            await ctx.send(f'{member.mention} is not muted.', ephemeral=True)
            return
        await member.timeout(None)
        embed = discord.Embed(
            title=small_caps('member unmuted'),
            description=f'{member.mention} was unmuted',
            color=CYAN
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='lock')
    @app_commands.describe(channel='Channel to lock')
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        """Lock a channel so nobody can send messages."""
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=False)
        embed = discord.Embed(
            description='\U0001f512 This channel has been locked.',
            color=CYAN
        )
        await channel.send(embed=embed)

    @commands.hybrid_command(name='unlock')
    @app_commands.describe(channel='Channel to unlock')
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlock a channel to allow messages again."""
        channel = channel or ctx.channel
        await channel.set_permissions(ctx.guild.default_role, send_messages=None)
        embed = discord.Embed(
            description='\U0001f513 This channel has been unlocked.',
            color=CYAN
        )
        await channel.send(embed=embed)

    @commands.hybrid_command(name='warn')
    @app_commands.describe(member='Member to warn', reason='Reason for warning')
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason='No reason provided'):
        """Warn a member and DM them the warning."""
        embed = discord.Embed(
            title=small_caps('warning'),
            description=f'You have been warned in {ctx.guild.name}',
            color=CYAN
        )
        embed.add_field(name=small_caps('moderator'), value=ctx.author.mention)
        embed.add_field(name=small_caps('reason'), value=reason)
        embed.set_footer(text=f'User ID: {member.id}')
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            pass
        await ctx.send(f'{member.mention} has been warned. Reason: {reason}')

    @commands.hybrid_command(name='delete')
    @app_commands.describe(message_id='ID of the message to delete')
    @commands.has_permissions(manage_messages=True)
    async def delete(self, ctx, message_id: str):
        """Delete a specific message by its ID."""
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send('Invalid message ID.', ephemeral=True)
            return

        try:
            msg = await ctx.channel.fetch_message(msg_id)
        except discord.NotFound:
            await ctx.send('Message not found in this channel.', ephemeral=True)
            return
        except discord.Forbidden:
            await ctx.send('I don\'t have permission to read this channel.', ephemeral=True)
            return

        try:
            await msg.delete()
            embed = discord.Embed(
                description=f'{small_caps("message deleted")} by {ctx.author.mention}',
                color=CYAN
            )
            confirmation = await ctx.send(embed=embed)
            await confirmation.delete(delay=3)
        except discord.Forbidden:
            await ctx.send('I don\'t have permission to delete that message.', ephemeral=True)
        except discord.NotFound:
            await ctx.send('Message was already deleted.', ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
