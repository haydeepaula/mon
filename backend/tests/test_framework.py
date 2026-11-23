import json
from datetime import date
from pathlib import Path

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.domain.framework import FiltroRequisitos, requisito_de_dict, validar_lote
from app.repositories.framework_repository import SqlFrameworkRepository
from app.services.framework.framework_service import FrameworkService

SEED = Path(__file__).resolve().parents[2] / "data" / "framework" / "framework-v0.1.json"


def _req(codigo="REG-01", **extra):
    return {
        "codigo": codigo,
        "fonte_documento": "Portaria MEC nº 378/2025",
        "texto": "Mínimo de 40% da carga horária presencial",
        "tipo": "legal",
        "evidencia_esperada": "Matriz curricular",
        **extra,
    }


# --- domínio --------------------------------------------------------------------------------
def test_requisito_normaliza_campos():
    req = requisito_de_dict(
        _req("reg-01", documentos_provaveis="Matriz; PPC", formatos="semipresencial", termos_chave="a, b")
    )
    assert req.codigo == "REG-01" and req.grupo == "REG"
    assert req.documentos_provaveis == ["matriz", "ppc"]
    assert req.formatos == ["semipresencial"]
    assert req.termos_chave == ["a", "b"]
    assert req.status_validacao == "pendente" and req.situacao_normativa == "vigente"


def test_peso_da_dimensao_inep_e_preenchido():
    req = requisito_de_dict(_req("INEP-D2", tipo="qualidade", dimensao_inep=2))
    assert req.peso_dimensao == 40


