"""H1.3.5 T5 na página de resultado da equipe (consulta GET /documentos/{id})."""

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
    at = AppTest.from_file(PAGINA, default_timeout=30).run()
    at.text_input[0].set_value("DOC-1")
    at.button[0].click().run()
    return at


def tabelas(at):
    return [t.value.to_dict("records") for t in at.dataframe]


def test_lista_de_exames_mostra_o_codigo_tuss_ao_lado(api):
    api["resposta"] = resultado(
        tipo="Guia de Solicitação de Procedimento",
        exames=[
            {"nome": "Ressonancia magnetica de joelho", "codigo_tuss": "40801020"},
            {"nome": "Ultrassonografia de abdome total", "codigo_tuss": None},
        ],
    )
    assert tabelas(buscar())[0] == [
        {"Exame": "Ressonancia magnetica de joelho", "Código TUSS": "40801020"},
        {"Exame": "Ultrassonografia de abdome total", "Código TUSS": "—"},
    ]


def test_sem_exames_nao_mostra_a_secao(api):
    at = buscar()
    assert not any(s.value == "Exames e procedimentos" for s in at.subheader)


def test_medicamentos_e_exames_aparecem_juntos_sem_se_misturar(api):
    api["resposta"] = resultado(
        medicamentos=[{"nome": "Dipirona", "dose": "1g"}],
        exames=[{"nome": "Hemograma", "codigo_tuss": "40304361"}],
    )
    tabelas_ = tabelas(buscar())
    assert [list(t[0]) for t in tabelas_] == [
        ["Medicamento", "Dose", "Via", "Frequência", "Duração"],
        ["Exame", "Código TUSS"],
    ]


def test_a_pagina_da_equipe_continua_mostrando_tipo_e_destino(api):
    at = buscar()
    assert not at.exception
    assert {m.label for m in at.metric} >= {
        "Tipo do documento",
        "Especialidade provável",
    }


def test_guia_de_rotina_exibe_destino_auditoria_autorizacoes_e_dados(api):
    api["resposta"] = {
        "status": "processado",
        "documento_id": "GUIA-UI-001",
        "problemas": [],
        "classificacao": {
            "tipo_documento": "Guia de Solicitação de Procedimento",
            "especialidade": "Ortopedia",
            "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.95,
        },
        "decisao_roteamento": {
            "destino_principal": "Auditoria_Autorizacoes",
            "requer_auditoria_humana": False,
            "justificativa_roteamento": "Guia de Solicitação de Procedimento → Auditoria_Autorizacoes.",
            "regra_aplicada": "R-GUIA",
        },
        "dados_extraidos": {
            "medico_solicitante": {"nome": "Dra. Ana Torres", "crm": "100002-RJ"},
            "diagnostico_principal": "Lumbago com ciatica",
            "cid_sugerido": "M54.5",
            "cid_origem": "escrito",
            "exames_solicitados": [
                {"nome": "Ressonancia de joelho", "codigo_tuss": "40801020"}
            ],
        },
    }
    at = buscar()
    assert not at.exception
    assert any("Destino: Auditoria_Autorizacoes" in s.value for s in at.success)
    assert any(s.value == "Exames e procedimentos" for s in at.subheader)
    assert tabelas(at)[0] == [
        {"Exame": "Ressonancia de joelho", "Código TUSS": "40801020"}
    ]
