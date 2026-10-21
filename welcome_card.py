from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from io import BytesIO
import aiohttp
import os
import re
import time


# ============================================================
# CONFIG / PATHS
# ============================================================

FONT_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'fonts')
BACKGROUND_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'backgrounds')

# Windows fallback fonts when custom .ttf are not provided
_FONT_FALLBACKS = {
    'Inter-Regular.ttf': 'C:/Windows/Fonts/segoeui.ttf',
    'Inter-SemiBold.ttf': 'C:/Windows/Fonts/segoeuib.ttf',
    'Inter-Bold.ttf': 'C:/Windows/Fonts/segoeuib.ttf',
    'Inter-Black.ttf': 'C:/Windows/Fonts/ariblk.ttf',
    'Inter-Italic.ttf': 'C:/Windows/Fonts/segoeuii.ttf',
    'Display-Regular.ttf': 'C:/Windows/Fonts/impact.ttf',      # big poster quote font
    'Display-Bold.ttf': 'C:/Windows/Fonts/impact.ttf',
    'Display-Italic.ttf': 'C:/Windows/Fonts/impacti.ttf',
    'DelaGothicOne-Regular.ttf': 'C:/Windows/Fonts/impact.ttf',  # main display font (Impact fallback)
    'Script-Regular.ttf': 'C:/Windows/Fonts/constanb.ttf',        # curved decorative quote mark
    'DMSerifDisplay-Regular.ttf': 'C:/Windows/Fonts/constanb.ttf', # elegant serif display (quote mark)
    'Rounded-Bold.ttf': 'C:/Windows/Fonts/arlrdbd.ttf',           # smooth modern rounded sans (quote)
    'Sans-Bold.ttf': 'C:/Windows/Fonts/segoeuib.ttf',             # user info lines
    'Sans-SemiBold.ttf': 'C:/Windows/Fonts/seguisb.ttf',          # quote font (different weight)
    'CJK-Gothic-Bold.ttc': 'C:/Windows/Fonts/yugothb.ttc',        # japanese typography
    'Symbol-Regular.ttf': 'C:/Windows/Fonts/seguisym.ttf',        # phonetic / math alphanumerics
    'Emoji-Regular.ttf': 'C:/Windows/Fonts/seguiemj.ttf',         # emoji / SMP blocks
}

# Unicode ranges that need a specific font so names never render as "tofu" boxes
_CHAR_FONT_RANGES = [
    ((0x4E00, 0x9FFF), 'CJK-Gothic-Bold.ttc'),    # CJK unified ideographs
    ((0x3400, 0x4DBF), 'CJK-Gothic-Bold.ttc'),    # CJK extension A
    ((0x3040, 0x30FF), 'CJK-Gothic-Bold.ttc'),    # hiragana + katakana
    ((0x31F0, 0x31FF), 'CJK-Gothic-Bold.ttc'),    # katakana phonetic extensions
    ((0xAC00, 0xD7AF), 'CJK-Gothic-Bold.ttc'),    # hangul
    ((0x1100, 0x11FF), 'CJK-Gothic-Bold.ttc'),    # hangul jamo
    ((0x1D400, 0x1D7FF), 'Symbol-Regular.ttf'),   # math alphanumerics
    ((0x1D00, 0x1D7F), 'Symbol-Regular.ttf'),     # phonetic extensions
    ((0x0250, 0x02AF), 'Symbol-Regular.ttf'),     # IPA extensions
    ((0x0370, 0x03FF), 'Sans-Bold.ttf'),          # greek
    ((0x0400, 0x052F), 'Sans-Bold.ttf'),          # cyrillic
    ((0x10000, 0x1FFFF), 'Emoji-Regular.ttf'),    # supplementary planes (emoji, etc.)
]


def char_font_name(char):
    cp = ord(char)
    for (lo, hi), name in _CHAR_FONT_RANGES:
        if lo <= cp <= hi:
            return name
    return None


def pick_unicode_font(text, size, default='Sans-Bold.ttf'):
    """Pick the font covering the most characters of `text` so unicode names never become boxes."""
    counts = {}
    for ch in text:
        name = char_font_name(ch) or default
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return font(default, size)
    return font(max(counts, key=counts.get), size)


def font(name, size):
    path = os.path.join(FONT_DIR, name)
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    fallback = _FONT_FALLBACKS.get(name, 'C:/Windows/Fonts/segoeui.ttf')
    if os.path.exists(fallback):
        return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


