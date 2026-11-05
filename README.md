# MediFlow 🏥
### Agente Inteligente para Triagem, Extração e Roteamento de Documentos

![Status](https://img.shields.io/badge/status-em%20desenvolvimento-orange)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Oracle Cloud](https://img.shields.io/badge/Cloud-Oracle%20Cloud%20Infrastructure-F80000?logo=oracle&logoColor=white)

**MediFlow** é um projeto de automação inteligente para o processamento de documentos clínicos e administrativos. A solução propõe utilizar Inteligência Artificial, agentes autônomos e fluxos de decisão para classificar documentos, extrair informações relevantes, identificar inconsistências e direcionar cada solicitação ao fluxo adequado.

Desenvolvido no contexto de um hackathon da **Alura + Oracle Next Education (ONE)**, o projeto tem como objetivo explorar a aplicação prática de agentes de IA em processos que exigem organização, rastreabilidade e supervisão humana.

> **Status do projeto:** fase inicial de desenvolvimento e definição da arquitetura.

---

## 🎯 1. Problema e motivação

O processamento de documentos clínicos e administrativos pode envolver tarefas repetitivas, como leitura, classificação, extração de dados, conferência de informações e encaminhamento para diferentes setores.

Quando essas atividades dependem exclusivamente de processos manuais, podem surgir gargalos operacionais, retrabalho e dificuldades de rastreabilidade.

O MediFlow propõe automatizar parte desse processo por meio de um agente de IA capaz de analisar documentos, estruturar informações e recomendar encaminhamentos, mantendo a revisão humana nos casos ambíguos, inconsistentes ou que exijam avaliação especializada.

## 💡 2. Objetivos do projeto

- Automatizar a triagem inicial de documentos clínicos e administrativos.
- Classificar documentos conforme sua categoria.
- Extrair informações relevantes e organizá-las em estruturas padronizadas.
- Validar campos obrigatórios e identificar possíveis inconsistências.
- Aplicar regras de decisão para definir o encaminhamento adequado.
- Direcionar casos ambíguos ou inconsistentes para revisão humana.
- Registrar o histórico de processamento e das decisões tomadas.
- Utilizar a Oracle Cloud Infrastructure (OCI) para armazenamento de documentos.

## ⚙️ 3. Funcionalidades previstas

| Funcionalidade | Descrição |
|---|---|
| Recepção de documentos | Entrada de arquivos PDF, imagens e textos. |
| Classificação inteligente | Identificação da categoria documental. |
| Extração de informações | Estruturação dos dados identificados no documento. |
| Validação de dados | Verificação de campos obrigatórios, formatos e inconsistências. |
| Motor de decisão | Aplicação de regras para determinar o próximo fluxo. |
| Roteamento inteligente | Direcionamento conforme a categoria e as regras definidas. |
| Revisão humana | Encaminhamento de casos ambíguos ou que necessitem de conferência. |
| Histórico de processamento | Registro dos estados e resultados da triagem. |
| Armazenamento em nuvem | Persistência dos documentos no OCI Object Storage. |

### Categorias de documentos consideradas

- Prescrições médicas.
- Resultados de exames laboratoriais e de imagem.
- Solicitações de autorização.
- Relatórios de alta.
- Atestados e outros documentos clínicos ou administrativos.

A classificação definitiva, as regras de encaminhamento e os campos extraídos serão refinados durante a implementação.

## 🧠 4. Arquitetura proposta

A arquitetura será modular, separando interface, API, processamento inteligente, persistência e infraestrutura.

```text
                    ┌─────────────────────┐
                    │       Frontend      │
                    │   React + TypeScript│
                    └──────────┬──────────┘
                               │ HTTPS / REST
                    ┌──────────▼──────────┐
                    │       Backend       │
                    │   Python + FastAPI  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │    Orquestrador IA  │
                    │      LangGraph      │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
       ┌──────▼─────┐  ┌───────▼──────┐  ┌─────▼────────┐
       │ Classificar│  │ Extrair dados│  │ Validar e    │
       │ documento  │  │ estruturados │  │ decidir      │
       └────────────┘  └──────────────┘  └─────┬────────┘
                                               │
                                    ┌──────────▼─────────┐
                                    │ Fluxo condicional  │
                                    └──────────┬─────────┘
                                               │
                             ┌─────────────────┼──────────────┐
                             │                 │              │
                      ┌──────▼─────┐   ┌───────▼──────┐ ┌─────▼─────┐
                      │ Processar  │   │ Priorizar    │ │ Revisão   │
                      │ normalmente│   │ atendimento  │ │ humana    │
                      └────────────┘   └──────────────┘ └───────────┘

                  Persistência e infraestrutura
                  ┌─────────────────────────────┐
                  │ PostgreSQL + OCI Object     │
                  │ Storage                     │
                  └─────────────────────────────┘
```

O diagrama representa a arquitetura planejada. Os componentes serão implementados e integrados progressivamente.

## 🛠️ 5. Tecnologias previstas

| Camada | Tecnologia | Responsabilidade |
|---|---|---|
| Frontend | React + TypeScript + Vite | Interface de triagem e auditoria. |
| Backend | Python + FastAPI | API REST e regras de negócio. |
| Orquestração | LangGraph | Coordenação dos nós e decisões do agente. |
| Inteligência Artificial | LLM multimodal ou modelo compatível | Classificação e extração de informações. |
| Validação | Pydantic | Validação e estruturação dos dados. |
| OCR | Ferramenta compatível com Python | Extração de texto de documentos digitalizados. |
| Banco de dados | PostgreSQL | Metadados, resultados, estados e histórico. |
| Armazenamento | OCI Object Storage | Documentos originais e arquivos processados. |
| Infraestrutura | Oracle Cloud Infrastructure | Serviços de nuvem e armazenamento. |
| Testes | pytest e ferramentas de teste do frontend | Validação do comportamento da aplicação. |

A escolha definitiva do provedor de LLM e da ferramenta de OCR dependerá dos requisitos técnicos, da disponibilidade e dos limites de custo do projeto.

## 🔄 6. Fluxo de processamento

1. **Recepção:** o usuário envia um documento pela interface ou API.
2. **Armazenamento inicial:** o arquivo é registrado e armazenado de forma privada.
3. **Preparação:** o sistema extrai o texto, utilizando OCR quando necessário.
4. **Classificação:** o agente identifica a categoria do documento.
5. **Extração:** as informações relevantes são organizadas em um formato estruturado.
6. **Validação:** o sistema verifica o formato, os campos obrigatórios e as inconsistências detectáveis.
7. **Decisão:** o fluxo condicional aplica as regras de encaminhamento.
8. **Encaminhamento:** o documento segue para o fluxo correspondente ou para revisão humana.
9. **Persistência:** o resultado e o histórico são registrados para consulta e auditoria.

**Importante:** a IA auxilia na triagem e na organização das informações. Ela não substitui a avaliação de profissionais de saúde nem deve decidir autonomamente sobre diagnósticos ou condutas clínicas.

## 📦 7. Estrutura inicial do repositório

```text
mediflow/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   ├── hooks/
│   │   └── types/
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── main.py
│   └── requirements.txt
│
├── ia/
│   ├── nodes/
│   ├── prompts/
│   ├── schemas.py
│   ├── state.py
│   └── graph.py
│
├── infra/
│   └── docker-compose.yml
│
├── tests/
├── .env.example
├── .gitignore
└── README.md
```

A estrutura será ajustada conforme os componentes forem implementados.

## ☁️ 8. Estratégia de infraestrutura na OCI

O projeto será desenvolvido inicialmente no ambiente local, utilizando o VS Code. A integração com a nuvem ocorrerá de forma gradual.

### OCI Object Storage

Responsável pelo armazenamento dos documentos originais e dos resultados estruturados.

Organização lógica sugerida:

```text
mediflow-documentos/
├── recebidos/
├── processados/
├── auditoria-humana/
└── erros/
```

Os nomes acima representam prefixos de objetos no bucket, não diretórios físicos.

### PostgreSQL

Responsável pelos dados operacionais da aplicação, incluindo:

- Identificadores dos documentos.
- Categoria e estado do processamento.
- Referências aos objetos armazenados.
- Resultados estruturados da triagem.
- Histórico de revisões e decisões.

A forma de hospedagem será definida após a verificação dos recursos disponíveis no Always Free da OCI.

### Estratégia de custos

- Priorizar recursos elegíveis ao OCI Always Free.
- Desenvolver e testar localmente antes da publicação.
- Evitar recursos de infraestrutura desnecessários.
- Monitorar os limites de armazenamento, processamento e requisições.
- Avaliar separadamente os custos e as cotas do provedor de IA.

A utilização do Always Free não garante que todos os serviços, modelos ou configurações sejam gratuitos.

## 🔌 9. API REST planejada

Os seguintes endpoints são propostas iniciais e ainda precisam ser implementados.

| Método | Endpoint | Objetivo |
|---|---|---|
| `POST` | `/api/v1/documents` | Receber um documento. |
| `GET` | `/api/v1/documents` | Listar documentos. |
| `GET` | `/api/v1/documents/{id}` | Consultar um documento e seu resultado. |
| `GET` | `/api/v1/documents/{id}/status` | Consultar o estado do processamento. |
| `GET` | `/api/v1/audits/pending` | Listar casos pendentes de revisão. |
| `POST` | `/api/v1/audits/{id}/decision` | Registrar uma decisão de auditoria. |
| `GET` | `/api/v1/dashboard` | Consultar indicadores operacionais. |

## 🧾 10. Exemplo de saída estruturada

O agente deverá produzir resultados em JSON, validados antes de serem persistidos.

```json
{
  "document_id": "DOC-001",
  "status": "pending_review",
  "classification": {
    "document_type": "solicitacao_autorizacao",
    "confidence": 0.91
  },
  "extracted_data": {
    "patient_reference": null,
    "professional_registration": null,
    "diagnosis_code": null
  },
  "routing": {
    "destination": "auditoria",
    "requires_human_review": true,
    "reason": "Validacao humana pendente"
  }
}
```

Este exemplo é ilustrativo. Os campos, estados, categorias e critérios de validação serão definidos durante a implementação. A confiança retornada pelo modelo não representa, por si só, uma medida clínica validada.

## Integração via API

Envie um documento de texto e aguarde o resultado:

```bash
curl -X POST "http://localhost:8000/triagem?aguardar=true" \
  -H "Content-Type: application/json" \
  -d '{
    "documento_id": "DOC-CLIN-2026-8942",
    "tipo_arquivo": "TEXTO",
    "documento_texto": "LAUDO. Paciente: Fulano de Souza, 52 anos.",
    "canal_origem": "Pronto_Socorro"
  }'
```

Sem `aguardar=true`, a API responde `202` com `{"documento_id": "...", "status": "recebido"}`; o resultado fica em `GET /triagem/{documento_id}`.

Campo obrigatório ausente retorna `422` com `{"detail": "campo obrigatório ausente: <campo>"}`.

## 🧪 11. Cenários de demonstração do MVP

O projeto deverá demonstrar pelo menos três cenários:

**Caso 1 — Documento rotineiro**

- Documento fictício com campos legíveis.
- Classificação e extração estruturada.
- Validação dos campos e encaminhamento conforme as regras configuradas.

**Caso 2 — Documento prioritário**

- Documento sintético contendo uma condição definida pelas regras de prioridade do sistema.
- Identificação do caso para encaminhamento prioritário.
- Registro do motivo e do resultado.

**Caso 3 — Documento ambíguo ou inconsistente**

- Documento fictício com campos ausentes, conflitantes ou ilegíveis.
- Identificação da necessidade de revisão.
- Encaminhamento para auditoria humana e registro da decisão posterior.

Os cenários demonstram o comportamento do fluxo de automação, não a validação clínica do agente.

## 🔐 12. Segurança e privacidade

Como o sistema trata informações potencialmente sensíveis, segurança e privacidade devem ser consideradas desde a primeira versão.

- Utilizar documentos fictícios nos testes e nas demonstrações.
- Manter os buckets privados e restringir as permissões de acesso.
- Armazenar credenciais em variáveis de ambiente ou mecanismos seguros de gestão de segredos.
- Não versionar arquivos `.env`, chaves ou credenciais no Git.
- Validar arquivos recebidos, tipos permitidos e limites de tamanho.
- Implementar autenticação e autorização antes de disponibilizar a aplicação a usuários.
- Registrar as ações relevantes de processamento e auditoria.
- Evitar armazenar informações pessoais desnecessárias em logs.
- Considerar os requisitos aplicáveis da LGPD e as políticas de proteção de dados.

## 🚀 13. Roadmap de desenvolvimento

- [ ] Definir a estrutura inicial do repositório.
- [ ] Criar a API com FastAPI.
- [ ] Definir os schemas de entrada e saída com Pydantic.
- [ ] Implementar o primeiro fluxo de processamento de texto.
- [ ] Construir a classificação e extração com IA.
- [ ] Implementar as decisões condicionais com LangGraph.
- [ ] Criar o fluxo de revisão humana.
- [ ] Configurar o PostgreSQL e o histórico de processamento.
- [ ] Criar o bucket privado no OCI Object Storage.
- [ ] Integrar a aplicação à OCI.
- [ ] Desenvolver a interface React.
- [ ] Criar testes automatizados para os três cenários.
- [ ] Documentar a instalação e a execução.
- [ ] Preparar a demonstração final do MVP.

## ▶️ 14. Como executar

As instruções completas de instalação serão adicionadas conforme a estrutura inicial e as dependências forem definidas.

A execução prevista será dividida em três partes:

1. Inicialização do ambiente e banco de dados.
2. Execução do backend e do módulo de IA.
3. Execução do frontend e integração com a API.

As configurações locais ficarão documentadas em `.env.example`, sem credenciais reais.

## 👥 15. Contribuição

Contribuições podem incluir melhorias na classificação, validação de dados, orquestração do agente, interface, testes e integração com a OCI.

Antes de contribuir:

1. Leia a documentação do projeto.
2. Crie uma branch para a funcionalidade.
3. Implemente testes para as alterações relevantes.
4. Não inclua documentos clínicos reais ou segredos no repositório.
5. Descreva as mudanças realizadas no pull request.

## 📌 16. Considerações finais

O MediFlow busca demonstrar como agentes de Inteligência Artificial podem apoiar a automação de fluxos documentais por meio de classificação, extração estruturada, validação, roteamento condicional e supervisão humana.

A proposta combina engenharia de software, agentes de IA e infraestrutura em nuvem para construir uma solução modular, rastreável e preparada para evolução.

**Projeto acadêmico em desenvolvimento — Alura + Oracle Next Education (ONE).**

