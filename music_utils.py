"""YouTube helpers for the music cog.

Port of evobot's ``structs/Song.ts`` and ``structs/Playlist.ts`` on top of
yt-dlp instead of ``youtube-sr`` + ``play-dl``.
"""

import asyncio
import os
import re
import shutil
import tempfile
import urllib.parse

import discord
import yt_dlp

from config import MAX_PLAYLIST_SIZE

VIDEO_URL_PATTERN = re.compile(
    r'^(https?://)?(www\.)?(m\.|music\.)?(youtube\.com|youtu\.?be)/.+$', re.IGNORECASE
)
PLAYLIST_URL_PATTERN = re.compile(r'^.*(list=)([^#&?]*).*', re.IGNORECASE)
PLAYLIST_LOOKUP_PATTERN = re.compile(r'^.*(youtu\.be/|list=)([^#&?]*).*', re.IGNORECASE)
IS_URL_PATTERN = re.compile(
    r'^https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}'
    r'\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)'
)
BAD_PLAYLIST_TITLES = ('private video', 'deleted video', 'unavailable video')

# Audio-only preference: keeps ffmpeg work minimal and avoids video payloads.
AUDIO_FORMAT = 'bestaudio[vcodec=none]/bestaudio/best'

_FFMPEG_EXE = None


def ffmpeg_exe():
    """Locate an ffmpeg binary (system PATH first, bundled wheel second)."""
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        _FFMPEG_EXE = shutil.which('ffmpeg')
        if not _FFMPEG_EXE:
            try:
                import imageio_ffmpeg

                _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                _FFMPEG_EXE = 'ffmpeg'
    return _FFMPEG_EXE


class MusicError(Exception):
    """Base class for music lookup failures."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class NoResults(MusicError):
    pass


class InvalidURL(MusicError):
    pass


class _QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def _base_opts(**extra):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'nocheckcertificate': True,
        'logger': _QuietLogger(),
    }
    opts.update(extra)
    return opts


def _extract(url, noplaylist=True, flat=False, fmt=None):
    opts = _base_opts(
        noplaylist=noplaylist,
        skip_download=True,
        extract_flat='in_playlist' if flat else False,
    )
    if fmt:
        opts['format'] = fmt
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except Exception:
            return None


def _download(url, outdir):
    """Download the best audio track to ``outdir`` and return the file path."""
    os.makedirs(outdir, exist_ok=True)
    opts = _base_opts(
        noplaylist=True,
        format=AUDIO_FORMAT,
        outtmpl=os.path.join(outdir, '%(id)s.%(ext)s'),
        restrictfilenames=True,
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if not info:
        return None
    requested = info.get('requested_downloads') or []
    if requested and requested[0].get('filepath'):
        return requested[0]['filepath']
    for entry in info.get('entries') or []:
        if entry and entry.get('filepath'):
            return entry['filepath']
    return info.get('_filename')


async def _run(func, *args, **kwargs):
    """Run a blocking yt-dlp call off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def download_audio(url, outdir):
    return await _run(_download, url, outdir)