def hex_color(value):
    value = value.replace('#', '').strip()
    if len(value) == 3:
        value = ''.join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# ============================================================
# AVATAR
# ============================================================

async def download_avatar(url):
    """Download an avatar image. Returns None on ANY failure so cards still render without it."""
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f'[welcome_card] avatar download failed: HTTP {resp.status}')
                    return None
                data = await resp.read()
                return Image.open(BytesIO(data)).convert('RGBA')
    except Exception as e:
        print(f'[welcome_card] avatar download error: {e}')
        return None


def full_bleed_avatar(avatar, width, height):
    """Crop-cover into width x height and convert to black & white (like CSS background-size: cover)."""
    ratio = max(width / avatar.width, height / avatar.height)
    new_w = int(avatar.width * ratio)
    new_h = int(avatar.height * ratio)
    avatar = avatar.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    avatar = avatar.crop((left, top, left + width, top + height))
    return grayscale_avatar(avatar)


def fade_strip(width, height, vertical=False):
    """Dark fade strip: opaque at the start, transparent at the end.
    horizontal -> used on the right edge of a left-side image.
    vertical_fa -> used on the bottom edge of a top image."""
    fade = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    if vertical:
        for y in range(height):
            alpha = int(255 * (1 - y / height))
            fd.line((0, y, width, y), fill=(8, 9, 11, alpha))
    else:
        for x in range(width):
            alpha = int(255 * (1 - x / width))
            fd.line((x, 0, x, height), fill=(8, 9, 11, alpha))
    return fade


def smooth_fade(width, height, vertical=False):
    """Smooth (eased) fade strip: transparent at the start, opaque at the end.
    Used to blend the manga profile smoothly into the black text area."""
    fade = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    last = max(width if not vertical else height, 1)
    if vertical:
        for y in range(height):
            t = y / last
            alpha = int(255 * t * t * (3 - 2 * t))   # smoothstep easing
            fd.line((0, y, width, y), fill=(0, 0, 0, alpha))
    else:
        for x in range(width):
            t = x / last
            alpha = int(255 * t * t * (3 - 2 * t))
            fd.line((x, 0, x, height), fill=(0, 0, 0, alpha))
    return fade


def cover_avatar(img, width, height, align_x='left', align_y='bottom'):
    """Crop-cover an image into width x height, anchored (like object-fit + object-position)."""
    ratio = max(width / img.width, height / img.height)
    nw = int(img.width * ratio)
    nh = int(img.height * ratio)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = 0 if align_x == 'left' else (nw - width) // 2
    top = (nh - height) if align_y == 'bottom' else (nh - height) // 2
    return img.crop((left, top, left + width, top + height))


# ============================================================
# MANGA TREATMENT (monochrome, halftone, grain, ink, vignette)
# ============================================================

def apply_halftone(rgba, step=6):
    """Screentone-style halftone dots in the dark areas."""
    w, h = rgba.size
    lum = rgba.convert('L')
    px = lum.load()
    out = rgba.copy()
    d = ImageDraw.Draw(out)
    for gy in range(0, h, step):
        for gx in range(0, w, step):
            total = count = 0
            for yy in range(gy, min(gy + step, h)):
                for xx in range(gx, min(gx + step, w)):
                    total += px[xx, yy]
                    count += 1
            avg = total / max(1, count)
            if avg < 205:
                r = int((205 - avg) * step * 0.006)
                if r > 1:
                    r = min(r, int(step * 0.7))
                    cx, cy = gx + step / 2, gy + step / 2
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 255))
    return out


def apply_ink_edges(rgba, strength=100):
    """Sharp ink-like edge lines."""
    edges = rgba.convert('L').filter(ImageFilter.FIND_EDGES)
    edges = edges.point(lambda v: int(v * strength / 255))
    black = Image.new('RGBA', rgba.size, (0, 0, 0, 255))
    black.putalpha(edges)
    return Image.alpha_composite(rgba, black)


def apply_grain(rgba, sigma=20, alpha=26):
    """Subtle film grain."""
    noise = Image.effect_noise((rgba.width, rgba.height), sigma).convert('L')
    mask = Image.new('L', rgba.size, alpha)
    grain = Image.merge('RGBA', (noise, noise, noise, mask))
    return Image.alpha_composite(rgba, grain)


