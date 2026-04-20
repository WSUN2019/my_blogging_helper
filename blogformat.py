#!/usr/bin/env python3
"""
blogformat.py — Blogger-compatible HTML formatter for ModernSimpleLiving.com

Usage:
    python blogformat.py input.txt                      # default navy/gold -> stdout
    python blogformat.py input.txt -o out.html          # write to file
    python blogformat.py input.txt -t ocean             # choose theme
    python blogformat.py input.txt -t woodsy -o out.html
    cat input.txt | python blogformat.py                # pipe input
    python blogformat.py --list-themes                  # show themes
    python blogformat.py --help

Input format (plain text or light-markdown; rough HTML also tolerated):

    TITLE: My Blog Post Title
    SUBTITLE: An optional italic subtitle
    EYEBROW: Gear Review                  (optional; defaults to "Feature")
    STATS: 12 Items | 3 Days | $450 Total (optional; pipe-separated "number label")

    # Section Heading                     (becomes a major section; gets eyebrow "Section I/II/...")
    LABEL: Custom Section Label           (optional; overrides auto "Section I")

    ## Sub-label                          (small all-caps muted sub-label)

    Regular paragraph text here.

    - **Item name** — description         (bulleted list with bold name)
    - **Another** — desc

    > This is a callout / note block.

    | Col A | Col B | Col C |              (markdown table)
    |-------|-------|-------|
    | val   | val   | val   |

    FOOTER: Custom footer line             (optional; defaults to a generic closer)

Themes: navy_gold (default), woodsy, ocean, brick, purple, forest, slate
"""

from __future__ import annotations
import argparse
import re
import sys
import html as html_lib
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Color schemes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    name: str
    primary: str        # "navy" — headers, headings, strong text
    accent: str         # "gold" — eyebrows, arrows, callout border, stat numbers
    accent_light: str   # subtitle color on header
    bg: str             # body background (cream)
    warm: str           # alt table rows / callout bg
    border: str         # hairlines
    muted: str          # "#6b7280" — sub-labels, footer
    body_text: str      # "#3a3a3a" — paragraph text


THEMES: dict[str, Theme] = {
    "navy_gold": Theme(
        name="Navy / Gold (default)",
        primary="#1a2640",
        accent="#c9a84c",
        accent_light="#e8d5a3",
        bg="#faf8f4",
        warm="#f2ede4",
        border="#d9cfc0",
        muted="#6b7280",
        body_text="#3a3a3a",
    ),
    "woodsy": Theme(
        name="Woodsy (forest green / amber)",
        primary="#2d3f２e".replace("２", "2"),  # safeguard against accidental unicode
        accent="#b8893a",
        accent_light="#e4c78a",
        bg="#f8f5ef",
        warm="#ece5d6",
        border="#d4c9b3",
        muted="#6b6257",
        body_text="#3a3a3a",
    ),
    "ocean": Theme(
        name="Ocean (deep blue / seafoam)",
        primary="#12304a",
        accent="#3a9ea5",
        accent_light="#a8d8db",
        bg="#f5f8fa",
        warm="#e4edf1",
        border="#c8d4dc",
        muted="#5c6b75",
        body_text="#2f3a42",
    ),
    "brick": Theme(
        name="Brick (rust red / amber)",
        primary="#6e2b1f",
        accent="#d4892a",
        accent_light="#f0c88a",
        bg="#faf6f0",
        warm="#f0e6d6",
        border="#dac8b0",
        muted="#6f6254",
        body_text="#3a2f2a",
    ),
    "purple": Theme(
        name="Purple / Gold",
        primary="#3d2c5e",
        accent="#c9a84c",
        accent_light="#e8d5a3",
        bg="#f8f5fa",
        warm="#ece4f0",
        border="#d4c6df",
        muted="#6b6275",
        body_text="#3a3340",
    ),
    "forest": Theme(
        name="Forest (deep green / sage)",
        primary="#1f3d2f",
        accent="#7a9b5c",
        accent_light="#c4d6b0",
        bg="#f6f8f3",
        warm="#e4ebdc",
        border="#c9d3bf",
        muted="#606a5c",
        body_text="#2f3a34",
    ),
    "slate": Theme(
        name="Slate (charcoal / copper)",
        primary="#2b2f36",
        accent="#c87a4a",
        accent_light="#edc3a3",
        bg="#f6f5f2",
        warm="#e7e4dd",
        border="#cdc8bd",
        muted="#6a6862",
        body_text="#353434",
    ),
}

