import json

_ = """T4 — tela de resultado: consulta GET /documentos/{documento_id} e mostra
o tipo identificado, o score de confiança ao lado do tipo e a especialidade provável ao analista.
"""

_ = """H2.1.1 T5 — Tela de resultado: consulta GET /documentos/{documento_id} e exibe
o destino de roteamento em destaque, acima dos dados extraídos clínicos.
"""
import os
import sys
from pathlib import Path

import requests
import streamlit as st

PASTA_UI = str(Path(__file__).resolve().parents[1])
if PASTA_UI not in sys.path:
    sys.path.insert(0, PASTA_UI)


from componentes.classificacao import (  # noqa: F401
    carregar_limite_confianca,
    exibir_classificacao,
    formatar_confianca,
)
from componentes.fila import ROTULO_STATUS  # H2.3.2 T5

try:
    from componentes.paciente import bloco_paciente
except ImportError:
    bloco_paciente = None

API = os.getenv("API_URL", "http://localhost:8000")


def mostrar_medicamentos(dados, tipo_documento=None):
    """H1.3.4 T4: tabela de medicamentos e posologia."""
    itens = (dados or {}).get("medicamentos") or []
    if not itens:
        if tipo_documento == "Receituário Médico":
            st.subheader("Medicamentos")
            st.caption("Nenhum medicamento identificado nesta receita.")
        return
    st.subheader("Medicamentos")
    st.dataframe(
        [
            {
                "Medicamento": m.get("nome") or "—",
                "Dose": m.get("dose") or "—",
                "Via": m.get("via") or "—",
                "Frequência": m.get("frequencia") or "—",
                "Duração": m.get("duracao") or "—",
            }
            for m in itens
        ],
        hide_index=True,
    )
    if any(not m.get("dose") for m in itens):
        st.caption(
            "⚠ Há medicamento sem dose informada no documento (veja os pontos de atenção)."
        )


def mostrar_exames(dados):
    """H1.3.5 T5 / H2.1.2: exames e procedimentos, com o código TUSS ao lado."""
    itens = (dados or {}).get("exames") or (dados or {}).get("exames_solicitados") or []
    if not itens:
        return
    st.subheader("Exames e procedimentos")
    st.dataframe(
        [
            {"Exame": e.get("nome") or "—", "Código TUSS": e.get("codigo_tuss") or "—"}
            for e in itens
        ],
        hide_index=True,
    )


def mostrar_aviso_fora_das_categorias(cl):
    """H1.2.3 T3: avisa na tela quando o documento está fora das categorias clínicas."""
    if (cl or {}).get("tipo_documento") == "Não identificado":
        st.warning(
            "Documento fora das categorias clínicas (Não identificado): "
            "o documento foi separado para revisão humana."
        )


def mostrar_destino(decisao):
    """H2.2.1 T4: o destino em destaque e, logo abaixo, a justificativa e a regra aplicada."""
    destino = decisao.get("destino_principal", "-")
    (
        st.error
        if destino == "Fila_Emergencia_Medica"
        else st.warning
        if decisao.get("requer_auditoria_humana")
        else st.success
    )(f"**Destino: {destino}**")
    if decisao.get("justificativa_roteamento"):
        st.markdown(f"**Por quê?** {decisao['justificativa_roteamento']}")
    if decisao.get("regra_aplicada"):
        st.caption(f"Regra aplicada: {decisao['regra_aplicada']}")


def botao_download(resultado):
    """H2.3.1 T4: baixa o resultado exatamente como a API devolveu (formato combinado)."""
    nome = f"{resultado.get('documento_id') or 'resultado'}.json"
    st.download_button(
        "⬇️ Baixar resultado (JSON)",
        data=json.dumps(resultado, ensure_ascii=False, indent=2),
        file_name=nome,
        mime="application/json",
    )


st.set_page_config(page_title="MediFlow — Resultado", page_icon="🔎", layout="wide")

CAMINHO_LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.png"
if CAMINHO_LOGO.exists():
    st.logo(str(CAMINHO_LOGO), size="large")

