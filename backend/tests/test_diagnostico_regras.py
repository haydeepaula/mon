import pytest

from app.domain.concordancia import (
    interpretar_kappa,
    kappa_cohen,
    kappa_ponderado,
    matriz_confusao,
    percentual_acordo,
    resumo_concordancia,
)
from app.domain.diagnostico import causa_obrigatoria, proposta_sem_evidencia, validar_proposta


def _bruta(**extra):
    return {"classificacao": "C", "conceito_inep": None, "justificativa": "Atende [1].", "citacoes": [1],
            "lacunas": [], **extra}


# --- pós-validação da proposta ----------------------------------------------------------------
def test_proposta_valida_e_normalizada():
    proposta = validar_proposta(_bruta(classificacao="pc", citacoes=[2, 1, 2], lacunas=[" ata ", ""]), 3, "legal")
    assert proposta.classificacao == "PC" and proposta.citacoes == [2, 1]
    assert proposta.lacunas == ["ata"] and proposta.alertas == []


def test_classificacao_sem_citacao_valida_vira_ei():
    proposta = validar_proposta(_bruta(classificacao="NC", citacoes=[7]), 3, "legal")
    assert proposta.classificacao == "EI" and proposta.classificacao_original == "NC"
    assert set(proposta.alertas) == {"citacao_invalida", "sem_citacao"}


def test_ei_sem_citacao_e_aceito():
    proposta = validar_proposta(_bruta(classificacao="EI", citacoes=[]), 3, "legal")
    assert proposta.classificacao == "EI" and proposta.alertas == []


def test_conceito_so_para_qualidade():
    assert validar_proposta(_bruta(conceito_inep=4), 1, "legal").conceito_inep is None
    assert "conceito_descartado" in validar_proposta(_bruta(conceito_inep=4), 1, "legal").alertas
    assert validar_proposta(_bruta(conceito_inep=4), 1, "qualidade").conceito_inep == 4
    assert validar_proposta(_bruta(conceito_inep=9), 1, "qualidade").conceito_inep is None
    assert "conceito_ausente" in validar_proposta(_bruta(), 1, "qualidade").alertas


@pytest.mark.parametrize(
    "bruta",
    [_bruta(classificacao="X"), _bruta(justificativa=" "), _bruta(citacoes="1"), "texto"],
)
def test_proposta_invalida(bruta):
    with pytest.raises(ValueError):
        validar_proposta(bruta, 2, "legal")


def test_sem_evidencia_e_causa():
    proposta = proposta_sem_evidencia("Matriz curricular")
    assert proposta.classificacao == "EI" and proposta.lacunas == ["Matriz curricular"]
    assert proposta.alertas == ["sem_evidencia"]
    assert causa_obrigatoria("C", "NC") and not causa_obrigatoria("C", "C") and not causa_obrigatoria(None, "C")


# --- concordância ---------------------------------------------------------------------------------
def test_kappa_exemplo_classico():
    proposta = ["C"] * 5 + ["NC"] * 5
    final = ["C"] * 4 + ["NC"] * 5 + ["C"]
    pares = list(zip(proposta, final))
    assert percentual_acordo(pares) == pytest.approx(0.8)
    assert kappa_cohen(pares) == pytest.approx(0.6)
    assert interpretar_kappa(0.6) == "moderada"


def test_kappa_casos_limite():
    assert kappa_cohen([]) is None and percentual_acordo([]) is None
    assert kappa_cohen([("EI", "EI")] * 3) == 1.0  # pₑ = 1
    assert kappa_cohen([("C", "NC"), ("NC", "C")]) == pytest.approx(-1.0)
    assert interpretar_kappa(-0.1) == "pobre" and interpretar_kappa(0.95) == "quase perfeita"


def test_kappa_ponderado():
    assert kappa_ponderado([(3, 3), (4, 4), (5, 5)]) == pytest.approx(1.0)
    perto = kappa_ponderado([(3, 4), (4, 5), (5, 4), (2, 2)])
    longe = kappa_ponderado([(1, 5), (5, 1), (2, 4), (4, 2)])
    assert perto > longe
    assert kappa_ponderado([]) is None


def test_matriz_e_resumo():
    matriz = matriz_confusao([("C", "C"), ("C", "PC"), ("EI", "NC")])
    assert matriz["C"]["PC"] == 1 and matriz["EI"]["NC"] == 1 and matriz["NC"]["NC"] == 0
    resumo = resumo_concordancia([
        {"proposta": "C", "final": "C", "tipo": "legal"},
        {"proposta": "C", "final": "PC", "tipo": "legal", "causa": "geracao"},
        {"proposta": "EI", "final": None, "tipo": "competencia"},
        {"proposta": None, "final": "NC", "tipo": "legal"},  # proposta com erro: fora do kappa
    ])
    assert resumo["n_pares"] == 2 and resumo["n_validados"] == 3
    assert resumo["percentual_acordo"] == 0.5
    assert resumo["divergencias_por_causa"] == {"geracao": 1}
    assert resumo["por_tipo"]["legal"] == {"n": 2, "percentual_acordo": 0.5}
