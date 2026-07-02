import base64
import json
import os
import re
import unicodedata
from io import BytesIO

import requests
import streamlit as st
from dotenv import load_dotenv
from fpdf import FPDF
from pdf2image import convert_from_bytes
from PIL import Image


load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_APP_TITLE = "ZIGURAT-M7-T1"
DEFAULT_MODEL_A = "openai/gpt-5-mini"
DEFAULT_MODEL_B = "google/gemini-2.5-flash"
DEFAULT_MODEL_C = "anthropic/claude-haiku-4.5"
FALLBACK_VISION_MODELS = [
    DEFAULT_MODEL_A,
    DEFAULT_MODEL_B,
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash-lite",
]
FALLBACK_TEXT_MODELS = [
    DEFAULT_MODEL_C,
    "openai/gpt-4.1-nano",
    "anthropic/claude-3.5-haiku",
]


def ler_timeout_padrao():
    try:
        return int(os.getenv("OPENROUTER_TIMEOUT", "90"))
    except ValueError:
        return 90


DEFAULT_MODEL_1 = os.getenv("OPENROUTER_MODEL_1", DEFAULT_MODEL_A)
DEFAULT_MODEL_2 = os.getenv("OPENROUTER_MODEL_2", DEFAULT_MODEL_B)
DEFAULT_MODEL_3 = os.getenv("OPENROUTER_MODEL_3", DEFAULT_MODEL_C)
DEFAULT_TIMEOUT = ler_timeout_padrao()
FALLBACK_OPENROUTER_MODELS = list(
    dict.fromkeys(FALLBACK_VISION_MODELS + FALLBACK_TEXT_MODELS)
)

STATUS_VALIDOS = [
    "Conforme",
    "Parcialmente Conforme",
    "Não Conforme",
    "Não Verificável pela Imagem",
]
STATUS_REVISAO_HUMANA = "Revisão Humana Necessária"


st.set_page_config(page_title="ZIGURAT-M7-T1", layout="wide")


if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = None


class OpenRouterError(Exception):
    """Erro controlado para falhas de chamada ou resposta da API."""


def get_openrouter_api_key():
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def carregar_json_enviado(uploaded_json):
    if uploaded_json is None:
        return None, None, "Envie um arquivo JSON normativo antes de executar a análise."

    if not uploaded_json.name.lower().endswith(".json"):
        return None, None, "O arquivo normativo deve estar no formato .json."

    try:
        data = json.loads(uploaded_json.getvalue().decode("utf-8"))
    except UnicodeDecodeError:
        return None, None, "Não foi possível ler o JSON em UTF-8."
    except json.JSONDecodeError as exc:
        return None, None, f"JSON normativo inválido: {exc.msg}."

    if data in ({}, [], None):
        return None, None, "O JSON normativo está vazio."

    requisitos = extrair_requisitos_normativos(data)
    if not requisitos:
        return (
            data,
            None,
            "Estrutura mínima incompatível: envie uma lista de requisitos ou um objeto com a chave 'requisitos'.",
        )

    return data, requisitos, None


def extrair_requisitos_normativos(data):
    if isinstance(data, list):
        requisitos = data
    elif isinstance(data, dict) and isinstance(data.get("requisitos"), list):
        requisitos = data["requisitos"]
    else:
        return None

    requisitos_validos = [item for item in requisitos if isinstance(item, dict)]
    return requisitos_validos or None


def obter_id_requisito(requisito, indice):
    return requisito.get("id") or requisito.get("codigo") or requisito.get("código") or indice


def obter_nome_requisito(requisito, indice):
    for chave in ("item", "nome", "titulo", "título", "requisito", "descricao", "descrição"):
        valor = requisito.get(chave)
        if valor:
            return str(valor)
    return f"Requisito {indice}"


def exibir_previa_json(requisitos):
    st.success(f"JSON normativo carregado com sucesso: {len(requisitos)} requisitos encontrados.")
    with st.expander("Prévia resumida do JSON normativo"):
        for indice, requisito in enumerate(requisitos[:5], start=1):
            st.write(f"{obter_id_requisito(requisito, indice)}. {obter_nome_requisito(requisito, indice)}")
        if len(requisitos) > 5:
            st.caption(f"... mais {len(requisitos) - 5} requisito(s).")


