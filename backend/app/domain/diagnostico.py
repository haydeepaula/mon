"""Regras do processo de diagnóstico (TCC, seções 3.5, 3.6.1 e 3.7).

Princípio: o sistema propõe e o consultor decide (AMERSHI et al., 2019). A proposta do
LLM passa por regras determinísticas antes de chegar ao consultor:

- sem evidência recuperada, o item é "Evidência insuficiente" (EI) sem consultar o LLM;
- C, PC ou NC sem nenhuma citação válida é rebaixado para EI;
- citações fora do intervalo [1..n] são descartadas;
- conceito INEP (1 a 5) só vale para requisitos do tipo qualidade.

Ausência de evidência não é não conformidade: na dúvida entre NC e EI, prevalece EI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Classificacao(StrEnum):
    """Escala do Quadro 7."""

    C = "C"  # Conforme
    PC = "PC"  # Parcialmente conforme
    NC = "NC"  # Não conforme
    EI = "EI"  # Evidência insuficiente


ROTULOS_CLASSIFICACAO = {
    Classificacao.C: "Conforme",
    Classificacao.PC: "Parcialmente conforme",
    Classificacao.NC: "Não conforme",
    Classificacao.EI: "Evidência insuficiente",
}


class CausaDivergencia(StrEnum):
    """Causa atribuída pelo consultor quando discorda da proposta (seção 3.8, nível 2)."""

    RECUPERACAO = "recuperacao"  # a evidência existe, mas não foi recuperada
    OCR = "ocr"  # texto mal extraído de página digitalizada
    CHUNKING = "chunking"  # evidência partida entre trechos
    GERACAO = "geracao"  # o LLM interpretou mal trechos corretos
    INTERPRETACAO = "interpretacao"  # divergência de julgamento normativo


class DiagnosticoStatus(StrEnum):
    """Ciclo do Quadro 9. Coleta e indexação (etapas 2 e 3) ficam no módulo de documentos."""

    PLANEJAMENTO = "planejamento"  # etapa 1
    VERIFICANDO = "verificando"  # etapa 4 em execução
    EM_VALIDACAO = "em_validacao"  # etapa 5
    VALIDADO = "validado"  # todos os itens validados
    PRIORIZADO = "priorizado"  # etapa 6
    RELATORIO_EMITIDO = "relatorio_emitido"  # etapa 7
    CONCLUIDO = "concluido"  # etapa 8 (devolutiva registrada)
    FALHOU = "falhou"


class PropostaStatus(StrEnum):
    PENDENTE = "pendente"
    GERADA = "gerada"
    ERRO = "erro"


class Alerta(StrEnum):
    SEM_EVIDENCIA = "sem_evidencia"
    SEM_CITACAO = "sem_citacao"
    CITACAO_INVALIDA = "citacao_invalida"
    CONCEITO_DESCARTADO = "conceito_descartado"
    CONCEITO_AUSENTE = "conceito_ausente"


# JSON Schema da saída estruturada do LLM (seção 3.6.1 c). Compatível com o modo
# estrito da OpenAI: todos os campos obrigatórios e sem propriedades adicionais.
PROPOSTA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "classificacao": {
            "type": "string",
            "enum": [c.value for c in Classificacao],
            "description": "C, PC, NC ou EI, segundo a escala do Quadro 7.",
        },
        "conceito_inep": {
            "type": ["integer", "null"],
            "description": "Conceito estimado de 1 a 5 para indicadores do INEP; null nos demais casos.",
        },
        "justificativa": {
            "type": "string",
            "description": "Fundamentação objetiva, citando os trechos com [n].",
        },
        "citacoes": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Números dos trechos que sustentam a classificação.",
        },
        "lacunas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidências esperadas que não foram encontradas nos trechos.",
        },
    },
    "required": ["classificacao", "conceito_inep", "justificativa", "citacoes", "lacunas"],
    "additionalProperties": False,
}


@dataclass
class Proposta:
    classificacao: str
    justificativa: str
    citacoes: list[int] = field(default_factory=list)
    lacunas: list[str] = field(default_factory=list)
    conceito_inep: int | None = None
    alertas: list[str] = field(default_factory=list)
    classificacao_original: str | None = None  # quando uma regra alterou a proposta do LLM

    def to_dict(self) -> dict[str, Any]:
        return {
            "classificacao": self.classificacao,
            "conceito_inep": self.conceito_inep,
            "justificativa": self.justificativa,
            "citacoes": list(self.citacoes),
            "lacunas": list(self.lacunas),
            "alertas": list(self.alertas),
            "classificacao_original": self.classificacao_original,
        }


def proposta_sem_evidencia(evidencia_esperada: str) -> Proposta:
    """Regra determinística: nada recuperado → EI, sem chamar o LLM."""
    return Proposta(
        classificacao=Classificacao.EI,
        justificativa=(
            "Nenhum trecho dos documentos institucionais foi recuperado para este requisito. "
            "A ausência de evidência não permite concluir pelo atendimento nem pelo não atendimento; "
            "é necessária diligência junto ao curso."
        ),
        lacunas=[evidencia_esperada] if evidencia_esperada else [],
        alertas=[Alerta.SEM_EVIDENCIA],
    )


def validar_proposta(bruta: dict[str, Any], n_evidencias: int, tipo_requisito: str) -> Proposta:
    """Valida a resposta do LLM e aplica as regras de pós-validação. Lança ValueError se inválida."""
    if not isinstance(bruta, dict):
        raise ValueError("A resposta não é um objeto JSON.")
    classificacao = str(bruta.get("classificacao") or "").strip().upper()
    if classificacao not in {c.value for c in Classificacao}:
        raise ValueError(f"Classificação inválida: {bruta.get('classificacao')!r}.")
    justificativa = str(bruta.get("justificativa") or "").strip()
    if not justificativa:
        raise ValueError("Justificativa ausente.")

    alertas: list[str] = []
    citacoes_brutas = bruta.get("citacoes") or []
    if not isinstance(citacoes_brutas, list):
        raise ValueError("citacoes deve ser uma lista.")
    citacoes: list[int] = []
    for valor in citacoes_brutas:
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            numero = 0
        if 1 <= numero <= n_evidencias:
            if numero not in citacoes:
                citacoes.append(numero)
        elif Alerta.CITACAO_INVALIDA not in alertas:
            alertas.append(Alerta.CITACAO_INVALIDA)

    lacunas = [str(item).strip() for item in (bruta.get("lacunas") or []) if str(item).strip()]

    conceito = bruta.get("conceito_inep")
    if conceito is not None:
        try:
            conceito = int(conceito)
        except (TypeError, ValueError):
            conceito = None
        if conceito is not None and not 1 <= conceito <= 5:
            conceito = None
    if tipo_requisito != "qualidade" and conceito is not None:
        conceito = None
        alertas.append(Alerta.CONCEITO_DESCARTADO)

    proposta = Proposta(classificacao, justificativa, citacoes, lacunas, conceito, alertas)
    if classificacao != Classificacao.EI and not citacoes:
        proposta.classificacao_original = classificacao
        proposta.classificacao = Classificacao.EI
        proposta.conceito_inep = None
        proposta.alertas.append(Alerta.SEM_CITACAO)
    if tipo_requisito == "qualidade" and proposta.classificacao != Classificacao.EI and proposta.conceito_inep is None:
        proposta.alertas.append(Alerta.CONCEITO_AUSENTE)
    return proposta


def causa_obrigatoria(classificacao_proposta: str | None, classificacao_final: str) -> bool:
    """A causa da divergência é exigida quando o consultor discorda de uma proposta existente."""
    return bool(classificacao_proposta) and classificacao_proposta != classificacao_final
