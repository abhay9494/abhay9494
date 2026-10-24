#!/usr/bin/env python3
"""Build the profile README and its cards in the look of https://abhay9494.github.io.

Every card is an animated SVG set in the portfolio's fonts and colours, drawn once
for GitHub's dark theme and once for its light theme. .github/workflows/cards.yml
runs this every day so the rating graphs and the activity card stay current.
Ratings come from the portfolio's daily sync, activity from GitHub. A source that
cannot be reached keeps its last data (data/cache.json), so no card ever goes blank.

    pip install fonttools
    python scripts/build_cards.py
"""
import base64
import datetime
import html
import io
import json
import logging
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from types import SimpleNamespace

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / 'fonts'
CACHE = ROOT / 'data' / 'cache.json'
PORTRAIT = ROOT / 'data' / 'portrait.txt'
ASSETS = ROOT / 'assets'
README = ROOT / 'README.md'

USER = 'abhay9494'
SITE = 'https://abhay9494.github.io'
EMAIL = 'abhayyy9494@gmail.com'
LINKEDIN = 'https://www.linkedin.com/in/abhay9494'
CODEFORCES = 'https://codeforces.com/profile/abhay9494'
CODECHEF = 'https://www.codechef.com/users/abhay9492'
RESUME = SITE + '/assets/Abhay_Prasad_Resume.pdf'
RATINGS_URL = 'https://raw.githubusercontent.com/abhay9494/abhay9494.github.io/main/assets/data/ratings.json'
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def gmail(subject=''):
    return f'https://mail.google.com/mail/?view=cm&fs=1&to={EMAIL}&su={urllib.parse.quote(subject)}&body='


def drive(file_id):
    return f'https://drive.google.com/file/d/{file_id}/view'


# ---------- the portfolio's two themes ----------

THEMES = {
    'dark': SimpleNamespace(
        bg='#03060f', surface='#08142c', mock='#050b1a', bar='#0b1a38', field='#0e2044',
        ink='#e8f4ff', ink2='#a8c4e8', ink3='#7893bb', line='#82b9ff', la=.12, la2=.22,
        accent='#2ea6ff', accent_ink='#7cc9ff', soft='#0b2a56', shine='#d2efff', ascii='#49b4ff',
        amber='#ffb454', cyan='#5fe0ff', ok='#3fcf5f', live='#22c55e', chart='#2f8cf0', grain='#ffffff',
        blobs=('#0a2452', '#1e8fff', '#06345e'), pill=('#0f3570', '#0a2350'), heat0='#0e2044',
        langs=('#2ea6ff', '#7cc9ff', '#1d6fd8', '#5fe0ff', '#a8c4e8', '#3d5f99')),
    'light': SimpleNamespace(
        bg='#eef5fd', surface='#f8fbff', mock='#ffffff', bar='#f1f6fc', field='#eef4fb',
        ink='#06142e', ink2='#2f4a72', ink3='#566f94', line='#06142e', la=.12, la2=.22,
        accent='#0a72d8', accent_ink='#0759b0', soft='#d3e7fc', shine='#8fd0ff', ascii='#0a62c0',
        amber='#c26a00', cyan='#0089a8', ok='#1f9d3a', live='#16a34a', chart='#1f6fd1', grain='#06142e',
        blobs=('#c4e0ff', '#3d9bff', '#d2f1ff'), pill=('#e1effd', '#d3e7fc'), heat0='#e1edfb',
        langs=('#0a72d8', '#3d9bff', '#06428a', '#0089a8', '#7aa7d9', '#a9bdd8')),
}


# ---------- fonts ----------

FONT_SPEC = {  # css class: (file, weight, style, fallback stack)
    'serif': ('InstrumentSerif-Regular.ttf', 400, 'normal', "Georgia,'Times New Roman',serif"),
    'serif-i': ('InstrumentSerif-Italic.ttf', 400, 'italic', "Georgia,'Times New Roman',serif"),
    'sans': ('Geist-400.ttf', 400, 'normal', "'Segoe UI',Helvetica,Arial,sans-serif"),
    'sans5': ('Geist-500.ttf', 500, 'normal', "'Segoe UI',Helvetica,Arial,sans-serif"),
    'sans6': ('Geist-600.ttf', 600, 'normal', "'Segoe UI',Helvetica,Arial,sans-serif"),
    'mono': ('GeistMono-400.ttf', 400, 'normal', 'ui-monospace,SFMono-Regular,Consolas,monospace'),
    'mono5': ('GeistMono-500.ttf', 500, 'normal', 'ui-monospace,SFMono-Regular,Consolas,monospace'),
    'display': ('BebasNeue-Regular.ttf', 400, 'normal', 'Impact,sans-serif'),
}


class Font:
    """Measures text (with pair kerning) and embeds only the glyphs a card uses."""

    def __init__(self, key):
        self.key = key
        file, self.weight, self.style, self.fallback = FONT_SPEC[key]
        self.path = FONT_DIR / file
        tt = TTFont(self.path, recalcTimestamp=False)
        self.upm = tt['head'].unitsPerEm
        self.cmap = tt.getBestCmap()
        self.adv = {g: m[0] for g, m in tt['hmtx'].metrics.items()}
        self.pairs = self._pair_subtables(tt)
        self._kern, self._faces = {}, {}

    @staticmethod
    def _pair_subtables(tt):
        if 'GPOS' not in tt or not tt['GPOS'].table.FeatureList:
            return []
        gpos = tt['GPOS'].table
        ids = sorted({i for fr in gpos.FeatureList.FeatureRecord if fr.FeatureTag == 'kern'
                      for i in fr.Feature.LookupListIndex})
        out = []
        for i in ids:
            lookup = gpos.LookupList.Lookup[i]
            for st in lookup.SubTable:
                kind = lookup.LookupType
                if kind == 9:
                    kind, st = st.ExtensionLookupType, st.ExtSubTable
                if kind == 2:
                    out.append((st, {g: k for k, g in enumerate(st.Coverage.glyphs)}))
        return out

    def kern(self, a, b):
        if (a, b) not in self._kern:
            value = 0
            for st, cov in self.pairs:
                if a not in cov:
                    continue
                if st.Format == 1:
                    rec = next((r for r in st.PairSet[cov[a]].PairValueRecord if r.SecondGlyph == b), None)
                    if rec is None:
                        continue
                    value = getattr(rec.Value1, 'XAdvance', 0) or 0
                else:
                    c1 = st.ClassDef1.classDefs.get(a, 0) if st.ClassDef1 else 0
                    c2 = st.ClassDef2.classDefs.get(b, 0) if st.ClassDef2 else 0
                    value = getattr(st.Class1Record[c1].Class2Record[c2].Value1, 'XAdvance', 0) or 0
                break
            self._kern[(a, b)] = value
        return self._kern[(a, b)]

    def layout(self, s, size, ls=0.0):
        """x offset of every character, and the total advance."""
        k = size / self.upm
        xs, x, prev = [], 0.0, None
        for ch in s:
            g = self.cmap.get(ord(ch))
            if prev and g:
                x += self.kern(prev, g) * k
            xs.append(x)
            x += (self.adv[g] * k if g else size * 0.6) + ls
            prev = g
        return xs, x - (ls if s else 0)

    def width(self, s, size, ls=0.0):
        return self.layout(s, size, ls)[1]

    def face(self, chars):
        """@font-face rule carrying a WOFF of just these characters."""
        chars = ''.join(sorted(set(chars)))
        if chars not in self._faces:
            tt = TTFont(self.path, recalcTimestamp=False)
            opts = subset.Options()
            opts.flavor = 'woff'
            opts.hinting = False
            opts.drop_tables += ['meta']
            sub = subset.Subsetter(opts)
            sub.populate(unicodes={ord(c) for c in chars})
            sub.subset(tt)
            tt.flavor = 'woff'
            buf = io.BytesIO()
            tt.save(buf)
            data = base64.b64encode(buf.getvalue()).decode()
            self._faces[chars] = (f"@font-face{{font-family:'ap-{self.key}';font-weight:{self.weight};"
                                  f"font-style:{self.style};src:url(data:font/woff;base64,{data}) format('woff')}}")
        return self._faces[chars]


logging.getLogger('fontTools.subset').setLevel(logging.ERROR)
FONTS = {k: Font(k) for k in FONT_SPEC}


def fit(font, text, size, maxw):
    w = FONTS[font].width(text, size)
    return size if w <= maxw else size * maxw / w


# ---------- svg building blocks ----------

def n(v):
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def esc(s):
    return html.escape(str(s), quote=True)


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.css, self.defs, self.body = [], [], []
        self.chars = defaultdict(set)
        self.count = 0

    def uid(self, prefix='u'):
        self.count += 1
        return f'{prefix}{self.count}'

    def add(self, *parts):
        self.body.extend(parts)

    def style(self, *rules):
        for r in rules:
            if r not in self.css:
                self.css.append(r)

    def text(self, x, y, s, font='sans', size=14, fill=None, anchor=None, ls=None, cls=None, attrs=''):
        self.chars[font].update(s)
        a = f'class="{font}{" " + cls if cls else ""}" x="{n(x)}" y="{n(y)}" font-size="{n(size)}"'
        if fill:
            a += f' fill="{fill}"'
        if anchor:
            a += f' text-anchor="{anchor}"'
        if ls:
            a += f' letter-spacing="{n(ls)}"'
        if attrs:
            a += ' ' + attrs
        return f'<text {a}>{esc(s)}</text>'

    def line(self, x, y, segs, size, width=0.0, anchor='start', attrs=''):
        """One laid-out line from wrap(): every segment sits at its measured x."""
        x0 = x - (width / 2 if anchor == 'middle' else width if anchor == 'end' else 0)
        spans = []
        for font, s, fill, scale, dx in segs:
            self.chars[font].update(s)
            fs = f' font-size="{n(size * scale)}"' if scale != 1 else ''
            spans.append(f'<tspan class="{font}" x="{n(x0 + dx)}" fill="{fill}"{fs}>{esc(s)}</tspan>')
        return f'<text y="{n(y)}" font-size="{n(size)}"{" " + attrs if attrs else ""}>{"".join(spans)}</text>'

    def render(self):
        faces = ''.join(FONTS[k].face(''.join(v)) for k, v in sorted(self.chars.items()) if v)
        classes = ''.join(f".{k}{{font-family:'ap-{k}',{FONTS[k].fallback};font-weight:{FONTS[k].weight};"
                          f"font-style:{FONTS[k].style}}}" for k in sorted(self.chars))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{n(self.w)}" height="{n(self.h)}" '
                f'viewBox="0 0 {n(self.w)} {n(self.h)}" role="img" aria-label="{esc(self.title)}">'
                f'<title>{esc(self.title)}</title><style>{faces}{classes}{"".join(self.css)}</style>'
                f'<defs>{"".join(self.defs)}</defs>{"".join(self.body)}</svg>\n')


def runs(md, font='sans', fill=None, em=None, strong=None, em_scale=1.12):
    """'plain *serif italic* **bold**' -> [(font, text, fill, scale)]."""
    bold = {'sans': 'sans6', 'mono': 'mono5'}.get(font, font)
    out = []
    for part in re.split(r'(\*\*.+?\*\*|\*.+?\*)', md):
        if part.startswith('**'):
            out.append((bold, part[2:-2], strong or fill, 1))
        elif part.startswith('*') and len(part) > 1:
            out.append(('serif-i', part[1:-1], em or fill, em_scale))
        elif part:
            out.append((font, part, fill, 1))
    return out


