import os
import re
import json
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from bs4 import BeautifulSoup
from blogformat import THEMES, parse_input, render as render_post
from img_cleaner import clean_html_string as extract_img_tags

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blogger-tools-local-dev-key')

def _load_auth():
    # 1. Environment variables (Railway, Render, etc.)
    u = os.environ.get('APP_USERNAME', '').strip()
    p = os.environ.get('APP_PASSWORD', '').strip()
    if u and p:
        return u, p
    # 2. Local config file (your machine)
    path = os.path.join(os.path.dirname(__file__), 'config', 'auth.txt')
    if os.path.exists(path):
        lines = open(path).read().splitlines()
        if len(lines) >= 2:
            return lines[0].strip(), lines[1].strip()
    # 3. Fallback default
    return 'blogtester', 'ThisIsForTesting147$'

APP_USERNAME, APP_PASSWORD = _load_auth()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

BASE = os.path.dirname(__file__)
CREDENTIALS_FILE = os.path.join(BASE, 'config', 'credentials.json')
TOKEN_FILE = os.path.join(BASE, 'config', 'token.json')
GEMINI_KEY_FILE = os.path.join(BASE, 'config', 'gemini_key.txt')
GEMINI_MODEL_FILE = os.path.join(BASE, 'config', 'gemini_model.txt')
SAMPLE_FILE = os.path.join(BASE, 'sample.txt')

GEMINI_MODELS = [
    {'id': 'gemini-2.5-flash',              'label': 'Gemini 2.5 Flash'},
    {'id': 'gemini-2.5-flash-lite-preview', 'label': 'Gemini 2.5 Flash Lite'},
    {'id': 'gemini-3-flash-preview',        'label': 'Gemini 3 Flash'},
    {'id': 'gemini-3.1-flash-lite-preview', 'label': 'Gemini 3.1 Flash Lite'},
]
DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

BLOGGER_SCOPES = ['https://www.googleapis.com/auth/blogger']


# ---------------------------------------------------------------------------
# Image Cleaner
# ---------------------------------------------------------------------------

@app.route('/api/clean', methods=['POST'])
@login_required
def api_clean():
    data = request.get_json()
    html = data.get('html', '')
    tags = extract_img_tags(html)
    return jsonify({'tags': tags, 'count': len(tags), 'html': '\n'.join(tags)})


# ---------------------------------------------------------------------------
# Blog Formatter
# ---------------------------------------------------------------------------

def _is_html(text: str) -> bool:
    """True if the text looks like HTML (has styled tags or multiple block elements)."""
    return bool(re.search(r'<(div|p|header|section|span|ul|li|table|h[1-6])\b', text, re.I))


def _make_img_grid(img_links: list) -> str:
    parts = []
    for a in img_links:
        href = a.get('href', '#')
        img_tag = a.find('img')
        if not img_tag:
            continue
        src = img_tag.get('src', '')
        parts.append(
            f'<a href="{href}" style="display:block;flex-shrink:0;border-radius:5px;overflow:hidden;line-height:0;">'
            f'<img src="{src}" style="height:180px;width:auto;display:block;" /></a>'
        )
    if not parts:
        return ''
    return ('<div style="display:flex;flex-wrap:wrap;gap:10px;margin:24px 0;align-items:flex-start;">'
            + ''.join(parts) + '</div>')


def _mark(el, emitted: set):
    emitted.add(id(el))
    for d in el.descendants:
        emitted.add(id(d))


def _collect_img_group(children, start):
    """Starting at index start, collect consecutive <a><img> siblings. Returns (group, next_index)."""
    group = []
    i = start
    while i < len(children):
        nc = children[i]
        if not hasattr(nc, 'name'):
            t = str(nc).strip().replace('\xa0', '')
            if not t:
                i += 1
                continue
            break
        if nc.name == 'a' and nc.find('img'):
            group.append(nc)
            i += 1
        elif nc.name in ('br', 'span') and not nc.get_text(strip=True):
            i += 1
        else:
            break
    return group, i