@pytest.mark.parametrize(
    ("extra", "mensagem"),
    [
        ({"tipo": "outro"}, "tipo inválido"),
        ({"dimensao_inep": 1}, "só se aplica"),
        ({"documentos_provaveis": ["lei"]}, "documentos_provaveis inválidos"),
        ({"formatos": ["hibrido"]}, "formatos inválidos"),
        ({"gravidade_base": 9}, "gravidade_base"),
        ({"prazo_referencia": "31/12/2027"}, "Data inválida"),
        ({"codigo": "REG01"}, "formato GRUPO-NN"),
        ({"texto": " "}, "texto"),
    ],
)
def test_requisito_invalido(extra, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        requisito_de_dict(_req(**extra))


def test_lote_rejeita_duplicados_e_reune_erros():
    with pytest.raises(ValueError) as erro:
        validar_lote([_req(), _req(), _req("EXT-01", tipo="x")])
    assert "duplicado REG-01" in str(erro.value) and "EXT-01" in str(erro.value)


def test_aplicabilidade_e_tendencia():
    semi = requisito_de_dict(_req(formatos=["semipresencial"]))
    geral = requisito_de_dict(_req("EXT-01"))
    tendencia = requisito_de_dict(_req("TEND-01", situacao_normativa="tendencia"))
    assert semi.aplica_a("semipresencial") and not semi.aplica_a("presencial") and semi.aplica_a(None)
    assert geral.aplica_a("presencial")
    assert not tendencia.aplica_a("presencial") and tendencia.aplica_a("presencial", incluir_tendencia=True)


def test_consulta_usa_padrao_ou_texto():
    assert requisito_de_dict(_req(consulta_padrao="carga presencial")).consulta() == "carga presencial"
    consulta = requisito_de_dict(_req(termos_chave=["síncrona"])).consulta()
    assert consulta.startswith("Mínimo de 40%") and "Matriz curricular" in consulta and "síncrona" in consulta


def test_seed_do_repositorio_e_valido():
    dados = json.loads(SEED.read_text(encoding="utf-8"))
    requisitos = validar_lote(dados["requisitos"])
    codigos = {r.codigo for r in requisitos}
    # Exemplos do Quadro 6 do TCC.
    assert {"REG-01", "EXT-01", "DCN-01", "INEP-D1", "INEP-D2", "I40-01"} <= codigos
    assert all(r.status_validacao == "pendente" for r in requisitos)


# --- serviço e repositório ------------------------------------------------------------------
def test_seed_cria_versao_ativa_uma_unica_vez(db_session):
    service = FrameworkService(db_session)
    assert service.carregar_seed(SEED)["versao"] == "0.1"
    assert service.carregar_seed(SEED) is None
    ativa = SqlFrameworkRepository(db_session).versao_ativa()
    assert ativa.versao == "0.1" and ativa.data_corte == date(2026, 11, 30)


def test_listar_filtra_por_formato_tipo_e_texto(db_session):
    FrameworkService(db_session).carregar_seed(SEED)
    repo = SqlFrameworkRepository(db_session)
    presencial = {r.codigo for r in repo.listar(FiltroRequisitos(formato_oferta="presencial", incluir_tendencia=False))}
    assert "REG-01" not in presencial and "EXT-01" in presencial and "TEND-01" not in presencial
    assert {r.tipo for r in repo.listar(FiltroRequisitos(tipos=["competencia"]))} == {"competencia"}
    assert [r.codigo for r in repo.listar(FiltroRequisitos(texto="tutoria"))] == ["INEP-D2"]
    assert repo.obter("reg-01").versao == "0.1"
    with pytest.raises(NotFoundError):
        repo.obter("XXX-99")


def test_crud_e_reaprovacao(db_session):
    service = FrameworkService(db_session)
    service.criar_versao("1.0")
    criado = service.criar_requisito("1.0", _req())
    assert criado.ordem == 1
    with pytest.raises(ConflictError):
        service.criar_requisito("1.0", _req())

    service.validar_requisito("REG-01", "1.0", "aprovado", None)
    # Alterar o conteúdo de um requisito aprovado exige nova aprovação.
    alterado = service.atualizar_requisito("REG-01", "1.0", {"texto": "Novo texto"})
    assert alterado.texto == "Novo texto" and alterado.status_validacao == "pendente"
    with pytest.raises(ValidationError, match="comentário"):
        service.validar_requisito("REG-01", "1.0", "ajustar", "")
    with pytest.raises(ValidationError):
        service.atualizar_requisito("REG-01", "1.0", {"tipo": "invalido"})

    service.excluir_requisito("REG-01", "1.0")
    assert SqlFrameworkRepository(db_session).listar(FiltroRequisitos(versao="1.0")) == []


def test_ciclo_de_validacao_e_imutabilidade(db_session):
    service = FrameworkService(db_session)
    service.importar("1.0", [_req(), _req("EXT-01")], ativar=True)
    versao = service.repo.versao_model("1.0")

    with pytest.raises(ConflictError, match="Transição"):
        service.atualizar_versao(versao.id, {"status": "validado"}, None)
    service.atualizar_versao(versao.id, {"status": "em_validacao"}, None)
    with pytest.raises(ConflictError, match="não aprovado"):
        service.atualizar_versao(versao.id, {"status": "validado"}, None)

    for codigo in ("REG-01", "EXT-01"):
        service.validar_requisito(codigo, "1.0", "aprovado", None)
    service.atualizar_versao(versao.id, {"status": "validado"}, None)
    assert versao.validado_em is not None

    with pytest.raises(ConflictError, match="clone-a"):
        service.atualizar_requisito("REG-01", "1.0", {"texto": "x"})
    with pytest.raises(ConflictError):
        service.importar("1.0", [_req()])

    clone = service.clonar(versao.id, "1.1")
    assert clone.status == "rascunho" and not clone.ativa
    assert {r.status_validacao for r in clone.requisitos} == {"pendente"}
    service.atualizar_versao(clone.id, {"ativa": True}, None)
    assert service.repo.versao_ativa().versao == "1.1"
    service.atualizar_versao(versao.id, {"status": "arquivado"}, None)
    with pytest.raises(ConflictError):
        service.atualizar_versao(versao.id, {"ativa": True}, None)


def test_importar_mesclar_e_substituir(db_session):
    service = FrameworkService(db_session)
    assert service.importar("1.0", [_req(), _req("EXT-01")])["criados"] == 2
    resultado = service.importar("1.0", [_req(texto="Alterado"), _req("DCN-01")], modo="mesclar")
    assert (resultado["criados"], resultado["atualizados"], resultado["total"]) == (1, 1, 3)
    resultado = service.importar("1.0", [_req("DCN-01")], modo="substituir")
    assert resultado["total"] == 1
    with pytest.raises(ValidationError, match="duplicado"):
        service.importar("1.0", [_req(), _req()])


def test_csv_ida_e_volta(db_session):
    service = FrameworkService(db_session)
    service.carregar_seed(SEED)
    csv_texto = service.exportar_csv("0.1")
    assert csv_texto.startswith("﻿codigo;grupo;")

    itens = service.ler_csv(csv_texto.encode("utf-8"))
    service.importar("0.2", itens)
    original = service.exportar("0.1")["requisitos"]
    copia = service.exportar("0.2")["requisitos"]
    assert copia == original

    with pytest.raises(ValidationError, match="colunas obrigatórias"):
        service.ler_csv("a;b\n1;2\n".encode())
