"""H1.3.1 T3 — Bloco "Paciente" da tela de resultado.

Fica num arquivo próprio (e não dentro de ui/pages/2_Triagem.py) para não gerar
conflito com quem cria a página de resultado (H1.2.1 T4). A página só precisa de:

    from componentes.paciente import bloco_paciente
    ...
    bloco_paciente(resultado.get("dados_extraidos"))

Os valores vêm de documentos clínicos, então são exibidos como texto puro (campo
desabilitado), nunca como Markdown/HTML.
"""

import streamlit as st

AUSENTE = "—"


def resumo_paciente(paciente: dict | None) -> dict[str, str]:
    """Nome, idade e data de nacimento prontos para exibir("-" quando não há)."""
    p = paciente or {}
    idade = p.get("idade")
    return {
        "Nome": p.get("nome") or AUSENTE,
        "Idade": f"{idade} anos" if idade is not None else AUSENTE,
        "Data de nascimento": p.get("data_nascimento") or AUSENTE,
    }


def bloco_paciente(dados_extraidos: dict | None) -> None:
    st.subheader("Paciente")
    resumo = resumo_paciente((dados_extraidos or {}).get("paciente"))
    for rotulo, valor in resumo.items():
        st.text_input(rotulo, value=valor, disabled=True, key=f"paciente_{rotulo}")
