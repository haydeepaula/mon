"""Casos de uso do framework de critérios: versões, requisitos, validação, importação e exportação.

Regras (TCC, seção 3.5):
- o framework é versionado; uma versão validada pelo orientador ou arquivada é imutável;
  para alterá-la, clona-se uma nova versão;
- apenas uma versão fica ativa; é a usada por padrão no diagnóstico;
- uma versão só passa a "validado" quando todos os requisitos estão aprovados (passo c);
- alterar o conteúdo de um requisito aprovado o devolve para "pendente".
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ValidationError
from app.db.models import FrameworkVersao, RequisitoModel, utcnow
from app.domain.framework import (
    CAMPOS_REQUISITO,
    VERSOES_IMUTAVEIS,
    Requisito,
    StatusValidacao,
    StatusVersao,
    requisito_de_dict,
    requisito_para_dict,
    validar_lote,
)
from app.repositories.framework_repository import SqlFrameworkRepository, copiar_para_model, para_dominio

logger = logging.getLogger(__name__)

# Transições permitidas entre status de versão.
_TRANSICOES = {
    StatusVersao.RASCUNHO: {StatusVersao.EM_VALIDACAO, StatusVersao.ARQUIVADO},
    StatusVersao.EM_VALIDACAO: {StatusVersao.RASCUNHO, StatusVersao.VALIDADO, StatusVersao.ARQUIVADO},
    StatusVersao.VALIDADO: {StatusVersao.ARQUIVADO},
    StatusVersao.ARQUIVADO: set(),
}

# Campos cuja alteração exige nova aprovação do requisito.
_CAMPOS_CONTEUDO = tuple(c for c in CAMPOS_REQUISITO if c not in {"status_validacao", "comentario_validacao"})


def _invalido(exc: ValueError) -> ValidationError:
    return ValidationError(str(exc))


class FrameworkService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = SqlFrameworkRepository(session)

    # --- versões -----------------------------------------------------------------------
    def listar_versoes(self) -> list[FrameworkVersao]:
        return self.repo.listar_versoes()

    def criar_versao(
        self, versao: str, descricao: str = "", data_corte: date | None = None, ativar: bool = False
    ) -> FrameworkVersao:
        versao = versao.strip()
        if not versao:
            raise ValidationError("Informe o identificador da versão.")
        if self._existe(versao):
            raise ConflictError(f"A versão {versao} já existe.")
        model = FrameworkVersao(versao=versao, descricao=descricao, data_corte=data_corte)
        self.session.add(model)
        self.session.flush()
        if ativar or self.repo.versao_ativa() is None:
            self._ativar(model)
        return model

    def clonar(self, versao_id: uuid.UUID, nova_versao: str, descricao: str | None = None) -> FrameworkVersao:
        origem = self.repo.versao_por_id(versao_id)
        nova = self.criar_versao(
            nova_versao, descricao if descricao is not None else origem.descricao, origem.data_corte
        )
        for requisito in origem.requisitos:
            clone = para_dominio(requisito, nova.versao)
            # A cópia é um novo rascunho: a aprovação vale para a versão de origem.
            clone.status_validacao = StatusValidacao.PENDENTE
            clone.comentario_validacao = None
            nova.requisitos.append(copiar_para_model(clone, RequisitoModel()))
        nova.notas = f"Clonada de {origem.versao}."
        self.session.flush()
        return nova

    def atualizar_versao(self, versao_id: uuid.UUID, dados: dict[str, Any], user_id: uuid.UUID | None) -> FrameworkVersao:
        model = self.repo.versao_por_id(versao_id)
        if "status" in dados and dados["status"] and dados["status"] != model.status:
            self._mudar_status(model, StatusVersao(dados["status"]), user_id)
        for campo in ("descricao", "notas", "data_corte"):
            if campo in dados and dados[campo] != getattr(model, campo):
                if campo != "notas":
                    self._exigir_editavel(model)
                setattr(model, campo, dados[campo])
        if dados.get("ativa") is True and not model.ativa:
            self._ativar(model)
        elif dados.get("ativa") is False and model.ativa:
            raise ConflictError("Ative outra versão em vez de desativar a atual.")
        self.session.flush()
        return model

    def excluir_versao(self, versao_id: uuid.UUID) -> None:
        model = self.repo.versao_por_id(versao_id)
        if model.status != StatusVersao.RASCUNHO:
            raise ConflictError("Apenas versões em rascunho podem ser excluídas; arquive as demais.")
        if model.ativa:
            raise ConflictError("Ative outra versão antes de excluir esta.")
        self.session.delete(model)
        self.session.flush()

    def _mudar_status(self, model: FrameworkVersao, novo: StatusVersao, user_id: uuid.UUID | None) -> None:
        atual = StatusVersao(model.status)
        if novo not in _TRANSICOES[atual]:
            raise ConflictError(f"Transição de status inválida: {atual.value} → {novo.value}.")
        if novo == StatusVersao.VALIDADO:
            pendentes = [r.codigo for r in model.requisitos if r.status_validacao != StatusValidacao.APROVADO]
            if not model.requisitos:
                raise ConflictError("A versão não tem requisitos.")
            if pendentes:
                raise ConflictError(
                    f"{len(pendentes)} requisito(s) ainda não aprovado(s): {', '.join(pendentes[:10])}."
                )
            model.validado_por = user_id
            model.validado_em = utcnow()
        if novo == StatusVersao.ARQUIVADO and model.ativa:
            raise ConflictError("Ative outra versão antes de arquivar esta.")
        model.status = novo

    def _ativar(self, model: FrameworkVersao) -> None:
        if model.status == StatusVersao.ARQUIVADO:
            raise ConflictError("Versões arquivadas não podem ser ativadas.")
        for outra in self.repo.listar_versoes():
            outra.ativa = outra.id == model.id
        self.session.flush()

    @staticmethod
    def _exigir_editavel(model: FrameworkVersao) -> None:
        if model.status in VERSOES_IMUTAVEIS:
            raise ConflictError(
                f"A versão {model.versao} está {model.status} e não pode ser alterada; clone-a para editar."
            )

    def _existe(self, versao: str) -> bool:
        return any(v.versao == versao for v in self.repo.listar_versoes())

    # --- requisitos ----------------------------------------------------------------------
    def criar_requisito(self, versao: str | None, dados: dict[str, Any]) -> Requisito:
        framework = self.repo.versao_model(versao)
        self._exigir_editavel(framework)
        try:
            requisito = requisito_de_dict(dados)
        except ValueError as exc:
            raise _invalido(exc) from None
        if any(r.codigo == requisito.codigo for r in framework.requisitos):
            raise ConflictError(f"O requisito {requisito.codigo} já existe na versão {framework.versao}.")
        if not requisito.ordem:
            requisito.ordem = max((r.ordem for r in framework.requisitos), default=0) + 1
        model = copiar_para_model(requisito, RequisitoModel())
        framework.requisitos.append(model)
        self.session.flush()
        return para_dominio(model, framework.versao)

    def atualizar_requisito(self, codigo: str, versao: str | None, dados: dict[str, Any]) -> Requisito:
        model = self.repo.requisito_model(codigo, versao)
        self._exigir_editavel(model.framework)
        atual = para_dominio(model)
        try:
            novo = requisito_de_dict({**requisito_para_dict(atual), "ordem": atual.ordem, **dados})
        except ValueError as exc:
            raise _invalido(exc) from None
        if novo.codigo != model.codigo:
            raise ValidationError("O código do requisito não pode ser alterado; crie um novo requisito.")
        conteudo_mudou = any(getattr(novo, c) != getattr(atual, c) for c in _CAMPOS_CONTEUDO if hasattr(novo, c))
        if conteudo_mudou and atual.status_validacao == StatusValidacao.APROVADO and "status_validacao" not in dados:
            novo.status_validacao = StatusValidacao.PENDENTE
        copiar_para_model(novo, model)
        self.session.flush()
        return para_dominio(model)

    def excluir_requisito(self, codigo: str, versao: str | None) -> None:
        model = self.repo.requisito_model(codigo, versao)
        self._exigir_editavel(model.framework)
        self.session.delete(model)
        self.session.flush()

    def validar_requisito(self, codigo: str, versao: str | None, status: str, comentario: str | None) -> Requisito:
        """Registro da revisão do orientador (seção 3.5, passo c)."""
        model = self.repo.requisito_model(codigo, versao)
        self._exigir_editavel(model.framework)
        try:
            StatusValidacao(status)
        except ValueError:
            raise ValidationError(f"Status de validação inválido: {status}.") from None
        if status == StatusValidacao.AJUSTAR and not (comentario or "").strip():
            raise ValidationError("Explique o ajuste necessário no comentário.")
        model.status_validacao = status
        model.comentario_validacao = (comentario or "").strip() or None
        self.session.flush()
        return para_dominio(model)

    # --- importação e exportação ---------------------------------------------------------
    def importar(
        self,
        versao: str,
        itens: list[dict[str, Any]],
        modo: str = "mesclar",
        descricao: str | None = None,
        data_corte: date | None = None,
        ativar: bool = False,
    ) -> dict[str, Any]:
        """Importa requisitos para a versão (criada se não existir).

        ``substituir`` apaga os requisitos atuais; ``mesclar`` atualiza pelo código e acrescenta os novos.
        """
        if modo not in {"mesclar", "substituir"}:
            raise ValidationError("Modo de importação inválido; use mesclar ou substituir.")
        try:
            requisitos = validar_lote(itens)
        except ValueError as exc:
            raise _invalido(exc) from None

        if self._existe(versao):
            framework = self.repo.versao_model(versao)
            self._exigir_editavel(framework)
            if descricao is not None:
                framework.descricao = descricao
            if data_corte is not None:
                framework.data_corte = data_corte
            if ativar:
                self._ativar(framework)
        else:
            framework = self.criar_versao(versao, descricao or "", data_corte, ativar)

        criados = atualizados = 0
        existentes = {r.codigo: r for r in framework.requisitos}
        if modo == "substituir":
            framework.requisitos.clear()
            self.session.flush()
            existentes = {}
        for requisito in requisitos:
            model = existentes.get(requisito.codigo)
            if model is None:
                framework.requisitos.append(copiar_para_model(requisito, RequisitoModel()))
                criados += 1
            else:
                copiar_para_model(requisito, model)
                atualizados += 1
        self.session.flush()
        return {"versao": framework.versao, "criados": criados, "atualizados": atualizados, "total": len(framework.requisitos)}

    def exportar(self, versao: str | None) -> dict[str, Any]:
        framework = self.repo.versao_model(versao)
        return {
            "versao": framework.versao,
            "descricao": framework.descricao,
            "data_corte": framework.data_corte.isoformat() if framework.data_corte else None,
            "status": framework.status,
            "requisitos": [requisito_para_dict(para_dominio(r, framework.versao)) for r in framework.requisitos],
        }

    def exportar_csv(self, versao: str | None) -> str:
        dados = self.exportar(versao)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(CAMPOS_REQUISITO), delimiter=";", lineterminator="\n")
        writer.writeheader()
        for item in dados["requisitos"]:
            writer.writerow(
                {k: " | ".join(v) if isinstance(v, list) else ("" if v is None else v) for k, v in item.items()}
            )
        # BOM para o Excel reconhecer UTF-8.
        return "﻿" + buffer.getvalue()

    @staticmethod
    def ler_csv(conteudo: bytes) -> list[dict[str, Any]]:
        texto = conteudo.decode("utf-8-sig")
        primeira = texto.splitlines()[0] if texto.strip() else ""
        delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
        faltando = {"codigo", "texto", "tipo"} - set(leitor.fieldnames or [])
        if faltando:
            raise ValidationError(f"CSV sem as colunas obrigatórias: {', '.join(sorted(faltando))}.")
        return [{k.strip(): v for k, v in linha.items() if k} for linha in leitor]

    # --- carga inicial -----------------------------------------------------------------------
    def carregar_seed(self, caminho: Path) -> dict[str, Any] | None:
        """Importa o framework inicial se ainda não houver nenhuma versão."""
        if self.repo.contar_versoes() > 0 or not caminho.is_file():
            return None
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        data_corte = date.fromisoformat(dados["data_corte"]) if dados.get("data_corte") else None
        resultado = self.importar(
            dados["versao"], dados["requisitos"], "substituir", dados.get("descricao", ""), data_corte, ativar=True
        )
        logger.info("Framework %s carregado com %s requisito(s).", resultado["versao"], resultado["total"])
        return resultado