def _walk_children(el, lines, emitted):
    children = list(el.children)
    i = 0
    while i < len(children):
        child = children[i]
        if id(child) in emitted:
            i += 1
            continue
        if hasattr(child, 'name') and child.name == 'a' and child.find('img'):
            group, i = _collect_img_group(children, i)
            if group:
                grid = _make_img_grid(group)
                if grid:
                    lines.append(grid)
                for a in group:
                    _mark(a, emitted)
        else:
            _walk_el(child, lines, emitted)
            i += 1


def _walk_el(el, lines, emitted):
    if id(el) in emitted:
        return
    if not hasattr(el, 'name') or el.name is None:
        return
    tag = el.name.lower()

    if tag in ('script', 'style', 'link', 'head', 'meta', 'br', 'hr'):
        _mark(el, emitted)
        return
    if tag == 'header':
        _mark(el, emitted)
        return
    if tag == 'footer':
        text = el.get_text(' ', strip=True)
        if text:
            lines.append(f'FOOTER: {text}')
        _mark(el, emitted)
        return
    if tag == 'a' and el.find('img'):
        grid = _make_img_grid([el])
        if grid:
            lines.append(grid)
        _mark(el, emitted)
        return
    if tag in ('h1', 'h2'):
        text = el.get_text(' ', strip=True)
        if text:
            lines.append(f'# {text}')
        _mark(el, emitted)
        return
    if tag == 'h3':
        text = el.get_text(' ', strip=True)
        if text:
            lines.append(f'## {text}')
        _mark(el, emitted)
        return
    if tag == 'p':
        children = list(el.children)
        buf = []
        i = 0
        while i < len(children):
            child = children[i]
            if not hasattr(child, 'name') or child.name is None:
                t = str(child).strip()
                if t:
                    buf.append(t)
                i += 1
            elif child.name == 'a' and child.find('img'):
                if buf:
                    lines.append(' '.join(buf))
                    buf = []
                group, i = _collect_img_group(children, i)
                if group:
                    grid = _make_img_grid(group)
                    if grid:
                        lines.append(grid)
                    for a in group:
                        _mark(a, emitted)
            else:
                t = child.get_text(' ', strip=True)
                if t:
                    buf.append(t)
                i += 1
        if buf:
            lines.append(' '.join(buf))
        _mark(el, emitted)
        return
    if tag == 'li':
        text = el.get_text(' ', strip=True)
        if text:
            lines.append(f'- {text}')
        _mark(el, emitted)
        return
    if tag == 'blockquote':
        text = el.get_text(' ', strip=True)
        if text:
            lines.append(f'> {text}')
        _mark(el, emitted)
        return
    emitted.add(id(el))
    _walk_children(el, lines, emitted)


def _html_to_plain(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'link']):
        tag.decompose()
    lines = []
    emitted = set()
    _walk_el(soup, lines, emitted)
    seen, out = set(), []
    for line in lines:
        key = line.strip()[:200]
        if key and key not in seen:
            out.append(line)
            seen.add(key)
    return '\n\n'.join(out)


def _auto_inject_title(text: str) -> str:
    """If no TITLE: line present, promote the first non-empty line as the title."""
    if re.search(r'^TITLE\s*:', text, re.MULTILINE | re.IGNORECASE):
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip markdown headings — those stay as section headers
        if stripped and not stripped.startswith('#') and not stripped.startswith('<'):
            rest = '\n'.join(lines[i + 1:]).lstrip('\n')
            return f'TITLE: {stripped}\n\n{rest}'
    return text


@app.route('/api/format', methods=['POST'])
@login_required
def api_format():
    data = request.get_json()
    text = data.get('text', '')
    theme_name = data.get('theme', 'navy_gold')
    theme = THEMES.get(theme_name, THEMES['navy_gold'])

    html_stripped = False
    if _is_html(text):
        text = _html_to_plain(text)
        html_stripped = True

    text = _auto_inject_title(text)
    post = parse_input(text)
    html_out = render_post(post, theme)
    return jsonify({'html': html_out, 'html_stripped': html_stripped})


@app.route('/api/themes')
@login_required
def api_themes():
    return jsonify({'themes': [
        {'key': k, 'name': v.name, 'primary': v.primary, 'accent': v.accent, 'bg': v.bg}
        for k, v in THEMES.items()
    ]})


@app.route('/api/sample')
@login_required
def api_sample():
    with open(SAMPLE_FILE, 'r', encoding='utf-8') as f:
        return jsonify({'text': f.read()})


