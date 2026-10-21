import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput
import json
import os
import asyncio
import datetime

from config import (
    TICKET_PANEL_CHANNEL_ID, TICKET_CLAIM_CHANNEL_ID, TICKET_CATEGORY_ID,
    TICKET_LOG_CHANNEL_ID, SUPPORT_ROLE_IDS, WELCOME_COLOR
)

DATA_FILE = 'data/tickets_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

TICKET_CATEGORIES = [
    discord.SelectOption(label='General Support', description='We pretend to know what we are doing', emoji='❓'),
    discord.SelectOption(label='Job Applicant', description='We are not hiring but apply anyway', emoji='💼'),
    discord.SelectOption(label='Other Server Issue', description='Something broke. Definitely not our fault', emoji='🔧'),
    discord.SelectOption(label='Website Issue', description='Did you try turning it off and on again', emoji='🌐'),
    discord.SelectOption(label='Complaint', description='We will read this and totally not ignore it', emoji='😤'),
]

class TicketReasonModal(Modal, title='Create a Ticket'):
    reason = TextInput(label='Reason', placeholder='Please describe your issue...', style=discord.TextStyle.long, max_length=1000)

    def __init__(self, bot, category):
        super().__init__()
        self.bot = bot
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message('Creating your ticket...', ephemeral=True)
        try:
            await handle_ticket_submit(interaction, self.bot, self.category, self.reason.value)
        except Exception as e:
            try:
                await interaction.edit_original_response(content=f'Failed: {e}')
            except:
                pass

class TicketSelectView(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(TicketCategorySelect(bot))

class TicketCategorySelect(Select):
    def __init__(self, bot):
        super().__init__(placeholder='Select a ticket category...', options=TICKET_CATEGORIES, custom_id='ticket_cat_select')
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        try:
            modal = TicketReasonModal(self.bot, self.values[0])
            await interaction.response.send_modal(modal)
        except Exception as e:
            try:
                await interaction.response.send_message(f'Error: {e}', ephemeral=True)
            except:
                pass

class JoinTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JoinTicketButton())

class JoinTicketButton(Button):
    def __init__(self):
        super().__init__(label='Join Ticket', style=discord.ButtonStyle.primary, emoji='🎟️', custom_id='join_ticket')

    async def callback(self, interaction: discord.Interaction):
        if not any(interaction.user.get_role(rid) for rid in SUPPORT_ROLE_IDS):
            await interaction.response.send_message('Only support staff can claim tickets.', ephemeral=True)
            return

        data = load_data()
        gid = str(interaction.guild_id)
        msg_id = str(interaction.message.id)
        guild_data = data.get(gid, {})
        pending = guild_data.get('pending', {})

        ticket_info = pending.get(msg_id)
        if not ticket_info:
            await interaction.response.send_message('This ticket no longer exists.', ephemeral=True)
            return

        if ticket_info.get('claimed'):
            await interaction.response.send_message('This ticket has already been claimed.', ephemeral=True)
            return

        user_id = ticket_info['user_id']
        user = interaction.guild.get_member(user_id)
        if not user:
            await interaction.response.send_message('The ticket creator is no longer in the server.', ephemeral=True)
            return

        ticket_num = ticket_info['ticket_num']
        category_channel = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        cat = category_channel if isinstance(category_channel, discord.CategoryChannel) else None

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        for rid in SUPPORT_ROLE_IDS:
            role = interaction.guild.get_role(rid)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f'ticket-{ticket_num}'
        ticket_channel = await interaction.guild.create_text_channel(
            channel_name, category=cat, overwrites=overwrites,
            reason=f'Ticket claimed by {interaction.user}'
        )

        ticket_info['claimed'] = True
        ticket_info['claimed_by'] = interaction.user.id
        ticket_info['claimed_by_name'] = interaction.user.display_name
        ticket_info['channel_id'] = ticket_channel.id
        save_data(data)

        embed = discord.Embed(
            title=f'Ticket - {ticket_info["category"]}',
            description=f'Welcome {user.mention}\n**Reason:** {ticket_info["reason"]}',
            color=WELCOME_COLOR
        )
        embed.add_field(name='Category', value=ticket_info['category'], inline=True)
        embed.add_field(name='Status', value=f'✅ Claimed by {interaction.user.mention}', inline=True)
        embed.set_footer(text=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        async def close_cb(interaction: discord.Interaction):
            can_close = any(
                interaction.user.get_role(rid) for rid in SUPPORT_ROLE_IDS
            ) or interaction.user.guild_permissions.administrator
            if not can_close:
                await interaction.response.send_message('Only staff can close tickets.', ephemeral=True)
                return
            await interaction.response.send_message(embed=discord.Embed(
                description=f'Closing ticket by {interaction.user.mention}...', color=discord.Color.red()))
            await log_ticket_action(interaction.guild,
                f'Ticket {interaction.channel.name} closed by {interaction.user} ({interaction.user.id})')
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete(reason=f'Ticket closed by {interaction.user}')
            except:
                pass

        close_btn = Button(label='Close Ticket', style=discord.ButtonStyle.danger, emoji='🔒', custom_id='close_ticket')
        close_btn.callback = close_cb
        view = View(timeout=None)
        view.add_item(close_btn)
        await ticket_channel.send(embed=embed, view=view)

        log_msg = (
            f'Ticket {channel_name} claimed by {interaction.user} ({interaction.user.id})\n'
            f'Category: {ticket_info["category"]}\nReason: {ticket_info["reason"]}\n'
            f'Channel: {ticket_channel.mention}'
        )
        await log_ticket_action(interaction.guild, log_msg)

        claim_embed = discord.Embed(
            description=f'Ticket claimed by {interaction.user.mention}',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=claim_embed, ephemeral=True)

        await update_claim_message(interaction.message, ticket_info)

class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton())

