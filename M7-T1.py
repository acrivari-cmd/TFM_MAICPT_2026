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


def ler_timeout_padrao():
    try:
        return int(os.getenv("OPENROUTER_TIMEOUT", "90"))
    except ValueError:
        return 90


DEFAULT_MODEL_1 = os.getenv("OPENROUTER_MODEL_1", "google/gemini-2.0-flash-001")
DEFAULT_MODEL_2 = os.getenv("OPENROUTER_MODEL_2", "openai/gpt-4o-mini")
DEFAULT_MODEL_3 = os.getenv("OPENROUTER_MODEL_3", "anthropic/claude-3.5-haiku")
DEFAULT_TIMEOUT = ler_timeout_padrao()
FALLBACK_OPENROUTER_MODELS = list(
    dict.fromkeys(
        [
            DEFAULT_MODEL_1,
            DEFAULT_MODEL_2,
            DEFAULT_MODEL_3,
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-pro-1.5",
        ]
    )
)
FALLBACK_VISION_MODELS = list(dict.fromkeys([DEFAULT_MODEL_1, DEFAULT_MODEL_2]))

STATUS_VALIDOS = [
    "Atendido",
    "Parcialmente Atendido",
    "Não Atendido",
    "Não Aplicável",
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


def modelo_parece_aceitar_imagem(modelo):
    dados_modelo = json.dumps(modelo, ensure_ascii=False).lower()
    termos_visao = ["image", "vision", "multimodal", "visual"]
    return any(termo in dados_modelo for termo in termos_visao)


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


def preparar_opcoes_modelo(modelos_disponiveis, modelo_padrao):
    opcoes = list(modelos_disponiveis)
    if modelo_padrao and modelo_padrao not in opcoes:
        opcoes.insert(0, modelo_padrao)
    if not opcoes:
        opcoes = [modelo_padrao]
    return opcoes


def selecionar_modelo(label, modelos_disponiveis, modelo_padrao, help_text):
    opcoes = preparar_opcoes_modelo(modelos_disponiveis, modelo_padrao)
    indice_padrao = opcoes.index(modelo_padrao) if modelo_padrao in opcoes else 0
    return st.selectbox(
        label,
        options=opcoes,
        index=indice_padrao,
        help=help_text,
    )


def load_requirements():
    try:
        with open("requisitos_normativos.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        st.error("Arquivo requisitos_normativos.json não encontrado.")
        return None


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
        return "Parcialmente Atendido"
    if "nao aplicavel" in status_limpo or "não aplicável" in str(status).lower():
        return "Não Aplicável"
    if "nao atendido" in status_limpo:
        return "Não Atendido"
    if status_limpo == "atendido" or " atendido" in status_limpo:
        return "Atendido"

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


def criar_prompt_analise(requisitos):
    contexto_normativo = json.dumps(requisitos, ensure_ascii=False)
    return f"""
Você é um auditor especialista em normas de desenho técnico, incluindo a NBR 6492.

Analise a imagem do projeto técnico anexa e verifique os seguintes requisitos:
{contexto_normativo}

RETORNE APENAS UM OBJETO JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.

Formato obrigatório:
{{
  "resultados": [
    {{
      "id": 1,
      "item": "Nome do Item",
      "status": "Atendido",
      "justificativa": "Sua justificativa técnica aqui."
    }}
  ]
}}

Use apenas um destes status:
- Atendido
- Parcialmente Atendido
- Não Atendido
- Não Aplicável
"""


def criar_prompt_arbitro(requisito, resposta_modelo_1, resposta_modelo_2):
    requisito_json = json.dumps(requisito, ensure_ascii=False)
    resposta_1_json = json.dumps(resposta_modelo_1, ensure_ascii=False)
    resposta_2_json = json.dumps(resposta_modelo_2, ensure_ascii=False)

    return f"""
Você é um árbitro técnico. NÃO reanalise o PDF, a imagem ou o projeto completo.
Use apenas o requisito, as respostas e as justificativas abaixo.

Requisito analisado:
{requisito_json}

Resposta do Modelo 1:
{resposta_1_json}

Resposta do Modelo 2:
{resposta_2_json}

Decida qual justificativa é mais consistente com o requisito.
Se nenhuma justificativa for suficiente, indique incerteza de forma clara.

RETORNE APENAS UM OBJETO JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.

Formato obrigatório:
{{
  "decisao": "Modelo 1",
  "status_final": "Atendido",
  "justificativa_escolhida": "Justificativa selecionada.",
  "justificativa_arbitro": "Explique por que esta justificativa é mais consistente."
}}

Valores aceitos para "decisao":
- Modelo 1
- Modelo 2
- Incerteza
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
    for item in itens:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        resultados_por_id[item_id] = item

    resultados_normalizados = []
    for requisito in requisitos:
        item_id = int(requisito.get("id"))
        resposta_item = resultados_por_id.get(item_id, {})
        resultados_normalizados.append(
            {
                "id": item_id,
                "item": resposta_item.get("item") or requisito.get("item", ""),
                "status": normalizar_status(resposta_item.get("status")),
                "justificativa": str(
                    resposta_item.get("justificativa")
                    or "Modelo não retornou justificativa para este requisito."
                ).strip(),
            }
        )

    return resultados_normalizados


def analisar_documento_com_modelo(modelo, requisitos, image_data_url, api_key, temperature):
    prompt = criar_prompt_analise(requisitos)
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


def chamar_modelo_arbitro(modelo, requisito, resposta_modelo_1, resposta_modelo_2, api_key):
    prompt = criar_prompt_arbitro(requisito, resposta_modelo_1, resposta_modelo_2)
    mensagens = [{"role": "user", "content": prompt}]
    texto_resposta = chamar_openrouter(modelo, mensagens, api_key, temperature=0.0)
    resposta_json = carregar_json_da_resposta(texto_resposta)

    if not isinstance(resposta_json, dict):
        raise ValueError("A resposta do árbitro não contém um objeto JSON.")

    decisao = str(resposta_json.get("decisao", "")).strip().lower()
    if "modelo 1" in decisao or decisao == "1":
        decisao_normalizada = "Modelo 1"
    elif "modelo 2" in decisao or decisao == "2":
        decisao_normalizada = "Modelo 2"
    else:
        decisao_normalizada = "Incerteza"

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
        "id": requisito.get("id"),
        "item": requisito.get("item"),
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
        "id": requisito.get("id"),
        "item": requisito.get("item"),
        "modelo_1": resposta_modelo_1,
        "modelo_2": resposta_modelo_2,
        "status_comparacao": "concordância",
        "decisao_modelo_3": None,
        "justificativa_modelo_3": "",
        "justificativa_escolhida_modelo_3": "",
        "status": resposta_modelo_1.get("status"),
        "justificativa": (
            "Concordância entre Modelo 1 e Modelo 2. "
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
    if decisao == "Modelo 1":
        resposta_escolhida = resposta_modelo_1
    elif decisao == "Modelo 2":
        resposta_escolhida = resposta_modelo_2
    else:
        return {
            "id": requisito.get("id"),
            "item": requisito.get("item"),
            "modelo_1": resposta_modelo_1,
            "modelo_2": resposta_modelo_2,
            "status_comparacao": "revisão humana necessária",
            "decisao_modelo_3": "Incerteza",
            "justificativa_modelo_3": decisao_arbitro.get("justificativa_arbitro", ""),
            "justificativa_escolhida_modelo_3": "",
            "status": STATUS_REVISAO_HUMANA,
            "justificativa": (
                decisao_arbitro.get("justificativa_arbitro")
                or "O Modelo 3 indicou que nenhuma justificativa é suficiente."
            ),
        }

    justificativa_escolhida = (
        decisao_arbitro.get("justificativa_escolhida")
        or resposta_escolhida.get("justificativa")
        or "Justificativa escolhida pelo Modelo 3 não informada."
    )

    return {
        "id": requisito.get("id"),
        "item": requisito.get("item"),
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
                requisito,
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
                    "id": requisito.get("id"),
                    "item": requisito.get("item"),
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
        requisitos,
        image_data_url,
        api_key,
        temperature,
    )
    resultados_modelo_2 = analisar_documento_com_modelo(
        modelo_2,
        requisitos,
        image_data_url,
        api_key,
        temperature,
    )

    return consolidar_resultados(
        requisitos,
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
        self.cell(0, 10, "Baseado nos criterios da NBR e Manuais Internos", 0, 1, "C")
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
    if status_normalizado == "Atendido":
        return "🟢"
    if status_normalizado == "Parcialmente Atendido":
        return "🟡"
    if status_normalizado == "Não Aplicável":
        return "⚪"
    if status_normalizado == STATUS_REVISAO_HUMANA:
        return "🟠"
    return "🔴"


def exibir_resposta_modelo(titulo, resposta):
    st.markdown(f"**{titulo}**")
    st.write(f"Resultado: {resposta.get('status', 'Não avaliado')}")
    st.write(resposta.get("justificativa", "Sem justificativa."))


def exibir_resultado(res):
    modelo_1, modelo_2 = st.columns(2)
    with modelo_1:
        exibir_resposta_modelo("Modelo 1", res.get("modelo_1", {}))
    with modelo_2:
        exibir_resposta_modelo("Modelo 2", res.get("modelo_2", {}))

    st.info(f"Status da comparação: {res.get('status_comparacao', 'não informado')}")

    if res.get("decisao_modelo_3"):
        st.markdown("**Modelo 3 (árbitro)**")
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
st.write("Auditoria inteligente baseada nos critérios técnicos da NBR e Manuais Internos.")

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
        "Modelo 1",
        modelos_para_analise,
        DEFAULT_MODEL_1,
        "Modelo inicial que analisa a imagem/PDF convertido.",
    )
    model_2_choice = selecionar_modelo(
        "Modelo 2",
        modelos_para_analise,
        DEFAULT_MODEL_2,
        "Segundo modelo inicial que analisa a mesma imagem/PDF convertido.",
    )
    model_3_choice = selecionar_modelo(
        "Modelo 3 (árbitro)",
        modelos_disponiveis,
        DEFAULT_MODEL_3,
        "Modelo chamado apenas em divergência; recebe só respostas e justificativas.",
    )
    st.caption("O Modelo 3 só é chamado quando Modelo 1 e Modelo 2 divergem.")


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

            if st.button(":rocket: Executar Análise com IA", type="primary"):
                try:
                    with st.spinner(
                        "Modelos 1 e 2 estão auditando os requisitos técnicos..."
                    ):
                        data = load_requirements()

                        if data:
                            st.session_state.analysis_results = executar_fluxo_validacao(
                                image=image,
                                requisitos=data["requisitos"],
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