def apply_vignette(rgba, strength=0.40):
    """Dark vignette around the edges."""
    w, h = rgba.size
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.35, -h * 0.30, w * 1.35, h * 1.30), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(70))
    inv = Image.eval(mask, lambda v: 255 - v)
    dark = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dark.paste((0, 0, 0, 255), (0, 0), inv)
    return Image.alpha_composite(rgba, dark)


def manga_treatment(rgba):
    """High-contrast black & white manga/anime style treatment of the avatar."""
    from PIL import ImageEnhance, ImageOps
    gray = rgba.convert('L')
    gray = ImageOps.autocontrast(gray, cutoff=3)
    gray = ImageEnhance.Contrast(gray).enhance(1.55)
    gray = gray.point(lambda v: 0 if v < 18 else (255 if v > 238 else v))
    out = Image.merge('RGBA', (gray, gray, gray, rgba.getchannel('A')))
    out = apply_halftone(out)
    out = apply_ink_edges(out)
    out = apply_grain(out)
    out = apply_vignette(out)
    return out


def grayscale_avatar(avatar):
    """Convert an RGBA avatar to black & white while keeping transparency."""
    grey = avatar.convert('L')
    alpha = avatar.getchannel('A')
    return Image.merge('RGBA', (grey, grey, grey, alpha))


def _interpolate(c1, c2, ratio):
    return tuple(int(c1[i] * (1 - ratio) + c2[i] * ratio) for i in range(3))


def _interp_stops(stops, ratio):
    """Interpolate along a list of RGB stops by ratio in [0, 1]."""
    n = len(stops)
    if n == 1:
        return stops[0]
    x = min(max(ratio, 0.0), 1.0) * (n - 1)
    i = int(x)
    if i >= n - 1:
        return stops[-1]
    return _interpolate(stops[i], stops[i + 1], x - i)


def _draw_gradient_text(draw, position, text, font_obj, colors, color_right='#FFFFFF', center_white=False, stroke=0):
    """
    Draw text filled with a gradient. Returns end x.
    `colors` may be a single hex string or a list of hex gradient stops.
    center_white=False -> left -> right one-way gradient.
    center_white=True  -> palette at both ends, white in the middle.
    stroke>0 thickens the glyph (heavier weight).
    """
    if isinstance(colors, str):
        colors = [colors]
    stops = [hex_color(c) for c in colors]
    white_rgb = hex_color(color_right)
    x0, y = position
    total = draw.textlength(text, font=font_obj)
    if total == 0:
        return x0
    x = x0
    for char in text:
        char_w = draw.textlength(char, font=font_obj)
        ratio = (x + char_w / 2 - x0) / total
        fill = _interp_stops(stops, ratio)
        if center_white:
            w = 1 - abs(ratio - 0.5) * 2
            fill = _interpolate(fill, white_rgb, 0.9 * w)
        draw.text((x, y), char, font=font_obj, fill=fill, stroke_width=stroke, stroke_fill=fill)
        x += char_w
    return x


def strip_markdown(text):
    """Remove markdown syntax, keep plain text and line breaks."""
    text = re.sub(r'\[/\]', '', text)
    text = re.sub(r'\[#[A-Fa-f0-9]{6}\]', '', text)
    text = text.replace('**', '').replace('*', '').replace('`', '').replace('~~', '')
    return text


# ============================================================
# GRADIENT
# ============================================================

def gradient_overlay(width, height, left_color, right_color):
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    pixels = image.load()
    left_rgb = hex_color(left_color)
    right_rgb = hex_color(right_color)
    for x in range(width):
        ratio = x / max(width - 1, 1)
        r = int(left_rgb[0] * (1 - ratio) + right_rgb[0] * ratio)
        g = int(left_rgb[1] * (1 - ratio) + right_rgb[1] * ratio)
        b = int(left_rgb[2] * (1 - ratio) + right_rgb[2] * ratio)
        for y in range(height):
            pixels[x, y] = (r, g, b, 255)
    return image


# ============================================================
# BACKGROUND HELPERS
# ============================================================

