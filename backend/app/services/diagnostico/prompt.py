"""Instrução de sistema e prompt da verificação assistida (TCC, seção 3.6.1 c e e)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.framework import Evidencia, Requisito

# Usada se DIAGNOSTICO_PROMPT.md não estiver disponível.
INSTRUCAO_PADRAO = """Você é um auditor de conformidade de cursos de graduação em Engenharia à luz do SINAES,
das DCN e do marco regulatório da oferta semipresencial e a distância. Seu papel é PROPOR uma
classificação, que será validada por um consultor humano. Use somente os trechos em <evidencias>.
Escala: C = há evidência suficiente de atendimento; PC = atendimento parcial ou evidência incompleta;
NC = os trechos DEMONSTRAM o não atendimento; EI = os trechos não permitem concluir.
Ausência de evidência não é não conformidade: na dúvida entre NC e EI, escolha EI.
Cite cada afirmação com [n]. Em "lacunas", liste as evidências esperadas não encontradas.
Para indicadores do INEP, estime um conceito de 1 a 5 (instrumento de 2017); nos demais casos, use null.
Responda em português, em JSON."""

NOME_SCHEMA = "proposta_diagnostico"

ROTULOS_ATO = {
    "autorizacao": "autorização",
    "reconhecimento": "reconhecimento",
    "renovacao": "renovação de reconhecimento",
}


@dataclass(frozen=True)
class Instrucao:
    texto: str
    sha256: str
    origem: str


def carregar_instrucao(caminho: Path | None) -> Instrucao:
    if caminho is not None and caminho.is_file():
        texto = caminho.read_text(encoding="utf-8").strip()
        origem = str(caminho)
    else:
        texto, origem = INSTRUCAO_PADRAO, "padrao"
    texto = texto or INSTRUCAO_PADRAO
    return Instrucao(texto, hashlib.sha256(texto.encode("utf-8")).hexdigest(), origem)


def _escopo_texto(escopo: dict[str, Any], curso_nome: str | None) -> str:
    linhas = []
    if curso_nome:
        linhas.append(f"Curso: {curso_nome}")
    if escopo.get("formato_oferta"):
        linhas.append(f"Formato de oferta: {escopo['formato_oferta']}")
    if escopo.get("proximo_ato"):
        ato = ROTULOS_ATO.get(escopo["proximo_ato"], escopo["proximo_ato"])
        data = f" (previsto para {escopo['data_ato']})" if escopo.get("data_ato") else ""
        linhas.append(f"Próximo ato regulatório: {ato}{data}")
    return "\n".join(linhas) or "Não informado."


def formatar_evidencias(evidencias: list[Evidencia]) -> str:
    blocos = []
    for numero, evidencia in enumerate(evidencias, start=1):
        rotulo = evidencia.localizacao or evidencia.documento
        if evidencia.ocr:
            rotulo += " (texto obtido por OCR)"
        blocos.append(f"[{numero}] {rotulo}\n{evidencia.trecho.strip()}")
    return "\n\n".join(blocos)


def montar_prompt(
    requisito: Requisito, evidencias: list[Evidencia], escopo: dict[str, Any], curso_nome: str | None = None
) -> str:
    fonte = requisito.fonte_documento + (f", {requisito.fonte_dispositivo}" if requisito.fonte_dispositivo else "")
    linhas_requisito = [
        f"<codigo>{requisito.codigo}</codigo>",
        f"<fonte>{fonte}</fonte>",
        f"<texto>{requisito.texto}</texto>",
        f"<tipo>{requisito.tipo}</tipo>",
    ]
    if requisito.dimensao_inep:
        linhas_requisito.append(f"<dimensao_inep>{requisito.dimensao_inep}</dimensao_inep>")
    if requisito.indicador_inep:
        linhas_requisito.append(f"<indicador_inep>{requisito.indicador_inep}</indicador_inep>")
    linhas_requisito.append(f"<evidencia_esperada>{requisito.evidencia_esperada}</evidencia_esperada>")
    return (
        "Classifique o requisito abaixo com base exclusivamente nos trechos fornecidos.\n\n"
        "<requisito>\n" + "\n".join(linhas_requisito) + "\n</requisito>\n\n"
        f"<escopo>\n{_escopo_texto(escopo, curso_nome)}\n</escopo>\n\n"
        f"<evidencias>\n{formatar_evidencias(evidencias)}\n</evidencias>\n\n"
        "Responda em JSON com os campos: classificacao (C, PC, NC ou EI), conceito_inep (1 a 5 ou null), "
        "justificativa (com citações [n]), citacoes (lista de números dos trechos) e lacunas (lista de textos)."
    )