def modelo_parece_aceitar_imagem(modelo):
    arquitetura = modelo.get("architecture") or {}
    entradas = arquitetura.get("input_modalities") or []
    saidas = arquitetura.get("output_modalities") or []
    return "image" in entradas and "text" in saidas


@st.cache_data(ttl=3600, show_spinner=False)
def carregar_modelos_openrouter():
    try:
        response = requests.get(OPENROUTER_MODELS_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        return [], [], "Timeout ao carregar modelos do OpenRouter."
    except requests.RequestException as exc:
        return [], [], f"Não foi possível carregar modelos do OpenRouter: {exc}"
    except ValueError:
        return [], [], "A lista de modelos do OpenRouter não retornou JSON válido."

    modelos = []
    modelos_com_visao = []

    for modelo in data.get("data", []):
        model_id = modelo.get("id")
        if not model_id:
            continue

        modelos.append(model_id)
        if modelo_parece_aceitar_imagem(modelo):
            modelos_com_visao.append(model_id)

    modelos = sorted(set(modelos))
    modelos_com_visao = sorted(set(modelos_com_visao))

    if not modelos:
        return [], [], "A API do OpenRouter não retornou modelos disponíveis."

    return modelos, modelos_com_visao, None


def preparar_opcoes_modelo(modelos_disponiveis, modelo_padrao, permitir_modelo_externo=False):
    opcoes = list(dict.fromkeys(modelos_disponiveis))
    if permitir_modelo_externo and modelo_padrao and modelo_padrao not in opcoes:
        opcoes.insert(0, modelo_padrao)
    if not opcoes:
        opcoes = [modelo_padrao]
    return opcoes


def selecionar_modelo(
    label,
    modelos_disponiveis,
    modelo_padrao,
    help_text,
    permitir_modelo_externo=False,
):
    opcoes = preparar_opcoes_modelo(
        modelos_disponiveis,
        modelo_padrao,
        permitir_modelo_externo=permitir_modelo_externo,
    )
    indice_padrao = opcoes.index(modelo_padrao) if modelo_padrao in opcoes else 0
    return st.selectbox(
        label,
        options=opcoes,
        index=indice_padrao,
        help=help_text,
    )


def remover_acentos(texto):
    texto = str(texto or "")
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )


def normalizar_status(status):
    status_limpo = remover_acentos(status).strip().lower()

    if "revisao humana" in status_limpo:
        return STATUS_REVISAO_HUMANA
    if "parcial" in status_limpo:
        return "Parcialmente Conforme"
    if "nao verificavel" in status_limpo or "não verificável" in str(status).lower():
        return "Não Verificável pela Imagem"
    if "nao conforme" in status_limpo:
        return "Não Conforme"
    if status_limpo == "conforme" or " conforme" in status_limpo:
        return "Conforme"

    return "Não avaliado"