# ---------------------------------------------------------------------------
# Gemini Smart Format
# ---------------------------------------------------------------------------

GEMINI_PROMPT = """\
You are a blog formatter for a lifestyle blog covering travel, food, gear, and everyday living.

Convert the user's raw text into structured markdown that a blog formatter will render into styled HTML.

OUTPUT FORMAT (follow exactly, no code fences, no explanation):

TITLE: The post title
SUBTITLE: One-line italic subtitle (skip if nothing natural fits)
EYEBROW: Short category label — pick best: Travel Journal, Wine Review, Gear Review, Food & Drink, Road Trip, City Guide, Feature
STATS: value1 Label1 | value2 Label2 | value3 Label3

# Section Heading

Paragraph text here.

## Sub-label

More paragraph text.

- **Item Name** — description
- **Another** — description

> Tip or callout text — italic highlighted block

| Col A | Col B | Col C |
|-------|-------|-------|
| val   | val   | val   |

FOOTER: Closing line

RULES:
- STATS: extract or intelligently estimate 3–5 KPI numbers from the content.
  Examples: Days, Nights, Miles, Cities, Stops, Items, Bottles, Price, Hours, etc.
  Use ~ prefix for approximations (e.g. "~1,400").
- Create logical # sections. Posts with 3+ sections auto-get a table of contents.
- Use ## sub-labels for time periods (Morning, Evening), categories, or sub-topics.
- Convert enumerated items, gear lists, or steps to - bullet format with **Bold Name** — desc.
- Convert comparison or tabular data to markdown tables.
- Wrap tips, notes, key advice, or quotes in > callout blocks.
- Preserve ALL original content — restructure, never summarize or drop details.
- Section eyebrows can include context: e.g. "Section II — Day 1" as the LABEL.

User's text:
"""


def _get_gemini_key() -> str:
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if key:
        return key
    if os.path.exists(GEMINI_KEY_FILE):
        with open(GEMINI_KEY_FILE) as f:
            return f.read().strip()
    return ''


def _get_gemini_model() -> str:
    val = os.environ.get('GEMINI_MODEL', '').strip()
    if val:
        return val
    if os.path.exists(GEMINI_MODEL_FILE):
        val = open(GEMINI_MODEL_FILE).read().strip()
        if val:
            return val
    return DEFAULT_GEMINI_MODEL


@app.route('/api/gemini-status')
@login_required
def api_gemini_status():
    return jsonify({
        'configured': bool(_get_gemini_key()),
        'model': _get_gemini_model(),
        'models': GEMINI_MODELS,
    })


@app.route('/api/save-gemini-model', methods=['POST'])
@login_required
def api_save_gemini_model():
    model_id = (request.get_json() or {}).get('model', '').strip()
    valid_ids = {m['id'] for m in GEMINI_MODELS}
    if model_id not in valid_ids:
        return jsonify({'error': 'Invalid model'}), 400
    os.makedirs(os.path.dirname(GEMINI_MODEL_FILE), exist_ok=True)
    with open(GEMINI_MODEL_FILE, 'w') as f:
        f.write(model_id)
    return jsonify({'success': True, 'model': model_id})


@app.route('/api/save-gemini-key', methods=['POST'])
@login_required
def api_save_gemini_key():
    key = (request.get_json() or {}).get('key', '').strip()
    os.makedirs(os.path.dirname(GEMINI_KEY_FILE), exist_ok=True)
    with open(GEMINI_KEY_FILE, 'w') as f:
        f.write(key)
    return jsonify({'success': True})


