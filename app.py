"""Fila Justa — leitura analítica pública + gestão operacional autenticada.

A operação só é habilitada quando o banco dedicado e o segredo de sessão
estiverem configurados explicitamente. O leitor da Gold permanece somente leitura.
"""
import hmac
import os
import secrets

import psycopg
from psycopg.rows import dict_row
from flask import (Flask, jsonify, render_template, request, redirect,
                   url_for, session, g, abort)

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=32768,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('FJ_LOCAL_HTTP') != '1',
)


def get_connection():
    required = ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')
    if any(not os.getenv(name) for name in required):
        raise RuntimeError('Configuração do banco incompleta')
    return psycopg.connect(
        host=os.environ['DB_HOST'], dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
        port=int(os.getenv('DB_PORT', '5432')), sslmode='require',
        connect_timeout=5, row_factory=dict_row,
    )


def fetch_priorities():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT rank, tipo, area_nome,
                       ROUND(score_0_100::numeric, 2) AS score_0_100,
                       cluster_id
                FROM gold.mart_fila_priorizacao
                ORDER BY rank LIMIT 30
            ''')
            return cursor.fetchall()


def check_database():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1')
            return cursor.fetchone() is not None


def csrf_token():
    token = session.get('csrf')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf'] = token
    return token


def validar_csrf(req):
    esperado = session.get('csrf')
    fornecido = req.headers.get('X-CSRFToken') or req.form.get('csrf_token', '')
    return bool(esperado and fornecido and hmac.compare_digest(esperado, fornecido))


def operacional_configurado():
    return bool(app.config.get('OP_ENGINE'))


def usuario_atual():
    if not operacional_configurado():
        return None
    if not hasattr(g, 'usuario_operacional'):
        from fj_operacional.auth import usuario_por_id
        g.usuario_operacional = usuario_por_id(app.config['OP_ENGINE'], session.get('usuario_id'))
    return g.usuario_operacional


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers['Cache-Control'] = 'no-store' if ('/gestao' in request.path or request.path == '/login') else 'private, max-age=60'
    return response


@app.get('/')
def index():
    try:
        rows = fetch_priorities()
        return render_template('index.html', rows=rows, error=False,
                               operacional_ativo=operacional_configurado())
    except (psycopg.Error, RuntimeError):
        app.logger.error('Consulta à fila indisponível')
        return render_template('index.html', rows=[], error=True,
                               operacional_ativo=operacional_configurado()), 503


@app.get('/health')
def health():
    try:
        if check_database():
            return jsonify(status='healthy'), 200
    except (psycopg.Error, RuntimeError):
        pass
    return jsonify(status='degraded'), 503


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not operacional_configurado():
        return render_template('login.html', erro='Área operacional ainda não configurada.',
                               csrf_token=''), 503
    if request.method == 'POST':
        if not validar_csrf(request):
            abort(403)
        from fj_operacional.auth import autenticar
        usuario = autenticar(app.config['OP_ENGINE'], request.form.get('email', ''),
                             request.form.get('senha', ''))
        if usuario:
            session.clear()  # rotaciona a sessão e o CSRF no login
            session['usuario_id'] = usuario['id']
            csrf_token()
            return redirect(url_for('fj_operacional.tela_kanban'))
        erro = 'Credenciais inválidas.'
    else:
        erro = None
        if usuario_atual():
            return redirect(url_for('fj_operacional.tela_kanban'))
    return render_template('login.html', erro=erro, csrf_token=csrf_token()), (401 if erro else 200)


@app.post('/logout')
def logout():
    if not validar_csrf(request):
        abort(403)
    session.clear()
    return redirect(url_for('index'))


def configurar_operacional():
    url = os.getenv('OPERATIONAL_DATABASE_URL')
    secret = os.getenv('FJ_SESSION_SECRET')
    if not url or not secret:
        if url or secret:
            app.logger.warning('Gestão desabilitada: configure OPERATIONAL_DATABASE_URL e FJ_SESSION_SECRET')
        return
    if len(secret) < 32:
        app.logger.warning('Gestão desabilitada: FJ_SESSION_SECRET requer pelo menos 32 caracteres')
        return
    from sqlalchemy import create_engine
    from fj_operacional import criar_blueprint
    app.secret_key = secret
    engine = create_engine(url, pool_pre_ping=True, pool_size=4, max_overflow=2)
    app.config['OP_ENGINE'] = engine
    app.register_blueprint(criar_blueprint(
        engine=engine, usuario_atual=usuario_atual,
        validar_csrf=validar_csrf, token_csrf=csrf_token,
    ))


configurar_operacional()
