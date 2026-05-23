import os
import streamlit as st
import json
import google.generativeai as genai

from PIL import Image
from fpdf import FPDF
from pdf2image import convert_from_bytes
import io


# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ZIGURAT-M7-T1", layout="wide") 

# --- 2. GERENCIAMENTO DE ESTADO (SESSION STATE) ---
if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None 

# --- 3. FUNÇÕES AUXILIARES ---
def load_requirements():
    try:
        with open('requisitos_normativos.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        st.error("Arquivo requisitos_normativos.json não encontrado.")
        return None

class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Análise Avançada de Projetos', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 10, 'Baseado nos criterios da NBR 6492', 0, 1, 'C')
        self.ln(5)

def generate_pdf(analysis_results):
    pdf = PDFReport()
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    for item in analysis_results:
        pdf.set_font("Arial", 'B', 11)
        titulo = f"{item['id']}. {item['item']}".encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 10, titulo, 0, 1)

        pdf.set_font("Arial", 'I', 10)
        status = f"Status: {item['status']}".encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 8, status, 0, 1)

        pdf.set_font("Arial", size=10)
        justificativa = f"Justificativa: {item['justificativa']}".encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 5, justificativa)
        pdf.ln(5)

    pdf_out = pdf.output(dest='S')
    if isinstance(pdf_out, str):
        return pdf_out.encode('latin-1', 'replace')
    return bytes(pdf_out)

def nova_analise():
    st.session_state.uploader_key += 1
    st.session_state.analysis_results = None 

# --- 4. INTERFACE DO USUÁRIO ---
st.markdown(
    """
    <div style="display: flex; justify-content: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,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" width="300">
    </div>
    """,
    unsafe_allow_html=True
)
st.title("Análise Avançada de Projetos")
st.write("Auditoria inteligente baseada nos critérios técnicos da NBR 6492.") 

# --- 5. SIDEBAR: CREDENCIAIS E PARÂMETROS ---
with st.sidebar:
    st.header(":gear: Configurações do Sistema")

    # Campo para a Chave API (oculto como senha)
    api_key_input = st.text_input(
    "Chave API do Gemini",
    type="password",
    help="Insira sua chave gerada no Google AI Studio."
)

    # Controle de Temperatura (Criatividade)
    temp_input = st.slider(
        "Criatividade da IA (Temperature)",
        min_value=0.0, max_value=1.0, value=0.1, step=0.1,
        help="Para auditoria técnica, mantenha valores próximos a 0.0 para garantir precisão e evitar alucinações."
    )

    modelos_disponiveis = ["gemini-1.5-flash", "gemini-2.0-flash"]

    # Se o usuário informou a chave, configura a API e busca os modelos reais
    if api_key_input:
        genai.configure(api_key=api_key_input)
        try:
            modelos_dinamicos = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    nome_limpo = m.name.replace('models/', '')
                    if 'flash' in nome_limpo:
                        modelos_dinamicos.append(nome_limpo)
            if modelos_dinamicos:
                modelos_disponiveis = modelos_dinamicos
        except Exception:
            st.error(":warning: Erro: Verifique se sua Chave API está correta.")
            
    model_choice = st.selectbox("Modelo LLM", modelos_disponiveis)
    st.caption("Utilizando modelos 'flash' para análise avançada de projetos.")

# --- 6. FLUXO DE UPLOAD E ANÁLISE ---
# Trava de Segurança: Só libera o uso se a chave API for preenchida
if not api_key_input:
    st.warning(":point_left: Por favor, insira sua Chave API do Gemini na barra lateral para iniciar a aplicação.")
else:
    uploaded_file = st.file_uploader(
        "Arraste a prancha do projeto (.jpeg, .png, .pdf)",
        type=["jpg", "jpeg", "png", "pdf"],
        key=f"uploader_{st.session_state.uploader_key}"
    )
    # ATENÇÃO: Lembre-se de ajustar este caminho do seu Poppler no seu PC
    CAMINHO_POPPLER = r'D:\PERFIL\Área de Trabalho\CODE\POPPLER\Release-26.02.0-0\poppler-26.02.0\Library\bin'
    
    if uploaded_file is not None and st.session_state.analysis_results is None:
        image = None
        if uploaded_file.type == "application/pdf":
            try:
                with st.spinner("Convertendo PDF para imagem de alta resolução..."):
                    file_bytes = uploaded_file.getvalue()
                    images = convert_from_bytes(file_bytes, dpi=300, poppler_path=CAMINHO_POPPLER)
                    if images:
                        image = images[0]
                        st.success("PDF convertido com sucesso!")
            except Exception as e:
                st.error(f"Erro ao processar PDF. Verifique o caminho do Poppler: {e}")
        else:
            image = Image.open(uploaded_file)

        if image is not None:
            st.image(image, caption="Projeto Carregado", use_column_width=True)

            if st.button(":rocket: Executar Análise com IA", type="primary"):
                with st.spinner("a IA está auditando os requisitos técnicos..."):
                    try:
                        data = load_requirements()
                        if data:
                            contexto_normativo = json.dumps(data['requisitos'], ensure_ascii=False)

                            # Configurando o modelo com a temperatura escolhida no Slider
                            model = genai.GenerativeModel(
                                model_name=model_choice,
                                generation_config={
                                    "response_mime_type": "application/json",
                                    "temperature": temp_input
                                }
                            )

                            prompt = f"""
                            Você é um auditor especialista em normas de desenho técnico (NBR 6492).
                            Analise a imagem do projeto técnico anexa e verifique os seguintes 10 requisitos:
                            {contexto_normativo}

                            RETORNE APENAS UM ARRAY JSON VÁLIDO. NÃO INCLUA NENHUM TEXTO FORA DO JSON.
                            Exemplo do formato exigido:
                            [
                              {{
                                "id": 1,
                                "item": "Nome do Item",
                                "status": "Atendido",
                                "justificativa": "Sua justificativa técnica aqui."
                              }}
                            ]
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

# --- 7. EXIBIÇÃO DOS RESULTADOS E BOTÕES ---
if st.session_state.analysis_results is not None:
    st.success(":white_check_mark: Análise Concluída com Sucesso!")

    for res in st.session_state.analysis_results:
        status_atual = res.get('status', 'Não avaliado')
        # Pequena correção para considerar variações de maiúsculas/minúsculas no JSON gerado
        cor_status = (
    ":large_green_circle:" if "Atendido" == status_atual
    else ":large_yellow_circle:" if "Parcialmente" in status_atual.lower()
    else ":white_circle:" if "não aplicável" in status_atual.lower()
    else ":red_circle:"
)
        with st.expander(f"{res.get('id')}. {res.get('item')} - {cor_status} {status_atual}"):
            st.write(res.get('justificativa', 'Sem justificativa.'))

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        pdf_data = generate_pdf(st.session_state.analysis_results)
        st.download_button(
            label=":inbox_tray: Baixar Relatório em PDF",
            data=pdf_data,
            file_name="Análise Avançada de Projetos.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    with col2:
        if st.button(":arrows_counterclockwise: Iniciar Nova Análise", use_container_width=True):
            nova_analise()
            st.rerun()

st.divider()
st.caption("Master em Inteligência Artificial para Arquitetura - ZIGURAT Institute of Technology")