# Fix the woodsy typo proactively (from copy-paste safeguard above)
THEMES["woodsy"] = Theme(
    name="Woodsy (forest green / amber)",
    primary="#2d3f2e",
    accent="#b8893a",
    accent_light="#e4c78a",
    bg="#f8f5ef",
    warm="#ece5d6",
    border="#d4c9b3",
    muted="#6b6257",
    body_text="#3a3a3a",
)


# ---------------------------------------------------------------------------
# Input parser
# ---------------------------------------------------------------------------

CIRCLED = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
           "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
         "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


@dataclass
class Section:
    label: str           # eyebrow for this section, e.g. "Section I"
    heading: str         # h2 text
    blocks: list         # list of block dicts


@dataclass
class Post:
    title: str = "Untitled Post"
    subtitle: Optional[str] = None
    eyebrow: str = "Feature"
    stats: list = None   # list of (number, label) tuples
    sections: list = None
    footer: Optional[str] = None

    def __post_init__(self):
        if self.stats is None:
            self.stats = []
        if self.sections is None:
            self.sections = []


def parse_input(text: str) -> Post:
    """Parse a light-markdown-ish blog post into a Post object."""
    lines = text.splitlines()
    post = Post()

    # --- Pre-pass: extract any metadata lines from anywhere in the input ---
    # TITLE/SUBTITLE/EYEBROW/STATS/FOOTER can appear top or bottom; pull them out.
    meta_keys = {"TITLE", "SUBTITLE", "EYEBROW", "STATS", "FOOTER"}
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^([A-Z]+)\s*:\s*(.*)$", stripped)
        if m and m.group(1) in meta_keys:
            key, val = m.group(1), m.group(2).strip()
            if key == "TITLE":
                post.title = val
            elif key == "SUBTITLE":
                post.subtitle = val
            elif key == "EYEBROW":
                post.eyebrow = val
            elif key == "STATS":
                post.stats = parse_stats(val)
            elif key == "FOOTER":
                post.footer = val
            continue  # don't keep metadata lines in body
        filtered.append(line)

    body = filtered
    # Find all section headings (# lines) and split
    current_section: Optional[Section] = None
    current_label: Optional[str] = None
    buffer: list[str] = []
    section_count = 0

    def flush_buffer_into(section: Optional[Section]):
        if section is None or not buffer:
            buffer.clear()
            return
        section.blocks.extend(parse_blocks(buffer))
        buffer.clear()

    # Preamble (content before first #) becomes an "intro" section with no heading
    preamble_section = Section(label="", heading="", blocks=[])
    current_section = preamble_section

    idx = 0
    while idx < len(body):
        line = body[idx]
        stripped = line.strip()

        # Detect section-scoped LABEL: override for the next # heading
        m_label = re.match(r"^LABEL\s*:\s*(.*)$", stripped)
        if m_label:
            current_label = m_label.group(1).strip()
            idx += 1
            continue

        # H1-style section heading
        if stripped.startswith("# ") and not stripped.startswith("## "):
            # Flush whatever we've been building
            flush_buffer_into(current_section)
            if current_section is preamble_section and current_section.blocks:
                post.sections.append(current_section)
            elif current_section is not preamble_section:
                post.sections.append(current_section)

            section_count += 1
            heading = stripped[2:].strip()
            label = current_label or f"Section {ROMAN[min(section_count - 1, len(ROMAN) - 1)]}"
            current_label = None
            current_section = Section(label=label, heading=heading, blocks=[])
            idx += 1
            continue

        buffer.append(line)
        idx += 1

    # Flush trailing buffer
    flush_buffer_into(current_section)
    if current_section is preamble_section:
        if current_section.blocks:
            post.sections.append(current_section)
    else:
        post.sections.append(current_section)

    return post