@app.route('/api/smart-format', methods=['POST'])
@login_required
def api_smart_format():
    data = request.get_json()
    text = data.get('text', '').strip()
    theme_name = data.get('theme', 'navy_gold')
    model_id = data.get('model', '').strip() or _get_gemini_model()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    api_key = _get_gemini_key()
    if not api_key:
        return jsonify({'error': 'no_key'}), 400

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_id,
            contents=GEMINI_PROMPT + text,
        )
        structured = response.text.strip()

        # Strip any code fences Gemini might add
        if structured.startswith('```'):
            lines = structured.splitlines()
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
            structured = '\n'.join(lines[start:end]).strip()

        theme = THEMES.get(theme_name, THEMES['navy_gold'])
        post = parse_input(structured)
        html_out = render_post(post, theme)
        return jsonify({'html': html_out, 'structured_text': structured, 'model': model_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Blogger OAuth helpers
# ---------------------------------------------------------------------------

def _get_service():
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, BLOGGER_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as f:
                f.write(creds.to_json())
        if creds and creds.valid:
            return build('blogger', 'v3', credentials=creds)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Blogger API routes
# ---------------------------------------------------------------------------

@app.route('/blogger/auth')
def blogger_auth():
    if not os.path.exists(CREDENTIALS_FILE):
        return redirect('/?tab=blogger&error=no_credentials')
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE, scopes=BLOGGER_SCOPES,
            redirect_uri=url_for('blogger_callback', _external=True)
        )
        auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
        session['oauth_state'] = state
        session['code_verifier'] = getattr(flow, 'code_verifier', None)
        return redirect(auth_url)
    except Exception as e:
        return redirect(f'/?tab=blogger&error={e}')


@app.route('/blogger/callback')
def blogger_callback():
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE, scopes=BLOGGER_SCOPES,
            state=session.get('oauth_state'),
            redirect_uri=url_for('blogger_callback', _external=True)
        )
        kwargs = {}
        if session.get('code_verifier'):
            kwargs['code_verifier'] = session['code_verifier']
        flow.fetch_token(authorization_response=request.url, **kwargs)
        creds = flow.credentials
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
        return redirect('/?tab=blogger&connected=1')
    except Exception as e:
        return redirect(f'/?tab=blogger&error={e}')


@app.route('/blogger/status')
@login_required
def blogger_status():
    svc = _get_service()
    return jsonify({'connected': svc is not None, 'has_credentials': os.path.exists(CREDENTIALS_FILE)})


@app.route('/blogger/disconnect', methods=['POST'])
@login_required
def blogger_disconnect():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return jsonify({'success': True})


