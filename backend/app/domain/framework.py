"""Framework de critérios do diagnóstico (TCC, seção 3.5).

O framework transpõe a lógica da auditoria de sistemas de gestão para a gestão do
curso: requisitos são as exigências normativas e de qualidade, evidências são os
documentos do curso e não conformidade é o não atendimento de um requisito.

Este módulo é puro (sem banco nem framework web): entidades, vocabulário e regras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from app.domain.knowledge_base import TIPOS_DOCUMENTO, Colecao


class TipoRequisito(StrEnum):
    LEGAL = "legal"  # obrigação legal (Quadro 6: "Legal")
    QUALIDADE = "qualidade"  # indicador do instrumento INEP, conceito 1 a 5
    COMPETENCIA = "competencia"  # competência da Indústria 4.0


class SituacaoNormativa(StrEnum):
    VIGENTE = "vigente"
    TENDENCIA = "tendencia"  # norma em tramitação: referência, não requisito obrigatório (seção 3.3)


class StatusValidacao(StrEnum):
    """Revisão do requisito pelo orientador (seção 3.5, passo c)."""

    PENDENTE = "pendente"
    APROVADO = "aprovado"
    AJUSTAR = "ajustar"


class StatusVersao(StrEnum):
    RASCUNHO = "rascunho"
    EM_VALIDACAO = "em_validacao"
    VALIDADO = "validado"  # imutável
    ARQUIVADO = "arquivado"  # imutável


VERSOES_IMUTAVEIS = {StatusVersao.VALIDADO, StatusVersao.ARQUIVADO}

FORMATOS_OFERTA = ("presencial", "semipresencial", "distancia")

# Pesos das dimensões do instrumento INEP de 2017 (seção 3.3.1).
PESOS_DIMENSAO_INEP = {1: 30, 2: 40, 3: 30}

_CODIGO_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$")


@dataclass
class Requisito:
    """Requisito unitário, verificável isoladamente (seção 3.5, passos a e b)."""

    codigo: str  # ex.: REG-01, EXT-01, DCN-01, INEP-D1, I40-01
    grupo: str  # prefixo do código: REG, EXT, DCN, INEP, I40, EAD...
    fonte_documento: str  # ex.: "Portaria MEC nº 378/2025"
    texto: str
    tipo: str  # TipoRequisito
    evidencia_esperada: str
    fonte_dispositivo: str | None = None  # artigo, parágrafo ou indicador
    dimensao_inep: int | None = None  # 1 a 3 (instrumento 2017); 4 = proposta em consulta
    indicador_inep: str | None = None  # ex.: "1.5"
    documentos_provaveis: list[str] = field(default_factory=list)  # tipos da coleção institucional
    consulta_padrao: str | None = None  # consulta padronizada para a recuperação (seção 3.6.1 b)
    termos_chave: list[str] = field(default_factory=list)
    gravidade_base: int | None = None  # 1 a 5; sugere a nota G da matriz GUT
    peso_dimensao: int | None = None  # 30 ou 40 nos indicadores INEP
    aplicabilidade: dict[str, Any] = field(default_factory=dict)  # {"formatos": [...]}
    situacao_normativa: str = SituacaoNormativa.VIGENTE
    prazo_referencia: date | None = None  # prazo regulatório; sugere a nota U da GUT
    status_validacao: str = StatusValidacao.PENDENTE
    comentario_validacao: str | None = None
    ordem: int = 0
    versao: str | None = None

    @property
    def formatos(self) -> list[str]:
        return list(self.aplicabilidade.get("formatos") or [])

    def aplica_a(self, formato_oferta: str | None, incluir_tendencia: bool = False) -> bool:
        """Indica se o requisito entra no diagnóstico de um curso com esse formato de oferta."""
        if self.situacao_normativa == SituacaoNormativa.TENDENCIA and not incluir_tendencia:
            return False
        return not (formato_oferta and self.formatos and formato_oferta not in self.formatos)

    def consulta(self) -> str:
        """Consulta usada na recuperação de evidências."""
        if self.consulta_padrao:
            base = self.consulta_padrao
        else:
            base = f"{self.texto}. {self.evidencia_esperada}"
        if self.termos_chave:
            base = f"{base} ({', '.join(self.termos_chave)})"
        return base


@dataclass
class FiltroRequisitos:
    versao: str | None = None  # None = versão ativa
    tipos: list[str] = field(default_factory=list)
    grupos: list[str] = field(default_factory=list)
    dimensao_inep: int | None = None
    formato_oferta: str | None = None
    status_validacao: str | None = None
    incluir_tendencia: bool = True
    texto: str | None = None  # busca livre em código, texto e fonte


@dataclass(frozen=True)
class VersaoInfo:
    versao: str
    status: str
    ativa: bool
    data_corte: date | None = None


# Campos aceitos na importação, na ordem usada na exportação CSV.
CAMPOS_REQUISITO = (
    "codigo",
    "grupo",
    "fonte_documento",
    "fonte_dispositivo",
    "texto",
    "tipo",
    "dimensao_inep",
    "indicador_inep",
    "evidencia_esperada",
    "documentos_provaveis",
    "consulta_padrao",
    "termos_chave",
    "gravidade_base",
    "peso_dimensao",
    "formatos",
    "situacao_normativa",
    "prazo_referencia",
    "status_validacao",
    "comentario_validacao",
)


def _texto(dados: dict, campo: str, obrigatorio: bool = False) -> str | None:
    valor = dados.get(campo)
    valor = str(valor).strip() if valor is not None else ""
    if obrigatorio and not valor:
        raise ValueError(f"Campo obrigatório ausente: {campo}.")
    return valor or None


def _inteiro(dados: dict, campo: str, minimo: int, maximo: int) -> int | None:
    valor = dados.get(campo)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} deve ser um número inteiro.") from None
    if not minimo <= numero <= maximo:
        raise ValueError(f"{campo} deve estar entre {minimo} e {maximo}.")
    return numero


def _lista(valor: Any) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, str):
        valor = re.split(r"[;|,]", valor)
    return [str(item).strip() for item in valor if str(item).strip()]


def _data(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise ValueError(f"Data inválida: {valor!r} (use AAAA-MM-DD).") from None


def requisito_de_dict(dados: dict[str, Any]) -> Requisito:
    """Valida e normaliza um requisito vindo de JSON, CSV ou da API. Lança ValueError."""
    codigo = _texto(dados, "codigo", obrigatorio=True).upper()
    try:
        return _montar(codigo, dados)
    except ValueError as exc:
        raise ValueError(f"{codigo}: {exc}") from None


def _montar(codigo: str, dados: dict[str, Any]) -> Requisito:
    if not _CODIGO_RE.match(codigo):
        raise ValueError("código deve ter o formato GRUPO-NN (ex.: REG-01, INEP-D1).")
    grupo = (_texto(dados, "grupo") or codigo.split("-")[0]).upper()

    tipo = _texto(dados, "tipo", obrigatorio=True).lower()
    if tipo not in {t.value for t in TipoRequisito}:
        raise ValueError(f"tipo inválido: {tipo!r}. Use: {', '.join(t.value for t in TipoRequisito)}.")

    dimensao = _inteiro(dados, "dimensao_inep", 1, 4)
    if dimensao is not None and tipo != TipoRequisito.QUALIDADE:
        raise ValueError("dimensao_inep só se aplica a requisitos do tipo qualidade.")
    peso = _inteiro(dados, "peso_dimensao", 1, 100)
    if peso is None and dimensao is not None:
        peso = PESOS_DIMENSAO_INEP.get(dimensao)

    documentos = [d.lower() for d in _lista(dados.get("documentos_provaveis"))]
    validos = TIPOS_DOCUMENTO[Colecao.INSTITUCIONAL]
    invalidos = [d for d in documentos if d not in validos]
    if invalidos:
        raise ValueError(f"documentos_provaveis inválidos: {', '.join(invalidos)}. Use: {', '.join(validos)}.")

    aplicabilidade = dict(dados.get("aplicabilidade") or {})
    formatos = _lista(dados.get("formatos", aplicabilidade.get("formatos")))
    formatos = [f.lower() for f in formatos]
    invalidos = [f for f in formatos if f not in FORMATOS_OFERTA]
    if invalidos:
        raise ValueError(f"formatos inválidos: {', '.join(invalidos)}. Use: {', '.join(FORMATOS_OFERTA)}.")
    if formatos:
        aplicabilidade["formatos"] = formatos
    else:
        aplicabilidade.pop("formatos", None)

    situacao = (_texto(dados, "situacao_normativa") or SituacaoNormativa.VIGENTE).lower()
    if situacao not in {s.value for s in SituacaoNormativa}:
        raise ValueError(f"situacao_normativa inválida: {situacao!r}.")

    status = (_texto(dados, "status_validacao") or StatusValidacao.PENDENTE).lower()
    if status not in {s.value for s in StatusValidacao}:
        raise ValueError(f"status_validacao inválido: {status!r}.")

    return Requisito(
        codigo=codigo,
        grupo=grupo,
        fonte_documento=_texto(dados, "fonte_documento", obrigatorio=True),
        fonte_dispositivo=_texto(dados, "fonte_dispositivo"),
        texto=_texto(dados, "texto", obrigatorio=True),
        tipo=tipo,
        dimensao_inep=dimensao,
        indicador_inep=_texto(dados, "indicador_inep"),
        evidencia_esperada=_texto(dados, "evidencia_esperada", obrigatorio=True),
        documentos_provaveis=documentos,
        consulta_padrao=_texto(dados, "consulta_padrao"),
        termos_chave=_lista(dados.get("termos_chave")),
        gravidade_base=_inteiro(dados, "gravidade_base", 1, 5),
        peso_dimensao=peso,
        aplicabilidade=aplicabilidade,
        situacao_normativa=situacao,
        prazo_referencia=_data(dados.get("prazo_referencia")),
        status_validacao=status,
        comentario_validacao=_texto(dados, "comentario_validacao"),
        ordem=_inteiro(dados, "ordem", 0, 1_000_000) or 0,
    )


def requisito_para_dict(requisito: Requisito) -> dict[str, Any]:
    """Representação plana usada na exportação (JSON e CSV)."""
    return {
        "codigo": requisito.codigo,
        "grupo": requisito.grupo,
        "fonte_documento": requisito.fonte_documento,
        "fonte_dispositivo": requisito.fonte_dispositivo,
        "texto": requisito.texto,
        "tipo": requisito.tipo,
        "dimensao_inep": requisito.dimensao_inep,
        "indicador_inep": requisito.indicador_inep,
        "evidencia_esperada": requisito.evidencia_esperada,
        "documentos_provaveis": list(requisito.documentos_provaveis),
        "consulta_padrao": requisito.consulta_padrao,
        "termos_chave": list(requisito.termos_chave),
        "gravidade_base": requisito.gravidade_base,
        "peso_dimensao": requisito.peso_dimensao,
        "formatos": requisito.formatos,
        "situacao_normativa": requisito.situacao_normativa,
        "prazo_referencia": requisito.prazo_referencia.isoformat() if requisito.prazo_referencia else None,
        "status_validacao": requisito.status_validacao,
        "comentario_validacao": requisito.comentario_validacao,
    }


def validar_lote(itens: list[dict[str, Any]]) -> list[Requisito]:
    """Valida uma lista; reúne todos os erros e rejeita códigos duplicados."""
    requisitos: list[Requisito] = []
    erros: list[str] = []
    vistos: set[str] = set()
    for posicao, dados in enumerate(itens, start=1):
        try:
            requisito = requisito_de_dict(dados)
        except ValueError as exc:
            erros.append(f"item {posicao}: {exc}")
            continue
        if requisito.codigo in vistos:
            erros.append(f"item {posicao}: código duplicado {requisito.codigo}.")
            continue
        vistos.add(requisito.codigo)
        if not requisito.ordem:
            requisito.ordem = posicao
        requisitos.append(requisito)
    if erros:
        raise ValueError("Framework inválido:\n" + "\n".join(erros[:50]))
    return requisitos