def parse_stats(s: str) -> list:
    """STATS: '12 Items | 3 Days | $450 Total' -> [('12','Items'),('3','Days'),('$450','Total')]"""
    out = []
    for chunk in s.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        # split first whitespace-separated token as the number-ish part,
        # but also handle things like "$450 Total" or "2.5x Faster"
        m = re.match(r"^(\S+)\s+(.+)$", chunk)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
        else:
            out.append((chunk, ""))
    return out


def parse_blocks(lines: list[str]) -> list:
    """Turn a list of raw content lines into a list of block dicts.

    Block types:
      {"type": "subheading", "text": str}
      {"type": "paragraph", "text": str}
      {"type": "list", "items": [{"name": str|None, "desc": str}, ...]}
      {"type": "callout", "text": str}
      {"type": "table", "headers": [...], "rows": [[...]]}
      {"type": "raw_html", "html": str}
    """
    blocks = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Sub-label: ## Foo
        if stripped.startswith("## "):
            blocks.append({"type": "subheading", "text": stripped[3:].strip()})
            i += 1
            continue

        # Callout: > text  (may span multiple lines)
        if stripped.startswith(">"):
            chunks = []
            while i < n and lines[i].strip().startswith(">"):
                chunks.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append({"type": "callout", "text": " ".join(c for c in chunks if c)})
            continue

        # Table: | a | b | c |  with a separator line below
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i + 1]):
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2  # skip header + separator
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(row)
                i += 1
            blocks.append({"type": "table", "headers": headers, "rows": rows})
            continue

        # List: - item  (contiguous run)
        if stripped.startswith("- ") or stripped.startswith("* "):
            items = []
            while i < n and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                raw = lines[i].strip()[2:].strip()
                items.append(parse_list_item(raw))
                i += 1
            blocks.append({"type": "list", "items": items})
            continue

        # Raw HTML passthrough (if user feeds in an already-formed block)
        if stripped.startswith("<") and stripped.endswith(">") and len(stripped) > 20:
            # Cheap heuristic: treat as raw HTML only if the whole line is a tag
            blocks.append({"type": "raw_html", "html": stripped})
            i += 1
            continue

        # Paragraph (gather until blank line or block starter)
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if not nxt:
                break
            if (nxt.startswith("## ") or nxt.startswith("- ") or nxt.startswith("* ")
                    or nxt.startswith(">") or nxt.startswith("|")):
                break
            para_lines.append(nxt)
            i += 1
        blocks.append({"type": "paragraph", "text": " ".join(para_lines)})

    return blocks


def parse_list_item(raw: str) -> dict:
    """Parse '**Name** — description' or '**Name**: description' or plain text."""
    # **Name** — desc  /  **Name** - desc  /  **Name**: desc  /  **Name**, desc
    m = re.match(r"^\*\*(.+?)\*\*\s*[—–\-:,]\s*(.+)$", raw)
    if m:
        return {"name": m.group(1).strip(), "desc": m.group(2).strip()}
    m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", raw)
    if m:
        return {"name": m.group(1).strip(), "desc": m.group(2).strip()}
    return {"name": None, "desc": raw}


# ---------------------------------------------------------------------------
# Inline formatting (bold, italic, code, links) within paragraphs & cells
# ---------------------------------------------------------------------------

