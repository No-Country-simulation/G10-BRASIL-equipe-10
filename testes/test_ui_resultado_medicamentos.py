"""H1.3.4 T4/T6 na página de resultado da equipe (consulta GET /documentos/{id})."""

from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

PAGINA = str(Path(__file__).resolve().parents[1] / "ui" / "pages" / "2_Triagem.py")


class Resp:
    def __init__(self, status, corpo):
        self.status_code, self._corpo, self.text = status, corpo, ""

    def json(self):
        return self._corpo


def resultado(tipo="Receituário Médico", **dados):
    return {
        "status": "processado",
        "documento_id": "DOC-1",
        "problemas": [],
        "classificacao": {
            "tipo_documento": tipo,
            "especialidade": "Clínica Geral",
            "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.93,
        },
        "decisao_roteamento": {
            "destino_principal": "Farmacia_Hospitalar",
            "requer_auditoria_humana": False,
            "justificativa_roteamento": "ok",
        },
        "dados_extraidos": dados,
    }


@pytest.fixture(autouse=True)
def api(monkeypatch):
    monkeypatch.delenv("API_URL", raising=False)
    reg = {"resposta": resultado()}
    monkeypatch.setattr(requests, "get", lambda url, **kw: Resp(200, reg["resposta"]))
    return reg


def buscar():
    at = AppTest.from_file(PAGINA, default_timeout=10).run()
    at.text_input[0].set_value("DOC-1")
    at.button[0].click().run()
    return at


def tabelas(at):
    return [t.value.to_dict("records") for t in at.dataframe]


def test_a_pagina_da_equipe_continua_mostrando_tipo_e_destino(api):
    at = buscar()
    assert not at.exception
    assert {m.label for m in at.metric} >= {
        "Tipo do documento",
        "Especialidade provável",
        "Prioridade",
        "Confiança",
    }
    assert any("Farmacia_Hospitalar" in s.value for s in at.success)


def test_tabela_de_medicamentos_tem_uma_linha_por_item(api):
    api["resposta"] = resultado(
        medicamentos=[
            {
                "nome": "Amoxicilina",
                "dose": "500mg",
                "via": "via oral",
                "frequencia": "8/8h",
                "duracao": "7 dias",
            },
            {"nome": "Dipirona", "dose": "1g"},
            {"nome": "Omeprazol", "dose": "20mg"},
        ]
    )
    linhas = tabelas(buscar())[0]
    assert [linha["Medicamento"] for linha in linhas] == [
        "Amoxicilina",
        "Dipirona",
        "Omeprazol",
    ]
    assert linhas[0] == {
        "Medicamento": "Amoxicilina",
        "Dose": "500mg",
        "Via": "via oral",
        "Frequência": "8/8h",
        "Duração": "7 dias",
    }
    assert linhas[1]["Via"] == "—" and linhas[1]["Duração"] == "—"


def test_medicamento_sem_dose_mostra_travessao_e_aviso(api):
    api["resposta"] = resultado(medicamentos=[{"nome": "Amoxicilina", "dose": None}])
    at = buscar()
    assert tabelas(at)[0][0]["Dose"] == "—" and any(
        "sem dose" in c.value for c in at.caption
    )


def test_receita_sem_medicamentos_avisa(api):
    at = buscar()
    assert not at.dataframe and any("Nenhum medicamento" in c.value for c in at.caption)


def test_laudo_sem_medicamentos_nao_mostra_a_secao(api):
    api["resposta"] = resultado(tipo="Laudo de Exame de Imagem")
    assert not any(s.value == "Medicamentos" for s in buscar().subheader)
