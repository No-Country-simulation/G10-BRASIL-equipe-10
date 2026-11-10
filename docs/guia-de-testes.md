# 🧪 Guia de Testes — H1.2.2, H1.3.2 e H1.3.3

Este guia descreve passo a passo como testar e validar as três histórias implementadas no **MediFlow**:
- **H1.2.2** — Ver a confiança da classificação ([ui/componentes/classificacao.py](../ui/componentes/classificacao.py), [app/grafo.py](../app/grafo.py), [app/config.py](../app/config.py))
- **H1.3.2** — Ver o profissional e o CRM ([ui/componentes/medico.py](../ui/componentes/medico.py), [app/validacao.py](../app/validacao.py), [app/schemas.py](../app/schemas.py))
- **H1.3.3** — Ver diagnóstico e CID-10 ([ui/componentes/diagnostico.py](../ui/componentes/diagnostico.py), [config/cid10.csv](../config/cid10.csv), [app/validacao.py](../app/validacao.py))

---

## 1. Testar via Testes Automatizados (`pytest`)

Os testes utilizam dublês (`FakeLLM` e diretório temporário isolado em [testes/conftest.py](../testes/conftest.py)), portanto **não exigem chave `GEMINI_API_KEY` nem conta ativa na OCI**.

### No ambiente virtual local (`.venv`)

```bash
# Rodar todas as 3 histórias (49 testes)
.venv/bin/pytest -v

# Rodar apenas H1.2.2 — Confiança da classificação (13 testes)
.venv/bin/pytest -v testes/test_confianca.py

# Rodar apenas H1.3.2 — Médico solicitante e CRM (26 testes)
.venv/bin/pytest -v testes/test_medico.py

# Rodar apenas H1.3.3 — Diagnóstico e CID-10 (10 testes)
.venv/bin/pytest -v testes/test_diagnostico.py
```

### Dentro do container Podman/Docker

```bash
# Com o container mediflow-api já em execução:
podman exec mediflow-api python3 -m pytest -v

# Ou executando um container efémero a partir da imagem:
podman run --rm --entrypoint python3 mediflow-agent:dev -m pytest -v
```

---

## 2. Subir o Projeto nos Containers (API + Interface)

Caso os containers ainda não estejam a correr, execute na raiz do projeto:

```bash
# 1. Construir a imagem
podman build --build-arg PYTHON_VERSION=3.13 -t mediflow-agent:dev .

# 2. Subir a API FastAPI na porta 8000
podman run -d --replace --name mediflow-api --network host mediflow-agent:dev

# 3. Subir a interface Streamlit na porta 8501
podman run -d --replace --name mediflow-ui --network host \
  -e API_URL=http://localhost:8000 \
  --entrypoint streamlit mediflow-agent:dev \
  run ui/Home.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

Verifique se estão ativos:

```bash
curl -s http://localhost:8000/health
# Resposta esperada: {"status":"ok"}
```

---

## 3. Popular Cenários de Demonstração (Sem precisar de `GEMINI_API_KEY`)

Para testar visualmente no navegador todos os critérios de aceite sem gastar cota do Gemini, execute o comando abaixo para gravar **4 documentos sintéticos de teste** dentro do container `mediflow-api`:

```bash
podman exec mediflow-api python3 -c "
from app.servico import processar
from app.schemas import MedicoSolicitante
from testes.conftest import FakeLLM, LAUDO_TEP

# 1) Score alto (0.95) + CRM-SP 145892 -> 145892-SP + CID I26.9 (sugerido)
processar('DOC-DEMO-095', LAUDO_TEP, None, FakeLLM(score=0.95))

# 2) Score baixo (0.60) -> alerta abaixo do limite + revisão humana
processar('DOC-DEMO-060', LAUDO_TEP, None, FakeLLM(score=0.60, nivel_prioridade='Rotina'))

# 3) CID escrito no texto -> I26.9 com origem 'escrito' (sem etiqueta sugerido)
processar('DOC-CID-ESCRITO', LAUDO_TEP + ' CID-10: I26.9.', None, FakeLLM(score=0.95))

# 4) CRM inválido (CRM-XX 145892) -> inconsistente + revisão humana
processar('DOC-CRM-INVALIDO', LAUDO_TEP, None, FakeLLM(
    score=0.95,
    medico_solicitante=MedicoSolicitante(nome='Dra. Renata Silveira', crm='CRM-XX 145892')
))
"
```

---

## 4. Testar na Interface Visual (`http://localhost:8501`)

1. Abra **`http://localhost:8501`** no navegador.
2. No menu lateral esquerdo, clique em **Resultado** ([ui/pages/2_Triagem.py](../ui/pages/2_Triagem.py)).
3. Pesquise cada um dos IDs abaixo e confira os critérios de aceite na tela:

| ID do Documento | História Testada | Resultado Esperado na Tela |
| :--- | :--- | :--- |
| **`DOC-DEMO-095`** | **H1.2.2, H1.3.2 e H1.3.3** | • **Confiança:** `0.95` ao lado de `Laudo de Exame de Imagem` (sem alerta).<br>• **Médico solicitante:** Nome `Dra. Renata Silveira` e CRM **`145892-SP`**.<br>• **Diagnóstico e CID-10:** `Tromboembolismo Pulmonar Agudo (TEP)` e **`I26.9 (sugerido)`**.<br>• **Destino:** `Fila_Emergencia_Medica`. |
| **`DOC-DEMO-060`** | **H1.2.2** (Critério 2) | • **Confiança:** **`⚠️ 0.60 (abaixo do limite)`** ao lado do tipo.<br>• Banner amarelo de aviso de retenção.<br>• **Destino:** `Fila_Revisao_Humana` com justificativa contendo *"baixa confiança na classificação"*. |
| **`DOC-CID-ESCRITO`** | **H1.3.3** (Critério 2 / T6) | • **Diagnóstico e CID-10:** O campo CID-10 mostra apenas **`I26.9`** (sem `(sugerido)`), pois o código `I26.9` constava no texto do documento. |
| **`DOC-CRM-INVALIDO`** | **H1.3.2** (Critério 2) | • **Médico solicitante:** Nome `Dra. Renata Silveira` e CRM **`—`** (descartado).<br>• **Destino:** `Fila_Revisao_Humana`.<br>• **Pontos de atenção:** `"CRM em formato inválido: 'CRM-XX 145892'"`. |

---

## 5. Testar via API REST (`curl` ou Swagger)

Pode consultar a documentação interativa em **`http://localhost:8000/docs`** ou executar no terminal:

```bash
# 1. Caso aprovado com alta confiança (0.95), CRM "145892-SP" e CID "sugerido"
curl -s http://localhost:8000/documentos/DOC-DEMO-095 | python3 -m json.tool

# 2. Caso retido por baixa confiança (0.60 < 0.80)
curl -s http://localhost:8000/documentos/DOC-DEMO-060 | python3 -m json.tool

# 3. Caso com CID escrito no documento (origem_cid = "escrito")
curl -s http://localhost:8000/documentos/DOC-CID-ESCRITO | python3 -m json.tool

# 4. Caso retido por CRM inválido ("CRM-XX 145892")
curl -s http://localhost:8000/documentos/DOC-CRM-INVALIDO | python3 -m json.tool
```
