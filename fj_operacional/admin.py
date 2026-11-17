"""Provisão segura de contas, executada manualmente com um usuário de migração.

Use OPERATIONAL_MIGRATION_DATABASE_URL, e nunca a URL de runtime da aplicação.
"""
import argparse
import getpass
import os
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import create_engine, insert, select, update
from .auth import hash_senha
from .models import usuarios


def main():
    parser = argparse.ArgumentParser(description='Provisão de usuário Fila Justa (interativo)')
    parser.add_argument('--email', required=True)
    parser.add_argument('--nome', required=True)
    parser.add_argument('--perfil', required=True, choices=['operador', 'gestor', 'administrador'])
    args = parser.parse_args()
    url = os.getenv('OPERATIONAL_MIGRATION_DATABASE_URL')
    if not url:
        parser.error('OPERATIONAL_MIGRATION_DATABASE_URL não configurada')
    senha = getpass.getpass('Nova senha (não será exibida): ')
    confirma = getpass.getpass('Confirme a senha: ')
    if senha != confirma:
        parser.error('Senhas divergentes')
    senha_hash = hash_senha(senha)
    email = args.email.strip().lower()
    if '@' not in email or len(email) > 254 or len(args.nome.strip()) < 2:
        parser.error('Email ou nome inválido')
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        existente = conn.execute(select(usuarios.c.id).where(usuarios.c.email == email)).scalar_one_or_none()
        if existente:
            conn.execute(update(usuarios).where(usuarios.c.id == existente)
                         .values(nome=args.nome.strip(), perfil=args.perfil, senha_hash=senha_hash, ativo=True))
        else:
            conn.execute(insert(usuarios).values(id=str(uuid4()), email=email, nome=args.nome.strip(),
                        perfil=args.perfil, senha_hash=senha_hash, ativo=True,
                        criado_em=datetime.now(timezone.utc)))
    print(f'Conta provisionada: {email} ({args.perfil})')


if __name__ == '__main__':
    main()
