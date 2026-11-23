"""Adaptador SQL da porta FrameworkRepository e acesso às tabelas do framework."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import FrameworkVersao, RequisitoModel
from app.domain.framework import FiltroRequisitos, Requisito, VersaoInfo
from app.domain.ports import FrameworkRepository

# Campos copiados um a um entre a entidade de domínio e o modelo ORM.
_CAMPOS = (
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
    "aplicabilidade",
    "situacao_normativa",
    "prazo_referencia",
    "status_validacao",
    "comentario_validacao",
    "ordem",
)


def para_dominio(model: RequisitoModel, versao: str | None = None) -> Requisito:
    dados = {campo: getattr(model, campo) for campo in _CAMPOS}
    dados["documentos_provaveis"] = list(dados["documentos_provaveis"] or [])
    dados["termos_chave"] = list(dados["termos_chave"] or [])
    dados["aplicabilidade"] = dict(dados["aplicabilidade"] or {})
    return Requisito(**dados, versao=versao or (model.framework.versao if model.framework else None))


def copiar_para_model(requisito: Requisito, model: RequisitoModel) -> RequisitoModel:
    for campo in _CAMPOS:
        setattr(model, campo, getattr(requisito, campo))
    return model


class SqlFrameworkRepository(FrameworkRepository):
    def __init__(self, session: Session):
        self.session = session

    # --- versões -----------------------------------------------------------------
    def listar_versoes(self) -> list[FrameworkVersao]:
        return list(self.session.scalars(select(FrameworkVersao).order_by(FrameworkVersao.created_at.desc())))

    def versao_model(self, versao: str | None = None) -> FrameworkVersao:
        """Versão pelo nome; sem nome, a versão ativa."""
        if versao:
            model = self.session.scalar(select(FrameworkVersao).where(FrameworkVersao.versao == versao))
            if model is None:
                raise NotFoundError(f"Versão do framework não encontrada: {versao}.")
            return model
        model = self.session.scalar(select(FrameworkVersao).where(FrameworkVersao.ativa.is_(True)))
        if model is None:
            raise NotFoundError("Nenhuma versão do framework está ativa.")
        return model

    def versao_por_id(self, versao_id) -> FrameworkVersao:
        model = self.session.get(FrameworkVersao, versao_id)
        if model is None:
            raise NotFoundError("Versão do framework não encontrada.")
        return model

    def versao_ativa(self) -> VersaoInfo | None:
        model = self.session.scalar(select(FrameworkVersao).where(FrameworkVersao.ativa.is_(True)))
        if model is None:
            return None
        return VersaoInfo(model.versao, model.status, model.ativa, model.data_corte)

    def contar_versoes(self) -> int:
        return len(self.session.scalars(select(FrameworkVersao.id)).all())

    # --- requisitos ----------------------------------------------------------------
    def requisito_model(self, codigo: str, versao: str | None = None) -> RequisitoModel:
        framework = self.versao_model(versao)
        model = self.session.scalar(
            select(RequisitoModel).where(
                RequisitoModel.framework_id == framework.id, RequisitoModel.codigo == codigo.upper()
            )
        )
        if model is None:
            raise NotFoundError(f"Requisito {codigo} não encontrado na versão {framework.versao}.")
        return model

    def obter(self, codigo: str, versao: str | None = None) -> Requisito:
        model = self.requisito_model(codigo, versao)
        return para_dominio(model, model.framework.versao)

    def listar(self, filtros: FiltroRequisitos | None = None) -> list[Requisito]:
        filtros = filtros or FiltroRequisitos()
        framework = self.versao_model(filtros.versao)
        stmt = select(RequisitoModel).where(RequisitoModel.framework_id == framework.id)
        if filtros.tipos:
            stmt = stmt.where(RequisitoModel.tipo.in_(filtros.tipos))
        if filtros.grupos:
            stmt = stmt.where(RequisitoModel.grupo.in_([g.upper() for g in filtros.grupos]))
        if filtros.dimensao_inep is not None:
            stmt = stmt.where(RequisitoModel.dimensao_inep == filtros.dimensao_inep)
        if filtros.status_validacao:
            stmt = stmt.where(RequisitoModel.status_validacao == filtros.status_validacao)
        if filtros.texto:
            termo = f"%{filtros.texto}%"
            stmt = stmt.where(
                or_(
                    RequisitoModel.codigo.ilike(termo),
                    RequisitoModel.texto.ilike(termo),
                    RequisitoModel.fonte_documento.ilike(termo),
                )
            )
        stmt = stmt.order_by(RequisitoModel.ordem, RequisitoModel.codigo)
        requisitos = [para_dominio(m, framework.versao) for m in self.session.scalars(stmt)]
        # Aplicabilidade fica em JSON; o filtro é feito na aplicação (volume pequeno).
        return [r for r in requisitos if r.aplica_a(filtros.formato_oferta, filtros.incluir_tendencia)]