def wrap(rs, size, maxw=1e9, words=False):
    """Lay runs out in lines no wider than maxw -> [(segments, width)].
    Each segment is [font, text, fill, scale, x]; with words=True every word is its own segment."""
    lines, cur, x, gap = [], [], 0.0, 0.0
    for font, text, fill, scale in rs:
        F, fs = FONTS[font], size * scale
        for tok in re.findall(r'\s+|\S+', text):
            if tok.isspace():
                if cur:
                    gap = F.width(' ', fs)
                continue
            w = F.width(tok, fs)
            if cur and x + gap + w > maxw:
                lines.append((cur, x))
                cur, x, gap = [], 0.0, 0.0
            last = cur[-1] if cur else None
            if not words and last and last[0] == font and last[2] == fill and last[3] == scale:
                last[1] += (' ' if gap else '') + tok
            else:
                cur.append([font, tok, fill, scale, x + gap])
            x += gap + w
            gap = 0.0
    if cur:
        lines.append((cur, x))
    return lines


ICONS = {
    'arrow': '<path d="M7 17 17 7"/><path d="M7 7h10v10"/>',
    'down': '<path d="M12 4v16"/><path d="m6 14 6 6 6-6"/>',
    'lock': '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    'mail': '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    'linkedin': ('<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6z"/>'
                 '<rect width="4" height="12" x="2" y="9"/><circle cx="4" cy="4" r="2"/>'),
    'star': '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>',
    'bars': '<path d="M5 20v-7"/><path d="M12 20V4"/><path d="M19 20v-11"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'pause': '<path d="M9 5v14"/><path d="M15 5v14"/>',
    'bolt': '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
}


