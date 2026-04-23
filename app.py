import os
from flask import Flask, render_template, request, session, redirect, url_for
from config import APP_USERNAME, APP_PASSWORD

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blogger-tools-local-dev-key')

from routes.formatter import formatter_bp
from routes.gemini import gemini_bp
from routes.blogger import blogger_bp
from routes.cleanup import cleanup_bp
from routes.bulk import bulk_bp
from routes.versions import versions_bp
from routes.feed import feed_bp
from routes.config_routes import config_bp
from routes.skills import skills_bp

app.register_blueprint(formatter_bp)
app.register_blueprint(gemini_bp)
app.register_blueprint(blogger_bp)
app.register_blueprint(cleanup_bp)
app.register_blueprint(bulk_bp)
app.register_blueprint(versions_bp)
app.register_blueprint(feed_bp)
app.register_blueprint(config_bp)
app.register_blueprint(skills_bp)


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


@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('index.html')


if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
