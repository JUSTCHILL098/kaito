import asyncio
import os
import random
import re
import tempfile
import time
import traceback
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, button as ui_button
from discord.ui.select import SelectOption

from config import CYAN, MUSIC_FOOTER, DEFAULT_VOLUME, MAX_PLAYLIST_SIZE, STAY_TIME
from music_utils import (
    Song,
    MusicError,
    NoResults,
    InvalidURL,
    load_playlist,
    search_videos,
    format_time,
    split_bar,
    ffmpeg_exe,
    PLAYLIST_LOOKUP_PATTERN,
)
from utils import small_caps


class PlayerControls(View):
    """Now-playing controls with a live elapsed-time display.

    Row 0 is a single disabled button, which Discord stretches to the full
    width of the message - the "big" clock. It is refreshed by a background
    task while the track plays.
    """

    def __init__(self, cog, queue):
        super().__init__(timeout=None)
        self.cog = cog
        self.queue = queue
        button = self.child_button('mc:time')
        if button is not None:
            button.label = self.cog._time_label(queue)

    def child_button(self, custom_id):
        for child in self.children:
            if getattr(child, 'custom_id', None) == custom_id:
                return child
        return None

    def _apply_volume(self):
        self.cog._apply_volume(self.queue)

    async def interaction_check(self, interaction):
        if self.cog.can_modify(interaction.user, self.queue):
            return True
        await interaction.response.send_message(
            f'You need to be in {self.queue.voice.channel.mention} to use these controls.',
            ephemeral=True,
        )
        return False

    # ── row 0: live clock (full-width) ───────────────────────
    @ui_button(
        custom_id='mc:time', label='0:00 / 0:00',
        style=discord.ButtonStyle.secondary, disabled=True, row=0,
    )
    async def time_display(self, interaction, button):
        await interaction.response.defer()

    # ── row 1: pause / resume / skip ─────────────────────────
    @ui_button(custom_id='mc:pause', label='\u23f8\ufe0f', style=discord.ButtonStyle.primary, row=1)
    async def pause_button(self, interaction, button):
        await interaction.response.defer()
        await self.cog.do_pause(self.queue)
        await self.cog._sync_controls_message(self.queue)
        await interaction.followup.send('\u23f8\ufe0f Paused.', ephemeral=True)

    @ui_button(custom_id='mc:resume', label='\u25b6\ufe0f', style=discord.ButtonStyle.success, row=1)
    async def resume_button(self, interaction, button):
        await interaction.response.defer()
        await self.cog.do_resume(self.queue)
        await self.cog._sync_controls_message(self.queue)
        await interaction.followup.send('\u25b6\ufe0f Resumed.', ephemeral=True)

    @ui_button(custom_id='mc:skip', label='\u23ed\ufe0f', style=discord.ButtonStyle.secondary, row=1)
    async def skip_button(self, interaction, button):
        await interaction.response.defer()
        await self.cog.do_skip(interaction, self.queue)

    # ── row 2: replay / stop ─────────────────────────────────
    @ui_button(custom_id='mc:replay', label='\U0001f501', style=discord.ButtonStyle.secondary, row=2)
    async def replay_button(self, interaction, button):
        await interaction.response.defer()
        await self.cog.do_replay(self.queue)
        await interaction.followup.send('\U0001f501 Replaying this track.', ephemeral=True)

    @ui_button(custom_id='mc:stop', label='\u23f9\ufe0f', style=discord.ButtonStyle.secondary, row=2)
    async def stop_button(self, interaction, button):
        await interaction.response.defer()
        await self.cog.do_stop(interaction, self.queue)

    # ── row 3: close ─────────────────────────────────────────
    @ui_button(custom_id='mc:close', label='\u2716\ufe0f', style=discord.ButtonStyle.danger, row=3)
    async def close_button(self, interaction, button):
        await interaction.response.defer()
        if self.queue.controls_message is interaction.message:
            self.queue.controls_message = None
        self.stop()
        try:
            await interaction.message.delete()
        except Exception:
            pass