@app.route('/blogger/blog')
@login_required
def blogger_blog():
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_url = request.args.get('url', '')
    blog_id = request.args.get('id', '')
    try:
        if blog_url:
            r = svc.blogs().getByUrl(url=blog_url).execute()
        elif blog_id:
            r = svc.blogs().get(blogId=blog_id).execute()
        else:
            return jsonify({'error': 'Provide url or id'}), 400
        return jsonify({
            'id': r['id'], 'name': r['name'], 'url': r['url'],
            'posts': r.get('posts', {}).get('totalItems', 0)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/blogger/posts')
@login_required
def blogger_posts():
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_id = request.args.get('blog_id', '')
    page_token = request.args.get('page_token') or None
    year = request.args.get('year', '')
    try:
        max_results = min(int(request.args.get('max', 20)), 500)
        params = dict(blogId=blog_id, maxResults=max_results, orderBy='PUBLISHED',
                      status=['LIVE', 'DRAFT'], fetchImages=False)
        if page_token:
            params['pageToken'] = page_token
        if year:
            params['startDate'] = f'{year}-01-01T00:00:00Z'
            params['endDate']   = f'{year}-12-31T23:59:59Z'
        r = svc.posts().list(**params).execute()
        posts = [{'id': p['id'], 'title': p['title'],
                  'published': p.get('published', ''),
                  'status': p.get('status', 'live'),
                  'url': p.get('url', '')}
                 for p in r.get('items', [])]
        return jsonify({'posts': posts, 'next_page_token': r.get('nextPageToken')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/blogger/post/<post_id>', methods=['GET'])
@login_required
def blogger_get_post(post_id):
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_id = request.args.get('blog_id', '')
    try:
        r = svc.posts().get(blogId=blog_id, postId=post_id).execute()
        return jsonify({'id': r['id'], 'title': r['title'],
                        'content': r.get('content', ''),
                        'published': r.get('published', ''),
                        'url': r.get('url', ''),
                        'labels': r.get('labels', [])})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/blogger/post/<post_id>', methods=['PUT'])
@login_required
def blogger_update_post(post_id):
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_id = request.args.get('blog_id', '')
    data = request.get_json()
    try:
        body = {'id': post_id, 'title': data.get('title', ''), 'content': data.get('content', '')}
        if 'labels' in data:
            body['labels'] = data['labels']
        r = svc.posts().update(blogId=blog_id, postId=post_id, body=body).execute()
        return jsonify({'success': True, 'url': r.get('url', '')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Cleanup — remove stray Google Fonts <link> tags from all posts
# ---------------------------------------------------------------------------

_DEFAULT_FONTS_TAG = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Playfair+Display:ital,wght@0,400;0,700;1,400&amp;'
    'family=Lato:wght@300;400;700&amp;display=swap" rel="stylesheet"></link>'
)


def _build_tag_re(tag: str):
    """Build a regex that matches the literal tag string with optional trailing </link> and whitespace."""
    # Strip any trailing </link> the user may have included, then make it optional
    base = re.sub(r'\s*</link>\s*$', '', tag.strip(), flags=re.IGNORECASE)
    return re.compile(re.escape(base) + r'\s*(?:</link>)?', re.IGNORECASE)


def _strip_custom_tag(html: str, tag: str) -> str:
    return _build_tag_re(tag).sub('', html).strip()


@app.route('/blogger/cleanup/scan', methods=['POST'])
@login_required
def blogger_cleanup_scan():
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    blog_id = data.get('blog_id', '')
    tag = data.get('tag', _DEFAULT_FONTS_TAG).strip()
    if not blog_id:
        return jsonify({'error': 'blog_id required'}), 400
    try:
        pattern = _build_tag_re(tag)
        affected = []
        page_token = None
        while True:
            params = dict(blogId=blog_id, maxResults=50, orderBy='PUBLISHED',
                          status=['LIVE', 'DRAFT'], fetchImages=False)
            if page_token:
                params['pageToken'] = page_token
            r = svc.posts().list(**params).execute()
            for p in r.get('items', []):
                if pattern.search(p.get('content', '')):
                    affected.append({'id': p['id'], 'title': p['title'],
                                     'published': p.get('published', ''),
                                     'url': p.get('url', '')})
            page_token = r.get('nextPageToken')
            if not page_token:
                break
        return jsonify({'affected': affected, 'count': len(affected)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400





@app.route('/blogger/bulk/reformat-one', methods=['POST'])
@login_required
def blogger_bulk_reformat_one():
    """Fetch a single post, smart-format it, append extracted images, push back."""
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    blog_id = data.get('blog_id', '')
    post_id = data.get('post_id', '')
    theme_name = data.get('theme', 'navy_gold')
    if not blog_id or not post_id:
        return jsonify({'error': 'blog_id and post_id required'}), 400
    api_key = _get_gemini_key()
    if not api_key:
        return jsonify({'error': 'no_key'}), 400
    try:
        p = svc.posts().get(blogId=blog_id, postId=post_id).execute()
        original_html = p.get('content', '')

        plain = _html_to_plain(original_html)
        plain = _auto_inject_title(plain)

        import time as _time
        model_id = _get_gemini_model()
        from google import genai
        client = genai.Client(api_key=api_key)
        for _attempt in range(3):
            try:
                response = client.models.generate_content(model=model_id, contents=GEMINI_PROMPT + plain)
                break
            except Exception as _ge:
                if '429' in str(_ge) and _attempt < 2:
                    _time.sleep(15 * (_attempt + 1))
                else:
                    raise
        structured = response.text.strip()
        if structured.startswith('```'):
            lines = structured.splitlines()
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
            structured = '\n'.join(lines[start:end]).strip()

        theme = THEMES.get(theme_name, THEMES['navy_gold'])
        post_obj = parse_input(structured)
        formatted_html = render_post(post_obj, theme)

        img_tags = extract_img_tags(original_html)
        if img_tags:
            formatted_html += '\n' + '\n'.join(img_tags)

        body = {'id': post_id, 'title': p['title'], 'content': formatted_html}
        if 'labels' in p:
            body['labels'] = p['labels']
        svc.posts().update(blogId=blog_id, postId=post_id, body=body).execute()
        return jsonify({'status': 'done', 'title': p['title']})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


# ---------------------------------------------------------------------------
# Post Versions — blog_backup/versions/<post_id>.atom
# ---------------------------------------------------------------------------

VERSIONS_DIR = os.path.join(BASE, 'blog_backup', 'versions')


def _versions_file(post_id: str) -> str:
    return os.path.join(VERSIONS_DIR, f'{post_id}.atom')


def _read_versions(post_id: str) -> list:
    path = _versions_file(post_id)
    if not os.path.exists(path):
        return []
    import xml.etree.ElementTree as ET
    import html as _html_lib
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        versions = []
        for entry in root.findall('atom:entry', ns):
            id_el = entry.find('atom:id', ns)
            pub_el = entry.find('atom:published', ns)
            title_el = entry.find('atom:title', ns)
            content_el = entry.find('atom:content', ns)
            versions.append({
                'ts': pub_el.text if pub_el is not None else '',
                'title': title_el.text if title_el is not None else '',
                'content': _html_lib.unescape(content_el.text or '') if content_el is not None else '',
            })
        versions.sort(key=lambda v: v['ts'], reverse=True)
        return versions
    except Exception:
        return []


def _write_versions(post_id: str, versions: list):
    import html as _html_lib
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             "<feed xmlns='http://www.w3.org/2005/Atom'>",
             f"  <id>versions:{post_id}</id>"]
    for v in versions:
        escaped = _html_lib.escape(v['content'])
        lines += [
            "  <entry>",
            f"    <title>{_html_lib.escape(v['title'])}</title>",
            f"    <published>{v['ts']}</published>",
            f"    <content type='html'>{escaped}</content>",
            "  </entry>",
        ]
    lines.append("</feed>")
    with open(_versions_file(post_id), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


@app.route('/versions/save', methods=['POST'])
@login_required
def versions_save():
    data = request.get_json() or {}
    post_id = data.get('post_id', '').strip()
    title   = data.get('title', '').strip()
    content = data.get('content', '')
    if not post_id:
        return jsonify({'error': 'post_id required'}), 400
    from datetime import timezone, datetime
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    versions = _read_versions(post_id)
    versions.insert(0, {'ts': ts, 'title': title, 'content': content})
    _write_versions(post_id, versions)
    return jsonify({'success': True, 'ts': ts, 'count': len(versions)})


@app.route('/versions/<post_id>')
@login_required
def versions_list(post_id):
    versions = _read_versions(post_id)
    return jsonify({'versions': [{'ts': v['ts'], 'title': v['title']} for v in versions]})


@app.route('/versions/<post_id>/<ts>')
@login_required
def versions_get(post_id, ts):
    versions = _read_versions(post_id)
    for v in versions:
        if v['ts'] == ts:
            return jsonify(v)
    return jsonify({'error': 'Not found'}), 404


# ---------------------------------------------------------------------------
# Feed Review — blog_backup/feed.atom
# ---------------------------------------------------------------------------

FEED_FILE = os.path.join(BASE, 'blog_backup', 'feed.atom')
_feed_cache = None


def _parse_feed():
    global _feed_cache
    if _feed_cache is not None:
        return _feed_cache
    if not os.path.exists(FEED_FILE):
        _feed_cache = []
        return _feed_cache
    import xml.etree.ElementTree as ET
    import html as _html_lib
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'blogger': 'http://schemas.google.com/blogger/2018',
    }
    posts = []
    for entry in root.findall('atom:entry', ns):
        btype = entry.find('blogger:type', ns)
        if btype is None or btype.text != 'POST':
            continue
        title_el = entry.find('atom:title', ns)
        title = title_el.text if title_el is not None else '(no title)'
        content_el = entry.find('atom:content', ns)
        content_raw = content_el.text if content_el is not None else ''
        content_html = _html_lib.unescape(content_raw) if content_raw else ''
        published_el = entry.find('atom:published', ns)
        published = published_el.text if published_el is not None else ''
        updated_el = entry.find('atom:updated', ns)
        updated = updated_el.text if updated_el is not None else ''
        status_el = entry.find('blogger:status', ns)
        status = status_el.text if status_el is not None else ''
        filename_el = entry.find('blogger:filename', ns)
        filename = filename_el.text if filename_el is not None else ''
        labels = [cat.get('term', '') for cat in entry.findall('atom:category', ns)
                  if cat.get('term', '')]
        posts.append({
            'title': title,
            'content': content_html,
            'published': published,
            'updated': updated,
            'status': status,
            'filename': filename,
            'labels': labels,
        })
    posts.sort(key=lambda p: p['published'], reverse=True)
    for i, p in enumerate(posts):
        p['idx'] = i
    _feed_cache = posts
    return _feed_cache


@app.route('/feed/upload', methods=['POST'])
@login_required
def feed_upload():
    global _feed_cache
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400
    os.makedirs(os.path.dirname(FEED_FILE), exist_ok=True)
    f.save(FEED_FILE)
    _feed_cache = None  # bust cache so next request re-parses
    posts = _parse_feed()
    years = sorted({p['published'][:4] for p in posts if p['published']}, reverse=True)
    return jsonify({'success': True, 'count': len(posts), 'years': years})


@app.route('/feed/status')
@login_required
def feed_status():
    exists = os.path.exists(FEED_FILE)
    count, years = 0, []
    if exists:
        posts = _parse_feed()
        count = len(posts)
        years = sorted({p['published'][:4] for p in posts if p['published']}, reverse=True)
    return jsonify({'exists': exists, 'count': count, 'years': years})


@app.route('/feed/labels')
@login_required
def feed_labels():
    posts = _parse_feed()
    counts = {}
    for p in posts:
        for lbl in p['labels']:
            counts[lbl] = counts.get(lbl, 0) + 1
    labels = sorted(counts.items(), key=lambda x: -x[1])
    return jsonify({'labels': [{'name': n, 'count': c} for n, c in labels]})


@app.route('/feed/posts')
@login_required
def feed_posts():
    posts = _parse_feed()
    search = request.args.get('search', '').strip().lower()
    year   = request.args.get('year', '').strip()
    label  = request.args.get('label', '').strip()
    page   = max(1, int(request.args.get('page', 1)))
    per_page = 40

    filtered = posts
    if search:
        filtered = [p for p in filtered if search in p['title'].lower()]
    if year:
        filtered = [p for p in filtered if p['published'].startswith(year)]
    if label:
        filtered = [p for p in filtered if label in p['labels']]

    total = len(filtered)
    start = (page - 1) * per_page
    items = filtered[start:start + per_page]
    result = [{'idx': p['idx'], 'title': p['title'], 'published': p['published'],
               'labels': p['labels'], 'status': p['status']} for p in items]
    return jsonify({'posts': result, 'total': total, 'page': page, 'per_page': per_page,
                    'has_more': start + per_page < total})


@app.route('/feed/post/<int:idx>')
@login_required
def feed_get_post(idx):
    posts = _parse_feed()
    if idx < 0 or idx >= len(posts):
        return jsonify({'error': 'Not found'}), 404
    p = posts[idx]
    return jsonify({'idx': idx, 'title': p['title'], 'published': p['published'],
                    'updated': p['updated'], 'labels': p['labels'],
                    'status': p['status'], 'filename': p['filename'],
                    'content': p['content']})


@app.route('/blogger/cleanup/fix-one', methods=['POST'])
@login_required
def blogger_cleanup_fix_one():
    """Fix a single post — called one at a time by the frontend with a delay to avoid QPM limits."""
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    blog_id = data.get('blog_id', '')
    post_id = data.get('post_id', '')
    tag = data.get('tag', _DEFAULT_FONTS_TAG).strip()
    if not blog_id or not post_id:
        return jsonify({'error': 'blog_id and post_id required'}), 400
    try:
        p = svc.posts().get(blogId=blog_id, postId=post_id).execute()
        cleaned = _strip_custom_tag(p.get('content', ''), tag)
        body = {'id': post_id, 'title': p['title'], 'content': cleaned}
        if 'labels' in p:
            body['labels'] = p['labels']
        svc.posts().update(blogId=blog_id, postId=post_id, body=body).execute()
        return jsonify({'status': 'fixed', 'title': p['title']})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == APP_USERNAME and
                request.form.get('password') == APP_PASSWORD):
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    return render_template('index.html')


if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    # Get the port from the platform, default to 5000 for local dev
    port = int(os.environ.get("PORT", 5000))
    # Bind to 0.0.0.0 so the platform can "see" the app
    app.run(host="0.0.0.0", port=port)