def inline_format(text: str, theme: Theme) -> str:
    """Apply inline bold/italic/code/link with inlined styles."""
    # Escape first, then re-inject our simple markdown
    s = html_lib.escape(text, quote=False)

    # links: [text](url)
    s = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}" style="color:{theme.primary};text-decoration:underline;">{m.group(1)}</a>',
        s,
    )
    # bold: **text**
    s = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: f'<strong style="color:{theme.primary};font-weight:700;">{m.group(1)}</strong>',
        s,
    )
    # italic: *text*   (avoid matching ** which we already consumed)
    s = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        lambda m: f'<em>{m.group(1)}</em>',
        s,
    )
    # inline code: `text`
    s = re.sub(
        r"`([^`]+)`",
        lambda m: (
            f'<code style="background:{theme.warm};padding:1px 6px;border-radius:3px;'
            f'font-family:ui-monospace,Menlo,Consolas,monospace;font-size:0.85em;">{m.group(1)}</code>'
        ),
        s,
    )
    return s


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render(post: Post, theme: Theme) -> str:
    out = []

    # ---- Header ----
    out.append(render_header(post, theme))

    # ---- Body ----
    body_open = (
        f'<div style="max-width:820px;margin:0 auto;padding:0 24px 80px;'
        f'background:{theme.bg};'
        f'font-family:\'Lato\',sans-serif;font-weight:300;font-size:16px;'
        f'line-height:1.75;color:{theme.body_text};">'
    )
    out.append(body_open)

    # ---- Table of Contents ----
    # Include TOC for 3+ named sections
    named_sections = [s for s in post.sections if s.heading]
    if len(named_sections) >= 3:
        out.append(render_toc(named_sections, theme))

    # ---- Sections ----
    for section in post.sections:
        out.append(render_section(section, theme))

    out.append("</div>")  # close body wrapper

    # ---- Footer ----
    out.append(render_footer(post, theme))

    return "\n".join(out)


def render_header(post: Post, theme: Theme) -> str:
    parts = []
    parts.append(
        f'<header style="background:{theme.primary};text-align:center;'
        f'padding:64px 24px 56px;color:#ffffff;">'
    )

    # Eyebrow
    parts.append(
        f'<div style="color:{theme.accent};font-family:\'Lato\',sans-serif;'
        f'font-weight:700;font-size:0.75rem;letter-spacing:0.25em;'
        f'text-transform:uppercase;margin-bottom:18px;">'
        f'{html_lib.escape(post.eyebrow)}</div>'
    )

    # Title (H1)
    parts.append(
        f'<h1 style="font-family:\'Playfair Display\',serif;font-weight:700;'
        f'font-size:2.8rem;line-height:1.15;color:#ffffff;margin:0 0 14px 0;">'
        f'{html_lib.escape(post.title)}</h1>'
    )

    # Subtitle
    if post.subtitle:
        parts.append(
            f'<h2 style="font-family:\'Playfair Display\',serif;font-weight:400;'
            f'font-style:italic;font-size:1.25rem;color:{theme.accent_light};'
            f'margin:0;line-height:1.4;">'
            f'{html_lib.escape(post.subtitle)}</h2>'
        )

    # Stat bar
    if post.stats:
        parts.append(
            f'<div style="width:60px;height:1px;background:{theme.accent};'
            f'margin:36px auto 28px;"></div>'
        )
        parts.append(
            '<div style="display:flex;flex-wrap:wrap;justify-content:center;'
            'gap:48px;margin-top:8px;">'
        )
        for number, label in post.stats:
            parts.append(
                '<div style="text-align:center;">'
                f'<div style="font-family:\'Playfair Display\',serif;font-weight:700;'
                f'font-size:1.75rem;color:{theme.accent};line-height:1;">'
                f'{html_lib.escape(number)}</div>'
                f'<div style="font-family:\'Lato\',sans-serif;font-weight:700;'
                f'font-size:0.68rem;letter-spacing:0.2em;text-transform:uppercase;'
                f'color:{theme.accent_light};margin-top:8px;">'
                f'{html_lib.escape(label)}</div>'
                '</div>'
            )
        parts.append('</div>')

    parts.append('</header>')
    return "".join(parts)