def _load_background(background, width, height):
    if os.path.exists(background):
        bg = Image.open(background).convert('RGBA')
        bg_ratio = bg.width / bg.height
        canvas_ratio = width / height
        if bg_ratio > canvas_ratio:
            new_height = height
            new_width = int(height * bg_ratio)
        else:
            new_width = width
            new_height = int(width / bg_ratio)
        bg = bg.resize((new_width, new_height), Image.Resampling.LANCZOS)
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        bg = bg.crop((left, top, left + width, top + height))
        return bg
    return Image.new('RGBA', (width, height), '#08090B')


def _apply_theme(bg, width, height, accent):
    dark = Image.new('RGBA', (width, height), (0, 0, 0, 150))
    bg = Image.alpha_composite(bg, dark)

    gradient = gradient_overlay(width, height, '#000000', accent)
    gradient.putalpha(80)
    bg = Image.alpha_composite(bg, gradient)

    glow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    accent_rgb = hex_color(accent)
    glow_draw.ellipse((-200, height - 350, 350, height + 200), fill=(*accent_rgb, 100))
    glow = glow.filter(ImageFilter.GaussianBlur(100))
    bg = Image.alpha_composite(bg, glow)
    return bg


# ============================================================
# TEXT WRAPPING
# ============================================================

def wrap_text(text, draw, font_obj, max_width):
    words = text.split()
    lines = []
    current = ''
    for word in words:
        test = word if not current else current + ' ' + word
        bbox = draw.textbbox((0, 0), test, font=font_obj)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ============================================================
# MARKDOWN PARSER
# ============================================================

def parse_markdown(text):
    """
    Supports:
      **bold**  *italic*  `code`  ~~strike~~
      [#FF00FF]colored text[/]
    Example: **Welcome** [#00D9FF]Shahid[/]!
    """
    tokens = []
    pattern = re.compile(
        r'(\*\*.*?\*\*|\*.*?\*|`.*?`|~~.*?~~|\[#(?:[A-Fa-f0-9]{6})\].*?\[/\])'
    )
    parts = pattern.split(text)
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            tokens.append({'text': part[2:-2], 'style': 'bold'})
        elif part.startswith('*') and part.endswith('*'):
            tokens.append({'text': part[1:-1], 'style': 'italic'})
        elif part.startswith('`') and part.endswith('`'):
            tokens.append({'text': part[1:-1], 'style': 'code'})
        elif part.startswith('~~') and part.endswith('~~'):
            tokens.append({'text': part[2:-2], 'style': 'strike'})
        elif part.startswith('[#') and part.endswith('[/]'):
            match = re.match(r'\[#([A-Fa-f0-9]{6})\](.*?)\[/\]', part)
            if match:
                tokens.append({'text': match.group(2), 'style': 'color', 'color': '#' + match.group(1)})
        else:
            tokens.append({'text': part, 'style': 'normal'})
    return tokens


_STYLE_FONT = {
    'normal': 'DelaGothicOne-Regular.ttf',
    'bold': 'DelaGothicOne-Regular.ttf',
    'italic': 'DelaGothicOne-Regular.ttf',
    'code': 'Inter-Regular.ttf',
    'strike': 'DelaGothicOne-Regular.ttf',
    'color': 'DelaGothicOne-Regular.ttf',
}


def draw_markdown(draw, position, text, max_width, size=42, color='#FFFFFF'):
    """Render markdown text with word-wrap and \\n support. Returns final y position."""
    x, y = position
    current_x = x
    current_y = y
    line_height = int(size * 1.35)

    normal_font = font('Inter-Regular.ttf', size)
    space_width = draw.textlength(' ', font=normal_font)

    for token in parse_markdown(text):
        content = token['text']
        current_font = font(_STYLE_FONT[token['style']], size)
        token_color = hex_color(token.get('color', color)) if token['style'] == 'color' else hex_color(color)

        for i, line_part in enumerate(content.split('\n')):
            if i > 0:
                current_x = x
                current_y += line_height

            words = line_part.split(' ')
            for word in words:
                if not word:
                    continue
                word = word.replace('\n', ' ')
                word_width = draw.textlength(word, font=current_font)
                if current_x + word_width > x + max_width:
                    current_x = x
                    current_y += line_height

                draw.text((current_x, current_y), word, font=current_font, fill=token_color)

                if token['style'] == 'strike':
                    bbox = draw.textbbox((current_x, current_y), word, font=current_font)
                    middle = (bbox[1] + bbox[3]) // 2
                    draw.line((bbox[0], middle, bbox[2], middle), fill=token_color, width=2)

                current_x += word_width + space_width

    return current_y + line_height


