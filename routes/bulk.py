"""Bulk operation routes: /blogger/bulk/reformat-one"""
from flask import Blueprint, request, jsonify
from config import login_required
from blogformat import THEMES, parse_input, render as render_post
from blogger_client import _get_service
from html_utils import _html_to_plain, _auto_inject_title
from gemini_client import _get_reformat_prompt, _get_gemini_key, _get_gemini_model
from img_cleaner import clean_html_string as extract_img_tags

bulk_bp = Blueprint('bulk', __name__)


@bulk_bp.route('/blogger/bulk/reformat-one', methods=['POST'])
@login_required
def blogger_bulk_reformat_one():
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
                response = client.models.generate_content(model=model_id, contents=_get_reformat_prompt() + plain)
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
