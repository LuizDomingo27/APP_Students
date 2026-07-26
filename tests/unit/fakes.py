"""Repositório de usuários em memória, para testar os serviços sem banco.

Imita o `UsuarioRepository` real de perto — inclusive nos detalhes que os
serviços dependem: `criar` devolve None em e-mail repetido (como o
ON CONFLICT DO NOTHING), a ordenação de `listar` põe pendentes no topo e
`buscar_por_email` devolve o par (usuário, hash).

Os testes de integração é que provam que o repositório de verdade se comporta
assim; aqui a fidelidade é assumida, e é o que permite exercitar as regras de
negócio em milissegundos.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from acervo.core.models import Usuario

_PESO_STATUS = {"pendente": 0, "aprovado": 1, "bloqueado": 2, "recusado": 3}


@contextmanager
def cursor_fake():
    """Substitui `db.cursor()` nos serviços — o cursor nunca é usado pelo fake."""
    yield object()


class FakeUsuarioRepo:
    def __init__(self):
        self._usuarios: dict[int, Usuario] = {}
        self._hashes: dict[int, str] = {}
        self._proximo_id = 1
        self.acessos_registrados: list[int] = []
        self.decisoes: list[tuple[int, str, Optional[int]]] = []

    # ------------------------------------------------------- montagem no teste

    def semear(
        self,
        nome: str,
        email: str,
        senha_hash: str = "hash-qualquer",
        *,
        papel: str = "usuario",
        status: str = "pendente",
        senha_temporaria: bool = False,
    ) -> Usuario:
        """Cria uma conta direto, sem passar pelas regras do serviço."""
        usuario = Usuario(
            id=self._proximo_id,
            nome=nome,
            email=email,
            papel=papel,
            status=status,
            senha_temporaria=senha_temporaria,
            criado_em=datetime.now(timezone.utc),
            ultimo_acesso=None,
        )
        self._usuarios[usuario.id] = usuario
        self._hashes[usuario.id] = senha_hash
        self._proximo_id += 1
        return usuario

    def hash_de(self, usuario_id: int) -> str:
        return self._hashes[usuario_id]

    # ------------------------------------------------ interface do repositório

    def criar(self, cur, nome, email, senha_hash, *, papel="usuario", status="pendente"):
        if any(u.email == email for u in self._usuarios.values()):
            return None
        return self.semear(nome, email, senha_hash, papel=papel, status=status)

    def buscar_por_email(self, cur, email):
        for usuario in self._usuarios.values():
            if usuario.email == email:
                return usuario, self._hashes[usuario.id]
        return None

    def buscar_por_id(self, cur, usuario_id):
        return self._usuarios.get(usuario_id)

    def listar(self, cur, status=None):
        itens = [u for u in self._usuarios.values() if status is None or u.status == status]
        itens.sort(key=lambda u: (_PESO_STATUS.get(u.status, 9), -u.id))
        return tuple(itens)

    def contar_por_status(self, cur):
        contagem: dict[str, int] = {}
        for usuario in self._usuarios.values():
            contagem[usuario.status] = contagem.get(usuario.status, 0) + 1
        return contagem

    def atualizar_status(self, cur, usuario_id, status, *, decidido_por):
        if usuario_id not in self._usuarios:
            return False
        self._usuarios[usuario_id] = replace(self._usuarios[usuario_id], status=status)
        self.decisoes.append((usuario_id, status, decidido_por))
        return True

    def atualizar_papel(self, cur, usuario_id, papel):
        if usuario_id not in self._usuarios:
            return False
        self._usuarios[usuario_id] = replace(self._usuarios[usuario_id], papel=papel)
        return True

    def atualizar_senha(self, cur, usuario_id, senha_hash, *, temporaria=False):
        if usuario_id not in self._usuarios:
            return False
        self._hashes[usuario_id] = senha_hash
        self._usuarios[usuario_id] = replace(
            self._usuarios[usuario_id], senha_temporaria=temporaria,
        )
        return True

    def registrar_acesso(self, cur, usuario_id):
        self.acessos_registrados.append(usuario_id)
        self._usuarios[usuario_id] = replace(
            self._usuarios[usuario_id], ultimo_acesso=datetime.now(timezone.utc),
        )

    def contar_admins_ativos(self, cur, *, exceto=None):
        return sum(
            1 for u in self._usuarios.values()
            if u.eh_admin and u.tem_acesso and u.id != exceto
        )

    def existe_algum(self, cur):
        return bool(self._usuarios)