def icon(name, x, y, size, color, fill='none', sw=2):
    return (f'<g transform="translate({n(x)} {n(y)}) scale({size / 24:.4f})" fill="{fill}" stroke="{color}" '
            f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def stroke(T, a=None):
    return f'stroke="{T.line}" stroke-opacity="{n(T.la if a is None else a)}"'


def hline(T, x1, x2, y, a=None, dash=False):
    d = ' stroke-dasharray="3 4"' if dash else ''
    return f'<path d="M{n(x1)} {n(y)}H{n(x2)}" {stroke(T, a)}{d}/>'


def panel(s, T, x=0.5, y=0.5, w=None, h=None, r=22, glow=(.12, 0)):
    """A card like the site's: surface, hairline border and a faint glow in one corner."""
    w = s.w - 1 if w is None else w
    h = s.h - 1 if h is None else h
    gid = s.uid('pg')
    s.defs.append(f'<radialGradient id="{gid}" cx="{glow[0]}" cy="{glow[1]}" r="1">'
                  f'<stop offset="0" stop-color="{T.accent}" stop-opacity=".11"/>'
                  f'<stop offset=".55" stop-color="{T.accent}" stop-opacity="0"/></radialGradient>')
    box = f'x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{r}"'
    return f'<rect {box} fill="{T.surface}"/><rect {box} fill="url(#{gid})" {stroke(T)}/>'


def _kt(t):
    return f'{t:.4f}'.rstrip('0').rstrip('.') or '0'


def steps(attr, events, cycle):
    """Discrete SMIL animation through (time, value) events, repeating every `cycle` seconds."""
    ev = {}
    for t, v in sorted(events, key=lambda e: e[0]):
        ev[round(min(t, cycle - .001) / cycle, 4)] = v
    if 0 not in ev:
        ev[0.0] = ev[max(ev)]
    keys = sorted(ev)
    return (f'<animate attributeName="{attr}" dur="{n(cycle)}s" repeatCount="indefinite" calcMode="discrete" '
            f'keyTimes="{";".join(_kt(k) for k in keys)}" values="{";".join(n(ev[k]) for k in keys)}"/>')


def keyed(attr, points, cycle):
    """Linear SMIL animation through (time, value) points, repeating every `cycle` seconds."""
    pts = sorted(points, key=lambda p: p[0])
    if pts[0][0] > 0:
        pts.insert(0, (0, pts[0][1]))
    if pts[-1][0] < cycle:
        pts.append((cycle, pts[-1][1]))
    return (f'<animate attributeName="{attr}" dur="{n(cycle)}s" repeatCount="indefinite" '
            f'keyTimes="{";".join(_kt(min(t, cycle) / cycle) for t, _ in pts)}" '
            f'values="{";".join(n(v) for _, v in pts)}"/>')


def show(on, off, cycle, fade=.3, lo=0.0, hi=1.0):
    """Opacity that fades in at `on` and out at `off` seconds, every cycle."""
    return keyed('opacity', [(0, lo), (on, lo), (on + fade, hi), (off, hi), (min(off + fade, cycle), lo)], cycle)


def typed(s, x, y, text, font, size, fill, t0, cps, cycle, t_out):
    """Text that types itself in from t0 and clears at t_out (SMIL clip, one step per letter)."""
    xs, tw = FONTS[font].layout(text, size)
    ends = xs[1:] + [tw]
    ev = [(t0 + (k + 1) / cps, ends[k] + 1) for k in range(len(text))] + [(t_out, 0)]
    cid = s.uid('ty')
    s.defs.append(f'<clipPath id="{cid}"><rect x="{n(x - 1)}" y="{n(y - size * 1.05)}" height="{n(size * 1.45)}" '
                  f'width="0">{steps("width", ev, cycle)}</rect></clipPath>')
    return s.text(x, y, text, font, size, fill, attrs=f'clip-path="url(#{cid})"')


RISE = '.rise{animation:rise 1.1s cubic-bezier(.2,.8,.2,1) both}@keyframes rise{from{transform:translateY(1.08em)}}'
FADE = '.fade{animation:fade 1s ease both}@keyframes fade{from{opacity:0;transform:translateY(8px)}}'
PING = ('.ping{transform-box:fill-box;transform-origin:center;animation:ping 2s cubic-bezier(0,0,.2,1) infinite}'
        '@keyframes ping{75%,100%{transform:scale(2.6);opacity:0}}')
BLINK = '.blink{animation:blink 1s step-end infinite}@keyframes blink{50%{opacity:0}}'
SHEEN = ('.sheen{transform-box:fill-box;animation:sheen 6s cubic-bezier(.7,0,.3,1) infinite both}'
         '@keyframes sheen{0%{transform:translateX(-160%) skewX(-20deg)}30%,100%{transform:translateX(260%) skewX(-20deg)}}')


def sheen_band(s, x, y, w, h, clip, delay=0.0, alpha=.22):
    gid = s.uid('sg')
    s.defs.append(f'<linearGradient id="{gid}"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                  f'<stop offset=".5" stop-color="#fff" stop-opacity="{alpha}"/>'
                  f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    s.style(SHEEN)
    return (f'<g clip-path="url(#{clip})"><rect class="sheen" x="{n(x)}" y="{n(y)}" width="{n(w * .45)}" '
            f'height="{n(h)}" fill="url(#{gid})" style="animation-delay:{delay:.2f}s"/></g>')


def rising_words(s, T, x, y, md, size, maxw, d0=0.0, step=.06, hook_scale=.74):
    """A serif title whose *part* is accent italic, each word rising out of a mask like the site's SplitText."""
    rs = []
    for font, text, fill, scale in runs(md, 'serif', T.ink, em=T.accent, em_scale=1):
        if font == 'serif-i' and '↪' in text:
            head, _, rest = text.partition('↪')
            if head:
                rs.append(('serif-i', head, T.accent, 1))
            rs.append(('sans', '↪', T.accent, hook_scale))
            rs.append(('serif-i', rest, T.accent, 1))
        else:
            rs.append((font, text, fill, scale))
    s.style(RISE, '.hook{animation:hook 3.2s ease-in-out infinite}@keyframes hook{50%{transform:translateX(5px)}}')
    out, i = [], 0
    lines = wrap(rs, size, maxw, words=True)
    for li, (segs, _) in enumerate(lines):
        yy = y + li * size * 1.02
        cid = s.uid('hc')
        s.defs.append(f'<clipPath id="{cid}"><rect x="{n(x - 10)}" y="{n(yy - size)}" width="{n(maxw + 40)}" '
                      f'height="{n(size * 1.3)}"/></clipPath>')
        words = []
        for font, text, fill, scale, dx in segs:
            t = s.text(x + dx, yy, text, font, size * scale, fill, cls='rise',
                       attrs=f'style="animation-delay:{d0 + i * step:.2f}s"')
            words.append(f'<g class="hook">{t}</g>' if text == '↪' else t)
            i += 1
        out.append(f'<g clip-path="url(#{cid})">{"".join(words)}</g>')
    return ''.join(out), len(lines)


# ---------- content (kept in step with the portfolio) ----------

TICKER = [
    ('Now', 'Incoming SDE Intern at Tesco Technology, Bengaluru'),
    ('Best', 'Top 1,000 of 32,000+ teams · Amazon ML Challenge 2026'),
    ('Rating', 'Codeforces Specialist · max rating {cf_max}'),
    ('Rating', 'CodeChef {cc_rank} · peak rating {cc_max}'),
    ('Studying', 'Final-year B.Tech IT · IIIT Lucknow'),
    ('Built', 'Auto Form Filler · fills job applications, never presses Submit'),
    ('Certified', 'Microsoft Certified: SQL AI Developer Associate'),
    ('Finalist', 'Flipkart Grid 7.0 · National Semi-Finalist'),
]
TYPED = ['Chrome extensions', 'Telegram bots', 'ML pipelines', 'REST APIs', 'LLM integrations']

PROJECTS = [
    dict(key='aff', no='01', created='Oct 2026', type='Chrome extension', scope='Frontend · AI · Testing',
         title='Auto Form Filler', color='accent', visual='aff', private=True,
         lede='Fills job applications and Google Forms page by page, uploads the right resume, and '
              '*never presses the final Submit*.',
         points=['Profile and memory answer first, then **one batched LLM call** per form for the rest',
                 '**Resume Studio** tailors a one-page LaTeX resume to each job description',
                 '**90+ unit tests** and a **70+ check** Puppeteer end-to-end suite on live forms'],
         stack='JavaScript · Chrome MV3 · Gemini / Groq · LaTeX · Puppeteer'),
    dict(key='mailer', no='02', created='Aug 2026', type='Automation bot', scope='Backend · DevOps',
         title='HR Auto Mailer Bot', color='amber', visual='mailer', private=True,
         lede='Cold-email outreach that runs itself on GitHub Actions. *No laptop, no server.*',
         points=['Reads recruiter contacts from Google Sheets and sends personalised emails with my resume',
                 '**10 runs a day** with per-account limits, **48-hour cooldowns** and a dry-run mode',
                 'Telegram commands (/status, /cooldown, /volume) control sending remotely'],
         stack='Python · Gmail SMTP / IMAP · Google Sheets · GitHub Actions · Telegram'),
    dict(key='amazon', no='03', created='Sep 2026', type='ML competition', scope='Data · Modelling · Validation',
         title='Amazon ML Challenge', color='cyan', visual='amazon', private=False,
         href='https://github.com/abhay9494/amazon-ml-challenge-2026',
         lede='Linking **10.3M** noisy, multilingual business records to **2.2M** entities, *on a CPU*.',
         points=['Blocking and a LightGBM pruner keep **~6 candidates per entity at 98.5% recall**',
                 'A 3-model LightGBM ensemble on ~140 features, validated leak-free over 13 versions',
                 '**Top 1,000 of 32,000+ teams** · 0.985 macro F0.5 · peak public rank 416'],
         stack='Python · Pandas / Polars · LightGBM · RapidFuzz · AWS'),
]

ROWS = [
    dict(no='04', title='Apply Links Telegram Bot', meta='Python · Telethon · Groq · Flask', year='2025',
         href='https://github.com/abhay9494/Apply-Links-Bot',
         desc='Reads the last 48 hours of posts from 20+ job channels, lets an LLM keep the ones that fit '
              "each student's batch, and sends them to **100+ subscribers**."),
    dict(no='05', title='MediEduMatch', meta='React · Spring Boot · MySQL · JWT', year='2024',
         href='https://github.com/abhay9494/Mediedumatch',
         desc='A NEET college predictor. I led a 4-member team and built the Spring Boot REST APIs that '
              'match a rank, category and state against **1,000+ college cutoffs**.'),
    dict(no='06', title='Social Media App', meta='Node.js · Express · EJS · MySQL', year='2024',
         href='https://github.com/abhay9494/InstagramClone',
         desc='An Instagram-style photo feed with 5 CRUD endpoints, Imgur image hosting, 500 Faker posts '
              'and layouts for five screen sizes.'),
]

EXPERIENCE = [
    ('Jan 2027 — Jun 2027', 'Software Development Engineer Intern', 'Tesco Technology · Bengaluru',
     'Selected through on-campus hiring at IIIT Lucknow.', True),
    ('Mar 2026 — May 2026', 'Business Analyst', 'Turing · Remote',
     'Ran side-by-side evaluations of AI-generated outputs, rating quality, accuracy and relevance, '
     'and fact-checked responses against sources.', False),
    ('Jan 2026 — Feb 2026', 'GUI Data Annotator', 'Turing · Remote',
     'Reconstructed GUI task trajectories as PyAutoGUI-style JSON for multimodal AI training. '
     'Rated **5/5** with **100% attendance** and a **0% rejection rate**.', False),
]
EDUCATION = [
    ('IIIT Lucknow', 'B.Tech · Information Technology', 'CGPA **8.0** / 10'),
    ('Tata DAV School', 'Class XII · Dhanbad', 'Scored **88.4%**'),
    ('De Nobili School, FRI', 'Class X · Dhanbad', 'Scored **94%**'),
]

CERTS = [
    dict(key='amazon', big='#416', small='peak public rank', label='ML competition · 2026',
         title='Amazon ML Challenge', sub='Top 1,000 of 32,000+ teams', cta='View the code',
         href='https://github.com/abhay9494/amazon-ml-challenge-2026'),
    dict(key='flipkart', big='Grid 7.0', small='national semi-finalist', label='Engineering challenge',
         title='Flipkart Grid 7.0', sub='National Semi-Finalist', cta='View certificate',
         href=drive('1cXhbC0zGDcfskCgY8G92dw1JQGunp4Kg')),
    dict(key='microsoft', big='SQL AI', small='developer associate', label='Certification',
         title='Microsoft Certified', sub='SQL AI Developer Associate', cta='View certificate',
         href=drive('1nxNUNpzdDlMcUilhQ099VTOhFexu_eba')),
    dict(key='algo', big='17', small='graph problems', label='Programming camp',
         title='AlgoUniversity', sub='GraphTheory Programming Camp · 17 advanced graph problems',
         cta='View certificate', href=drive('1afdVjzNCAyKGkr_Lu9aqwyEvKUHOhMyI')),
]

TOOLBOX = [
    ('Languages', 'C++ · C · Java · Python · JavaScript · SQL'),
    ('Frontend', 'React · Next.js · Tailwind CSS · HTML5 · CSS3 · EJS'),
    ('Backend & APIs', 'Node.js · Express · Spring Boot · FastAPI · JWT'),
    ('Data & ML', 'NumPy · Pandas · Polars · LightGBM · RapidFuzz'),
    ('Databases', 'MySQL · MongoDB'),
    ('Cloud & DevOps', 'AWS · Google Cloud · GitHub Actions · Git · NPM'),
    ('Automation & AI', 'Chrome MV3 · Puppeteer · Telethon · Gemini / Groq'),
]

RATING = {
    'codeforces': dict(
        title='Codeforces', href=CODEFORCES, source='Codeforces', peak_label='max rating',
        best=('Round 1002 (Div. 2)', '1,294 / 19,943 · top 6.5%'),
        bands=[(0, 1200, 'Newbie', '#9aa3ad'), (1200, 1400, 'Pupil', '#3fcf5f'),
               (1400, 1600, 'Specialist', '#2cc6b0'), (1600, 1900, 'Expert', '#4d7cff'),
               (1900, 2100, 'Cand. Master', '#c35cf0'), (2100, 2400, 'Master', '#ffb347')],
        rank=lambda r: ('Newbie' if r < 1200 else 'Pupil' if r < 1400 else 'Specialist' if r < 1600
                        else 'Expert' if r < 1900 else 'Candidate Master' if r < 2100 else 'Master')),
    'codechef': dict(
        title='CodeChef', href=CODECHEF, source='CodeChef', peak_label='peak rating',
        best=('Starters 167 (Div. 3)', '55 / 2,702 · top 2.0%'),
        bands=[(0, 1400, '1★', '#9aa3ad'), (1400, 1600, '2★', '#3fcf5f'), (1600, 1800, '3★', '#4d7cff'),
               (1800, 2000, '4★', '#9b6ad6'), (2000, 2200, '5★', '#ffbf00')],
        rank=lambda r: ('1★' if r < 1400 else '2★' if r < 1600 else '3★' if r < 1800
                        else '4★' if r < 2000 else '5★' if r < 2200 else '6★')),
}


# ---------- cards ----------

def banner(T, facts):
    W, H = 880, 456
    s = Svg(W, H, "Abhay Prasad, software engineer. I build Chrome extensions, Telegram bots, ML pipelines, "
                  "REST APIs and LLM integrations that take the boring parts off people's plates.")
    b1, b2, b3 = T.blobs
    s.defs.append(f'<clipPath id="card"><rect width="{W}" height="{H}" rx="26"/></clipPath>')
    s.defs.append('<filter id="soft" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="48"/></filter>')
    s.defs.append('<filter id="halo" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="16"/></filter>')
    s.defs.append(f'<filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="3" stitchTiles="stitch"/>'
                  f'<feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .7 0"/></filter>')
    s.defs.append(f'<linearGradient id="legible" x1="0" x2="1"><stop offset="0" stop-color="{T.bg}" stop-opacity=".7"/>'
                  f'<stop offset=".62" stop-color="{T.bg}" stop-opacity="0"/></linearGradient>')
    s.defs.append(f'<linearGradient id="shine" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="320" y2="0">'
                  f'<stop offset="0" stop-color="{T.accent}"/><stop offset=".42" stop-color="{T.accent}"/>'
                  f'<stop offset=".5" stop-color="{T.shine}"/><stop offset=".58" stop-color="{T.accent}"/>'
                  f'<stop offset="1" stop-color="{T.accent}"/>'
                  f'<animateTransform attributeName="gradientTransform" type="translate" values="-460 0;760 0" '
                  f'dur="7s" repeatCount="indefinite"/></linearGradient>')
    s.style('.blob{transform-box:fill-box;transform-origin:center}',
            '.b1{animation:b1 17s ease-in-out infinite alternate}@keyframes b1{to{transform:translate(-140px,70px) scale(1.25)}}',
            '.b2{animation:b2 21s ease-in-out infinite alternate}@keyframes b2{to{transform:translate(170px,-60px) scale(.85)}}',
            '.b3{animation:b3 19s ease-in-out infinite alternate}@keyframes b3{to{transform:translate(-110px,-70px) scale(1.2)}}',
            '.b4{animation:b4 9s ease-in-out infinite alternate}@keyframes b4{to{transform:translate(60px,40px) scale(1.5);opacity:.15}}',
            RISE, FADE, PING, BLINK,
            '.halo{animation:halo 5s ease-in-out 1.4s infinite alternate both}@keyframes halo{from{opacity:.12}to{opacity:.6}}',
            '.reveal{transform-box:fill-box;transform-origin:50% 0;animation:reveal 2.2s cubic-bezier(.2,.8,.2,1) .4s both}'
            '@keyframes reveal{from{transform:scaleY(0)}}',
            '.scan{animation:scan 6s linear 2.6s infinite both}@keyframes scan{from{transform:translateY(0)}to{transform:translateY(380px)}}',
            '.tk{animation:tk 32s linear infinite both}'
            '@keyframes tk{0%{opacity:0;transform:translateY(8px)}1.6%{opacity:1;transform:none}11%{opacity:1;transform:none}'
            '12.5%{opacity:0;transform:translateY(-8px)}100%{opacity:0}}',
            '.tkbar{transform-box:fill-box;transform-origin:0 50%;animation:tkbar 4s linear infinite}'
            '@keyframes tkbar{from{transform:scaleX(0)}to{transform:scaleX(1)}}')

    s.add('<g clip-path="url(#card)">', f'<rect width="{W}" height="{H}" fill="{T.bg}"/>',
          '<g filter="url(#soft)">',
          f'<ellipse class="blob b2" cx="220" cy="410" rx="330" ry="150" fill="{b1}"/>',
          f'<ellipse class="blob b1" cx="500" cy="120" rx="250" ry="170" fill="{b2}" opacity=".55"/>',
          f'<ellipse class="blob b3" cx="830" cy="420" rx="240" ry="190" fill="{b3}"/>',
          f'<ellipse class="blob b4" cx="720" cy="260" rx="120" ry="90" fill="{T.accent}" opacity=".35"/>',
          '</g>',
          f'<rect width="{W}" height="{H}" fill="url(#legible)"/>',
          f'<rect width="{W}" height="{H}" filter="url(#grain)" fill="{T.grain}" opacity=".07"/>')

    # meta row and status pill
    s.add(s.text(34, 46, '(Software engineer)', 'mono', 12, T.ink2, cls='fade', attrs='style="animation-delay:.2s"'),
          s.text(214, 46, 'B.Tech IT · IIIT Lucknow', 'mono', 12, T.ink2, cls='fade', attrs='style="animation-delay:.3s"'))
    status = 'Incoming SDE Intern · Tesco Technology'
    sw = FONTS['sans'].width(status, 13) + 50
    sx = W - 26 - sw
    s.add(f'<g class="fade" style="animation-delay:.4s">',
          f'<rect x="{n(sx)}" y="24" width="{n(sw)}" height="32" rx="16" fill="{T.surface}" fill-opacity=".72" {stroke(T, T.la2)}/>',
          f'<circle class="ping" cx="{n(sx + 19)}" cy="40" r="4" fill="{T.live}"/>',
          f'<circle cx="{n(sx + 19)}" cy="40" r="4" fill="{T.live}"/>',
          s.text(sx + 33, 44.5, status, 'sans', 13, T.ink2), '</g>')

    # name, letter by letter out of a mask
    def word(text, font, size, x, y, fill, d0):
        xs, w = FONTS[font].layout(text, size)
        cid = s.uid('nm')
        s.defs.append(f'<clipPath id="{cid}"><rect x="{n(x - 20)}" y="{n(y - size)}" width="{n(w + 60)}" height="{n(size * 1.32)}"/></clipPath>')
        letters = ''.join(s.text(x + dx, y, ch, font, size, fill, cls='rise', attrs=f'style="animation-delay:{d0 + i * .055:.3f}s"')
                          for i, (ch, dx) in enumerate(zip(text, xs)))
        return f'<g clip-path="url(#{cid})">{letters}</g>'

    s.add(word('Abhay', 'serif', 124, 30, 168, T.ink, .25),
          f'<g class="halo" filter="url(#halo)">{s.text(30, 268, "Prasad", "serif-i", 124, T.accent)}</g>',
          word('Prasad', 'serif-i', 124, 30, 268, 'url(#shine)', .5))

    # "I build ___" typewriter on its own line, like the site, so nothing shifts
    y1, y2, ts = 326, 356, 19
    s.add(s.text(34, y1, 'I build', 'sans', ts, T.ink2, cls='fade', attrs='style="animation-delay:.9s"'))
    tx = 34 + FONTS['sans'].width('I build ', ts)
    per, caret = 3.2, []
    cycle = per * len(TYPED)
    for i, w in enumerate(TYPED):
        xs, tw = FONTS['sans5'].layout(w, ts)
        ends = xs[1:] + [tw]
        t0 = i * per + .2
        ev = [(t0 + (k + 1) * .065, ends[k]) for k in range(len(w))]
        t_del = t0 + per - .45 - len(w) * .022
        ev += [(t_del + (len(w) - k) * .022, ends[k - 1] if k else 0) for k in range(len(w) - 1, -1, -1)]
        caret += ev
        cid = s.uid('tw')
        s.defs.append(f'<clipPath id="{cid}"><rect x="{n(tx - 1)}" y="{y1 - 22}" height="30" width="0">'
                      f'{steps("width", [(t, x + 1.5 if x else 0) for t, x in ev], cycle)}</rect></clipPath>')
        s.add(s.text(tx, y1, w, 'sans5', ts, T.ink, attrs=f'clip-path="url(#{cid})"'))
    s.add(f'<rect class="blink" x="{n(tx)}" y="{y1 - 16}" width="2" height="20" rx="1" fill="{T.accent}">'
          f'{steps("x", [(t, tx + x + 2) for t, x in caret], cycle)}</rect>')
    line2 = wrap(runs("that take the *boring parts* off people's plates.", 'sans', T.ink2, em=T.ink, em_scale=1.2), ts)
    s.add(s.line(34, y2, line2[0][0], ts, attrs='class="fade" style="animation-delay:1s"'))

    # portrait made of code (the site's hero photo, as characters)
    rows = PORTRAIT.read_text('utf-8').rstrip('\n').split('\n')
    fs = 6.6
    pw, ph = max(map(len, rows)) * fs * .6, len(rows) * fs
    px, py = W - 30 - pw, 66
    asc = ''.join(s.text(px, py + (i + 1) * fs - fs * .2, r.replace(' ', ' '), 'mono', fs)
                  for i, r in enumerate(rows) if r.strip())
    s.defs.append(f'<g id="asc">{asc}</g>')
    s.defs.append('<radialGradient id="pfade" cx=".5" cy=".42" r=".6"><stop offset=".6" stop-color="#fff"/>'
                  '<stop offset="1" stop-color="#000"/></radialGradient>')
    s.defs.append('<linearGradient id="band" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000"/>'
                  '<stop offset=".5" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>')
    box = f'x="{n(px - 6)}" y="{n(py - 6)}" width="{n(pw + 12)}" height="{n(ph + 12)}"'
    s.defs.append(f'<mask id="pm" maskUnits="userSpaceOnUse" {box}><rect {box} fill="url(#pfade)"/></mask>')
    s.defs.append(f'<mask id="pr" maskUnits="userSpaceOnUse" {box}><rect class="reveal" {box} fill="#fff"/></mask>')
    s.defs.append(f'<mask id="pb" maskUnits="userSpaceOnUse" {box}><rect class="scan" x="{n(px - 6)}" y="{n(py - 70)}" '
                  f'width="{n(pw + 12)}" height="70" fill="url(#band)"/></mask>')
    s.add('<g mask="url(#pm)"><g mask="url(#pr)">',
          f'<use href="#asc" fill="{T.ascii}"/>',
          f'<use href="#asc" fill="{T.shine}" mask="url(#pb)"/>', '</g></g>',
          s.text(px + pw / 2, py + ph + 20, '[ made of code ]', 'mono', 10, T.ink3, anchor='middle', ls=.8,
                 cls='fade', attrs='style="animation-delay:1.6s"'))

    # header-style capsule with the rotating highlights
    cy, ch, cx = 392, 44, 24
    cw = W - 2 * cx
    s.defs.append(f'<clipPath id="cap"><rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="22"/></clipPath>')
    s.defs.append('<linearGradient id="ap" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3fb4ff"/>'
                  '<stop offset=".6" stop-color="#0a5fd0"/><stop offset="1" stop-color="#062a6b"/></linearGradient>')
    s.defs.append(f'<clipPath id="apc"><rect x="{cx + 6}" y="{cy + 6}" width="32" height="32" rx="10"/></clipPath>')
    s.add(f'<g class="fade" style="animation-delay:1.2s">',
          f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" rx="22" fill="{T.surface}" fill-opacity=".8" {stroke(T, T.la2)}/>',
          f'<rect x="{cx + 6}" y="{cy + 6}" width="32" height="32" rx="10" fill="url(#ap)"/>',
          s.text(cx + 22, cy + 29, 'AP', 'display', 19, '#fff', anchor='middle', ls=.4),
          sheen_band(s, cx + 6, cy + 6, 32, 32, 'apc', 1.0, .55))
    for i, (label, text) in enumerate(TICKER):
        text = text.format(**facts)
        lw = FONTS['mono5'].width(label.upper(), 10.5, .8) + 20
        s.add(f'<g class="tk" style="animation-delay:{i * 4}s">',
              f'<rect x="{cx + 48}" y="{cy + 11}" width="{n(lw)}" height="22" rx="11" fill="{T.soft}"/>',
              s.text(cx + 48 + lw / 2, cy + 26, label.upper(), 'mono5', 10.5, T.accent_ink, anchor='middle', ls=.8),
              s.text(cx + 48 + lw + 12, cy + 27, text, 'sans', 14.5, T.ink), '</g>')
    link = 'abhay9494.github.io'
    lx = W - cx - 38
    s.add(s.text(lx, cy + 27, link, 'mono', 11.5, T.accent_ink, anchor='end'),
          icon('arrow', lx + 6, cy + 15, 14, T.accent_ink),
          f'<g clip-path="url(#cap)"><rect class="tkbar" x="{cx}" y="{cy + ch - 2}" width="{cw}" height="2" fill="{T.accent}" opacity=".7"/></g>',
          '</g>', '</g>',
          f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="26" fill="none" {stroke(T)}/>')
    return s


def pill(T, label, name, glow=False):
    """The site's pill buttons: glowing glass for the main action, hairline for the rest."""
    h, fs, pad, gap, iw = 42, 14, 19, 8, 15
    tw = FONTS['sans5'].width(label, fs)
    w = round(pad + tw + gap + iw + pad)
    s = Svg(w + 2, h + 2, label)
    box = f'x="1" y="1" width="{w}" height="{h}" rx="{h / 2}"'
    s.defs.append(f'<clipPath id="pc"><rect {box}/></clipPath>')
    if glow:
        top, bottom = T.pill
        s.defs.append(f'<linearGradient id="pf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
                      f'<stop offset="1" stop-color="{bottom}"/></linearGradient>')
        s.defs.append(f'<radialGradient id="pl" cx=".5" cy="1.1" r=".8"><stop offset="0" stop-color="{T.accent}" stop-opacity=".5"/>'
                      f'<stop offset="1" stop-color="{T.accent}" stop-opacity="0"/></radialGradient>')
        s.add(f'<rect {box} fill="url(#pf)"/>', f'<rect {box} fill="url(#pl)"/>',
              f'<path d="M{h / 2} 1.8H{w - h / 2}" stroke="#fff" stroke-opacity=".2"/>',
              sheen_band(s, 1, 1, w, h, 'pc', .8, .3),
              f'<rect {box} fill="none" stroke="{T.accent}" stroke-opacity=".5"/>')
        color, ic = T.accent_ink, T.accent_ink
    else:
        s.add(f'<rect {box} fill="{T.surface}" {stroke(T, T.la2)}/>', sheen_band(s, 1, 1, w, h, 'pc', 2.4, .08))
        color, ic = T.ink, T.accent
    s.add(s.text(1 + pad, 1 + h / 2 + fs * .36, label, 'sans5', fs, color),
          icon(name, 1 + pad + tw + gap, 1 + h / 2 - iw / 2, iw, ic))
    return s


def heading(T, label, md, sub=None, size=54):
    W = 880
    lines = wrap(runs(md.replace('*', ''), 'serif'), size, W - 40)
    top = 30
    y = top + 34 + size * .9
    h = y + (len(lines) - 1) * size * 1.02 + (44 if sub else 22)
    s = Svg(W, round(h), f'{label} — {md.replace("*", "").replace("↪ ", "")}')
    s.style(FADE)
    s.add(s.text(20, top + 22, label.upper(), 'mono', 12, T.ink3, ls=.96, cls='fade'))
    words, count = rising_words(s, T, 20, y, md, size, W - 40, .1)
    s.add(words)
    if sub:
        s.add(s.text(20, y + (count - 1) * size * 1.02 + 32, sub.upper(), 'mono', 11.5, T.ink3, ls=.9,
                     cls='fade', attrs='style="animation-delay:.6s"'))
    return s


def odometer(s, x, y, value, size, fill, delay, cycle):
    """Digits that roll up to `value` like the site's count-up. Returns (svg, end x)."""
    F = FONTS['serif']
    cell = max(F.width(d, size) for d in '0123456789')
    step = size * 1.15
    out = []
    for ch in value:
        if not ch.isdigit():
            out.append(s.text(x, y, ch, 'serif', size, fill))
            x += F.width(ch, size)
            continue
        d = int(ch)
        col = ''.join(s.text(x + cell / 2, y + k * step, str(k % 10), 'serif', size, fill, anchor='middle')
                      for k in range(11 + d))
        name, cid = s.uid('od'), s.uid('oc')
        end = n((10 + d) * step)
        s.style(f'@keyframes {name}{{0%{{transform:translateY(0)}}17%,100%{{transform:translateY(-{end}px)}}}}')
        s.defs.append(f'<clipPath id="{cid}"><rect x="{n(x - 2)}" y="{n(y - size * .82)}" width="{n(cell + 4)}" '
                      f'height="{n(size * 1.04)}"/></clipPath>')
        out.append(f'<g clip-path="url(#{cid})"><g style="animation:{name} {n(cycle)}s cubic-bezier(.2,.8,.2,1) '
                   f'{delay:.2f}s infinite both">{col}</g></g>')
        x += cell
        delay += .08
    return ''.join(out), x


NUMFADE = ('.numfade{animation:numfade 14s linear infinite both}'
           '@keyframes numfade{0%{opacity:0}2%{opacity:1}93%{opacity:1}98%,100%{opacity:0}}')


def about(T, facts):
    W = 880
    statement = "*↪* I'm a final-year IT student at IIIT Lucknow who likes problems where software can quietly take over a chore."
    rs = [('sans', '↪', T.accent, .8) if f == 'serif-i' else (f, t, c, sc)
          for f, t, c, sc in runs(statement, 'serif', T.ink)]
    size, lh = 33, 40
    lines = wrap(rs, size, W - 40, words=True)
    top = 46 + len(lines) * lh + 18
    H = top + 126
    s = Svg(W, H, "I'm a final-year IT student at IIIT Lucknow who likes problems where software can quietly "
                  "take over a chore. 900+ problems solved, 80+ contests, Codeforces max " + facts['cf_max'] +
                  ', 100+ bot users.')
    s.style('.sc{animation:sc 14s ease infinite both}'
            '@keyframes sc{0%{opacity:.18}4%{opacity:1}90%{opacity:1}96%,100%{opacity:.18}}', NUMFADE)
    i = 0
    for li, (segs, _) in enumerate(lines):
        for font, text, fill, scale, dx in segs:
            s.add(s.text(20 + dx, 46 + li * lh, text, font, size * scale, fill, cls='sc',
                         attrs=f'style="animation-delay:{i * .07:.2f}s"'))
            i += 1
    stats = [('Problems solved', '900', '+'), ('Contests', '80', '+'),
             ('Codeforces max', facts['cf_max'], ''), ('Bot users', '100', '+')]
    colw = (W - 40) / 4
    s.add('<g class="numfade">')
    for k, (label, value, plus) in enumerate(stats):
        x = 20 + k * colw
        s.add(hline(T, x, x + colw - 24, top), s.text(x, top + 24, label.upper(), 'mono', 11.5, T.ink3, ls=.92))
        digits, end = odometer(s, x, top + 96, value, 68, T.ink, .2 + k * .15, 14)
        s.add(digits)
        if plus:
            s.add(s.text(end + 2, top + 96, plus, 'serif', 68, T.accent))
    s.add('</g>')
    return s


def mock_window(s, T, x, y, w, h, title):
    """The site's mock browser/terminal frame."""
    cid = s.uid('mw')
    s.defs.append(f'<clipPath id="{cid}"><rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="12"/></clipPath>')
    dots = ''.join(f'<circle cx="{n(x + 14 + k * 12)}" cy="{n(y + 13)}" r="3.5" fill="{T.ink3}" fill-opacity=".45"/>'
                   for k in range(3))
    return (f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="12" fill="{T.mock}"/>'
            f'<g clip-path="url(#{cid})"><rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="26" fill="{T.bar}"/></g>'
            f'{dots}{s.text(x + 52, y + 16.5, title, "mono", 9.5, T.ink3)}'
            f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="12" fill="none" {stroke(T)}/>')


def vis_aff(s, T, x, y, w, h):
    cyc = 9.0
    out = [mock_window(s, T, x, y, w, h, 'docs.google.com/forms/…/viewform'),
           s.text(x + 14, y + 47, 'SDE Intern · Application', 'sans6', 12, T.ink),
           s.text(x + w - 14, y + 47, 'Page 2 of 3', 'mono', 9, T.ink3, anchor='end')]
    fields = [('Full name', 'Abhay Prasad', 'profile', T.accent, .4),
              ('Current city', 'Dhanbad, Jharkhand', 'memory', T.cyan, 1.6),
              ('Why do you want to join us?', 'I enjoy building tools that save…', 'AI · review', T.amber, 3.0)]
    for i, (label, value, src, col, t0) in enumerate(fields):
        fy = y + 60 + i * 41
        t1 = t0 + len(value) / 26
        cw = FONTS['mono'].width(src, 8.5) + 12
        out += [s.text(x + 14, fy + 8, label, 'sans', 10, T.ink3),
                f'<rect x="{n(x + 14)}" y="{n(fy + 13)}" width="{n(w - 28)}" height="22" rx="6" fill="{T.field}"/>',
                typed(s, x + 22, fy + 28, value, 'sans5', 11, T.ink, t0, 26, cyc, 8.4),
                f'<g opacity="0">{show(t1 + .1, 8.4, cyc, .25)}'
                f'<rect x="{n(x + w - 20 - cw)}" y="{n(fy + 17)}" width="{n(cw)}" height="14" rx="7" fill="{col}" fill-opacity=".16"/>'
                f'{s.text(x + w - 20 - cw / 2, fy + 27, src, "mono", 8.5, col, anchor="middle")}</g>']
    fy = y + h - 34
    sub_x = x + 62
    out += [f'<rect x="{n(x + 14)}" y="{n(fy)}" width="40" height="22" rx="11" fill="none" {stroke(T, T.la2)}/>',
            s.text(x + 34, fy + 14.5, 'Back', 'sans5', 9.5, T.ink2, anchor='middle'),
            f'<g opacity=".55"><rect x="{n(sub_x)}" y="{n(fy)}" width="64" height="22" rx="11" fill="{T.accent}" fill-opacity=".22"/>',
            icon('lock', sub_x + 9, fy + 5.5, 11, T.accent_ink),
            s.text(sub_x + 24, fy + 14.5, 'Submit', 'sans5', 9.5, T.accent_ink), '</g>',
            f'<rect x="{n(sub_x)}" y="{n(fy)}" width="64" height="22" rx="11" fill="none" stroke="{T.accent}" stroke-width="1.5" opacity="0">'
            f'{keyed("opacity", [(0, 0), (4.6, 0), (5, 1), (5.6, .2), (6.2, 1), (6.8, .2), (7.4, 1), (8.4, 1), (8.7, 0)], cyc)}</rect>',
            f'<g opacity="0">{show(4.4, 8.4, cyc)}',
            s.text(x + w - 14, fy + 9, '3 / 3 answered', 'mono', 9, T.ok, anchor='end'),
            s.text(x + w - 14, fy + 21, 'You press Submit.', 'mono', 9, T.accent_ink, anchor='end'), '</g>']
    return ''.join(out)


def vis_mailer(s, T, x, y, w, h):
    cyc = 10.0
    th = 162
    out = [mock_window(s, T, x, y, w, th, 'GitHub Actions · mailer.yml')]
    lines = [('t', [('09:30 IST', T.ink3), (' ▶ run 3/10', T.accent_ink), (' started by cron', T.ink2)]),
             ('check', [('Google Sheet synced · pending rows found', T.ink2)]),
             ('check', [('sent → careers@acme.example', T.ink2), (' + resume', T.ink3)]),
             ('check', [('sent → hr@contoso.example', T.ink2), (' + resume', T.ink3)]),
             ('!', [('IMAP bounce → row marked ', T.ink2), ('failed', T.amber)]),
             ('pause', [('limit reached · cooling down 48 h', T.ink2)]),
             ('check', [('done · next run 11:00 IST', T.ink2)])]
    fs, lh = 9.6, 17.4
    for i, (mark, parts) in enumerate(lines):
        ly = y + 46 + i * lh
        tx = x + 14 if mark == 't' else x + 28
        segs = wrap([('mono', t, c, 1) for t, c in parts], fs)[0][0]
        if mark == 'check':
            m = icon('check', x + 13, ly - 8.5, 10, T.ok, sw=3)
        elif mark == 'pause':
            m = icon('pause', x + 13, ly - 8.5, 10, T.accent_ink, sw=3)
        elif mark == '!':
            m = s.text(x + 18, ly, '!', 'mono5', fs, T.amber, anchor='middle')
        else:
            m = ''
        last = i == len(lines) - 1
        caret = ''
        if last:
            end = tx + wrap([('mono', t, c, 1) for t, c in parts], fs)[0][1]
            caret = f'<rect class="blink" x="{n(end + 3)}" y="{n(ly - 8)}" width="5" height="10" fill="{T.accent}"/>'
        s.style(BLINK)
        out.append(f'<g opacity="0">{show(.4 + i * .85, 9.3, cyc, .2)}{m}{s.line(tx, ly, segs, fs)}{caret}</g>')
    by = y + th + 12
    me = '/status'
    mw = FONTS['mono'].width(me, 10) + 20
    bot = 'Mailer · running · next run 11:00'
    bw = FONTS['sans'].width(bot, 10.5) + 22
    out += [f'<g opacity="0">{show(6.6, 9.3, cyc)}<rect x="{n(x + w - mw)}" y="{n(by)}" width="{n(mw)}" height="24" rx="12" '
            f'fill="{T.accent}" fill-opacity=".2"/>{s.text(x + w - mw / 2, by + 16, me, "mono", 10, T.accent_ink, anchor="middle")}</g>',
            f'<g opacity="0">{show(7.4, 9.3, cyc)}<rect x="{n(x)}" y="{n(by + 4)}" width="{n(bw)}" height="24" rx="12" fill="{T.field}"/>'
            f'{s.text(x + 11, by + 20, bot, "sans", 10.5, T.ink2)}</g>']
    return ''.join(out)


def vis_amazon(s, T, x, y, w, h):
    cyc = 10.0
    out = []
    stages = ['Normalise', 'Block', 'Prune', 'Match', 'Decide']
    widths = [FONTS['mono'].width(t, 9.5) + 14 for t in stages]
    gap = (w - sum(widths)) / (len(stages) - 1)
    cx = x
    for i, (t, sw) in enumerate(zip(stages, widths)):
        t0 = .3 + i * .45
        out += [f'<rect x="{n(cx)}" y="{n(y)}" width="{n(sw)}" height="22" rx="11" fill="{T.field}" {stroke(T)}/>',
                f'<rect x="{n(cx)}" y="{n(y)}" width="{n(sw)}" height="22" rx="11" fill="{T.accent}" fill-opacity=".18" '
                f'stroke="{T.accent}" opacity="0">{show(t0, 9.2, cyc, .25)}</rect>',
                s.text(cx + sw / 2, y + 14.5, t, 'mono', 9.5, T.ink2, anchor='middle')]
        cx += sw + gap
    cy = y + 34
    ch = h - 34
    out.append(f'<rect x="{n(x)}" y="{n(cy)}" width="{n(w)}" height="{n(ch)}" rx="12" fill="{T.mock}" {stroke(T)}/>')
    out += [s.text(x + 14, cy + 22, 'Public leaderboard score', 'sans6', 11.5, T.ink),
            s.text(x + 14, cy + 36, 'macro F0.5 by version', 'mono', 9, T.ink3)]
    pts = [(1, .977, 'v1'), (4, .982256, 'v4'), (7, .98299, 'v7c'), (8, .983617, 'v8c'),
           (11, .985089, 'v11a'), (13, .985246, 'v13c')]
    px0, px1, py0, py1 = x + 22, x + w - 30, cy + 52, cy + ch - 26
    X = lambda v: px0 + (v - 1) / 12 * (px1 - px0)
    Y = lambda sc: py1 - (sc - .976) / (.986 - .976) * (py1 - py0)
    for g in (.978, .982, .986):
        out.append(hline(T, px0 - 6, px1 + 8, Y(g), .1))
    d = ' '.join(f'{"L" if i else "M"}{n(X(v))} {n(Y(sc))}' for i, (v, sc, _) in enumerate(pts))
    s.style('.mlline{stroke-dasharray:1;stroke-dashoffset:1;animation:mlline 10s linear infinite}'
            '@keyframes mlline{0%,22%{stroke-dashoffset:1;opacity:1}46%{stroke-dashoffset:0}92%{stroke-dashoffset:0;opacity:1}'
            '97%,100%{stroke-dashoffset:0;opacity:0}}')
    out.append(f'<path class="mlline" d="{d}" pathLength="1" fill="none" stroke="{T.chart}" stroke-width="2" '
               f'stroke-linejoin="round" stroke-linecap="round"/>')
    for i, (v, sc, label) in enumerate(pts):
        t = 2.2 + i / (len(pts) - 1) * 2.4
        out += [f'<circle cx="{n(X(v))}" cy="{n(Y(sc))}" r="3.5" fill="{T.chart}" stroke="{T.mock}" stroke-width="1.5" opacity="0">'
                f'{show(t, 9.2, cyc, .2)}</circle>',
                s.text(X(v), py1 + 16, label, 'mono', 8.5, T.ink3, anchor='middle')]
    lx, ly = X(13), Y(.985246)
    out.append(f'<g opacity="0">{show(4.8, 9.2, cyc)}<circle cx="{n(lx)}" cy="{n(ly)}" r="7" fill="none" stroke="{T.accent}" stroke-width="1.5"/>'
               f'{s.text(lx - 10, ly - 12, "0.9852 · submitted", "mono5", 9.5, T.accent_ink, anchor="end")}</g>')
    return ''.join(out)


VISUALS = {'aff': vis_aff, 'mailer': vis_mailer, 'amazon': vis_amazon}


def project(T, p):
    W = 880
    color = getattr(T, p['color'])
    mainw = 480
    lede = wrap(runs(p['lede'], 'sans', T.ink2, em=T.ink, strong=T.ink, em_scale=1.15), 15.5, mainw)
    points = [wrap(runs(t, 'sans', T.ink2, strong=T.ink), 13.5, mainw - 20) for t in p['points']]
    y = 140 + (len(lede) - 1) * 23 + 32
    pts_h = sum(len(pl) * 19 + 9 for pl in points)
    H = round(max(y + pts_h + 88, 330))
    title = f'Project {p["no"]}: {p["title"]}. {re.sub(r"[*]", "", p["lede"])}'
    s = Svg(W, H, title)
    s.add(panel(s, T, glow=(.0, .0)))
    gid = s.uid('cg')
    s.defs.append(f'<radialGradient id="{gid}" cx="1" cy="1" r=".7"><stop offset="0" stop-color="{color}" stop-opacity=".13"/>'
                  f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>')
    s.add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="22" fill="url(#{gid})"/>')

    spec = [('PRJCT', '/' + p['no']), ('Created:', p['created']), ('Type:', p['type']), ('Scope:', p['scope'])]
    x = 28
    for i, (dt, dd) in enumerate(spec):
        s.add(s.text(x, 38, dt.upper(), 'mono', 10.5, T.ink3, ls=.6))
        x += FONTS['mono'].width(dt.upper(), 10.5, .6) + 8
        s.add(s.text(x, 38, dd, 'mono5' if i == 0 else 'mono', 11, color if i == 0 else T.ink))
        x += FONTS['mono'].width(dd, 11) + 30
    s.add(hline(T, 28, W - 28, 54))

    s.add(s.text(28, 108, p['title'], 'serif', fit('serif', p['title'], 44, mainw), T.ink))
    for i, (segs, _) in enumerate(lede):
        s.add(s.line(28, 140 + i * 23, segs, 15.5))
    for pl in points:
        s.add(f'<rect x="28" y="{n(y - 5)}" width="10" height="1.6" rx=".8" fill="{color}"/>')
        for segs, _ in pl:
            s.add(s.line(48, y, segs, 13.5))
            y += 19
        y += 9
    s.add(s.text(28, H - 66, p['stack'], 'mono', 11, T.ink3))

    by = H - 50
    if p['private']:
        label = 'Private repo · ask for a demo'
        bw = FONTS['sans5'].width(label, 13) + 58
        s.add(f'<rect x="28" y="{by}" width="{n(bw)}" height="34" rx="17" fill="none" {stroke(T, T.la2)} stroke-dasharray="4 4"/>',
              icon('lock', 46, by + 10, 14, T.ink2), s.text(68, by + 21.5, label, 'sans5', 13, T.ink2))
    else:
        label = 'View code'
        tw = FONTS['sans5'].width(label, 13)
        bw = tw + 58
        s.defs.append(f'<clipPath id="vc"><rect x="28" y="{by}" width="{n(bw)}" height="34" rx="17"/></clipPath>')
        s.add(f'<rect x="28" y="{by}" width="{n(bw)}" height="34" rx="17" fill="{T.soft}" fill-opacity=".5" stroke="{T.accent}" stroke-opacity=".45"/>',
              sheen_band(s, 28, by, bw, 34, 'vc', 1.5, .25),
              s.text(46, by + 21.5, label, 'sans5', 13, T.accent_ink), icon('arrow', 46 + tw + 8, by + 10, 14, T.accent_ink))
    vx, vy = 548, 72
    s.add(VISUALS[p['visual']](s, T, vx, vy, W - 28 - vx, H - 24 - vy))
    return s


def row(T, r):
    W = 880
    desc = wrap(runs(r['desc'], 'sans', T.ink2, strong=T.ink), 13.5, W - 72 - 40)
    H = round(76 + (len(desc) - 1) * 20 + 24)
    s = Svg(W, H, f'Project {r["no"]}: {r["title"]} ({r["meta"]}, {r["year"]}). {r["desc"].replace("**", "")}')
    s.style('.nudge{animation:nudge 2.6s ease-in-out infinite}@keyframes nudge{50%{transform:translate(3px,-3px)}}')
    s.add(panel(s, T, r=18, glow=(1, 0)),
          s.text(24, 44, '/' + r['no'], 'mono', 12, T.ink3),
          s.text(72, 47, r['title'], 'serif', 32, T.ink),
          s.text(W - 128, 43, r['meta'], 'mono', 11, T.ink3, anchor='end'),
          s.text(W - 64, 43, r['year'], 'mono', 11, T.ink3, anchor='end'),
          f'<g class="nudge">{icon("arrow", W - 50, 31, 16, T.accent)}</g>')
    for i, (segs, _) in enumerate(desc):
        s.add(s.line(72, 76 + i * 20, segs, 13.5))
    return s


def experience(T):
    W = 880
    s = Svg(W, 10, '')
    s.style(PING)
    y = 30
    body = [s.text(24, y, 'EXPERIENCE', 'mono', 11.5, T.ink3, ls=.92)]
    y += 16
    for date, role, org, detail, live in EXPERIENCE:
        rl = wrap([('serif', role, T.ink, 1)], 26, 300)
        dl = wrap(runs(detail, 'sans', T.ink2, strong=T.ink), 13, 300)
        h = max(len(rl) * 28 + 26, len(dl) * 19 + 8, 50 if live else 0) + 34
        body.append(hline(T, 24, W - 24, y))
        top = y + 34
        body.append(s.text(24, top, date, 'mono', 11.5, T.ink3))
        for i, (segs, _) in enumerate(rl):
            body.append(s.line(196, top + 2 + i * 28, segs, 26))
        body.append(s.text(196, top + 2 + (len(rl) - 1) * 28 + 22, org, 'mono', 11, T.ink3))
        for i, (segs, _) in enumerate(dl):
            body.append(s.line(530, top + i * 19, segs, 13))
        if live:  # the site's "Incoming" tag, under the dates
            tw = FONTS['mono5'].width('INCOMING', 10, .8) + 34
            ty = top + 14
            body += [f'<rect x="24" y="{n(ty)}" width="{n(tw)}" height="22" rx="11" fill="{T.live}" fill-opacity=".14"/>',
                     f'<circle class="ping" cx="37" cy="{n(ty + 11)}" r="3.5" fill="{T.live}"/>',
                     f'<circle cx="37" cy="{n(ty + 11)}" r="3.5" fill="{T.live}"/>',
                     s.text(47, ty + 15, 'INCOMING', 'mono5', 10, T.live, ls=.8)]
        y += h
    y += 28
    body.append(s.text(24, y, 'EDUCATION', 'mono', 11.5, T.ink3, ls=.92))
    y += 16
    for name, course, score in EDUCATION:
        body += [hline(T, 24, W - 24, y), s.text(24, y + 36, name, 'serif', 25, T.ink),
                 s.text(330, y + 34, course, 'mono', 11.5, T.ink3)]
        segs, wd = wrap(runs(score, 'sans', T.ink2, strong=T.ink), 14)[0]
        body.append(s.line(W - 24, y + 34, segs, 14, wd, 'end'))
        y += 54
    s.h = y + 14
    s.title = ('Experience: incoming Software Development Engineer Intern at Tesco Technology, Bengaluru (Jan to Jun 2027); '
               'Business Analyst and GUI Data Annotator at Turing. Education: IIIT Lucknow, B.Tech Information Technology, '
               'CGPA 8.0; Tata DAV School, Class XII, 88.4%; De Nobili School, FRI, Class X, 94%.')
    s.add(panel(s, T, glow=(0, 0)), *body)
    return s


def rating_card(T, key, rows):
    cfg = RATING[key]
    W, H = 432, 384
    rs = [r[1] for r in rows]
    peak, now = max(rs), rs[-1]
    s = Svg(W, H, f'{cfg["title"]} rating graph: {len(rows)} rated contests, {cfg["peak_label"]} {peak:,} '
                  f'({cfg["rank"](peak)}), current {now:,} ({cfg["rank"](now)}).')
    s.add(panel(s, T, glow=(1, 0)))
    s.add(s.text(24, 36, 'COMPETITIVE PROGRAMMING', 'mono', 10.5, T.ink3, ls=.84),
          s.text(24, 78, cfg['title'], 'serif', 38, T.ink),
          s.text(W - 24, 84, f'{peak:,}', 'serif', 44, T.accent, anchor='end'))
    lab = cfg['peak_label'].upper()
    lx = W - 24 - FONTS['mono'].width(lab, 10, .8)
    s.add(s.text(W - 24, 44, lab, 'mono', 10, T.ink3, anchor='end', ls=.8))
    if key == 'codechef':
        for k in range(int(cfg['rank'](peak)[0])):
            s.add(icon('star', lx - 18 - k * 13, 34.5, 11, '#ffc94a', fill='#ffc94a', sw=0))

    # the graph, drawn like the site's: rank bands, then the line, dots appearing as it reaches them
    x0, y0, pw, ph = 20, 104, W - 40, 172
    padL, padR, padT, padB = 36, 8, 12, 20
    yMin = max(0, (min(rs) - 60) // 200 * 200)
    yMax = -(-(max(rs) + 90) // 200) * 200
    day = 86400
    t0, t1 = rows[0][0] - 25 * day, rows[-1][0] + 25 * day
    X = lambda t: x0 + padL + (t - t0) / (t1 - t0) * (pw - padL - padR)
    Y = lambda r: y0 + padT + (1 - (r - yMin) / (yMax - yMin)) * (ph - padT - padB)
    g = []
    for lo, hi, name, col in cfg['bands']:
        a, b = max(lo, yMin), min(hi, yMax)
        if b <= a:
            continue
        g.append(f'<rect x="{n(x0 + padL)}" y="{n(Y(b))}" width="{n(pw - padL - padR)}" height="{n(Y(a) - Y(b))}" fill="{col}" opacity=".13"/>')
        if Y(a) - Y(b) > 16:
            g.append(s.text(x0 + pw - padR - 6, Y(b) + 12, name, 'mono5', 9, T.ink3, anchor='end', ls=.36))
    for v in range(yMin, yMax + 1, 200):
        g += [hline(T, x0 + padL, x0 + pw - padR, Y(v), .12),
              s.text(x0 + padL - 6, Y(v) + 3.5, str(v), 'mono', 9.5, T.ink3, anchor='end')]
    start = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
    span = (t1 - t0) / (30.44 * day)
    step = next((m for m in (1, 2, 3, 4, 6, 12) if span / m <= (pw - padL - padR) / 62), 12)
    first = -(-start.month // step) * step  # same rounding as the site: next month index on the step
    yy, mm = start.year + first // 12, first % 12 + 1
    while True:
        d = datetime.datetime(yy, mm, 1, tzinfo=datetime.timezone.utc)
        if d.timestamp() >= t1:
            break
        x = X(d.timestamp())
        g.append(f'<path d="M{n(x)} {n(y0 + padT)}V{n(y0 + ph - padB)}" {stroke(T, .12)}/>')
        label = str(yy) if step >= 12 or mm == 1 else f'{d.strftime("%b")} ’{str(yy)[2:]}'
        g.append(s.text(x, y0 + ph - 5, label, 'mono', 9.5, T.ink3, anchor='middle'))
        mm += step
        while mm > 12:
            mm -= 12
            yy += 1
    s.add(*g)

    pts = [(X(t), Y(r)) for t, r, *_ in rows]
    seg = [0] + [((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2) ** .5 for i in range(1, len(pts))]
    total = sum(seg) or 1
    along, acc = [], 0
    for v in seg:
        acc += v
        along.append(acc / total)
    cyc, draw = 16, 3.8
    p_draw = draw / cyc * 100
    s.style('.ln{stroke-dasharray:1;stroke-dashoffset:1;animation:ln 16s linear infinite}'
            f'@keyframes ln{{0%{{stroke-dashoffset:1;opacity:1}}{p_draw:.2f}%{{stroke-dashoffset:0}}'
            '92%{stroke-dashoffset:0;opacity:1}97%,100%{stroke-dashoffset:0;opacity:0}}',
            '.dt{transform-box:fill-box;transform-origin:center}',
            f'.pk{{animation:pk 16s ease infinite both}}@keyframes pk{{0%,{p_draw:.2f}%{{opacity:0}}'
            f'{p_draw + 4:.2f}%,92%{{opacity:1}}97%,100%{{opacity:0}}}}')
    d = ' '.join(f'{"L" if i else "M"}{n(x)} {n(y)}' for i, (x, y) in enumerate(pts))
    s.add(f'<path class="ln" d="{d}" pathLength="1" fill="none" stroke="{T.chart}" stroke-width="2" '
          'stroke-linejoin="round" stroke-linecap="round"/>')
    dots = []
    for i, ((x, y), a) in enumerate(zip(pts, along)):
        on = a * p_draw
        name = f'd{i}'
        s.style(f'@keyframes {name}{{0%,{on:.2f}%{{opacity:0;transform:scale(.2)}}{on + 2.2:.2f}%,92%{{opacity:1;transform:scale(1)}}'
                f'97%,100%{{opacity:0;transform:scale(1)}}}}')
        dots.append(f'<circle class="dt" cx="{n(x)}" cy="{n(y)}" r="3.5" fill="{T.chart}" stroke="{T.surface}" '
                    f'stroke-width="1.5" style="animation:{name} 16s ease infinite both"/>')
    s.add(*dots)
    k = rs.index(peak)
    px, py = pts[k]
    s.add(f'<g class="pk"><circle cx="{n(px)}" cy="{n(py)}" r="6" fill="none" stroke="{T.accent}" stroke-width="2"/>',
          s.text(min(max(px, x0 + padL + 30), x0 + pw - padR - 30), py - 11, f'{peak:,} peak', 'mono5', 10.5, T.ink,
                 anchor='middle'), '</g>')

    s.add(s.text(24, 300, f'{len(rows)} RATED CONTESTS · SYNCED DAILY FROM {cfg["source"].upper()}', 'mono', 10, T.ink3, ls=.6))
    facts = [('Current rating', f'{now:,} · {cfg["rank"](now)}'), cfg['best']]
    for i, (a, b) in enumerate(facts):
        fy = 314 + i * 32
        s.add(hline(T, 24, W - 24, fy, dash=True), s.text(24, fy + 21, a, 'sans', 13.5, T.ink),
              s.text(W - 24, fy + 21, b, 'mono', 11, T.ink3, anchor='end'))
    return s


def cert(T, c, i):
    W, H = 432, 172
    s = Svg(W, H, f'{c["title"]}: {c["sub"]}.')
    s.add(panel(s, T, glow=(0, 0)))
    s.defs.append(f'<clipPath id="md"><rect x="14" y="14" width="150" height="{H - 28}" rx="16"/></clipPath>')
    gid = s.uid('mg')
    s.defs.append(f'<radialGradient id="{gid}" cx=".3" cy=".2" r="1"><stop offset="0" stop-color="{T.accent}" stop-opacity=".35"/>'
                  f'<stop offset="1" stop-color="{T.accent}" stop-opacity="0"/></radialGradient>')
    big = fit('serif', c['big'], 46, 124)
    s.add(f'<rect x="14" y="14" width="150" height="{H - 28}" rx="16" fill="{T.soft}" fill-opacity=".6"/>',
          f'<rect x="14" y="14" width="150" height="{H - 28}" rx="16" fill="url(#{gid})" {stroke(T)}/>',
          s.text(89, 92, c['big'], 'serif', big, T.accent, anchor='middle'),
          s.text(89, 116, c['small'].upper(), 'mono', 9, T.ink3, anchor='middle', ls=.6),
          sheen_band(s, 14, 14, 150, H - 28, 'md', i * 1.4, .18),
          s.text(184, 42, c['label'].upper(), 'mono', 10, T.ink3, ls=.8),
          s.text(184, 76, c['title'], 'serif', fit('serif', c['title'], 28, W - 208), T.ink))
    for k, (segs, _) in enumerate(wrap([('sans', c['sub'], T.ink2, 1)], 13, W - 208)[:2]):
        s.add(s.line(184, 100 + k * 18, segs, 13))
    s.add(s.text(184, H - 24, c['cta'], 'mono5', 11, T.accent_ink),
          icon('arrow', 184 + FONTS['mono5'].width(c['cta'], 11) + 6, H - 35, 13, T.accent_ink))
    return s


def streaks(days):
    i = len(days) - 1
    if i >= 0 and days[i][1] == 0:  # today may simply not have started yet
        i -= 1
    current = 0
    while i >= 0 and days[i][1] > 0:
        current += 1
        i -= 1
    longest = run = 0
    for _, count, _ in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    return current, longest


def activity(T, gh):
    pitch, cell = 15, 12
    gx, gy = 58, 170
    ly = gy + 7 * pitch + 18
    by = ly + 30
    W, H = 880, by + 60
    days = gh['calendar']
    current, longest = streaks(days)
    s = Svg(W, H, f'GitHub activity: {gh["total"]:,} contributions in the last year, current streak {current} days, '
                  f'longest streak {longest} days, {gh["repos"]} public repositories.')
    s.style(NUMFADE, '.wv{animation:wv 7s ease-in-out infinite both}@keyframes wv{0%,14%,100%{opacity:1}6%{opacity:.25}}')
    s.add(panel(s, T, glow=(1, 0)),
          s.text(24, 36, 'GITHUB · LAST 12 MONTHS', 'mono', 10.5, T.ink3, ls=.84),
          s.text(W - 24, 36, 'SYNCED DAILY', 'mono', 10.5, T.ink3, ls=.84, anchor='end'))
    stats = [(f'{gh["total"]:,}', 'contributions'), (str(current), 'day streak now'),
             (str(longest), 'day longest streak'), (str(gh['repos']), 'public repositories')]
    colw = (W - 48) / 4
    s.add('<g class="numfade">')
    for k, (value, label) in enumerate(stats):
        x = 24 + k * colw
        digits, _ = odometer(s, x, 100, value, 52, T.ink, .2 + k * .15, 14)
        s.add(digits, s.text(x, 124, label.upper(), 'mono', 10.5, T.ink3, ls=.84))
    s.add('</g>')

    # contribution calendar, in the site's blues
    first = datetime.date.fromisoformat(days[0][0])
    offset = (first.weekday() + 1) % 7  # GitHub weeks start on Sunday
    alphas = [None, .3, .5, .75, 1]
    cols = defaultdict(list)
    last_month, last_x = None, -99
    for idx, (date, count, level) in enumerate(days):
        c, r = divmod(idx + offset, 7)
        x, y = gx + c * pitch, gy + r * pitch
        fill = (f'fill="{T.heat0}"' if level == 0 else f'fill="{T.accent}" fill-opacity="{alphas[min(level, 4)]}"')
        cols[c].append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" {fill}/>')
        m = date[:7]
        if r == 0 or idx == 0:
            if m != last_month and x - last_x > 34:
                s.add(s.text(x, gy - 8, datetime.date.fromisoformat(date).strftime('%b'), 'mono', 9.5, T.ink3))
                last_x = x
            last_month = m
    for c in sorted(cols):
        s.add(f'<g class="wv" style="animation-delay:{c * .05:.2f}s">{"".join(cols[c])}</g>')
    for r, label in ((1, 'Mon'), (3, 'Wed'), (5, 'Fri')):
        s.add(s.text(24, gy + r * pitch + 10, label, 'mono', 9.5, T.ink3))
    lx = W - 24 - 5 * pitch - FONTS['mono'].width('More', 9.5) - 6
    s.add(s.text(lx - 6, ly, 'Less', 'mono', 9.5, T.ink3, anchor='end'))
    for k in range(5):
        fill = (f'fill="{T.heat0}"' if k == 0 else f'fill="{T.accent}" fill-opacity="{alphas[k]}"')
        s.add(f'<rect x="{n(lx + k * pitch)}" y="{ly - 10}" width="{cell}" height="{cell}" rx="2.5" {fill}/>')
    s.add(s.text(lx + 5 * pitch + 2, ly, 'More', 'mono', 9.5, T.ink3))

    # languages across public repositories
    # notebooks are mostly JSON and cell output, so their byte count says little about the code
    langs = sorted(((k, v) for k, v in gh['languages'].items() if k != 'Jupyter Notebook'), key=lambda kv: -kv[1])
    total = sum(v for _, v in langs) or 1
    top = langs[:5]
    rest = total - sum(v for _, v in top)
    if rest > 0:
        top.append(('Other', rest))
    s.add(s.text(24, by, 'TOP LANGUAGES · PUBLIC REPOS', 'mono', 10.5, T.ink3, ls=.84))
    s.defs.append(f'<clipPath id="lb"><rect x="24" y="{by + 12}" width="{W - 48}" height="8" rx="4"/></clipPath>')
    bar, x = [], 24.0
    for k, (name, v) in enumerate(top):
        w = (W - 48) * v / total
        bar.append(f'<rect x="{n(x)}" y="{by + 12}" width="{n(w + .5)}" height="8" fill="{T.langs[k]}"/>')
        x += w
    s.add(f'<g clip-path="url(#lb)">{"".join(bar)}</g>', sheen_band(s, 24, by + 12, W - 48, 8, 'lb', .5, .5))
    x = 24.0
    for k, (name, v) in enumerate(top):
        label = f'{name} {v / total * 100:.1f}%'
        s.add(f'<circle cx="{n(x + 4)}" cy="{by + 37}" r="4" fill="{T.langs[k]}"/>',
              s.text(x + 13, by + 41, label, 'mono', 11, T.ink2))
        x += FONTS['mono'].width(label, 11) + 34
    return s


def toolbox(T):
    W = 880
    rh = 50
    H = 20 + len(TOOLBOX) * rh + 12
    s = Svg(W, H, 'Toolbox: ' + '; '.join(f'{a}: {b}' for a, b in TOOLBOX) + '.')
    s.add(panel(s, T, glow=(0, 0)))
    cyc = len(TOOLBOX) * 1.4
    for i, (name, tools) in enumerate(TOOLBOX):
        y = 20 + i * rh
        s.add(f'<rect x="12" y="{y + 4}" width="{W - 24}" height="{rh - 8}" rx="12" fill="{T.accent}" opacity="0">'
              f'{show(i * 1.4, i * 1.4 + 1.4, cyc, .35, 0, .07)}</rect>')
        if i:
            s.add(hline(T, 24, W - 24, y))
        s.add(s.text(24, y + 31, f'({i + 1:03d})', 'mono', 11.5, T.ink3),
              f'<g opacity="0">{show(i * 1.4, i * 1.4 + 1.4, cyc, .35)}{s.text(24, y + 31, f"({i + 1:03d})", "mono", 11.5, T.accent)}</g>',
              s.text(90, y + 34, name, 'serif', 27, T.ink),
              s.text(W - 24, y + 31, tools, 'mono', 12, T.ink2, anchor='end'))
    return s


def footer(T, year):
    W = 880
    a, b = 'abhay', 'prasad'
    size = 150
    wa = FONTS['serif'].width(a + ' ', size)
    total = wa + FONTS['serif-i'].width(b, size)
    size *= (W - 40) / total
    wa = FONTS['serif'].width(a + ' ', size)
    total = wa + FONTS['serif-i'].width(b, size)
    H = round(48 + size * .76 + size * .26 + 10)
    s = Svg(W, H, f'Abhay Prasad · © {year}')
    s.style('.wave{animation:wave 6s ease-in-out infinite both}@keyframes wave{0%,24%,100%{transform:none}12%{transform:translateY(-.07em)}}')
    s.add(s.text(20, 22, f'© {year} ABHAY PRASAD', 'mono', 11.5, T.ink3, ls=.92),
          s.text(W - 20, 22, 'ABHAY9494.GITHUB.IO', 'mono', 11.5, T.ink3, ls=.92, anchor='end'))
    x0, y = (W - total) / 2, 48 + size * .76
    i = 0
    for word, font, fill, start in ((a, 'serif', T.ink, x0), (b, 'serif-i', T.accent, x0 + wa)):
        xs, _ = FONTS[font].layout(word, size)
        for ch, dx in zip(word, xs):
            s.add(s.text(start + dx, y, ch, font, size, fill, cls='wave', attrs=f'style="animation-delay:{i * .09:.2f}s"'))
            i += 1
    return s


# ---------- data ----------

def get(url, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'profile-cards (https://github.com/abhay9494)', **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode('utf-8', 'replace')


def fetch_ratings():
    data = json.loads(get(RATINGS_URL))
    out = {k: data[k] for k in ('codeforces', 'codechef') if isinstance(data.get(k), list) and data[k]}
    if len(out) < 2:
        raise RuntimeError('the rating file is missing a platform')
    return out


def fetch_github():
    headers = {'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    user = json.loads(get(f'https://api.github.com/users/{USER}', headers))
    repos = [r for r in json.loads(get(f'https://api.github.com/users/{USER}/repos?per_page=100&type=owner', headers))
             if not r['fork']]
    langs = defaultdict(int)
    for r in repos:
        for lang, size in json.loads(get(r['languages_url'], headers)).items():
            langs[lang] += size
    page = get(f'https://github.com/users/{USER}/contributions')
    counts = {m.group(1): int(m.group(2))
              for m in re.finditer(r'<tool-tip[^>]*\bfor="([^"]+)"[^>]*>(\d+) contributions? on', page)}
    days = []
    for tag in re.findall(r'<td\b[^>]*ContributionCalendar-day[^>]*>', page):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        if 'data-date' in a:
            days.append([a['data-date'], counts.get(a.get('id'), 0), int(a.get('data-level', 0))])
    total = re.search(r'([\d,]+)\s+contributions?\s+in the last year', page)
    if not days or not total:
        raise RuntimeError('contribution calendar not found')
    return {'repos': user['public_repos'], 'stars': sum(r['stargazers_count'] for r in repos),
            'languages': dict(sorted(langs.items())), 'total': int(total.group(1).replace(',', '')),
            'calendar': sorted(days)}


# ---------- README ----------

def pic(name, alt, width=None, height=None):
    size = (f' width="{width}"' if width else '') + (f' height="{height}"' if height else '')
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dark/{name}.svg">'
            f'<source media="(prefers-color-scheme: light)" srcset="assets/light/{name}.svg">'
            f'<img src="assets/dark/{name}.svg" alt="{esc(alt)}"{size}></picture>')


def a(href, inner):
    return f'<a href="{esc(href)}">{inner}</a>'


PILLS = [
    ('portfolio', 'See my portfolio', 'arrow', True, SITE),
    ('email', 'Email me', 'mail', False, gmail()),
    ('linkedin', 'LinkedIn', 'linkedin', False, LINKEDIN),
    ('resume', 'Resume', 'down', False, RESUME),
    ('codeforces', 'Codeforces', 'bars', False, CODEFORCES),
    ('codechef', 'CodeChef', 'star', False, CODECHEF),
]
CONTACT_PILLS = [
    ('talk', 'Start a conversation', 'arrow', True, gmail('Hello Abhay')),
    ('linkedin', 'LinkedIn', 'linkedin', False, LINKEDIN),
    ('portfolio-line', 'abhay9494.github.io', 'arrow', False, SITE),
]


def readme(cards, facts):
    pills = lambda items: '\n'.join(a(href, pic(f'pill-{key}', label, height=44)) for key, label, *_, href in items)
    return f'''<!-- Generated by scripts/build_cards.py — edit the facts there, not here. Cards refresh daily (.github/workflows/cards.yml). -->

{a(SITE, pic('banner', cards['banner'].title, '100%'))}

<p align="center">
{pills(PILLS)}
</p>

{pic('h-about', 'About')}

{pic('about', cards['about'].title, '100%')}

My Chrome extension fills job applications page by page and never presses Submit. A bot emails recruiters from a Google Sheet on a schedule. A Telegram bot sends **100+ students** the job links that fit their batch. Outside of building, I compete: Codeforces Specialist, CodeChef {facts['cc_rank']}, and an entity-resolution pipeline I built solo that placed in the **top 1,000 of 32,000+ teams** at the Amazon ML Challenge 2026.

{pic('h-work', 'Some of my projects')}

{a(gmail('Demo request: Auto Form Filler'), pic('project-aff', cards['project-aff'].title, '100%'))}

{a(gmail('Demo request: HR Auto Mailer Bot'), pic('project-mailer', cards['project-mailer'].title, '100%'))}

{a(PROJECTS[2]['href'], pic('project-amazon', cards['project-amazon'].title, '100%'))}

{chr(10).join(a(r['href'], pic(f'row-{r["no"]}', cards[f'row-{r["no"]}'].title, '100%')) for r in ROWS)}

{pic('h-experience', "Where I've worked")}

{a(SITE + '/#experience', pic('experience', cards['experience'].title, '100%'))}

{pic('h-awards', 'Awards and rankings')}

{a(CODEFORCES, pic('rating-codeforces', cards['rating-codeforces'].title, '49%'))}
{a(CODECHEF, pic('rating-codechef', cards['rating-codechef'].title, '49%'))}
{chr(10).join(a(c['href'], pic(f'cert-{c["key"]}', cards[f'cert-{c["key"]}'].title, '49%')) for c in CERTS)}

{pic('h-activity', 'On GitHub')}

{pic('activity', cards['activity'].title, '100%')}

{pic('h-toolbox', 'What I build with')}

{pic('toolbox', cards['toolbox'].title, '100%')}

{pic('h-contact', "Let's build something useful")}

<p align="center">Have a role, a project or a question about something I built?<br>Write to me at <strong>{EMAIL}</strong>.</p>

<p align="center">
{pills(CONTACT_PILLS)}
</p>

{a(SITE, pic('footer', cards['footer'].title, '100%'))}
'''


def build(data):
    cf, cc = data['ratings']['codeforces'], data['ratings']['codechef']
    cc_peak = max(r[1] for r in cc)
    facts = {'cf_max': f'{max(r[1] for r in cf):,}', 'cc_max': f'{cc_peak:,}', 'cc_rank': RATING['codechef']['rank'](cc_peak)}
    year = datetime.datetime.now(IST).year
    written = 0
    for theme, T in THEMES.items():
        cards = {
            'banner': banner(T, facts),
            'h-about': heading(T, '(01) About', 'A bit *↪ about* me'),
            'about': about(T, facts),
            'h-work': heading(T, '(02) Work', 'Some *↪ of my* projects',
                              'Things I built because I needed them — and a few I built to learn'),
            'h-experience': heading(T, '(03) Experience', "Where I've *↪ worked*"),
            'experience': experience(T),
            'h-awards': heading(T, '(04) Recognition', 'Awards *↪ & rankings*',
                                'Contests, ratings and certificates · open any of them'),
            'rating-codeforces': rating_card(T, 'codeforces', cf),
            'rating-codechef': rating_card(T, 'codechef', cc),
            'h-activity': heading(T, '(05) Activity', 'On *↪ GitHub*'),
            'activity': activity(T, data['github']),
            'h-toolbox': heading(T, '(06) Toolbox', 'What I *↪ build* with'),
            'toolbox': toolbox(T),
            'h-contact': heading(T, '(07) Stay in touch', "Let's build *↪ something* useful", size=60),
            'footer': footer(T, year),
        }
        for p in PROJECTS:
            cards[f'project-{p["key"]}'] = project(T, p)
        for r in ROWS:
            cards[f'row-{r["no"]}'] = row(T, r)
        for i, c in enumerate(CERTS):
            cards[f'cert-{c["key"]}'] = cert(T, c, i)
        for key, label, name, glow, _ in PILLS + CONTACT_PILLS:
            cards[f'pill-{key}'] = pill(T, label, name, glow)
        out = ASSETS / theme
        out.mkdir(parents=True, exist_ok=True)
        for name, svg in cards.items():
            path = out / f'{name}.svg'
            body = svg.render()
            if not path.exists() or path.read_text('utf-8') != body:
                path.write_text(body, 'utf-8', newline='\n')
                written += 1
    text = readme(cards, facts)
    if not README.exists() or README.read_text('utf-8') != text:
        README.write_text(text, 'utf-8', newline='\n')
        written += 1
    print(f'{written} file(s) changed')


def main():
    cache = json.loads(CACHE.read_text('utf-8')) if CACHE.exists() else {}
    failed = []
    for key, fetch in (('ratings', fetch_ratings), ('github', fetch_github)):
        try:
            cache[key] = fetch()
        except Exception as e:  # keep the last good data for this source
            print(f'{key}: {e}', file=sys.stderr)
            failed.append(key)
    missing = [k for k in ('ratings', 'github') if k not in cache]
    if missing:
        sys.exit('no data yet for: ' + ', '.join(missing))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, sort_keys=True, separators=(',', ':')) + '\n', 'utf-8', newline='\n')
    build(cache)
    if failed:  # whatever did arrive is saved above; flag the run so the failure is visible
        sys.exit('could not fetch: ' + ', '.join(failed))


if __name__ == '__main__':
    main()