# ============================================================
# WELCOME CARD
# ============================================================

def _route_font_name(char, default='Sans-Bold.ttf'):
    """Choose a font that supports `char` (CJK, symbols, emoji) or the default."""
    return char_font_name(char) or default


def _routed_text_width(draw, text, size, default='Sans-Bold.ttf'):
    fonts = {}
    total = 0.0
    for ch in text:
        name = _route_font_name(ch, default)
        if name not in fonts:
            fonts[name] = font(name, size)
        total += draw.textlength(ch, font=fonts[name])
    return total, fonts


def _draw_routed_line(draw, cx, cy, text, size, fill, default='Sans-Bold.ttf'):
    """Draw `text` centered at (cx, cy), routing each character to a font that
    supports it, so emoji / CJK / symbols never render as boxes."""
    if not text:
        return
    total, fonts = _routed_text_width(draw, text, size, default)
    ascent = max(f.getmetrics()[0] for f in fonts.values())
    descent = max(f.getmetrics()[1] for f in fonts.values())
    x = cx - total / 2
    y = cy - (ascent - descent) / 2
    for ch in text:
        f = fonts[_route_font_name(ch, default)]
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f)


# ============================================================
# WELCOME CARD (template-based, matches the old canvas layout)
# ============================================================

WELCOME_TEMPLATE = os.path.join(os.path.dirname(__file__), 'assets', 'welcome-template.png')


