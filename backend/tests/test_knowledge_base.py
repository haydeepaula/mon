import pytest

from app.domain.knowledge_base import Classificacao, classificar_por_caminho, validar_classificacao


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("normativa/portaria/378-2025.pdf", Classificacao("normativa", "portaria")),
        ("institucional/ppc/ppc-2024.pdf", Classificacao("institucional", "ppc")),
        ("Institucional/PPC/ppc.pdf", Classificacao("institucional", "ppc")),
        ("institucional/ppc.pdf", Classificacao("institucional", None)),
        ("institucional/desconhecido/a.pdf", Classificacao("institucional", None)),
        ("normativa/ppc/a.pdf", Classificacao("normativa", None)),  # ppc não é tipo normativo
        ("institucional/atas/2024/ata.pdf", Classificacao("institucional", None)),
        ("institucional/ata/2024/ata.pdf", Classificacao("institucional", "ata")),
    ],
)
def test_classificar_por_caminho(path, expected):
    assert classificar_por_caminho(path) == expected


@pytest.mark.parametrize("path", ["arquivo.pdf", "outra/pasta/a.pdf", "relatorios/cpa.pdf"])
def test_caminho_fora_das_colecoes_mantem_classificacao(path):
    assert classificar_por_caminho(path) is None


def test_validar_classificacao():
    assert validar_classificacao("normativa", "resolucao") == Classificacao("normativa", "resolucao")
    assert validar_classificacao("institucional", None) == Classificacao("institucional", None)
    with pytest.raises(ValueError, match="Coleção inválida"):
        validar_classificacao("outra", None)
    with pytest.raises(ValueError, match="Tipo de documento inválido"):
        validar_classificacao("normativa", "ppc")


def test_build_filter():
    qdrant = pytest.importorskip("qdrant_client")
    from app.infrastructure.vectorstore.qdrant_store import build_filter

    models = qdrant.models
    assert build_filter(None) is None
    assert build_filter({"curso": None, "tipo_documento": []}) is None

    result = build_filter({"colecao": "institucional", "tipo_documento": ["ppc", "matriz"], "curso": None})
    assert result.must == [
        models.FieldCondition(key="colecao", match=models.MatchValue(value="institucional")),
        models.FieldCondition(key="tipo_documento", match=models.MatchAny(any=["ppc", "matriz"])),
    ]
