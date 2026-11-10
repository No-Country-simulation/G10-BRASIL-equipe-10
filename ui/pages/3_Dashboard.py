from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="MediFlow HealthTech",
    page_icon="🩺",
    layout="wide",
)

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

CAMINHO_LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.png"

if CAMINHO_LOGO.exists():
    st.logo(str(CAMINHO_LOGO), size="large")

with st.sidebar:
    st.markdown("<div style='height: 35vh;'></div>", unsafe_allow_html=True)
    st.divider()
    st.caption("⚙️ Configurações")
    st.caption("🚪 Sair")

st.title("Painel de Triagem")
st.write("2 colunas com o laudo, o raio-X e os cards clínicos")