class CloseTicketButton(Button):
    def __init__(self):
        super().__init__(label='Close Ticket', style=discord.ButtonStyle.danger, emoji='🔒', custom_id='close_ticket')

    async def callback(self, interaction: discord.Interaction):
        can_close = any(
            interaction.user.get_role(rid) for rid in SUPPORT_ROLE_IDS
        ) or interaction.user.guild_permissions.administrator

        if not can_close:
            await interaction.response.send_message('Only staff can close tickets.', ephemeral=True)
            return

        await interaction.response.send_message(embed=discord.Embed(
            description=f'Closing ticket by {interaction.user.mention}...', color=discord.Color.red()))
        await log_ticket_action(interaction.guild,
            f'Ticket {interaction.channel.name} closed by {interaction.user} ({interaction.user.id})')
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f'Ticket closed by {interaction.user}')
        except:
            pass

async def handle_ticket_submit(interaction: discord.Interaction, bot, category: str, reason: str):
    guild = interaction.guild
    user = interaction.user
    gid = str(guild.id)

    data = load_data()
    data.setdefault(gid, {})
    data[gid].setdefault('counter', 0)
    data[gid].setdefault('pending', {})

    data[gid]['counter'] += 1
    ticket_num = data[gid]['counter']
    save_data(data)

    claim_channel = guild.get_channel(TICKET_CLAIM_CHANNEL_ID)
    if not claim_channel:
        await interaction.edit_original_response(content='Claim channel not found. Contact an admin.')
        return

    ticket_info = {
        'ticket_num': ticket_num,
        'user_id': user.id,
        'username': user.display_name,
        'category': category,
        'reason': reason,
        'claimed': False,
        'claimed_by': None,
        'claimed_by_name': None,
        'channel_id': None,
    }

    embed = discord.Embed(
        title='🎟️ Join Ticket',
        description=(
            f'ticket-{ticket_num} with ID: {ticket_num} has been opened. '
            f'Press the button below to join it.\n\n'
            f'🔓 **Opened By**\n▸ {user.mention}\n\n'
            f'📋 **Panel**\n▸ {category}\n\n'
            f'👥 **Staff In Ticket**\n▸ 0\n\n'
            f'👤 **Staff Members**\n▸ None'
        ),
        color=WELCOME_COLOR
    )
    embed.set_footer(text='Animedex')

    view = JoinTicketView()
    claim_msg = await claim_channel.send(embed=embed, view=view)
    ticket_info['claim_message_id'] = claim_msg.id

    data[gid]['pending'][str(claim_msg.id)] = ticket_info
    save_data(data)

    await interaction.edit_original_response(
        content=f'Ticket #{ticket_num} submitted! Staff will join shortly.')

    await log_ticket_action(guild,
        f'Ticket #{ticket_num} created by {user} ({user.id})\n'
        f'Category: {category}\nReason: {reason}\n'
        f'Claim message: {claim_msg.jump_url}')

