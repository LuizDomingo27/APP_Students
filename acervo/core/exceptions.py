"""Hierarquia de exceções do Acervo DS.

Toda falha esperada (arquivo corrompido, banco fora do ar, configuração
ausente) deve ser levantada como uma destas classes, nunca como uma exceção
genérica solta — isso é o que permite às camadas de cima (indexador, app)
decidirem com segurança o que é seguro ignorar/logar e seguir em frente.
"""


class AcervoError(Exception):
    """Erro base do Acervo DS."""


class ConfiguracaoError(AcervoError):
    """Configuração ausente ou inválida (ex.: DATABASE_URL ou categorias.json)."""


class ConexaoBancoError(AcervoError):
    """Falha ao conectar ou executar um comando no banco (Neon)."""


class ArquivoParseError(AcervoError):
    """Um arquivo não pôde ser lido/interpretado pelo parser responsável."""

    def __init__(self, caminho: str, etapa: str, causa: Exception):
        self.caminho = caminho
        self.etapa = etapa
        self.causa = causa
        super().__init__(f"[{etapa}] falha ao processar '{caminho}': {causa}")


class BuscaError(AcervoError):
    """Falha ao executar uma busca (query inválida, banco indisponível etc.)."""


class UploadError(AcervoError):
    """Um conteúdo enviado pela interface não pôde ser adicionado ao acervo."""


class CadastroError(AcervoError):
    """Dados de cadastro recusados (e-mail em uso ou malformado, senha fraca).

    Também cobre a troca de senha, que aplica as mesmas regras do cadastro.
    A mensagem é sempre segura para exibir ao usuário — ela existe justamente
    para dizer o que precisa ser corrigido no formulário.
    """


class AutenticacaoError(AcervoError):
    """Login recusado: credenciais inválidas ou conta sem acesso liberado.

    Cuidado ao mexer nas mensagens desta exceção: elas vão para uma tela
    pública, então não podem revelar se um e-mail existe no banco.
    """


class PermissaoError(AcervoError):
    """Ação administrativa não permitida.

    Cobre os dois casos: quem pediu não é admin, ou a ação em si é inválida
    (transição de status que não existe, admin tentando se auto-bloquear,
    remoção do último administrador).

    Levantada pela camada de serviço, não pela interface — esconder o botão
    é conveniência visual, a barreira de verdade é esta.
    """
