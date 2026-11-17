"""Credenciais persistidas no PostgreSQL; sessões assinadas pelo Flask.

Nenhuma senha ou papel vem de headers enviados pelo navegador.
"""
from datetime import datetime, timezone
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash
from .models import usuarios


def usuario_por_id(engine, identificador):
    if not identificador:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(usuarios.c.id, usuarios.c.nome, usuarios.c.email, usuarios.c.perfil)
                           .where(usuarios.c.id == identificador, usuarios.c.ativo.is_(True))).mappings().first()
    return dict(row) if row else None


def autenticar(engine, email, senha):
    # Nunca vazar se o email existe; não registrar senhas em logs.
    if not isinstance(email, str) or not isinstance(senha, str) or len(email) > 254 or len(senha) > 1024:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(usuarios).where(usuarios.c.email == email.strip().lower(),
                                                 usuarios.c.ativo.is_(True))).mappings().first()
    if not row or not check_password_hash(row['senha_hash'], senha):
        return None
    return {ch: row[ch] for ch in ('id', 'nome', 'email', 'perfil')}


def hash_senha(senha):
    if not 12 <= len(senha) <= 1024:
        raise ValueError('A senha deve ter no mínimo 12 caracteres')
    return generate_password_hash(senha, method='scrypt')
