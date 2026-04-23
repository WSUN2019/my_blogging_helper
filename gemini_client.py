"""Shared Gemini API helpers."""
import os
from config import GEMINI_KEY_FILE, GEMINI_MODEL_FILE, BASE

GEMINI_MODELS = [
    {'id': 'gemini-2.5-flash',              'label': 'Gemini 2.5 Flash'},
    {'id': 'gemini-2.5-flash-lite-preview', 'label': 'Gemini 2.5 Flash Lite'},
    {'id': 'gemini-3-flash-preview',        'label': 'Gemini 3 Flash'},
    {'id': 'gemini-3.1-flash-lite-preview', 'label': 'Gemini 3.1 Flash Lite'},
]
DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

_REFORMAT_SKILLS_FILE = os.path.join(BASE, 'skills', 'reformat_blog_skills.md')


def _get_reformat_prompt() -> str:
    if os.path.exists(_REFORMAT_SKILLS_FILE):
        with open(_REFORMAT_SKILLS_FILE, encoding='utf-8') as f:
            return f.read().strip() + '\n\n'
    return ''


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