def render_toc(sections: list[Section], theme: Theme) -> str:
    parts = []
    parts.append(
        f'<nav style="background:{theme.primary};border-radius:4px;'
        f'padding:36px 40px;margin:48px 0 56px;">'
    )
    parts.append(
        f'<div style="color:{theme.accent};font-family:\'Lato\',sans-serif;'
        f'font-weight:700;font-size:0.72rem;letter-spacing:0.25em;'
        f'text-transform:uppercase;margin-bottom:20px;">Table of Contents</div>'
    )
    parts.append(
        '<ul style="list-style:none;padding:0;margin:0;display:grid;'
        'grid-template-columns:repeat(auto-fill, minmax(220px, 1fr));'
        'gap:10px 24px;">'
    )
    for idx, sec in enumerate(sections):
        marker = CIRCLED[idx] if idx < len(CIRCLED) else f"{idx+1}."
        parts.append(
            '<li style="color:rgba(255,255,255,0.8);font-family:\'Lato\',sans-serif;'
            'font-weight:300;font-size:0.95rem;line-height:1.5;">'
            f'<span style="color:{theme.accent};margin-right:10px;font-weight:700;">{marker}</span>'
            f'{html_lib.escape(sec.heading)}'
            '</li>'
        )
    parts.append('</ul></nav>')
    return "".join(parts)


def render_section(section: Section, theme: Theme) -> str:
    parts = []
    parts.append('<section style="margin:48px 0;">')

    if section.heading:
        # Eyebrow label
        if section.label:
            parts.append(
                f'<div style="color:{theme.accent};font-family:\'Lato\',sans-serif;'
                f'font-weight:700;font-size:0.72rem;letter-spacing:0.25em;'
                f'text-transform:uppercase;margin-bottom:10px;">'
                f'{html_lib.escape(section.label)}</div>'
            )
        # H2 heading
        parts.append(
            f'<h2 style="font-family:\'Playfair Display\',serif;font-weight:700;'
            f'font-size:1.75rem;color:{theme.primary};margin:0 0 24px 0;'
            f'padding-bottom:14px;border-bottom:1px solid {theme.border};'
            f'line-height:1.25;">'
            f'{html_lib.escape(section.heading)}</h2>'
        )

    for block in section.blocks:
        parts.append(render_block(block, theme))

    parts.append('</section>')
    return "".join(parts)


def render_block(block: dict, theme: Theme) -> str:
    btype = block["type"]

    if btype == "subheading":
        return (
            f'<div style="font-family:\'Lato\',sans-serif;font-weight:700;'
            f'font-size:0.7rem;letter-spacing:0.2em;text-transform:uppercase;'
            f'color:{theme.muted};margin:28px 0 6px 0;">'
            f'{html_lib.escape(block["text"])}</div>'
        )

    if btype == "paragraph":
        return (
            f'<p style="font-family:\'Lato\',sans-serif;font-weight:300;'
            f'font-size:0.97rem;color:{theme.body_text};line-height:1.75;'
            f'margin:0 0 16px 0;">'
            f'{inline_format(block["text"], theme)}</p>'
        )

    if btype == "callout":
        return (
            f'<div style="background:{theme.warm};'
            f'border-left:3px solid {theme.accent};'
            f'padding:14px 20px;margin:20px 0;border-radius:0 4px 4px 0;'
            f'font-family:\'Lato\',sans-serif;font-weight:400;font-style:italic;'
            f'font-size:0.88rem;color:{theme.muted};line-height:1.65;">'
            f'{inline_format(block["text"], theme)}</div>'
        )

    if btype == "list":
        return render_list(block["items"], theme)

    if btype == "table":
        return render_table(block["headers"], block["rows"], theme)

    if btype == "raw_html":
        return block["html"]

    return ""


