import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# enum + submodelo de classificação e destino moram em app/modelos/ (fonte única
# das categorias); são reexportados aqui para manter os imports antigos.
from .modelos import (  # noqa: F401
    Classificacao,
    DecisaoRoteamento,
    Destino,
    DestinoLiteral,
    Notificacao,
    Prioridade,
    TipoDocumento,
    TipoDocumentoLiteral,
)

# ---------- ENTRADA (H1.1.1 T1) ----------
ID_REGEX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}")
CANAL_REGEX = re.compile(r"[\w-]{1,50}")
MAX_TEXTO = (
    200_000  # caracteres: limita o tamanho do que a API aceita (proteção contra abuso)
)


def validar_id(valor: str) -> str:
    """O ID vira nome de arquivo/objeto: só letras, números, _ e -.
    Isso fecha o buraco de 'path traversal' (ex.: ../../x)."""
    valor = (valor or "").strip()
    if not ID_REGEX.fullmatch(valor):
        raise ValueError("documento_id inválido: use 3 a 64 letras, números, _ ou -")
    return valor


class DocumentoEntrada(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "documento_id": "DOC-CLIN-2026-8942",
                    "tipo_arquivo": "TEXTO",
                    "documento_texto": "LAUDO. Paciente: Fulano de Souza, 52 anos.",
                    "canal_origem": "Pronto_Socorro",
                }
            ]
        }
    )
    documento_id: str
    tipo_arquivo: str = "TEXTO"
    documento_texto: str
    canal_origem: str

    @field_validator("documento_id")
    @classmethod
    def _id(cls, v):
        return validar_id(v)

    @field_validator("documento_texto")
    @classmethod
    def _texto(cls, v):
        if not v or not v.strip():
            raise ValueError("documento vazio")
        if len(v) > MAX_TEXTO:
            raise ValueError(f"documento acima de {MAX_TEXTO} caracteres")
        return v

    @field_validator("canal_origem")
    @classmethod
    def _canal(cls, v):
        v = (v or "").strip()
        if not CANAL_REGEX.fullmatch(v):
            raise ValueError("canal_origem inválido")
        return v


class Paciente(BaseModel):
    nome: str | None = None
    idade: int | None = None
    data_nascimento: str | None = None  # preservada como está (H1.3.1)


class MedicoSolicitante(BaseModel):  # H1.3.2 T1
    nome: str | None = None
    crm: str | None = None


# Alias mantido para compatibilidade com imports existentes
Medico = MedicoSolicitante


class Medicamento(BaseModel):  # H1.3.4 T1
    nome: str
    dose: str | None = None
    via: str | None = None
    frequencia: str | None = None
    duracao: str | None = None


class Exame(BaseModel):  # H1.3.5 T1
    nome: str
    codigo_tuss: str | None = None


class Evidencia(BaseModel):  # H1.3.6 T1
    campo: str
    trecho: str


class Extracao(BaseModel):
    tipo_documento: TipoDocumentoLiteral
    especialidade: str | None = None
    nivel_prioridade: Prioridade
    score_confianca_classificacao: float = Field(ge=0, le=1)
    paciente: Paciente = Field(default_factory=Paciente)
    medico_solicitante: MedicoSolicitante = Field(default_factory=MedicoSolicitante)
    diagnostico_principal: str | None = None
    cid_sugerido: str | None = None
    cid: str | None = None  # alias mantido para compatibilidade (H2.1.2 T2)
    origem_cid: Literal["escrito", "sugerido"] | None = None  # H1.3.3 T1
    cid_origem: str | None = None  # alias mantido para compatibilidade
    medicamentos: list[Medicamento] = Field(default_factory=list)
    exames: list[Exame] = Field(default_factory=list)
    exames_solicitados: list[Exame] = Field(default_factory=list)  # alias H2.1.2 T2
    evidencias: list[Evidencia] = Field(default_factory=list)
    inconsistencias: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sincronizar_campos(self):
        # Sincroniza CID
        if self.cid is None and self.cid_sugerido is not None:
            self.cid = self.cid_sugerido
        elif self.cid_sugerido is None and self.cid is not None:
            self.cid_sugerido = self.cid

        # Sincroniza exames e exames_solicitados
        if not self.exames and self.exames_solicitados:
            self.exames = list(self.exames_solicitados)
        elif not self.exames_solicitados and self.exames:
            self.exames_solicitados = list(self.exames)

        # Sincroniza origem do CID
        if self.origem_cid is None and self.cid_origem in ("escrito", "sugerido"):
            self.origem_cid = self.cid_origem
        elif self.origem_cid is None and self.cid_origem == "documento":
            self.origem_cid = "escrito"
        if self.cid_origem is None and self.origem_cid is not None:
            self.cid_origem = self.origem_cid
        return self


# ---------- RESULTADO (H2.3.1 T1) — o contrato combinado com o edital ----------
# Classificacao (tipada com o enum) é definida em app/modelos/classificacao.py
# e reexportada no topo deste arquivo.


class ArmazenamentoOCI(BaseModel):  # H5.1.2 T1
    bucket: str
    caminho_objeto: str
    status_backup: str
    local: str
    urgente: bool


class ResultadoTriagem(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "processado",
                    "documento_id": "DOC-CLIN-2026-8942",
                    "classificacao": {
                        "tipo_documento": "Laudo de Exame de Imagem",
                        "especialidade": "Clínica Geral",
                        "nivel_prioridade": "Rotina",
                        "score_confianca_classificacao": 0.93,
                    },
                    "dados_extraidos": {
                        "paciente": {"nome": "Fulano de Souza", "idade": 52}
                    },
                    "problemas": [],
                    "decisao_roteamento": {
                        "destino_principal": "Prontuario_Eletronico",
                        "requer_auditoria_humana": False,
                        "justificativa_roteamento": "Laudo de rotina.",
                        "regra_aplicada": "R-LAUDO",
                        "notificacao_gerada": None,
                    },
                    "armazenamento_oci": None,
                }
            ]
        }
    )
    status: str
    documento_id: str
    classificacao: Classificacao | None = None
    dados_extraidos: dict | None = None
    problemas: list[str] = Field(default_factory=list)
    decisao_roteamento: DecisaoRoteamento
    armazenamento_oci: ArmazenamentoOCI | None = None


class Legibilidade(BaseModel):  # H1.1.3 T3
    legivel: bool
    motivo: str | None = None


class LeituraImagem(BaseModel):
    texto: str
    legibilidade: Legibilidade
