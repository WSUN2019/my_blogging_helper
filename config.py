import os
from functools import wraps
from flask import session, redirect, url_for

BASE = os.path.dirname(__file__)

# File paths (all under config/ — gitignored)
CREDENTIALS_FILE = os.path.join(BASE, 'config', 'credentials.json')
TOKEN_FILE        = os.path.join(BASE, 'config', 'token.json')
GEMINI_KEY_FILE   = os.path.join(BASE, 'config', 'gemini_key.txt')
GEMINI_MODEL_FILE = os.path.join(BASE, 'config', 'gemini_model.txt')
BLOG_URL_FILE     = os.path.join(BASE, 'config', 'blog_url.txt')
SAMPLE_FILE       = os.path.join(BASE, 'sample.txt')
BLOG_SKILLS_FILE  = os.path.join(BASE, 'skills', 'blog_creation_skills.md')

BLOGGER_SCOPES = ['https://www.googleapis.com/auth/blogger']


def _load_auth():
    u = os.environ.get('APP_USERNAME', '').strip()
    p = os.environ.get('APP_PASSWORD', '').strip()
    if u and p:
        return u, p
    path = os.path.join(BASE, 'config', 'auth.txt')
    if os.path.exists(path):
        lines = open(path).read().splitlines()
        if len(lines) >= 2:
            return lines[0].strip(), lines[1].strip()
    return 'blogtester', 'ThisIsForTesting147$'


APP_USERNAME, APP_PASSWORD = _load_auth()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
