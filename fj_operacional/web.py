"""Adaptador Flask da Etapa 1: conectar à autenticação/CSRF já existentes.

Por segurança, a ausência de callbacks de autenticação e CSRF não libera gravações.
"""
from flask import Blueprint, jsonify, render_template, request, abort, redirect, url_for

from .repository import DemandasRepository
from .domain import (
    RegraNegocioError, ConflitoVersaoError,
    NaoEncontradoError, SemPermissaoError,
)


def criar_blueprint(*, engine, usuario_atual, validar_csrf, token_csrf):
    """usuario_atual(): dict {id, perfil} ou None; nunca confiar em cabeçalhos do cliente.

    validar_csrf(request): bool — valida o token usando a sessão atual.
    token_csrf(): str — emite token criado pela autenticação atual.
    Todos os callbacks são obrigatórios, para integração com o app real.
    """
    if not all(callable(x) for x in (usuario_atual, validar_csrf, token_csrf)):
        raise RuntimeError("Conecte autenticação e proteção CSRF reais antes de registrar o Kanban")
    repo = DemandasRepository(engine)
    bp = Blueprint("fj_operacional", __name__,
                   template_folder="templates", static_folder="static", static_url_path="/gestao/assets")

    def contexto():
        user = usuario_atual()
        if not isinstance(user, dict) or not user.get("id") or user.get("perfil") not in (
            "operador", "gestor", "administrador"
        ):
            abort(403, description="Acesso restrito ao gestor/equipe autorizada")
        return user

    @bp.before_request
    def proteger():
        usuario = usuario_atual()
        if not usuario:
            if request.path.startswith('/api/'):
                abort(401, description='Faça login para acessar a API')
            return redirect(url_for('login'))
        contexto()
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            if not validar_csrf(request):
                abort(403, description="Token CSRF inválido")

    @bp.errorhandler(RegraNegocioError)
    def regra_erro(exc):
        if isinstance(exc, NaoEncontradoError):
            codigo = 404
        elif isinstance(exc, SemPermissaoError):
            codigo = 403
        elif isinstance(exc, ConflitoVersaoError):
            codigo = 409
        else:
            codigo = 422
        return jsonify({"erro": str(exc)}), codigo

    @bp.route("/gestao/kanban", methods=["GET"])
    def tela_kanban():
        return render_template("kanban.html", csrf_token=token_csrf(), perfil=contexto()["perfil"])

    @bp.get('/gestao/demandas')
    def tela_demandas():
        busca = request.args.get('q', '')[:120]
        situacao = request.args.get('status', '')
        pagina = request.args.get('page', '1', type=int) or 1
        dados = repo.listar(busca=busca, status=situacao, pagina=pagina)
        return render_template('demandas.html', dados=dados, busca=busca,
                               situacao=situacao, perfil=contexto()['perfil'],
                               csrf_token=token_csrf())

    @bp.get('/gestao/dashboard')
    def dashboard():
        return render_template('dashboard.html', metricas=repo.metricas(),
                               perfil=contexto()['perfil'], csrf_token=token_csrf())

    @bp.get('/api/gestao/demandas')
    def listar():
        return jsonify(repo.listar(busca=request.args.get('q', ''),
             status=request.args.get('status', ''),
             pagina=request.args.get('page', 1, type=int) or 1))

    @bp.route("/api/gestao/kanban", methods=["GET"])
    def kanban():
        return jsonify(repo.kanban(limite_por_coluna=30))

    @bp.route("/api/gestao/demandas/<demanda_id>", methods=["GET"])
    def detalhar(demanda_id):
        return jsonify(repo.buscar(demanda_id))

    @bp.route("/api/gestao/demandas/<demanda_id>/historico", methods=["GET"])
    def historico(demanda_id):
        return jsonify(repo.historico_da_demanda(demanda_id))

    @bp.route("/api/gestao/demandas", methods=["POST"])
    def criar():
        usuario = contexto()
        j = request.get_json(silent=True) or {}
        return jsonify(repo.criar_manual(ator=usuario["id"], perfil=usuario["perfil"],
            titulo=j.get("titulo", ""), descricao=j.get("descricao", ""),
            tipo=j.get("tipo"), area_nome=j.get("area_nome"), prazo_em=j.get("prazo_em"))), 201

    @bp.route("/api/gestao/importar-gold", methods=["POST"])
    def importar():
        usuario = contexto()
        j = request.get_json(silent=True) or {}
        return jsonify(repo.importar_gold(ator=usuario["id"], perfil=usuario["perfil"],
            cluster_id=j.get("cluster_id", ""))), 200

    @bp.route("/api/gestao/demandas/<demanda_id>", methods=["PATCH"])
    def editar(demanda_id):
        usuario = contexto()
        j = request.get_json(silent=True) or {}
        if not isinstance(j.get("versao"), int) or isinstance(j["versao"], bool):
            return jsonify({"erro": "Informe a versão inteira da demanda"}), 422
        return jsonify(repo.editar(demanda_id=demanda_id, versao=j["versao"],
            ator=usuario["id"], perfil=usuario["perfil"],
            titulo=j.get("titulo", ""), descricao=j.get("descricao", ""),
            tipo=j.get("tipo"), area_nome=j.get("area_nome"), prazo_em=j.get("prazo_em")))

    @bp.route("/api/gestao/demandas/<demanda_id>/status", methods=["POST"])
    def status(demanda_id):
        usuario = contexto()
        j = request.get_json(silent=True) or {}
        if not isinstance(j.get("versao"), int) or isinstance(j["versao"], bool):
            return jsonify({"erro": "Informe a versão inteira da demanda"}), 422
        return jsonify(repo.mudar_status(demanda_id=demanda_id, versao=j["versao"],
            destino=j.get("status", ""), ator=usuario["id"], perfil=usuario["perfil"],
            justificativa=j.get("justificativa", "")))

    return bp