async def generate_welcome_card(
    username,
    member_number,
    avatar_url,
    quote='Welcome to the server.',
    author='The Staff',
    background=None,
    orientation='landscape',
    accent='#27d9b5',
    text_color='#FFFFFF',
    muted_color='#8B8B8B',
    quote_color='#FFFFFF',
):
    if os.path.exists(WELCOME_TEMPLATE):
        bg = Image.open(WELCOME_TEMPLATE).convert('RGBA')
    else:
        bg = Image.new('RGBA', (500, 350), (34, 36, 37, 255))
    WIDTH, HEIGHT = bg.size
    draw = ImageDraw.Draw(bg)
    white = hex_color(text_color)

    avatar = await download_avatar(avatar_url) if avatar_url else None

    # smooth circular avatar, no border
    avatar_size = 120
    cx = 250
    cy = 150
    if avatar:
        av = avatar.convert('RGBA')
        w, h = av.size
        side = min(w, h)
        av = av.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
        # supersampled mask => anti-aliased circle edge (no jagged pixels)
        ss = 4
        big = av.resize((avatar_size * ss, avatar_size * ss), Image.LANCZOS)
        mask = Image.new('L', (avatar_size * ss, avatar_size * ss), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_size * ss, avatar_size * ss), fill=255)
        mask = mask.resize((avatar_size, avatar_size), Image.LANCZOS)
        av = big.resize((avatar_size, avatar_size), Image.LANCZOS)
        bg.paste(av, (cx - avatar_size // 2, cy - avatar_size // 2), mask)

    # member number text
    _draw_routed_line(draw, 250, 62, f'Member #{member_number}', 21, white)

    # welcome + the member's (unicode-safe) name below the avatar
    display = username
    if len(display) > 15:
        _draw_routed_line(draw, 250, 225, 'Welcome,', 20, white)
        _draw_routed_line(draw, 250, 260, f'{display}!', 20, white)
    else:
        _draw_routed_line(draw, 250, 245, f'Welcome, {display}!', 24, white)

    # ---- Save ----
    out_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(out_dir, exist_ok=True)
    filename = os.path.join(out_dir, f'welcome_{member_number}.png')
    bg.convert('RGB').save(filename, quality=95)
    _prune_output(out_dir)
    return filename


# ============================================================
# QUOTE CARD (black & white profile + gold/white gradient quote)
# ============================================================

def _prune_output(out_dir, keep=40):
    """Keep the output folder small - free hosting only has ~1 GB of disk."""
    try:
        files = [f for f in os.listdir(out_dir) if f.endswith('.png')]
    except OSError:
        return
    if len(files) <= keep:
        return
    files.sort(key=lambda name: os.path.getmtime(os.path.join(out_dir, name)))
    for name in files[:len(files) - keep]:
        try:
            os.remove(os.path.join(out_dir, name))
        except OSError:
            pass

def _quote_mark_sprite(tt_size, fill, angle=180):
    """Render a big \"mark\" character (low double comma `,,`) flipped 180 degrees
    so it looks like an opening quote symbol. Returns a cropped RGBA sprite."""
    tmp = Image.new('RGBA', (tt_size * 3, tt_size * 3), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text(
        (tt_size * 1.5, tt_size * 1.5),
        '\u201e',
        font=font('DMSerifDisplay-Regular.ttf', tt_size),
        fill=fill,
        anchor='mm',
    )
    tmp = tmp.rotate(angle, resample=Image.BICUBIC, expand=True)
    bbox = tmp.getbbox()
    return tmp.crop(bbox)


async def generate_quote_card(
    text,
    author,
    username,
    nickname=None,
    avatar_url=None,
    background=None,
    orientation='landscape',
    accent='#C9A227',
    text_color='#F5F5F5',
    muted_color='#9A9A9A',
    quote_color='#FFFFFF',
    font_name='DelaGothicOne-Regular.ttf',
    color='gold',
):
    if background is None:
        background = os.path.join(BACKGROUND_DIR, 'default.jpg')

    if orientation == 'portrait':
        WIDTH, HEIGHT = 900, 1200
    else:
        WIDTH, HEIGHT = 1200, 630        # premium horizontal card

    bg = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(bg)

    avatar = await download_avatar(avatar_url) if avatar_url else None

    quote_text = strip_markdown(text)
    name = nickname or author
    PALETTES = {
        'gold': ['#cf9a0d', '#efc504', '#fff6cd', '#ffeb9d', '#fadc5a'],
        'silver': ['#B1B2B4', '#7A7B7F', '#F0F0F0', '#A7A8AC', '#EDEDED'],
        'blue': ['#29364E', '#0CB6D7', '#8DD1E3', '#164E7E', '#21242B'],
    }
    outer = PALETTES.get((color or 'gold').lower()) or PALETTES['gold']
    qfont_name = font_name or 'DelaGothicOne-Regular.ttf'
    mark_grey = (150, 150, 150, 255)

    if orientation == 'landscape':
        # ========= LEFT — B&W dimmed profile (~57%) with smooth fade =========
        # ========= RIGHT — black shifts a bit past center, quote hugs edge =========
        panel = 680
        if avatar:
            photo = cover_avatar(avatar, panel + 80, 700, align_x='left', align_y='bottom')
            photo = photo.crop((0, 0, panel, HEIGHT))
            photo = ImageOps.grayscale(photo).convert('RGBA')
            dim = Image.new('RGBA', photo.size, (0, 0, 0, 105))
            photo = Image.alpha_composite(photo, dim)
            bg.alpha_composite(photo, (0, 0))
            bg.alpha_composite(smooth_fade(250, HEIGHT), (430, 0))
            draw = ImageDraw.Draw(bg)

        x0 = 700                      # straight left edge of the whole column
        text_x = x0
        x1 = WIDTH - 60
        qw = x1 - text_x

        block_size, lines, line_height = fit_quote(quote_text, draw, qw, 330, font_name=qfont_name)
        dh = int(line_height * 1.18)      # tight, even line spacing
        block_h = (len(lines) - 1) * dh + line_height

        spr = _quote_mark_sprite(110, (*mark_grey[:3], 255))
        GAP_M, GAP_I, info_h = 26, 28, 60
        middle = HEIGHT // 2
        total = spr.height + GAP_M + block_h + GAP_I + info_h
        start_top = middle - total // 2
        if start_top < 20:
            start_top = 20

        # flipped ",," mark directly above the text, flush with its left edge
        bg.alpha_composite(spr, (x0, start_top))
        start_y = start_top + spr.height + GAP_M

        # quote lines — every line starts at the same left x
        y = start_y
        for line in lines:
            line = line.strip()
            if line:
                lf = pick_unicode_font(line, block_size, default=qfont_name)
                _draw_gradient_text(draw, (text_x, y), line, lf, outer, '#FFFFFF', center_white=True, stroke=0)
                y += dh

        # ─── divider + name, then @username sharing the same left edge as the name
        ny = start_y + block_h + GAP_I
        nf = pick_unicode_font(name, 24, default='Sans-SemiBold.ttf')
        uf = pick_unicode_font(username, 18, default='Sans-Bold.ttf')
        name_cx = text_x + 40
        draw.line((text_x, ny + 16, text_x + 26, ny + 16), fill=(119, 119, 119, 255), width=2)
        draw.text((name_cx, ny), name, font=nf, fill=(245, 245, 245, 255))
        draw.text((name_cx, ny + 34), f'@{username}', font=uf, fill=(136, 136, 136, 255))

    else:
        # ========= PORTRAIT — B&W dimmed profile on top, quote below =========
        avatar_h = 470
        if avatar:
            photo = cover_avatar(avatar, WIDTH, avatar_h + 40, align_x='center', align_y='bottom')
            photo = photo.crop((0, 0, WIDTH, avatar_h))
            photo = ImageOps.grayscale(photo).convert('RGBA')
            dim = Image.new('RGBA', photo.size, (0, 0, 0, 105))
            photo = Image.alpha_composite(photo, dim)
            bg.alpha_composite(photo, (0, 0))
            bg.alpha_composite(smooth_fade(WIDTH, 160, vertical=True), (0, avatar_h - 160))
            draw = ImageDraw.Draw(bg)

        x0 = 90
        text_x = x0
        x1 = WIDTH - 50
        qw = x1 - text_x

        block_size, lines, line_height = fit_quote(quote_text, draw, qw, 420, font_name=qfont_name)
        dh = int(line_height * 1.25)
        block_h = (len(lines) - 1) * dh + line_height

        spr = _quote_mark_sprite(110, (*mark_grey[:3], 255))
        GAP_M, GAP_I, info_h = 26, 28, 60
        top_m = avatar_h + 40
        bot_m = HEIGHT - 10
        middle = (top_m + bot_m) // 2
        total = spr.height + GAP_M + block_h + GAP_I + info_h
        start_top = middle - total // 2
        if start_top < top_m:
            start_top = top_m

        # flipped ",," mark directly above the text, flush with its left edge
        bg.alpha_composite(spr, (x0, start_top))
        start_y = start_top + spr.height + GAP_M

        # quote lines — every line starts at the same left x
        y = start_y
        for line in lines:
            line = line.strip()
            if line:
                lf = pick_unicode_font(line, block_size, default=qfont_name)
                _draw_gradient_text(draw, (text_x, y), line, lf, outer, '#FFFFFF', center_white=True, stroke=0)
                y += dh

        # ─── divider + name, then @username sharing the same left edge as the name
        ny = start_y + block_h + GAP_I
        nf = pick_unicode_font(name, 24, default='Sans-SemiBold.ttf')
        uf = pick_unicode_font(username, 18, default='Sans-Bold.ttf')
        name_cx = text_x + 40
        draw.line((text_x, ny + 16, text_x + 26, ny + 16), fill=(119, 119, 119, 255), width=2)
        draw.text((name_cx, ny), name, font=nf, fill=(245, 245, 245, 255))
        draw.text((name_cx, ny + 34), f'@{username}', font=uf, fill=(136, 136, 136, 255))

    # ---- Save ----
    out_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(out_dir, exist_ok=True)
    filename = os.path.join(out_dir, f'quote_{int(time.time() * 1000)}.png')
    bg.convert('RGB').save(filename, quality=95)
    _prune_output(out_dir)
    return filename


def fit_quote(text, draw, max_w, max_block_h, words_per_line=4, font_name='DelaGothicOne-Regular.ttf'):
    """Wrap so each line holds ~`words_per_line` words and pick a size that fits.
    Short text renders BIG, long text renders small — size scales with how much text there is."""
    words = text.split()
    n = len(text)
    if n <= 28:        cap = 46
    elif n <= 48:      cap = 40
    elif n <= 72:      cap = 34
    elif n <= 104:     cap = 30
    else:              cap = 26
    best_lines, best = None, None
    for size in (46, 40, 36, 32, 29, 26, 24, 22, 20):
        if size > cap:
            continue
        f = font(font_name, size)
        lines, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= words_per_line:
                lines.append(' '.join(cur))
                cur = []
        if cur:
            lines.append(' '.join(cur))
        if any(draw.textlength(l, font=f) > max_w for l in lines):
            continue
        lh = int(size * 1.6)
        if len(lines) * lh <= max_block_h:
            return size, lines, lh
        best_lines, best = lines, size
    if best is not None:
        return best, best_lines, int(best * 1.6)
    return 20, words, int(20 * 1.6)