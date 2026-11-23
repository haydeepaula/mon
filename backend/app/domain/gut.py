"""Matriz GUT para priorizar os itens NC e PC (TCC, seção 3.5, último parágrafo).

Gravidade, Urgência e Tendência recebem notas de 1 a 5; a prioridade é o produto G×U×T.
O sistema apenas sugere G e U; a decisão é do consultor, e T fica inteiramente a cargo dele.

- G: natureza do requisito (obrigação legal pesa mais que indicador de qualidade) e peso da
  dimensão do instrumento INEP. Usa a ``gravidade_base`` do requisito quando definida.
  Itens parcialmente conformes recebem um ponto a menos que os não conformes.
- U: proximidade do prazo regulatório (``prazo_referencia`` do requisito ou data do próximo
  ato informada no plano), o que estiver mais próximo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

CLASSIFICACOES_PRIORIZAVEIS = ("NC", "PC")

# Faixas de urgência: meses até o prazo → nota U.
FAIXAS_URGENCIA = ((6, 5), (12, 4), (24, 3))
URGENCIA_DISTANTE = 2


@dataclass(frozen=True)
class Sugestao:
    g: int
    motivo_g: str
    u: int | None
    motivo_u: str

    def to_dict(self) -> dict[str, Any]:
        return {"g": self.g, "motivo_g": self.motivo_g, "u": self.u, "motivo_u": self.motivo_u}


def priorizavel(classificacao_final: str | None) -> bool:
    return classificacao_final in CLASSIFICACOES_PRIORIZAVEIS


def gravidade_base(requisito: dict[str, Any]) -> tuple[int, str]:
    if requisito.get("gravidade_base"):
        return int(requisito["gravidade_base"]), "gravidade base definida no framework"
    tipo = requisito.get("tipo")
    if tipo == "legal":
        return 5, "obrigação legal"
    if tipo == "qualidade":
        peso = requisito.get("peso_dimensao") or 0
        if peso >= 40:
            return 4, f"indicador de qualidade em dimensão de peso {peso}"
        return 3, f"indicador de qualidade{f' em dimensão de peso {peso}' if peso else ''}"
    return 3, "competência da Indústria 4.0"


def sugerir_g(requisito: dict[str, Any], classificacao_final: str) -> tuple[int, str]:
    nota, motivo = gravidade_base(requisito)
    if classificacao_final == "PC" and nota > 1:
        return nota - 1, f"{motivo}; parcialmente conforme (−1)"
    return nota, motivo


def meses_ate(prazo: date, hoje: date) -> int:
    return (prazo.year - hoje.year) * 12 + (prazo.month - hoje.month) - (1 if prazo.day < hoje.day else 0)


def sugerir_u(prazo_requisito: date | None, data_ato: date | None, hoje: date) -> tuple[int | None, str]:
    candidatos = [(p, rotulo) for p, rotulo in ((prazo_requisito, "prazo regulatório"), (data_ato, "próximo ato")) if p]
    if not candidatos:
        return None, "sem prazo informado; defina a urgência"
    prazo, rotulo = min(candidatos, key=lambda c: c[0])
    meses = meses_ate(prazo, hoje)
    if meses < 0:
        return 5, f"{rotulo} vencido em {prazo.isoformat()}"
    for limite, nota in FAIXAS_URGENCIA:
        if meses <= limite:
            return nota, f"{rotulo} em {meses} mês(es) ({prazo.isoformat()})"
    return URGENCIA_DISTANTE, f"{rotulo} em {meses} meses ({prazo.isoformat()})"


def _data(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        return None


def sugerir(requisito: dict[str, Any], classificacao_final: str, data_ato: Any, hoje: date) -> Sugestao:
    g, motivo_g = sugerir_g(requisito, classificacao_final)
    u, motivo_u = sugerir_u(_data(requisito.get("prazo_referencia")), _data(data_ato), hoje)
    return Sugestao(g, motivo_g, u, motivo_u)


def validar_nota(nome: str, valor: Any) -> int:
    try:
        nota = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} deve ser um número de 1 a 5.") from None
    if not 1 <= nota <= 5:
        raise ValueError(f"{nome} deve estar entre 1 e 5.")
    return nota


def chave_ranking(prioridade: int | None, g: int | None, u: int | None, codigo: str) -> tuple:
    """Ordena por G×U×T decrescente; empates por G, depois U, depois código."""
    return (-(prioridade or 0), -(g or 0), -(u or 0), codigo)
