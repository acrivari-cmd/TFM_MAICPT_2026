import streamlit as st
import json
import google.generativeai as genai
from PIL import Image
from fpdf import FPDF
from pdf2image import convert_from_bytes


st.set_page_config(page_title="ZIGURAT-M7-T1", layout="wide")


if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = None


def load_requirements():
    try:
        with open("requisitos_normativos.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        st.error("Arquivo requisitos_normativos.json não encontrado.")
        return None


class PDFReport(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Análise Avançada de Projetos", 0, 1, "C")
        self.set_font("Arial", "", 10)
        self.cell(0, 10, "Baseado nos criterios da NBR 6492", 0, 1, "C")
        self.ln(5)


def generate_pdf(analysis_results):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    for item in analysis_results:
        pdf.set_font("Arial", "B", 11)
        titulo = f"{item['id']}. {item['item']}".encode("latin-1", "replace").decode("latin-1")
        pdf.cell(0, 10, titulo, 0, 1)

        pdf.set_font("Arial", "I", 10)
        status = f"Status: {item['status']}".encode("latin-1", "replace").decode("latin-1")
        pdf.cell(0, 8, status, 0, 1)

        pdf.set_font("Arial", size=10)
        justificativa = f"Justificativa: {item['justificativa']}".encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 5, justificativa)
        pdf.ln(5)

    pdf_out = pdf.output(dest="S")
    if isinstance(pdf_out, str):
        return pdf_out.encode("latin-1", "replace")
    return bytes(pdf_out)


def nova_analise():
    st.session_state.uploader_key += 1
    st.session_state.analysis_results = None


st.markdown(
    """
    <div style="display: flex; justify-content: center; margin-bottom: 20px;">
        <h2>ZIGURAT Institute of Technology</h2>
    </div>
    """,
    unsafe_allow_html=True,
)

st.title("Análise Avançada de Projetos")
st.write("Auditoria inteligente baseada nos critérios técnicos da NBR 6492.")


with st.sidebar:
    st.header(":gear: Configurações do Sistema")

    api_key_input = st.text_input(
        "Chave API do Gemini",
        type="password",
        help="Insira sua chave gerada no Google AI Studio.",
    )

    temp_input = st.slider(
        "Criatividade da IA (Temperature)",
        min_value=0.0,
        max_value=1.0,
        value=0.1,
        step=0.1,
        help="Para auditoria técnica, mantenha valores próximos a 0.0.",
    )

    modelos_disponiveis = ["gemini-1.5-flash", "gemini-2.0-flash"]

    if api_key_input:
        genai.configure(api_key=api_key_input)
        try:
            modelos_dinamicos = []
            for m in genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    nome_limpo = m.name.replace("models/", "")
                    if "flash" in nome_limpo:
                        modelos_dinamicos.append(nome_limpo)

            if modelos_dinamicos:
                modelos_disponiveis = modelos_dinamicos

        except Exception:
            st.error(":warning: Erro: Verifique se sua Chave API está correta.")

    model_choice = st.selectbox("Modelo LLM", modelos_disponiveis)
    st.caption("Utilizando modelos 'flash' para análise avançada de projetos.")


if not api_key_input:
    st.warning(":point_left: Por favor, insira sua Chave API do Gemini na barra lateral para iniciar a aplicação.")

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
                    with st.spinner("A IA está auditando os requisitos técnicos..."):
                        data = load_requirements()

                        if data:
                            contexto_normativo = json.dumps(
                                data["requisitos"],
                                ensure_ascii=False,
                            )

                            model = genai.GenerativeModel(
                                model_name=model_choice,
                                generation_config={
                                    "temperature": temp_input,
                                },
                            )

                            prompt = f"""
Você é um auditor especialista em normas de desenho técnico, incluindo a NBR 6492.

Analise a imagem do projeto técnico anexa e verifique os seguintes requisitos:
{contexto_normativo}

RETORNE APENAS UM ARRAY JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.

Formato obrigatório:
[
  {{
    "id": 1,
    "item": "Nome do Item",
    "status": "Atendido",
    "justificativa": "Sua justificativa técnica aqui."
  }}
]

Use apenas um destes status:
- Atendido
- Parcialmente Atendido
- Não Atendido
- Não Aplicável
"""

                            response = model.generate_content([prompt, image])
                            raw_json = response.text.strip()

                            if raw_json.startswith("```json"):
                                raw_json = raw_json[7:]

                            if raw_json.endswith("```"):
                                raw_json = raw_json[:-3]

                            st.session_state.analysis_results = json.loads(raw_json.strip())
                            st.rerun()

                except Exception as e:
                    st.error(f"Ocorreu um erro ao processar a resposta da IA. Detalhes: {e}")


if st.session_state.analysis_results is not None:
    st.success(":white_check_mark: Análise Concluída com Sucesso!")

    for res in st.session_state.analysis_results:
        status_atual = res.get("status", "Não avaliado")

        cor_status = (
            ":large_green_circle:" if status_atual == "Atendido"
            else ":large_yellow_circle:" if "parcialmente" in status_atual.lower()
            else ":white_circle:" if "não aplicável" in status_atual.lower()
            else ":red_circle:"
        )

        with st.expander(f"{res.get('id')}. {res.get('item')} - {cor_status} {status_atual}"):
            st.write(res.get("justificativa", "Sem justificativa."))

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
