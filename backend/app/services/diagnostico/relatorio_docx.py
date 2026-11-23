"""Exporta o relatório de diagnóstico (Markdown) para DOCX com python-docx.

Cobre o subconjunto de Markdown gerado por ``relatorio.py``: títulos, parágrafos, listas,
citações em bloco, tabelas e ênfase (**negrito** e *itálico*).
"""

from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

_ENFASE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")
_SEPARADOR_TABELA = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _inline(paragrafo, texto: str) -> None:
    """Acrescenta texto com **negrito** e *itálico* ao parágrafo."""
    texto = texto.replace("\\|", "|")
    for parte in _ENFASE.split(texto):
        if not parte:
            continue
        if parte.startswith("**") and parte.endswith("**"):
            paragrafo.add_run(parte[2:-2]).bold = True
        elif parte.startswith("*") and parte.endswith("*") and len(parte) > 2:
            paragrafo.add_run(parte[1:-1]).italic = True
        else:
            paragrafo.add_run(parte)


def _celulas(linha: str) -> list[str]:
    linha = linha.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", linha)]


def _tabela(documento, linhas: list[str]) -> None:
    cabecalho = _celulas(linhas[0])
    corpo = [_celulas(linha) for linha in linhas[2:]]
    tabela = documento.add_table(rows=1, cols=len(cabecalho))
    tabela.style = "Table Grid"
    tabela.alignment = WD_TABLE_ALIGNMENT.CENTER
    for celula, texto in zip(tabela.rows[0].cells, cabecalho):
        celula.text = ""
        _inline(celula.paragraphs[0], texto)
        for run in celula.paragraphs[0].runs:
            run.bold = True
    for valores in corpo:
        celulas = tabela.add_row().cells
        for celula, texto in zip(celulas, valores):
            celula.text = ""
            _inline(celula.paragraphs[0], texto)
    for linha in tabela.rows:
        for celula in linha.cells:
            for paragrafo in celula.paragraphs:
                for run in paragrafo.runs:
                    run.font.size = Pt(9)
    documento.add_paragraph()


def markdown_para_docx(markdown: str) -> bytes:
    documento = Document()
    estilo = documento.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(11)

    linhas = markdown.splitlines()
    i = 0
    while i < len(linhas):
        linha = linhas[i].rstrip()
        if not linha.strip():
            i += 1
            continue
        if linha.startswith("|") and i + 1 < len(linhas) and _SEPARADOR_TABELA.match(linhas[i + 1].strip()):
            bloco = []
            while i < len(linhas) and linhas[i].strip().startswith("|"):
                bloco.append(linhas[i])
                i += 1
            _tabela(documento, bloco)
            continue
        titulo = re.match(r"^(#{1,4})\s+(.*)$", linha)
        if titulo:
            nivel = len(titulo.group(1))
            cabecalho = documento.add_heading(level=0 if nivel == 1 else nivel - 1)
            _inline(cabecalho, titulo.group(2))
            if nivel == 1:
                cabecalho.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif linha.startswith("> "):
            paragrafo = documento.add_paragraph()
            _inline(paragrafo, linha[2:])
            for run in paragrafo.runs:
                run.italic = True
                run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        elif re.match(r"^\s*[-*]\s+", linha):
            _inline(documento.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", linha))
        else:
            _inline(documento.add_paragraph(), linha)
        i += 1

    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()
