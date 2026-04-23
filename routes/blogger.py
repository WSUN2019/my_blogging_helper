"""Blogger OAuth + CRUD routes: /blogger/auth, /callback, /status, /disconnect, /blog, /posts, /post"""
import os
from flask import Blueprint, request, jsonify, session, redirect, url_for
from config import CREDENTIALS_FILE, TOKEN_FILE, BLOGGER_SCOPES, login_required
from blogger_client import _get_service

blogger_bp = Blueprint('blogger', __name__)


@blogger_bp.route('/blogger/auth')
def blogger_auth():
    if not os.path.exists(CREDENTIALS_FILE):
        return redirect('/?tab=blogger&error=no_credentials')
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE, scopes=BLOGGER_SCOPES,
            redirect_uri=url_for('.blogger_callback', _external=True)
        )
        auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
        session['oauth_state'] = state
        session['code_verifier'] = getattr(flow, 'code_verifier', None)
        return redirect(auth_url)
    except Exception as e:
        return redirect(f'/?tab=blogger&error={e}')


@blogger_bp.route('/blogger/callback')
def blogger_callback():
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            CREDENTIALS_FILE, scopes=BLOGGER_SCOPES,
            state=session.get('oauth_state'),
            redirect_uri=url_for('.blogger_callback', _external=True)
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


@blogger_bp.route('/blogger/status')
@login_required
def blogger_status():
    svc = _get_service()
    return jsonify({'connected': svc is not None, 'has_credentials': os.path.exists(CREDENTIALS_FILE)})


@blogger_bp.route('/blogger/disconnect', methods=['POST'])
@login_required
def blogger_disconnect():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    return jsonify({'success': True})


@blogger_bp.route('/blogger/blog')
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


@blogger_bp.route('/blogger/posts')
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


@blogger_bp.route('/blogger/post', methods=['POST'])
@login_required
def blogger_create_post():
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_id = request.args.get('blog_id', '')
    data = request.get_json()
    title = (data.get('title') or '').strip() or 'Untitled'
    content = data.get('content', '')
    labels = data.get('labels', [])
    is_draft = data.get('draft', False)
    try:
        body = {'title': title, 'content': content}
        if labels:
            body['labels'] = labels
        r = svc.posts().insert(blogId=blog_id, body=body, isDraft=is_draft).execute()
        return jsonify({'success': True, 'id': r['id'], 'url': r.get('url', ''), 'title': r['title']})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@blogger_bp.route('/blogger/post/<post_id>', methods=['GET'])
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


@blogger_bp.route('/blogger/post/<post_id>', methods=['PUT'])
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


@blogger_bp.route('/blogger/post/<post_id>', methods=['DELETE'])
@login_required
def blogger_delete_post(post_id):
    svc = _get_service()
    if not svc:
        return jsonify({'error': 'Not authenticated'}), 401
    blog_id = request.args.get('blog_id', '')
    try:
        svc.posts().delete(blogId=blog_id, postId=post_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