def limpar_bloco_json(texto):
    texto = str(texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s*```$", "", texto)
    return texto.strip()


def carregar_json_da_resposta(texto):
    texto_limpo = limpar_bloco_json(texto)
    candidatos = [texto_limpo]

    inicio_objeto = texto_limpo.find("{")
    fim_objeto = texto_limpo.rfind("}")
    if inicio_objeto >= 0 and fim_objeto > inicio_objeto:
        candidatos.append(texto_limpo[inicio_objeto : fim_objeto + 1])

    inicio_array = texto_limpo.find("[")
    fim_array = texto_limpo.rfind("]")
    if inicio_array >= 0 and fim_array > inicio_array:
        candidatos.append(texto_limpo[inicio_array : fim_array + 1])

    for candidato in candidatos:
        try:
            return json.loads(candidato)
        except json.JSONDecodeError:
            continue

    raise ValueError("A resposta não contém JSON válido.")


def preparar_imagem_para_api(image, max_side=1800):
    # Reduz o payload enviado ao modelo sem alterar a pré-visualização exibida ao usuário.
    imagem = image.copy()
    imagem.thumbnail((max_side, max_side))
    if imagem.mode != "RGB":
        imagem = imagem.convert("RGB")

    buffer = BytesIO()
    imagem.save(buffer, format="PNG")
    imagem_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{imagem_base64}"


def extrair_texto_openrouter(data):
    choices = data.get("choices") or []
    if not choices:
        raise OpenRouterError("O modelo não retornou escolhas na resposta.")

    mensagem = choices[0].get("message", {})
    conteudo = mensagem.get("content")

    if isinstance(conteudo, str) and conteudo.strip():
        return conteudo.strip()

    if isinstance(conteudo, list):
        partes_texto = [
            parte.get("text", "")
            for parte in conteudo
            if isinstance(parte, dict) and parte.get("type") == "text"
        ]
        texto = "\n".join(partes_texto).strip()
        if texto:
            return texto

    raise OpenRouterError("O modelo retornou uma resposta vazia.")


def chamar_openrouter(modelo, mensagens, api_key, temperature=0.1, timeout=DEFAULT_TIMEOUT):
    if not api_key:
        raise OpenRouterError("Variável de ambiente OPENROUTER_API_KEY não configurada.")
    if not modelo:
        raise OpenRouterError("Nome do modelo OpenRouter não informado.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": OPENROUTER_APP_TITLE,
    }

    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        headers["HTTP-Referer"] = referer

    payload = {
        "model": modelo,
        "messages": mensagens,
        "temperature": temperature,
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise OpenRouterError("Timeout ao chamar a API OpenRouter.") from exc
    except requests.ConnectionError as exc:
        raise OpenRouterError("Erro de conexão ao chamar a API OpenRouter.") from exc
    except requests.HTTPError as exc:
        detalhe = response.text[:500] if "response" in locals() else str(exc)
        raise OpenRouterError(f"Falha HTTP na API OpenRouter: {detalhe}") from exc
    except requests.RequestException as exc:
        raise OpenRouterError(f"Falha na chamada à API OpenRouter: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterError("A API OpenRouter retornou uma resposta que não é JSON.") from exc

    return extrair_texto_openrouter(data)


def criar_prompt_analise(contexto_normativo):
    return f"""
Você é um auditor técnico especializado em análise de documentos, desenhos e projetos técnicos.

Sua tarefa é avaliar a imagem do documento/projeto enviada, utilizando exclusivamente os requisitos normativos fornecidos no contexto abaixo.

Contexto normativo carregado pelo usuário:
{contexto_normativo}

Instruções de auditoria:

1. Analise a imagem com olhar técnico, crítico e criterioso.
2. Verifique cada requisito normativo informado no contexto.
3. Não assuma informações que não estejam visíveis na imagem.
4. Não invente conformidades ou não conformidades.
5. Quando um requisito não puder ser verificado visualmente, classifique como "não verificável pela imagem".
6. Quando houver evidência parcial, classifique como "parcialmente conforme".
7. Para cada requisito, informe identificação ou nome do requisito, status, justificativa técnica objetiva, evidência observada e recomendação quando aplicável.
8. Ao final, apresente um resumo geral da auditoria com os principais riscos técnicos encontrados.

RETORNE APENAS UM OBJETO JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.
Não cite normas específicas que não estejam presentes no contexto normativo carregado.
Não utilize conhecimento externo para complementar requisitos ausentes.

Formato obrigatório:
{{
  "resultados": [
    {{
      "id": 1,
      "requisito": "Nome ou identificação do requisito",
      "status": "conforme",
      "justificativa": "Justificativa técnica curta.",
      "evidencia": "Evidência observada na imagem, quando existir.",
      "recomendacao": "Recomendação de correção, quando aplicável."
    }}
  ],
  "resumo_geral": "Resumo objetivo da auditoria."
}}

Use apenas um destes status:
- conforme
- não conforme
- parcialmente conforme
- não verificável pela imagem
"""


def criar_prompt_arbitro(contexto_normativo, resposta_modelo_1, resposta_modelo_2):
    return f"""
Você é um auditor técnico sênior atuando como juiz de consistência entre duas auditorias independentes.

A imagem do projeto/documento foi analisada por dois modelos diferentes.

Contexto normativo utilizado:
{contexto_normativo}

Resposta do Modelo A:
{json.dumps(resposta_modelo_1, ensure_ascii=False)}

Resposta do Modelo B:
{json.dumps(resposta_modelo_2, ensure_ascii=False)}

Sua tarefa:

1. Compare as respostas do Modelo A e do Modelo B.
2. Identifique divergências de status, justificativa ou interpretação técnica.
3. Escolha a resposta mais bem fundamentada para cada requisito divergente.
4. Não faça uma nova auditoria completa do zero.
5. Use apenas o contexto normativo e as justificativas apresentadas pelos modelos A e B.
6. Se nenhuma das duas respostas for tecnicamente suficiente, indique que a decisão é inconclusiva.
7. Justifique de forma objetiva por que uma resposta foi escolhida.

RETORNE APENAS UM OBJETO JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.

Formato obrigatório:
{{
  "decisao": "Modelo A",
  "status_final": "conforme",
  "justificativa_escolhida": "Justificativa selecionada ou consolidada.",
  "justificativa_arbitro": "Por que esta resposta foi escolhida.",
  "resumo_divergencia": "Resumo objetivo da divergência."
}}

Valores aceitos para "decisao":
- Modelo A
- Modelo B
- inconclusivo
"""


def normalizar_lista_resultados(resposta_json, requisitos):
    if isinstance(resposta_json, dict):
        itens = resposta_json.get("resultados")
    elif isinstance(resposta_json, list):
        itens = resposta_json
    else:
        itens = None

    if not isinstance(itens, list):
        raise ValueError("A resposta não contém a lista 'resultados'.")

    resultados_por_id = {}
    resultados_por_nome = {}
    for item in itens:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        item_nome = str(item.get("requisito") or item.get("item") or "").strip().lower()
        if item_id:
            resultados_por_id[item_id] = item
        if item_nome:
            resultados_por_nome[item_nome] = item

    resultados_normalizados = []
    for indice, requisito in enumerate(requisitos, start=1):
        item_id = obter_id_requisito(requisito, indice)
        item_nome = obter_nome_requisito(requisito, indice)
        resposta_item = (
            resultados_por_id.get(str(item_id))
            or resultados_por_nome.get(item_nome.lower())
            or {}
        )
        resultados_normalizados.append(
            {
                "id": item_id,
                "item": resposta_item.get("requisito") or resposta_item.get("item") or item_nome,
                "status": normalizar_status(resposta_item.get("status")),
                "justificativa": str(
                    resposta_item.get("justificativa")
                    or "Modelo não retornou justificativa para este requisito."
                ).strip(),
                "evidencia": str(resposta_item.get("evidencia") or resposta_item.get("evidência") or "").strip(),
                "recomendacao": str(resposta_item.get("recomendacao") or resposta_item.get("recomendação") or "").strip(),
            }
        )

    return resultados_normalizados


def analisar_documento_com_modelo(modelo, contexto_normativo, requisitos, image_data_url, api_key, temperature):
    prompt = criar_prompt_analise(contexto_normativo)
    mensagens = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    texto_resposta = chamar_openrouter(modelo, mensagens, api_key, temperature=temperature)
    resposta_json = carregar_json_da_resposta(texto_resposta)
    return normalizar_lista_resultados(resposta_json, requisitos)


def respostas_concordam(resposta_modelo_1, resposta_modelo_2):
    status_1 = resposta_modelo_1.get("status")
    status_2 = resposta_modelo_2.get("status")
    return status_1 == status_2 and status_1 in STATUS_VALIDOS


def respostas_validas_para_comparacao(resposta_modelo_1, resposta_modelo_2):
    return (
        resposta_modelo_1.get("status") in STATUS_VALIDOS
        and resposta_modelo_2.get("status") in STATUS_VALIDOS
    )


def chamar_modelo_arbitro(modelo, contexto_normativo, resposta_modelo_1, resposta_modelo_2, api_key):
    prompt = criar_prompt_arbitro(contexto_normativo, resposta_modelo_1, resposta_modelo_2)
    mensagens = [{"role": "user", "content": prompt}]
    texto_resposta = chamar_openrouter(modelo, mensagens, api_key, temperature=0.0)
    resposta_json = carregar_json_da_resposta(texto_resposta)

    if not isinstance(resposta_json, dict):
        raise ValueError("A resposta do árbitro não contém um objeto JSON.")

    decisao = str(resposta_json.get("decisao", "")).strip().lower()
    if "modelo a" in decisao or decisao == "a":
        decisao_normalizada = "Modelo A"
    elif "modelo b" in decisao or decisao == "b":
        decisao_normalizada = "Modelo B"
    else:
        decisao_normalizada = "Inconclusivo"

    return {
        "decisao": decisao_normalizada,
        "status_final": normalizar_status(resposta_json.get("status_final")),
        "justificativa_escolhida": str(
            resposta_json.get("justificativa_escolhida", "")
        ).strip(),
        "justificativa_arbitro": str(
            resposta_json.get("justificativa_arbitro", "")
        ).strip(),
    }


def consolidar_revisao_humana_sem_arbitro(requisito, resposta_modelo_1, resposta_modelo_2):
    return {
        "id": resposta_modelo_1.get("id") or resposta_modelo_2.get("id") or requisito.get("id"),
        "item": resposta_modelo_1.get("item") or resposta_modelo_2.get("item") or requisito.get("item"),
        "modelo_1": resposta_modelo_1,
        "modelo_2": resposta_modelo_2,
        "status_comparacao": "revisão humana necessária",
        "decisao_modelo_3": None,
        "justificativa_modelo_3": "",
        "justificativa_escolhida_modelo_3": "",
        "status": STATUS_REVISAO_HUMANA,
        "justificativa": (
            "Ao menos um dos modelos iniciais não retornou um status válido. "
            "O árbitro não foi chamado porque não houve duas respostas válidas para comparar."
        ),
    }


def consolidar_por_concordancia(requisito, resposta_modelo_1, resposta_modelo_2):
    justificativa_final = (
        resposta_modelo_1.get("justificativa")
        or resposta_modelo_2.get("justificativa")
        or "Concordância entre os modelos sem justificativa detalhada."
    )
    return {
        "id": resposta_modelo_1.get("id") or resposta_modelo_2.get("id") or requisito.get("id"),
        "item": resposta_modelo_1.get("item") or resposta_modelo_2.get("item") or requisito.get("item"),
        "modelo_1": resposta_modelo_1,
        "modelo_2": resposta_modelo_2,
        "status_comparacao": "concordância",
        "decisao_modelo_3": None,
        "justificativa_modelo_3": "",
        "justificativa_escolhida_modelo_3": "",
        "status": resposta_modelo_1.get("status"),
        "justificativa": (
            "Concordância entre Modelo A e Modelo B. "
            f"Justificativa de referência: {justificativa_final}"
        ),
    }


def consolidar_por_arbitro(
    requisito,
    resposta_modelo_1,
    resposta_modelo_2,
    decisao_arbitro,
):
    decisao = decisao_arbitro.get("decisao")
    if decisao == "Modelo A":
        resposta_escolhida = resposta_modelo_1
    elif decisao == "Modelo B":
        resposta_escolhida = resposta_modelo_2
    else:
        return {
            "id": resposta_modelo_1.get("id") or resposta_modelo_2.get("id") or requisito.get("id"),
            "item": resposta_modelo_1.get("item") or resposta_modelo_2.get("item") or requisito.get("item"),
            "modelo_1": resposta_modelo_1,
            "modelo_2": resposta_modelo_2,
            "status_comparacao": "revisão humana necessária",
            "decisao_modelo_3": "Inconclusivo",
            "justificativa_modelo_3": decisao_arbitro.get("justificativa_arbitro", ""),
            "justificativa_escolhida_modelo_3": "",
            "status": STATUS_REVISAO_HUMANA,
            "justificativa": (
                decisao_arbitro.get("justificativa_arbitro")
                or "O Modelo C indicou que nenhuma justificativa é suficiente."
            ),
        }

    justificativa_escolhida = (
        decisao_arbitro.get("justificativa_escolhida")
        or resposta_escolhida.get("justificativa")
        or "Justificativa escolhida pelo Modelo C não informada."
    )

    return {
        "id": resposta_modelo_1.get("id") or resposta_modelo_2.get("id") or requisito.get("id"),
        "item": resposta_modelo_1.get("item") or resposta_modelo_2.get("item") or requisito.get("item"),
        "modelo_1": resposta_modelo_1,
        "modelo_2": resposta_modelo_2,
        "status_comparacao": "divergência",
        "decisao_modelo_3": decisao,
        "justificativa_modelo_3": decisao_arbitro.get("justificativa_arbitro", ""),
        "justificativa_escolhida_modelo_3": justificativa_escolhida,
        "status": resposta_escolhida.get("status"),
        "justificativa": justificativa_escolhida,
    }


def consolidar_resultados(
    requisitos,
    contexto_normativo,
    resultados_modelo_1,
    resultados_modelo_2,
    modelo_arbitro,
    api_key,
):
    consolidados = []

    for requisito, resposta_1, resposta_2 in zip(
        requisitos,
        resultados_modelo_1,
        resultados_modelo_2,
    ):
        if respostas_concordam(resposta_1, resposta_2):
            consolidados.append(
                consolidar_por_concordancia(requisito, resposta_1, resposta_2)
            )
            continue

        if not respostas_validas_para_comparacao(resposta_1, resposta_2):
            consolidados.append(
                consolidar_revisao_humana_sem_arbitro(requisito, resposta_1, resposta_2)
            )
            continue

        try:
            decisao_arbitro = chamar_modelo_arbitro(
                modelo_arbitro,
                contexto_normativo,
                resposta_1,
                resposta_2,
                api_key,
            )
            consolidados.append(
                consolidar_por_arbitro(requisito, resposta_1, resposta_2, decisao_arbitro)
            )
        except (OpenRouterError, ValueError) as exc:
            consolidados.append(
                {
                    "id": resposta_1.get("id") or resposta_2.get("id") or requisito.get("id"),
                    "item": resposta_1.get("item") or resposta_2.get("item") or requisito.get("item"),
                    "modelo_1": resposta_1,
                    "modelo_2": resposta_2,
                    "status_comparacao": "revisão humana necessária",
                    "decisao_modelo_3": "Falha no árbitro",
                    "justificativa_modelo_3": str(exc),
                    "justificativa_escolhida_modelo_3": "",
                    "status": STATUS_REVISAO_HUMANA,
                    "justificativa": (
                        "Não foi possível consolidar automaticamente. "
                        f"Motivo: {exc}"
                    ),
                }
            )

    return consolidados


def executar_fluxo_validacao(
    image,
    contexto_normativo,
    requisitos,
    api_key,
    modelo_1,
    modelo_2,
    modelo_3,
    temperature,
):
    image_data_url = preparar_imagem_para_api(image)
    resultados_modelo_1 = analisar_documento_com_modelo(
        modelo_1,
        contexto_normativo,
        requisitos,
        image_data_url,
        api_key,
        temperature,
    )
    resultados_modelo_2 = analisar_documento_com_modelo(
        modelo_2,
        contexto_normativo,
        requisitos,
        image_data_url,
        api_key,
        temperature,
    )

    return consolidar_resultados(
        requisitos,
        contexto_normativo,
        resultados_modelo_1,
        resultados_modelo_2,
        modelo_3,
        api_key,
    )


class PDFReport(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Análise Avançada de Projetos", 0, 1, "C")
        self.set_font("Arial", "", 10)
        self.cell(0, 10, "Baseado no JSON normativo carregado pelo usuário", 0, 1, "C")
        self.ln(5)


def generate_pdf(analysis_results):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    for item in analysis_results:
        pdf.set_font("Arial", "B", 11)
        titulo = f"{item['id']}. {item['item']}".encode("latin-1", "replace").decode(
            "latin-1"
        )
        pdf.cell(0, 10, titulo, 0, 1)

        pdf.set_font("Arial", "I", 10)
        status = f"Status final: {item['status']}".encode(
            "latin-1",
            "replace",
        ).decode("latin-1")
        pdf.cell(0, 8, status, 0, 1)

        comparacao = f"Comparação: {item.get('status_comparacao', '')}".encode(
            "latin-1",
            "replace",
        ).decode("latin-1")
        pdf.cell(0, 8, comparacao, 0, 1)

        pdf.set_font("Arial", size=10)
        justificativa = f"Justificativa final: {item['justificativa']}".encode(
            "latin-1",
            "replace",
        ).decode("latin-1")
        pdf.multi_cell(0, 5, justificativa)
        pdf.ln(5)

    pdf_out = pdf.output(dest="S")
    if isinstance(pdf_out, str):
        return pdf_out.encode("latin-1", "replace")
    return bytes(pdf_out)


def nova_analise():
    st.session_state.uploader_key += 1
    st.session_state.analysis_results = None


def cor_status(status_atual):
    status_normalizado = normalizar_status(status_atual)
    if status_normalizado == "Conforme":
        return "🟢"
    if status_normalizado == "Parcialmente Conforme":
        return "🟡"
    if status_normalizado == "Não Verificável pela Imagem":
        return "⚪"
    if status_normalizado == STATUS_REVISAO_HUMANA:
        return "🟠"
    return "🔴"


def exibir_resposta_modelo(titulo, resposta):
    st.markdown(f"**{titulo}**")
    st.write(f"Resultado: {resposta.get('status', 'Não avaliado')}")
    st.write(resposta.get("justificativa", "Sem justificativa."))
    if resposta.get("evidencia"):
        st.write(f"Evidência: {resposta.get('evidencia')}")
    if resposta.get("recomendacao"):
        st.write(f"Recomendação: {resposta.get('recomendacao')}")


def exibir_resultado(res):
    modelo_1, modelo_2 = st.columns(2)
    with modelo_1:
        exibir_resposta_modelo("Modelo A", res.get("modelo_1", {}))
    with modelo_2:
        exibir_resposta_modelo("Modelo B", res.get("modelo_2", {}))

    st.info(f"Status da comparação: {res.get('status_comparacao', 'não informado')}")

    if res.get("decisao_modelo_3"):
        st.markdown("**Modelo C (juiz)**")
        st.write(f"Decisão: {res.get('decisao_modelo_3')}")
        if res.get("justificativa_escolhida_modelo_3"):
            st.write(
                "Justificativa escolhida: "
                f"{res.get('justificativa_escolhida_modelo_3')}"
            )
        if res.get("justificativa_modelo_3"):
            st.write(f"Justificativa do árbitro: {res.get('justificativa_modelo_3')}")

    st.markdown("**Resultado final consolidado**")
    st.write(f"Resultado: {res.get('status', 'Não avaliado')}")
    st.write(res.get("justificativa", "Sem justificativa final."))


st.markdown(
    """
    <div style="display: flex; justify-content: center; margin-bottom: 20px;">
        <h2>ZIGURAT Institute of Technology</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

st.title("Análise Avançada de Projetos")
st.write("Auditoria inteligente baseada no JSON normativo carregado pelo usuário.")

api_key_env = get_openrouter_api_key()

with st.sidebar:
    st.header(":gear: Configurações do Sistema")

    api_key_input = st.text_input(
        "Chave API OpenRouter",
        type="password",
        placeholder="sk-or-v1-...",
        help=(
            "Cole a chave aqui para usar nesta sessão. "
            "Se preferir, configure OPENROUTER_API_KEY no arquivo .env."
        ),
    )
    api_key = api_key_input.strip() or api_key_env

    if api_key_input.strip():
        st.success("Chave OpenRouter informada para esta sessão.")
    elif api_key_env:
        st.success("Chave OpenRouter carregada do ambiente.")
    else:
        st.error("Informe a chave acima ou configure OPENROUTER_API_KEY no ambiente.")

    temp_input = st.slider(
        "Criatividade da IA (Temperature)",
        min_value=0.0,
        max_value=1.0,
        value=0.1,
        step=0.1,
        help="Para auditoria técnica, mantenha valores próximos a 0.0.",
    )

    if st.button("Atualizar lista de modelos", use_container_width=True):
        carregar_modelos_openrouter.clear()

    modelos_openrouter, modelos_visao, erro_modelos = carregar_modelos_openrouter()
    modelos_disponiveis = modelos_openrouter or FALLBACK_OPENROUTER_MODELS
    modelos_para_analise = modelos_visao or modelos_disponiveis or FALLBACK_VISION_MODELS

    if erro_modelos:
        st.warning(f"{erro_modelos} Usando modelos padrão.")
    else:
        st.caption(f"{len(modelos_openrouter)} modelos carregados do OpenRouter.")

    if modelos_openrouter and not modelos_visao:
        st.caption("Não foi possível identificar modelos com visão; exibindo a lista completa.")

    model_1_choice = selecionar_modelo(
        "Modelo A",
        modelos_para_analise,
        DEFAULT_MODEL_1,
        "Modelo inicial que analisa a imagem/PDF convertido.",
        permitir_modelo_externo=True,
    )
    model_2_choice = selecionar_modelo(
        "Modelo B",
        modelos_para_analise,
        DEFAULT_MODEL_2,
        "Segundo modelo inicial que analisa a mesma imagem/PDF convertido.",
        permitir_modelo_externo=True,
    )
    model_3_choice = selecionar_modelo(
        "Modelo C (juiz)",
        modelos_disponiveis,
        DEFAULT_MODEL_3,
        "Modelo chamado apenas em divergência; recebe só respostas e justificativas.",
        permitir_modelo_externo=True,
    )
    for label, modelo in (
        ("Modelo A", model_1_choice),
        ("Modelo B", model_2_choice),
        ("Modelo C", model_3_choice),
    ):
        if modelos_openrouter and modelo not in modelos_openrouter:
            st.warning(f"{label} não apareceu no catálogo atual do OpenRouter. Se a chamada falhar, selecione outro modelo.")

    st.caption("O Modelo C só é chamado quando Modelo A e Modelo B divergem.")


if not api_key:
    st.warning(
        ":point_left: Informe a Chave API OpenRouter na barra lateral para iniciar a aplicação."
    )

else:
    uploaded_file = st.file_uploader(
        "Arraste a prancha do projeto (.jpeg, .png, .pdf)",
        type=["jpg", "jpeg", "png", "pdf"],
        key=f"uploader_{st.session_state.uploader_key}",
    )

    uploaded_json = st.file_uploader(
        "Envie o JSON de requisitos normativos",
        type=["json"],
        key=f"json_{st.session_state.uploader_key}",
    )
    json_normativo, requisitos_normativos, erro_json = carregar_json_enviado(uploaded_json)

    if erro_json:
        st.warning(erro_json)
    else:
        exibir_previa_json(requisitos_normativos)

    contexto_normativo = (
        json.dumps(json_normativo, ensure_ascii=False, indent=2)
        if json_normativo is not None
        else ""
    )

    if uploaded_file is not None and st.session_state.analysis_results is None:
        image = None

        if uploaded_file.type == "application/pdf":
            try:
                with st.spinner("Convertendo PDF para imagem de alta resolução..."):
                    file_bytes = uploaded_file.getvalue()
                    images = convert_from_bytes(file_bytes, dpi=300)

                    if images:
                        image = images[0]
                        st.success("PDF convertido com sucesso!")

            except Exception as e:
                st.error(f"Erro ao processar PDF: {e}")

        else:
            image = Image.open(uploaded_file)

        if image is not None:
            st.image(image, caption="Projeto Carregado", use_column_width=True)

            analise_bloqueada = requisitos_normativos is None
            if st.button(
                ":rocket: Executar Análise com IA",
                type="primary",
                disabled=analise_bloqueada,
            ):
                try:
                    with st.spinner(
                        "Modelos A e B estão auditando os requisitos técnicos..."
                    ):
                        st.session_state.analysis_results = executar_fluxo_validacao(
                            image=image,
                            contexto_normativo=contexto_normativo,
                            requisitos=requisitos_normativos,
                            api_key=api_key,
                            modelo_1=model_1_choice.strip(),
                            modelo_2=model_2_choice.strip(),
                            modelo_3=model_3_choice.strip(),
                            temperature=temp_input,
                        )
                        st.rerun()

                except OpenRouterError as e:
                    st.error(f"Falha na API OpenRouter: {e}")
                except ValueError as e:
                    st.error(f"Resposta fora do formato esperado: {e}")
                except Exception as e:
                    st.error(f"Ocorreu um erro ao processar a análise. Detalhes: {e}")


if st.session_state.analysis_results is not None:
    st.success(":white_check_mark: Análise Concluída com Sucesso!")

    for res in st.session_state.analysis_results:
        status_atual = res.get("status", "Não avaliado")
        marcador = cor_status(status_atual)

        with st.expander(
            f"{res.get('id')}. {res.get('item')} - {marcador} {status_atual}"
        ):
            exibir_resultado(res)

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        pdf_data = generate_pdf(st.session_state.analysis_results)
        st.download_button(
            label=":inbox_tray: Baixar Relatório em PDF",
            data=pdf_data,
            file_name="Analise_Avancada_de_Projetos.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    with col2:
        if st.button(":arrows_counterclockwise: Iniciar Nova Análise", use_container_width=True):
            nova_analise()
            st.rerun()


st.divider()
st.caption("Master em Inteligência Artificial para Arquitetura - ZIGURAT Institute of Technology")