class SearchView(View):
    """Select-menu picker for /search."""

    def __init__(self, cog, author, songs, timeout=120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author = author
        self.songs = songs
        self.value = None

        options = []
        for index, song in enumerate(songs[:25], start=1):
            options.append(
                SelectOption(
                    label=f'{index}. {song.title}'[:100],
                    value=str(index - 1),
                    description=f'{song.uploader or "unknown"} \u00b7 {format_time(song.duration)}'[:100],
                )
            )

        select = Select(
            placeholder='Pick up to 10 tracks to play',
            min_values=1,
            max_values=min(10, len(options)),
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message('This search is not yours.', ephemeral=True)
            return

        indices = [int(v) for v in interaction.data['values']]
        self.value = [self.songs[i] for i in indices]
        await interaction.response.edit_message(
            content=f'\u23f3 Loading {len(indices)} track(s)...', view=None
        )
        self.stop()
        await self.cog.enqueue_songs(self.author, interaction.channel, self.value)


class QueuePages(View):
    """Paginated /queue view."""

    def __init__(self, author, embeds, timeout=90):
        super().__init__(timeout=timeout)
        self.author = author
        self.embeds = embeds
        self.page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message('This queue view is not yours.', ephemeral=True)
        return False

    async def _shift(self, interaction, delta):
        self.page = max(0, min(self.page + delta, len(self.embeds) - 1))
        await interaction.response.edit_message(
            content=f'**Page {self.page + 1}/{len(self.embeds)}**',
            embed=self.embeds[self.page],
            view=self,
        )

    @ui_button(custom_id='qp:prev', label='⬅️', style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self._shift(interaction, -1)

    @ui_button(custom_id='qp:stop', label='⏹', style=discord.ButtonStyle.secondary)
    async def close(self, interaction, button):
        await interaction.response.edit_message(view=None)
        self.stop()

    @ui_button(custom_id='qp:next', label='➡️', style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        await self._shift(interaction, 1)


class MusicQueue:
    """Per-guild playback queue."""

    def __init__(self, guild, voice, text_channel):
        self.guild = guild
        self.voice = voice
        self.text_channel = text_channel
        self.songs = []
        self.current = None
        self.volume = DEFAULT_VOLUME
        self.loop = False
        self.muted = False
        self.locked = False
        self.stopped = False
        self.jumped = False
        self.stay_task = None
        self.controls_message = None
        self.controls_view = None
        self.progress_task = None
        self.elapsed = 0.0
        self.started_at = None

    @property
    def is_paused(self):
        return bool(self.voice and self.voice.is_paused())

    @property
    def is_playing(self):
        return bool(self.voice and self.voice.is_playing())

    @property
    def now(self):
        return self.songs[0] if self.songs else None

    def shuffle(self):
        if len(self.songs) > 1:
            random.shuffle(self.songs)

    def start_position(self):
        """Reset the clock to zero for a freshly started track."""
        self.elapsed = 0.0
        self.started_at = None if self.is_paused else time.monotonic()

    def pause_position(self):
        if self.started_at is not None:
            self.elapsed += time.monotonic() - self.started_at
            self.started_at = None

    def resume_position(self):
        if self.started_at is None:
            self.started_at = time.monotonic()

    def position(self):
        pos = self.elapsed
        if self.started_at is not None:
            pos += time.monotonic() - self.started_at
        return max(pos, 0.0)

    def clear_stay_task(self):
        if self.stay_task and not self.stay_task.done():
            self.stay_task.cancel()
        self.stay_task = None
        self.stopped = False


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.workdir = os.path.join(tempfile.gettempdir(), 'tomoe_music')
        os.makedirs(self.workdir, exist_ok=True)

    # ─── helpers ─────────────────────────────────────────────
    def get_queue(self, guild):
        return self.queues.get(guild.id)

    def can_modify(self, member, queue):
        """Mirror evobot's ``canModifyQueue``: must share the bot's channel."""
        if member is None or queue is None or queue.voice is None:
            return False
        channel = member.voice.channel if member.voice else None
        if channel is None or not queue.voice.is_connected():
            return False
        return channel.id == queue.voice.channel.id

    def _apply_volume(self, queue):
        if queue.voice and queue.voice.is_connected():
            queue.voice.volume = 0.0 if queue.muted else queue.volume / 100

    def _time_label(self, queue):
        song = queue.current or queue.now
        total = song.duration if song else 0
        return f'{format_time(int(queue.position()))} / {format_time(total)}'

    async def _sync_controls_message(self, queue):
        """Refresh the now-playing embed + clock button on the tracked message."""
        message = queue.controls_message
        view = queue.controls_view
        song = queue.current or queue.now
        if message is None or view is None or song is None:
            return
        button = view.child_button('mc:time')
        if button is not None:
            button.label = self._time_label(queue)
        embed = self._now_playing_embed(song, queue, seek=int(queue.position()))
        try:
            await message.edit(embed=embed, view=view)
        except Exception:
            pass

    async def _progress_loop(self, queue):
        try:
            while not queue.stopped and queue.controls_message is not None:
                await asyncio.sleep(5)
                song = queue.current or queue.now
                if queue.stopped or song is None:
                    break
                if song.duration and queue.position() >= song.duration + 1:
                    break
                await self._sync_controls_message(queue)
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()

    def _restart_progress(self, queue):
        if queue.progress_task and not queue.progress_task.done():
            queue.progress_task.cancel()
        queue.progress_task = asyncio.create_task(self._progress_loop(queue))

    async def do_skip(self, ctx, queue=None):
        queue = queue or self.get_queue(ctx.guild)
        if queue and queue.voice and queue.voice.is_playing():
            queue.voice.stop()

    async def do_pause(self, queue):
        if queue and queue.voice and queue.voice.is_playing() and not queue.voice.is_paused():
            queue.voice.pause()
            queue.pause_position()
            return True
        return False

    async def do_resume(self, queue):
        if queue and queue.voice and queue.voice.is_paused():
            queue.voice.resume()
            queue.resume_position()
            return True
        return False

    async def do_toggle(self, queue):
        if not queue or not queue.voice:
            return None
        if queue.voice.is_paused():
            queue.voice.resume()
            queue.resume_position()
            return False
        queue.voice.pause()
        queue.pause_position()
        return True

    async def do_replay(self, queue):
        """Restart the current track from the beginning."""
        if not queue or not queue.songs:
            return
        queue.elapsed = 0.0
        queue.started_at = None
        if queue.voice and (queue.voice.is_playing() or queue.voice.is_paused()):
            queue.jumped = True
            queue.voice.stop()
        else:
            await self.play_next(queue)

    async def do_stop(self, ctx, queue=None):
        queue = queue or self.get_queue(ctx.guild)
        if queue:
            self._teardown(queue, notify=True)

    async def do_volume(self, ctx, volume, queue=None):
        queue = queue or self.get_queue(ctx.guild)
        if queue is None:
            return None
        volume = max(0, min(int(volume), 100))
        queue.volume = volume
        self._apply_volume(queue)
        return volume

    async def do_loop(self, ctx, queue=None):
        queue = queue or self.get_queue(ctx.guild)
        if queue is None:
            return None
        queue.loop = not queue.loop
        return queue.loop

    def _teardown(self, queue, notify=False):
        if queue.stopped:
            return
        queue.stopped = True
        queue.loop = False
        for song in queue.songs:
            song.cleanup()
        if queue.current is not None:
            queue.current.cleanup()
        queue.songs.clear()
        if queue.voice and queue.voice.is_playing():
            queue.voice.stop()
        if queue.progress_task and not queue.progress_task.done():
            queue.progress_task.cancel()
        queue.progress_task = None
        queue.controls_view = None
        if queue.controls_message:
            asyncio.create_task(self._safe_delete(queue.controls_message))
            queue.controls_message = None
        if notify:
            asyncio.create_task(self._send(queue, '\U0001f3b5 Queue ended.'))
        if queue.stay_task and not queue.stay_task.done():
            queue.stay_task.cancel()
        queue.stay_task = asyncio.create_task(self._stay_timer(queue))

    async def _stay_timer(self, queue):
        try:
            await asyncio.sleep(STAY_TIME * 60)
        except asyncio.CancelledError:
            return
        except Exception:
            traceback.print_exc()
            return

        if self.queues.get(queue.guild.id) is queue:
            self.queues.pop(queue.guild.id, None)

        channel_name = queue.voice.channel.name if queue.voice and queue.voice.channel else None
        if queue.voice and queue.voice.is_connected():
            try:
                await queue.voice.disconnect(force=True)
            except Exception:
                traceback.print_exc()
            if channel_name:
                await self._send(
                    queue, f'\U0001f5c3️ Leaving **{channel_name}** after {STAY_TIME} minutes of inactivity.'
                )

    async def _safe_delete(self, message):
        try:
            await message.delete()
        except Exception:
            pass

    async def _send(self, queue, content, embed=None, view=None):
        if not queue.text_channel:
            return None
        try:
            return await queue.text_channel.send(content, embed=embed, view=view)
        except Exception:
            traceback.print_exc()
            return None

    def _progress_fields(self, song, queue, seek=0):
        fields = []
        if song.duration > 0:
            fields.append(
                (
                    '\u200b',
                    f'`{format_time(seek)}` `[{split_bar(song.duration, seek)}]` `{format_time(song.duration)}`',
                    False,
                )
            )
        if song.uploader:
            fields.append((small_caps('channel'), song.uploader, True))
        fields.append(
            (
                small_caps('volume'),
                f'{queue.volume}%' + (' \u2014 muted' if queue.muted else ''),
                True,
            )
        )
        if len(queue.songs) > 1:
            fields.append((small_caps('up next'), f'{len(queue.songs) - 1} track(s)', True))
        return fields

    def _now_playing_embed(self, song, queue, seek=0):
        voice_channel = queue.voice.channel if queue.voice else None
        description = f'[{song.title}]({song.url})'
        if voice_channel is not None:
            description += f'\n\U0001f5e3\ufe0f {voice_channel.mention}'

        embed = discord.Embed(
            title=small_caps('now playing'),
            description=description,
            color=CYAN,
        )
        for name, value, inline in self._progress_fields(song, queue, seek):
            embed.add_field(name=name, value=value, inline=inline)

        if song.duration > 0 and seek:
            left = max(song.duration - seek, 0)
            embed.set_footer(text=f'{format_time(left)} remaining \u00b7 {MUSIC_FOOTER}')
        else:
            embed.set_footer(text=MUSIC_FOOTER)

        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return embed

    async def play_next(self, queue):
        """Start playing ``queue.songs[0]`` (the head of the queue)."""
        if queue.locked:
            return
        queue.locked = True
        try:
            if not queue.songs:
                self._teardown(queue, notify=True)
                return

            if queue.voice is None or not queue.voice.is_connected():
                self.queues.pop(queue.guild.id, None)
                return

            while queue.songs:
                song = queue.songs[0]
                try:
                    await self._send(
                        queue, f'\u23f3 Loading **{song.title}**\u2026'
                    )
                    await song.prepare(self.workdir)
                    source = song.make_source(queue.volume)
                except MusicError:
                    song.cleanup()
                    queue.songs.pop(0)
                    await self._send(
                        queue, f'\u26a0\ufe0f Skipped **{song.title}** \u2014 stream unavailable.'
                    )
                    continue
                except Exception:
                    traceback.print_exc()
                    song.cleanup()
                    queue.songs.pop(0)
                    await self._send(
                        queue, f'\u26a0\ufe0f Skipped **{song.title}** \u2014 playback error.'
                    )
                    continue

                queue.clear_stay_task()
                queue.current = song
                self._apply_volume(queue)
                queue.voice.play(
                    source, after=lambda error=None: self._on_stream_end(queue, error)
                )
                queue.start_position()

                controls = PlayerControls(self, queue)
                embed = self._now_playing_embed(song, queue, seek=0)
                content = f'\U0001f3b5 **{song.title}**'
                message = queue.controls_message
                if message is not None:
                    try:
                        await message.edit(content=content, embed=embed, view=controls)
                    except Exception:
                        message = None
                if message is None:
                    message = await self._send(queue, content, embed=embed, view=controls)
                queue.controls_message = message
                queue.controls_view = controls
                self._restart_progress(queue)
                return

            self._teardown(queue, notify=True)
        except Exception:
            traceback.print_exc()
        finally:
            queue.locked = False

    async def enqueue_songs(self, member, channel, songs, voice_channel=None):
        """Shared path used by /play, /playlist and /search."""
        if voice_channel is None:
            state = member.voice
            voice_channel = state.channel if state else None
        if voice_channel is None:
            await channel.send('You need to be in a voice channel to use this command.')
            return

        queue = self.get_queue(member.guild)
        if queue and queue.voice and queue.voice.is_connected():
            if queue.voice.channel.id != voice_channel.id:
                await channel.send(
                    f'{self.bot.user.name} is already playing in {queue.voice.channel.mention}.'
                )
                return
        else:
            queue = None

        if queue is None:
            existing = member.guild.voice_client
            try:
                if existing and existing.is_connected():
                    if existing.channel.id != voice_channel.id:
                        await existing.move_to(voice_channel)
                    voice = existing
                else:
                    if existing is not None:
                        try:
                            await existing.disconnect(force=True)
                        except Exception:
                            pass
                    try:
                        voice = await voice_channel.connect(timeout=60.0, self_deaf=True)
                    except discord.ClientException:
                        voice = await voice_channel.connect(timeout=60.0, self_deaf=False)
            except Exception as exc:
                traceback.print_exc()
                me = member.guild.me
                perms = voice_channel.permissions_for(me) if me else None
                detail = ''
                if perms is not None:
                    detail = (
                        f' (connect={perms.connect}, speak={perms.speak}, '
                        f'view={perms.view_channel})'
                    )
                await channel.send(
                    f'Could not join **{voice_channel.mention}**{detail}\n'
                    f'`{type(exc).__name__}: {exc}`'
                )
                return
            queue = MusicQueue(member.guild, voice, channel)
            self.queues[member.guild.id] = queue
        else:
            queue.text_channel = channel
            queue.clear_stay_task()

        queue.songs.extend(songs)

        if len(songs) > 1:
            listing = '\n'.join(
                f'`{index}`. {song.title}'[:100] for index, song in enumerate(songs, 1)
            )
            embed = discord.Embed(
                title=small_caps('added to queue'),
                description=listing[:4000],
                color=CYAN,
            )
            embed.set_footer(text=f'{len(songs)} tracks \u00b7 {MUSIC_FOOTER}')
            await channel.send(f'\U0001f3b5 Added **{len(songs)}** tracks to the queue.', embed=embed)

        if not queue.voice.is_playing() and not queue.voice.is_paused():
            await self.play_next(queue)

    # ─── automatic advance ───────────────────────────────────
    def _on_stream_end(self, queue, error):
        """Callback handed to ``VoiceClient.play(after=...)``.

        Runs in the audio thread, so hop back onto the loop before touching
        the queue.
        """
        if error is not None:
            print(f'Music stream error: {error!r}')

        try:
            asyncio.run_coroutine_threadsafe(self._advance(queue), self.bot.loop)
        except Exception:
            traceback.print_exc()

    async def _advance(self, queue):
        """Drop the finished track and start the next one."""
        if queue.stopped or queue.locked:
            return

        if queue.jumped:
            queue.jumped = False
        elif queue.songs:
            finished = queue.songs.pop(0)
            if queue.loop:
                queue.songs.append(finished)
            else:
                finished.cleanup()

        if not queue.songs:
            self._teardown(queue, notify=True)
            return

        await self.play_next(queue)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Leave once the bot is alone in its channel (evobot's behaviour)."""
        queue = self.get_queue(member.guild)
        if not queue or not queue.voice or not queue.voice.is_connected():
            return
        channel = queue.voice.channel
        if channel is None:
            return
        if queue.stopped or len(queue.songs) <= 0:
            return
        if len(channel.members) <= 1:
            self._teardown(queue, notify=False)

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'Music system ready (ffmpeg: {ffmpeg_exe()})')

    # ─── commands ────────────────────────────────────────────
    @commands.hybrid_command(name='play', aliases=['p'])
    @app_commands.describe(song='YouTube URL or search query')
    async def play(self, ctx, song: str):
        """Play a track from a URL or a search query."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send('You need to be in a voice channel to use this command.')
            return

        await ctx.defer()

        if PLAYLIST_LOOKUP_PATTERN.match(song or ''):
            await self.playlist(ctx, playlist=song)
            return

        try:
            track = await Song.load(song)
        except NoResults:
            await ctx.send(f'\u274c No results found for **{song}**.')
            return
        except InvalidURL:
            await ctx.send(f'\u274c That is not a valid YouTube link: <{song}>')
            return
        except Exception:
            traceback.print_exc()
            await ctx.send('\u274c Something went wrong while loading that track.')
            return

        await self.enqueue_songs(ctx.author, ctx.channel, [track], ctx.author.voice.channel)

    @commands.hybrid_command(name='playlist')
    @app_commands.describe(playlist='Playlist URL or search query')
    async def playlist(self, ctx, playlist: str):
        """Play a YouTube playlist from a URL or a search query."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send('You need to be in a voice channel to use this command.')
            return

        await ctx.defer()

        try:
            title, url, songs = await load_playlist(playlist, MAX_PLAYLIST_SIZE)
        except MusicError:
            await ctx.send('\U0001f6ab Could not find that playlist.')
            return
        except Exception:
            traceback.print_exc()
            await ctx.send('\u274c Something went wrong while loading that playlist.')
            return

        await self.enqueue_songs(ctx.author, ctx.channel, songs, ctx.author.voice.channel)

        embed = discord.Embed(title=title[:256], url=url, color=CYAN)
        listing = '\n'.join(
            f'`{index}`. {song.title}'[:100] for index, song in enumerate(songs, 1)
        )
        embed.description = listing[:4000]
        embed.set_footer(text=f'{len(songs)} tracks \u00b7 {MUSIC_FOOTER}')
        try:
            await ctx.send(f'\U0001f3b5 Started the playlist.', embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.hybrid_command(name='search')
    @app_commands.describe(query='What to search for on YouTube')
    async def search(self, ctx, query: str):
        """Search YouTube and pick tracks from a menu."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send('You need to be in a voice channel to use this command.')
            return

        await ctx.defer(thinking=True)

        try:
            songs = await search_videos(query, limit=10)
        except Exception:
            traceback.print_exc()
            await ctx.send('\u274c Search failed.')
            return

        if not songs:
            await ctx.send(f'\U0001f50e No results for **{query}**.')
            return

        view = SearchView(self, ctx.author, songs)
        await ctx.send(f'\U0001f50e Results for **{query}** \u2014 pick up to 10 tracks.', view=view)

    @commands.hybrid_command(name='pause')
    async def pause(self, ctx):
        """Pause the current track."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return

        paused = await self.do_toggle(queue)
        if paused:
            await ctx.send(f'\U0001f6ab Paused by {ctx.author.mention}.')
        else:
            await ctx.send('\U0001f6ab The player is already paused.')

    @commands.hybrid_command(name='resume')
    async def resume(self, ctx):
        """Resume playback."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        if not queue.voice.is_paused():
            await ctx.send('\U0001f3b5 Already playing.')
            return
        queue.voice.resume()
        await ctx.send(f'\U0001f3b5 Resumed by {ctx.author.mention}.')

    @commands.hybrid_command(name='skip', aliases=['s'])
    async def skip(self, ctx):
        """Skip the current track."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        if not queue.voice.is_playing():
            await ctx.send('The player is paused \u2014 resume it or use `skipto` first.')
            return
        await ctx.send(f'\u23ed\ufe0f Skipped by {ctx.author.mention}.')
        await self.do_skip(ctx, queue)

    @commands.hybrid_command(name='skipto')
    @app_commands.describe(number='Queue position to jump to')
    async def skipto(self, ctx, number: int):
        """Jump to a specific position in the queue."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        if number < 1 or number > len(queue.songs):
            await ctx.send(f'Pick a number between 1 and {len(queue.songs)}.')
            return

        queue.songs = queue.songs[number - 1:]
        await ctx.send(f'\U0001f3b5 Skipping to track **#{number}** \u2014 {ctx.author.mention}')
        if queue.voice.is_playing() or queue.voice.is_paused():
            queue.jumped = True
            queue.voice.stop()
        else:
            await self.play_next(queue)

    @commands.hybrid_command(name='stop', aliases=['leave'])
    async def stop(self, ctx):
        """Clear the queue and stop playing."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        await ctx.send(f'\U0001f6d1 Stopped by {ctx.author.mention}.')
        await self.do_stop(ctx, queue)

    @commands.hybrid_command(name='queue', aliases=['q'])
    async def show_queue(self, ctx):
        """Show the current queue."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('The queue is empty.')
            return

        songs = queue.songs
        embeds = []
        chunks = [songs[i:i + 10] for i in range(0, len(songs), 10)]
        for offset, chunk in enumerate(chunks):
            listing = '\n'.join(
                f'`{offset + index + 1}`. [{song.title}]({song.url}) \u2014 `{format_time(song.duration)}`'
                for index, song in enumerate(chunk)
            )
            embed = discord.Embed(
                title=small_caps('queue'),
                description=listing[:4000],
                color=CYAN,
            )
            embed.set_footer(text=f'{len(songs)} track(s) \u00b7 {MUSIC_FOOTER}')
            embeds.append(embed)

        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
            return

        await ctx.send(content=f'**Page 1/{len(embeds)}**', embed=embeds[0], view=QueuePages(ctx.author, embeds))

    @commands.hybrid_command(name='remove')
    @app_commands.describe(slot='Queue number(s), for example 2 or 2,4,5')
    async def remove(self, ctx, slot: str):
        """Remove one or more tracks from the queue."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('The queue is empty.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return

        parts = [part.strip() for part in str(slot).split(',') if part.strip()]
        if not parts or not all(part.isdigit() for part in parts):
            await ctx.send('Usage: `remove 2` or `remove 2,4,5`')
            return

        indices = sorted({int(part) for part in parts if 1 <= int(part) <= len(queue.songs)}, reverse=True)
        if not indices:
            await ctx.send(f'Pick numbers between 1 and {len(queue.songs)}.')
            return

        removed = [queue.songs.pop(index - 1) for index in indices]
        listing = '\n'.join(f'\u2022 {song.title}' for song in reversed(removed))
        await ctx.send(f'\U0001f5d1\ufe0f Removed:\n{listing}')

    @commands.hybrid_command(name='move')
    @app_commands.describe(movefrom='Current queue number', moveto='New queue number')
    async def move(self, ctx, movefrom: int, moveto: int):
        """Move a track to a different queue position."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('The queue is empty.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        if movefrom < 1 or movefrom > len(queue.songs):
            await ctx.send(f'Pick a number between 1 and {len(queue.songs)}.')
            return

        song = queue.songs.pop(movefrom - 1)
        target = max(1, min(moveto, len(queue.songs) + 1))
        queue.songs.insert(target - 1, song)
        await ctx.send(f'\U0001f501 Moved **{song.title}** to position **{target}**.')

    @commands.hybrid_command(name='shuffle')
    async def shuffle(self, ctx):
        """Shuffle the queue."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('The queue is empty.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        queue.shuffle()
        await ctx.send('\U0001f500 Queue shuffled.')

    @commands.hybrid_command(name='loop')
    async def loop(self, ctx):
        """Toggle looping the current track."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return
        enabled = await self.do_loop(ctx, queue)
        state = 'enabled' if enabled else 'disabled'
        await ctx.send(f'\U0001f501 Loop **{state}**.')

    @commands.hybrid_command(name='volume')
    @app_commands.describe(volume='Volume between 0 and 100')
    async def volume(self, ctx, volume: Optional[int] = None):
        """Show or change the player volume."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return
        if not self.can_modify(ctx.author, queue):
            await ctx.send('You need to be in my voice channel to do that.')
            return

        if volume is None:
            await ctx.send(f'\U0001f3a7 Current volume: **{queue.volume}%**')
            return
        if volume < 0 or volume > 100:
            await ctx.send('Volume must be between 0 and 100.')
            return

        applied = await self.do_volume(ctx, volume, queue)
        await ctx.send(f'\U0001f3a7 Volume set to **{applied}%** by {ctx.author.mention}.')

    @commands.hybrid_command(name='nowplaying', aliases=['np'])
    async def nowplaying(self, ctx):
        """Show the track that is currently playing."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.songs:
            await ctx.send('Nothing is playing right now.')
            return

        song = queue.now
        seek = ((queue.voice.current_position if queue.voice else 0) or 0) / 1000
        state = 'paused' if queue.is_paused else 'playing'
        await ctx.send(content=f'\U0001f3b5 {state.upper()}', embed=self._now_playing_embed(song, queue, seek))

    @commands.hybrid_command(name='lyrics')
    @app_commands.describe(title='Song title \u2014 defaults to the current track')
    async def lyrics(self, ctx, title: Optional[str] = None):
        """Fetch lyrics for the current or a given track."""
        queue = self.get_queue(ctx.guild)
        if title is None:
            if not queue or not queue.songs:
                await ctx.send('No track is playing \u2014 provide a song title instead.')
                return
            title = queue.now.title

        await ctx.defer(thinking=True)

        cleaned = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*', ' ', title).strip()
        parts = re.split(r'\s+-\s+', cleaned, maxsplit=1)
        artist = parts[0] if len(parts) > 1 else ''
        track = parts[-1].strip()

        found = None
        if artist:
            found = await self._fetch_lyrics(artist, track)
        if not found:
            found = await self._fetch_lyrics('', track)

        if not found:
            await ctx.send(f'\U0001f3a4 No lyrics found for **{title}**.')
            return

        text = found
        if len(text) > 4000:
            embed = discord.Embed(title=f'\U0001f3a4 {title}'[:256], color=CYAN)
            embed.description = f'```\n{text[:3990]}\n```\n\u2026'
        else:
            embed = discord.Embed(
                title=f'\U0001f3a4 {title}'[:256],
                description=f'```\n{text}\n```',
                color=CYAN,
            )
        embed.set_footer(text=MUSIC_FOOTER)
        await ctx.send(embed=embed)

    async def _fetch_lyrics(self, artist, title):
        import aiohttp

        url = (
            f'https://api.lyrics.ovh/v1/'
            f'{aiohttp.helpers.requote_uri(artist)}/{aiohttp.helpers.requote_uri(title)}'
        )
        try:
            async with self.bot.http.request('GET', url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
        except Exception:
            return None

        text = ((data or {}).get('lyrics') or '').replace('\r\n', '\n').strip()
        if len(text) < 20:
            return None
        return text[:4000]

    @commands.hybrid_command(name='leavevc')
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel='Voice channel to disconnect from')
    async def leavevc(self, ctx, channel: discord.VoiceChannel = None):
        """Force the bot out of a voice channel (admin only)."""
        queue = self.get_queue(ctx.guild)
        if not queue or not queue.voice or not queue.voice.is_connected():
            await ctx.send('The bot is not connected to voice.')
            return
        target = channel or queue.voice.channel
        self.queues.pop(ctx.guild.id, None)
        queue.songs.clear()
        queue.stopped = True
        if queue.stay_task and not queue.stay_task.done():
            queue.stay_task.cancel()
        if queue.progress_task and not queue.progress_task.done():
            queue.progress_task.cancel()
        await queue.voice.disconnect(force=True)
        await ctx.send(f'\U0001f5c3️ Left {target.mention}.')

    async def cog_unload(self):
        for guild_id in list(self.queues):
            queue = self.queues.pop(guild_id, None)
            if queue is None:
                continue
            if queue.progress_task and not queue.progress_task.done():
                queue.progress_task.cancel()
            for song in queue.songs:
                song.cleanup()
            if queue.current is not None:
                queue.current.cleanup()
            if queue.voice and queue.voice.is_connected():
                try:
                    await queue.voice.disconnect(force=True)
                except Exception:
                    traceback.print_exc()


async def setup(bot):
    await bot.add_cog(Music(bot))