def format_time(seconds):
    seconds = max(int(seconds or 0), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def split_bar(total, current, width=20):
    """Text progress bar, matching evobot's ``string-progressbar`` output."""
    if not total or total <= 0:
        return '\u2500' * width
    ratio = max(0.0, min(current / total, 1.0))
    filled = int(width * ratio)
    return '\u2588' * filled + '\u2500' * (width - filled)


class Song:
    __slots__ = (
        'url', 'title', 'duration', 'thumbnail', 'uploader', 'stream_url', 'file_path'
    )

    def __init__(
        self, url, title, duration=0, thumbnail=None, uploader=None,
        stream_url=None, file_path=None,
    ):
        self.url = url
        self.title = title
        self.duration = int(duration or 0)
        self.thumbnail = thumbnail
        self.uploader = uploader
        self.stream_url = stream_url
        self.file_path = file_path

    def __repr__(self):
        return f'<Song {self.title!r} ({format_time(self.duration)})>'

    @classmethod
    def from_info(cls, info):
        return cls(
            url=info.get('webpage_url') or info.get('original_url') or '',
            title=info.get('title') or 'Unknown',
            duration=info.get('duration') or 0,
            thumbnail=info.get('thumbnail'),
            uploader=info.get('uploader') or info.get('channel'),
            stream_url=info.get('url'),
        )

    @classmethod
    def from_entry(cls, entry):
        """Build from a flat search / playlist entry (no stream yet)."""
        video_id = entry.get('id')
        url = entry.get('webpage_url') or entry.get('url') or ''
        if not url and video_id:
            url = f'https://www.youtube.com/watch?v={video_id}'
        thumbnails = entry.get('thumbnails') or []
        return cls(
            url=url,
            title=entry.get('title') or 'Unknown',
            duration=entry.get('duration') or 0,
            thumbnail=thumbnails[-1].get('url') if thumbnails else None,
            uploader=entry.get('uploader') or entry.get('channel'),
        )

    @classmethod
    async def load(cls, query):
        """Mirror evobot's ``Song.from(url, search)``."""
        if VIDEO_URL_PATTERN.match(query or ''):
            info = await _run(_extract, query, True, False, AUDIO_FORMAT)
            if not info or not info.get('url'):
                raise NoResults(f'No results found for <{query}>')
            return cls.from_info(info)

        if IS_URL_PATTERN.match(query or ''):
            raise InvalidURL(f'Invalid URL <{query}>')

        results = await search_videos(query, limit=1)
        if not results:
            raise NoResults(f'No results found for <{query}>')

        info = await _run(_extract, results[0].url, True, False, AUDIO_FORMAT)
        if not info or not info.get('url'):
            raise NoResults(f'No results found for <{query}>')
        return cls.from_info(info)

    async def refresh(self):
        """Fetch full metadata (stream URL + duration) for this track."""
        if self.stream_url and self.duration:
            return self
        info = await _run(_extract, self.url, True, False, AUDIO_FORMAT)
        if not info:
            raise NoResults(f'Could not load <{self.url}>')
        self.title = info.get('title') or self.title
        self.duration = int(info.get('duration') or self.duration or 0)
        self.thumbnail = info.get('thumbnail') or self.thumbnail
        self.uploader = info.get('uploader') or self.uploader
        self.stream_url = info.get('url')
        if not self.stream_url:
            raise NoResults(f'Could not load <{self.url}>')
        return self

    async def prepare(self, workdir):
        """Resolve metadata and download the audio to a local file.

        Streaming a googlevideo URL can die partway through, so playback uses
        a fully downloaded temp file and only falls back to streaming if the
        download fails.
        """
        if self.file_path and os.path.exists(self.file_path):
            return self
        if not self.stream_url or not self.duration:
            await self.refresh()
        try:
            path = await download_audio(self.url, workdir)
        except Exception:
            path = None
        if path and os.path.exists(path):
            self.file_path = path
        return self

    def cleanup(self):
        """Delete the downloaded temp file, if any."""
        if self.file_path:
            try:
                os.remove(self.file_path)
            except Exception:
                pass
        self.file_path = None

    def make_source(self, volume=100):
        """Build a ``discord.AudioSource``.

        Volume is applied through ffmpeg because discord.py has no inline volume
        on ``FFmpegPCMAudio``.
        """
        gain = max(0.0, min(volume, 100) / 100)
        if self.file_path and os.path.exists(self.file_path):
            return discord.FFmpegPCMAudio(
                self.file_path,
                executable=ffmpeg_exe(),
                options=f'-af volume={gain:.2f}',
            )
        if not self.stream_url:
            raise NoResults(f'Stream not loaded for <{self.url}>')
        return discord.FFmpegPCMAudio(
            self.stream_url,
            executable=ffmpeg_exe(),
            before_options=(
                '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
                '-nostdin'
            ),
            options=f'-af volume={gain:.2f}',
        )


async def search_videos(query, limit=10):
    """Search YouTube's video tab (mirrors evobot's ``type: 'video'``)."""
    if VIDEO_URL_PATTERN.match(query or ''):
        target = query
    else:
        target = (
            'https://www.youtube.com/results?search_query='
            f'{urllib.parse.quote(str(query))}&sp=EgIQAQ%253D%253D'
        )
    info = await _run(_extract, target, False, True)
    if not info:
        return []
    entries = info.get('entries') or []
    songs = []
    for entry in entries:
        if not entry:
            continue
        song = Song.from_entry(entry)
        if not song.url:
            continue
        songs.append(song)
        if len(songs) >= limit:
            break
    return songs


async def search_playlists(query, limit=1):
    """Search YouTube's playlist tab (``sp=EgIQAw%3D%3D`` is the filter)."""
    target = (
        'https://www.youtube.com/results?search_query='
        f'{urllib.parse.quote(str(query))}&sp=EgIQAw%253D%253D'
    )
    info = await _run(_extract, target, False, True)
    if not info:
        return []
    songs = []
    for entry in info.get('entries') or []:
        if not entry:
            continue
        url = entry.get('url') or entry.get('webpage_url') or ''
        if PLAYLIST_URL_PATTERN.match(url):
            song = Song.from_entry(entry)
            song.url = url
            songs.append(song)
        if len(songs) >= limit:
            break
    return songs


async def load_playlist(query, max_size=MAX_PLAYLIST_SIZE):
    """Return ``(title, url, [Song, ...])`` for a playlist URL or a query.

    Mirrors evobot's ``Playlist.from``: a URL is used as-is, anything else is
    resolved through a YouTube search first.
    """
    if PLAYLIST_LOOKUP_PATTERN.match(query or ''):
        title, page_url, songs = await _playlist_entries(query, max_size)
        if not songs:
            raise NoResults(f'No playlist found for <{query}>')
        return title, page_url, songs

    results = await search_playlists(query, limit=1)
    if results:
        title, page_url, songs = await _playlist_entries(results[0].url, max_size)
        if songs:
            return title, page_url, songs

    # No playlist matched; fall back to the top video for that query.
    videos = await search_videos(query, limit=1)
    if not videos:
        raise NoResults(f'No playlist found for <{query}>')
    song = videos[0]
    return song.title, song.url, [song][:max_size]


async def _playlist_entries(target, max_size):
    """Flatten a playlist link into per-entry songs (flat extraction)."""
    info = await _run(_extract, target, False, True)
    if not info:
        return None, target, []

    title = info.get('title') or 'Playlist'
    page_url = info.get('webpage_url') or target

    songs = []
    for entry in info.get('entries') or []:
        if not entry:
            continue
        name = (entry.get('title') or '').strip().lower()
        if name in BAD_PLAYLIST_TITLES:
            continue
        song = Song.from_entry(entry)
        if not song.url:
            continue
        songs.append(song)
        if len(songs) >= max_size:
            break

    return title, page_url, songs