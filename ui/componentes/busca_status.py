"""H2.3.2 T5 — chame render() no topo de ui/pages/2_Triagem.py."""

import os

import requests
import streamlit as st

from ui.componentes.fila import ROTULO_STATUS

API_URL = os.getenv("API_URL", "http://localhost:8000")


def render():
    st.subheader("Acompanhar documento")
    doc_id = st.text_input("ID do documento", key="busca_status_id").strip()
    if st.button("Consultar", key="busca_status_btn") and doc_id:
        try:
            r = requests.get(f"{API_URL}/documentos/{doc_id}", timeout=5)
        except requests.RequestException:
            st.error("Não foi possível consultar agora. Tente novamente.")
            return
        if r.status_code == 404:
            st.warning("documento não encontrado")
        elif r.ok:
            status = r.json()["status"]
            st.success(f"Status: **{ROTULO_STATUS.get(status, status)}**")
        else:
            st.error("Erro ao consultar o documento.")
