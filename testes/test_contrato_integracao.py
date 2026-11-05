from app.schemas import ResultadoTriagem
from testes.conftest import cliente_com, extracao

CORPO = {
    "documento_id": "DOC-CLIN-2026-9001",
    "tipo_arquivo": "TEXTO",
    "documento_texto": "LAUDO sintetico. Paciente: Fulano Sintetico de Souza, 52 anos.",
    "canal_origem": "Pronto_Socorro",
}


def test_aguardar_true_devolve_resultado_valido():
    client = cliente_com(lambda _t: extracao())
    r = client.post("/triagem?aguardar=true", json=CORPO)
    assert r.status_code == 200
    resultado = ResultadoTriagem.model_validate(r.json())
    assert resultado.documento_id == CORPO["documento_id"]


def test_sem_canal_origem_cita_o_campo():
    client = cliente_com(lambda _t: extracao())
    corpo = {k: v for k, v in CORPO.items() if k != "canal_origem"}
    r = client.post("/triagem?aguardar=true", json=corpo)
    assert r.status_code == 422
    assert "canal_origem" in r.json()["detail"]


def test_varios_campos_ausentes_citam_todos():
    client = cliente_com(lambda _t: extracao())
    r = client.post("/triagem", json={"documento_id": "DOC-CLIN-2026-9002"})
    assert r.status_code == 422
    detalhe = r.json()["detail"]
    assert "documento_texto" in detalhe and "canal_origem" in detalhe


def test_openapi_declara_versao_e_exemplos():
    client = cliente_com(lambda _t: extracao())
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == "1.0"
    assert spec["components"]["schemas"]["DocumentoEntrada"]["examples"]
