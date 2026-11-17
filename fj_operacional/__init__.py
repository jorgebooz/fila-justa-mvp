"""Extensão operacional isolada do Fila Justa 2.0."""
from .repository import DemandasRepository

__all__ = ["DemandasRepository", "criar_blueprint"]

def criar_blueprint(**kwargs):
    """Importação tardia: os testes de domínio não exigem Flask instalado."""
    from .web import criar_blueprint as _criar
    return _criar(**kwargs)