async def update_claim_message(message, ticket_info):
    embed = discord.Embed(
        title='🎟️ Join Ticket',
        description=(
            f'ticket-{ticket_info["ticket_num"]} with ID: {ticket_info["ticket_num"]} has been opened. '
            f'Press the button below to join it.\n\n'
            f'🔓 **Opened By**\n▸ {ticket_info["username"]}\n\n'
            f'📋 **Panel**\n▸ {ticket_info["category"]}\n\n'
            f'👥 **Staff In Ticket**\n▸ 1\n\n'
            f'👤 **Staff Members**\n▸ {ticket_info["claimed_by_name"]}'
        ),
        color=WELCOME_COLOR
    )
    embed.set_footer(text='Animedex')

    disabled_view = JoinTicketView()
    for item in disabled_view.children:
        item.disabled = True

    try:
        await message.edit(embed=embed, view=disabled_view)
    except:
        pass

async def log_ticket_action(guild, message):
    log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if not log_channel:
        return
    embed = discord.Embed(
        title='📋 Ticket Log',
        description=message,
        color=WELCOME_COLOR,
        timestamp=datetime.datetime.now()
    )
    try:
        await log_channel.send(embed=embed)
    except:
        pass

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(TicketSelectView(bot))
        self.bot.add_view(JoinTicketView())
        self.bot.add_view(CloseTicketView())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        if message.channel.name.startswith('ticket-') or message.channel.name.startswith('claimed-'):
            emojis = ['👋', '💬', '👍', '✨', '🫡']
            import random
            try:
                await message.add_reaction(random.choice(emojis))
            except:
                pass

    @commands.hybrid_command(name='ticket')
    @app_commands.describe(option='Action to perform')
    @commands.has_permissions(administrator=True)
    async def ticket(self, ctx, option: str = None):
        if option == 'panel' or option is None:
            panel_channel = ctx.guild.get_channel(TICKET_PANEL_CHANNEL_ID) or ctx.channel
            embed = discord.Embed(
                title='🎫 Support Tickets',
                description=(
                    'Need help? Create a ticket and our staff will assist you!\n\n'
                    'Select a category from the dropdown below to get started.'
                ),
                color=WELCOME_COLOR
            )
            embed.add_field(name='How it works', value='1. Select a category\n2. Describe your issue\n3. Wait for staff response', inline=False)
            embed.set_footer(text='Animedex Support Team')
            view = TicketSelectView(self.bot)
            await panel_channel.send(embed=embed, view=view)
            if panel_channel.id != ctx.channel.id:
                await ctx.send(embed=discord.Embed(description=f'Ticket panel sent to {panel_channel.mention}', color=WELCOME_COLOR))
            else:
                try:
                    await ctx.message.delete()
                except:
                    pass
        elif option == 'config':
            roles = [ctx.guild.get_role(rid) for rid in SUPPORT_ROLE_IDS if ctx.guild.get_role(rid)]
            embed = discord.Embed(title='Ticket Configuration', color=WELCOME_COLOR)
            embed.add_field(name='Support Roles', value='\n'.join(r.mention for r in roles) if roles else 'None', inline=False)
            embed.add_field(name='Panel Channel', value=f'<#{TICKET_PANEL_CHANNEL_ID}>', inline=False)
            embed.add_field(name='Claim Channel', value=f'<#{TICKET_CLAIM_CHANNEL_ID}>', inline=False)
            embed.add_field(name='Category', value=f'<#{TICKET_CATEGORY_ID}>', inline=True)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name='ticket-close')
    @app_commands.describe(reason='Reason for closing')
    async def ticket_close(self, ctx, *, reason: str = 'No reason'):
        can_close = any(ctx.author.get_role(rid) for rid in SUPPORT_ROLE_IDS) or ctx.author.guild_permissions.administrator
        if not can_close:
            await ctx.send('Only staff can close tickets.', ephemeral=True)
            return
        await ctx.send(embed=discord.Embed(description=f'Closing ticket. Reason: {reason}', color=discord.Color.red()))
        await log_ticket_action(ctx.guild, f'Ticket {ctx.channel.name} closed by {ctx.author} ({ctx.author.id}). Reason: {reason}')
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete(reason=f'Ticket closed by {ctx.author}')
        except:
            pass

async def setup(bot):
    await bot.add_cog(Tickets(bot))