def render_list(items: list, theme: Theme) -> str:
    parts = [
        '<ul style="list-style:none;padding:0;margin:20px 0;'
        f'border-top:1px solid {theme.border};">'
    ]
    last = len(items) - 1
    for idx, item in enumerate(items):
        border = (
            f"border-bottom:1px solid {theme.border};"
            if idx != last else ""
        )
        name_html = ""
        if item["name"]:
            name_html = (
                f'<strong style="color:{theme.primary};font-weight:700;'
                f'font-family:\'Lato\',sans-serif;">'
                f'{inline_format(item["name"], theme).replace("<strong", "<span").replace("</strong>", "</span>")}'
                f'</strong>'
                + (" — " if item["desc"] else "")
            )
        desc_html = inline_format(item["desc"], theme) if item["desc"] else ""
        parts.append(
            f'<li style="display:flex;gap:14px;padding:9px 0;{border}'
            f'font-family:\'Lato\',sans-serif;font-weight:300;'
            f'font-size:0.97rem;color:{theme.body_text};line-height:1.65;">'
            f'<span style="color:{theme.accent};font-weight:700;flex-shrink:0;">→</span>'
            f'<span>{name_html}{desc_html}</span>'
            '</li>'
        )
    parts.append('</ul>')
    return "".join(parts)


def render_table(headers: list, rows: list, theme: Theme) -> str:
    parts = [
        f'<div style="overflow-x:auto;border:1px solid {theme.border};'
        f'border-radius:6px;margin:24px 0;">'
    ]
    parts.append(
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:\'Lato\',sans-serif;font-size:0.95rem;">'
    )

    # Head
    parts.append(f'<thead><tr style="background:{theme.primary};">')
    for h in headers:
        parts.append(
            '<th style="color:#ffffff;font-family:\'Lato\',sans-serif;'
            'font-weight:700;font-size:0.7rem;letter-spacing:0.15em;'
            'text-transform:uppercase;text-align:left;padding:13px 18px;'
            f'vertical-align:top;">{inline_format(h, theme)}</th>'
        )
    parts.append('</tr></thead>')

    # Body
    parts.append('<tbody>')
    last_row = len(rows) - 1
    for r_idx, row in enumerate(rows):
        bg = "#ffffff" if r_idx % 2 == 0 else theme.warm
        border = (
            f"border-bottom:1px solid {theme.border};"
            if r_idx != last_row else ""
        )
        parts.append(f'<tr style="background:{bg};">')
        for c_idx, cell in enumerate(row):
            style = (
                f"padding:13px 18px;vertical-align:top;line-height:1.5;{border}"
                f"color:{theme.body_text};"
            )
            if c_idx == 0:
                style += (
                    f"font-weight:700;color:{theme.primary};"
                    "font-family:'Lato',sans-serif;"
                )
            parts.append(f'<td style="{style}">{inline_format(cell, theme)}</td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    return "".join(parts)


def render_footer(post: Post, theme: Theme) -> str:
    text = post.footer or "Thanks for reading — more posts at ModernSimpleLiving.com"
    return (
        f'<footer style="border-top:1px solid {theme.border};text-align:center;'
        f'padding:32px 24px 48px;font-family:\'Lato\',sans-serif;'
        f'font-weight:400;font-size:0.8rem;color:{theme.muted};'
        f'background:{theme.bg};">'
        f'{html_lib.escape(text)}</footer>'
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Format a blog post into Blogger-compatible inlined HTML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input", nargs="?", help="Input file (omit to read stdin)")
    ap.add_argument("-o", "--output", help="Output file (default: stdout)")
    ap.add_argument(
        "-t", "--theme",
        default="navy_gold",
        choices=list(THEMES.keys()),
        help="Color scheme (default: navy_gold)",
    )
    ap.add_argument(
        "--list-themes", action="store_true",
        help="Show available themes and exit",
    )
    args = ap.parse_args()

    if args.list_themes:
        print("Available themes:")
        for key, theme in THEMES.items():
            print(f"  {key:<12}  {theme.name}")
            print(f"               primary={theme.primary}  accent={theme.accent}  bg={theme.bg}")
        return

    # Read input
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            ap.error("No input file provided and stdin is empty.")
        text = sys.stdin.read()

    theme = THEMES[args.theme]
    post = parse_input(text)
    html_out = render(post, theme)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html_out)
        print(f"Wrote {args.output} ({len(html_out):,} chars, theme: {args.theme})", file=sys.stderr)
    else:
        print(html_out)


if __name__ == "__main__":
    main()