st.markdown(
    """
<style>
    [data-testid="stLogo"] {
        height: 3.5rem !important;
    }
    [data-testid="stLogo"] img {
        height: 3.5rem !important;
        max-height: 3.5rem !important;
        width: auto !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("<div style='height: 35vh;'></div>", unsafe_allow_html=True)
    st.divider()
    st.caption("⚙️ Configurações")
    st.caption("🚪 Sair")

st.title("🔎 Resultado da triagem")

with st.form("consulta"):
    doc_id = st.text_input("ID do documento", placeholder="DOC-CLIN-2026-8942")
    buscar = st.form_submit_button("Buscar resultado")

if buscar and doc_id.strip():
    try:
        r = requests.get(f"{API}/documentos/{doc_id.strip()}", timeout=30)
    except requests.RequestException as exc:
        st.error(f"Não consegui falar com a API: {exc}")
        st.stop()

    if r.status_code == 400:
        st.error(r.json().get("detail", "documento_id inválido"))
    elif r.status_code == 404:
        st.warning("Documento não encontrado. Confere o ID.")
    elif r.status_code == 202:
        st.info(
            "Documento recebido e ainda processando. Tenta buscar de novo em instantes."
        )
    elif r.status_code != 200:
        st.error(r.json().get("detail", r.text))
    else:
        res = r.json()
        status_doc = res.get(
            "status_documento"
        )  # H2.3.2 T5: estágio do documento em destaque
        if status_doc:
            st.subheader(
                f"Status do documento: {ROTULO_STATUS.get(status_doc, status_doc)}"
            )
        st.caption(f"**Status:** {res.get('status', '-')}")
        cl = res.get("classificacao")
        if cl:
            a, b = st.columns(2)
            a.metric("Tipo do documento", cl.get("tipo_documento") or "—")
            b.metric("Especialidade provável", cl.get("especialidade") or "—")
            c, d = st.columns(2)
            c.metric("Prioridade", cl.get("nivel_prioridade") or "—")
            d.metric("Confiança", cl.get("score_confianca_classificacao", "—"))
            mostrar_aviso_fora_das_categorias(cl)
        else:
            st.warning("Sem classificação: o documento foi para revisão humana.")
        decisao = res.get("decisao_roteamento") or {}
        mostrar_destino(decisao)

        # Dados Extraídos (H1.3.1, H1.3.4, H1.3.5)
        dados = res.get("dados_extraidos") or {}
        if dados:
            st.markdown("---")
            st.markdown("### 📋 Dados Clínicos Extraídos")

            col_paciente, col_medico = st.columns(2)
            with col_paciente:
                if bloco_paciente:
                    bloco_paciente(dados)
                else:
                    st.subheader("Paciente")
                    st.json(dados.get("paciente", {}))

            with col_medico:
                st.subheader("Médico solicitante")
                med = dados.get("medico_solicitante") or {}
                st.text_input(
                    "Nome",
                    value=med.get("nome") or "—",
                    disabled=True,
                    key="medico_nome",
                )
                st.text_input(
                    "CRM", value=med.get("crm") or "—", disabled=True, key="medico_crm"
                )

            diag = dados.get("diagnostico_principal")
            cid = dados.get("cid_sugerido") or dados.get("cid")
            cid_origem = dados.get("cid_origem") or dados.get("origem_cid")
            if diag or cid:
                st.markdown(f"**Diagnóstico:** {diag or '—'}")
                st.markdown(
                    f"**CID:** {cid or '—'} ({cid_origem or 'não especificado'})"
                )

        # Medicamentos estruturados (H1.3.4 / H2.1.1)
        tipo_documento = (cl or {}).get("tipo_documento")
        mostrar_medicamentos(dados, tipo_documento)
        mostrar_exames(dados)

        # Problemas identificados / pontos de atenção
        problemas = res.get("problemas") or []
        if problemas:
            st.subheader("⚠️ Pontos de atenção")
            for p in problemas:
                st.write(f"- {p}")

        st.download_button(
            "Baixar resultado (JSON)",
            json.dumps(res, ensure_ascii=False, indent=2),
            file_name=f"{res.get('documento_id', doc_id)}.json",
            mime="application/json",
        )
