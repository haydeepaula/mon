"""Organização da base de conhecimento em coleções lógicas (TCC, seção 3.6.1 a).

- ``normativa``: fontes dos requisitos (Quadro 3): leis, portarias, resoluções, instrumentos.
- ``institucional``: evidências do curso (Quadro 5): PPC, matriz, ementas, atas, relatórios.

As coleções são lógicas: um campo ``colecao`` no payload de cada trecho, na mesma
coleção física do banco vetorial, usado como filtro na recuperação.
"""

from dataclasses import dataclass
from enum import StrEnum


class Colecao(StrEnum):
    NORMATIVA = "normativa"
    INSTITUCIONAL = "institucional"


COLECAO_PADRAO = Colecao.INSTITUCIONAL

# Vocabulário de tipos de documento por coleção.
TIPOS_DOCUMENTO: dict[Colecao, tuple[str, ...]] = {
    Colecao.INSTITUCIONAL: (
        "ppc",  # Projeto Pedagógico do Curso
        "matriz",  # matriz curricular
        "ementas",  # ementas e planos de ensino
        "regulamento",  # estágio, TCC, atividades complementares, extensão
        "relatorio_cpa",  # autoavaliação
        "relatorio_inep",  # avaliação externa e atos no e-MEC
        "enade",  # ENADE, CPC, IDD
        "ata",  # atas do NDE e do colegiado
        "polos_ava",  # polos, mediação pedagógica, AVA
        "outro",
    ),
    Colecao.NORMATIVA: (
        "lei",
        "decreto",
        "portaria",
        "resolucao",
        "parecer",
        "instrumento",  # instrumentos de avaliação do INEP
        "referencial",  # Referenciais de Qualidade EaD
        "nota_tecnica",
        "minuta",  # normas em tramitação (referência de tendência)
        "outro",
    ),
}


@dataclass(frozen=True)
class Classificacao:
    colecao: str
    tipo_documento: str | None = None


def validar_classificacao(colecao: str, tipo_documento: str | None) -> Classificacao:
    """Valida colecao e tipo_documento; lança ValueError com mensagem legível."""
    try:
        alvo = Colecao(colecao)
    except ValueError:
        opcoes = ", ".join(c.value for c in Colecao)
        raise ValueError(f"Coleção inválida: {colecao!r}. Use: {opcoes}.") from None
    if tipo_documento is not None and tipo_documento not in TIPOS_DOCUMENTO[alvo]:
        opcoes = ", ".join(TIPOS_DOCUMENTO[alvo])
        raise ValueError(f"Tipo de documento inválido para {alvo.value}: {tipo_documento!r}. Use: {opcoes}.")
    return Classificacao(alvo.value, tipo_documento)


def classificar_por_caminho(relative_path: str) -> Classificacao | None:
    """Deduz a classificação pela posição na pasta de fontes.

    ``normativa/portaria/378-2025.pdf`` → (normativa, portaria)
    ``institucional/ppc/ppc-2024.pdf``  → (institucional, ppc)
    ``institucional/arquivo.pdf``        → (institucional, None)
    ``arquivo.pdf`` ou pasta desconhecida → None (mantém a classificação atual)
    """
    partes = relative_path.replace("\\", "/").split("/")
    if len(partes) < 2:
        return None
    try:
        colecao = Colecao(partes[0].lower())
    except ValueError:
        return None
    tipo = partes[1].lower() if len(partes) >= 3 else None
    if tipo not in TIPOS_DOCUMENTO[colecao]:
        tipo = None
    return Classificacao(colecao.value, tipo)
