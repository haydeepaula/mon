"""Concordância diagnóstica entre a proposta do protótipo e a decisão do consultor
(TCC, seção 3.8, nível 2): percentual de acordo, kappa de Cohen (COHEN, 1960),
matriz de confusão e kappa ponderado quadrático para o conceito INEP de 1 a 5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.domain.diagnostico import Classificacao

CATEGORIAS = tuple(c.value for c in Classificacao)


def percentual_acordo(pares: Sequence[tuple[str, str]]) -> float | None:
    if not pares:
        return None
    return sum(1 for a, b in pares if a == b) / len(pares)


def kappa_cohen(pares: Sequence[tuple[str, str]], categorias: Sequence[str] = CATEGORIAS) -> float | None:
    """κ = (pₒ − pₑ) / (1 − pₑ). Com pₑ = 1 (uma só categoria nos dois avaliadores), κ = 1."""
    n = len(pares)
    if n == 0:
        return None
    p_o = percentual_acordo(pares)
    proposta = Counter(a for a, _ in pares)
    final = Counter(b for _, b in pares)
    p_e = sum(proposta[c] * final[c] for c in categorias) / (n * n)
    if p_e >= 1.0:
        return 1.0
    return (p_o - p_e) / (1 - p_e)


def kappa_ponderado(pares: Sequence[tuple[int, int]], minimo: int = 1, maximo: int = 5) -> float | None:
    """Kappa ponderado quadrático para escalas ordinais (conceito INEP)."""
    n = len(pares)
    if n == 0:
        return None
    k = maximo - minimo + 1
    peso = [[((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)] for i in range(k)]
    observada = [[0.0] * k for _ in range(k)]
    for a, b in pares:
        observada[a - minimo][b - minimo] += 1 / n
    linhas = [sum(observada[i]) for i in range(k)]
    colunas = [sum(observada[i][j] for i in range(k)) for j in range(k)]
    desacordo_obs = sum(peso[i][j] * observada[i][j] for i in range(k) for j in range(k))
    desacordo_esp = sum(peso[i][j] * linhas[i] * colunas[j] for i in range(k) for j in range(k))
    if desacordo_esp == 0:
        return 1.0
    return 1 - desacordo_obs / desacordo_esp


def matriz_confusao(pares: Sequence[tuple[str, str]], categorias: Sequence[str] = CATEGORIAS) -> dict[str, dict[str, int]]:
    """Linhas: proposta do protótipo; colunas: decisão do consultor."""
    matriz = {a: {b: 0 for b in categorias} for a in categorias}
    for a, b in pares:
        if a in matriz and b in matriz[a]:
            matriz[a][b] += 1
    return matriz


def interpretar_kappa(kappa: float | None) -> str | None:
    """Faixas de Landis e Koch (1977)."""
    if kappa is None:
        return None
    if kappa < 0:
        return "pobre"
    for limite, rotulo in ((0.2, "leve"), (0.4, "razoável"), (0.6, "moderada"), (0.8, "substancial")):
        if kappa <= limite:
            return rotulo
    return "quase perfeita"


def resumo_concordancia(itens: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Métricas a partir de itens com ``proposta``, ``final``, ``tipo``, ``causa`` e conceitos."""
    pares = [(i["proposta"], i["final"]) for i in itens if i.get("proposta") and i.get("final")]
    conceitos = [
        (int(i["conceito_proposto"]), int(i["conceito_final"]))
        for i in itens
        if i.get("conceito_proposto") and i.get("conceito_final")
    ]
    kappa = kappa_cohen(pares)
    por_tipo: dict[str, dict[str, Any]] = {}
    for tipo in sorted({i.get("tipo") for i in itens if i.get("tipo")}):
        pares_tipo = [(i["proposta"], i["final"]) for i in itens if i.get("tipo") == tipo and i.get("proposta") and i.get("final")]
        por_tipo[tipo] = {"n": len(pares_tipo), "percentual_acordo": percentual_acordo(pares_tipo)}
    causas = Counter(i["causa"] for i in itens if i.get("causa") and i.get("proposta") != i.get("final"))
    return {
        "n_itens": len(itens),
        "n_pares": len(pares),
        "n_validados": sum(1 for i in itens if i.get("final")),
        "percentual_acordo": percentual_acordo(pares),
        "kappa": kappa,
        "kappa_interpretacao": interpretar_kappa(kappa),
        "kappa_ponderado_conceito": kappa_ponderado(conceitos),
        "n_pares_conceito": len(conceitos),
        "matriz_confusao": matriz_confusao(pares),
        "divergencias_por_causa": dict(causas),
        "por_tipo": por_tipo,
        "distribuicao_proposta": dict(Counter(a for a, _ in pares)),
        "distribuicao_final": dict(Counter(i["final"] for i in itens if i.get("final"))),
    }
