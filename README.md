# ZIGURAT M7-T1 - Validação com OpenRouter

Protótipo acadêmico em Python/Streamlit para analisar pranchas de projeto com múltiplos modelos de IA via OpenRouter.

## O que foi implementado

- Integração com API OpenRouter por variável de ambiente.
- Análise inicial do mesmo documento com Modelo 1 e Modelo 2.
- Comparação dos resultados por requisito normativo.
- Chamada do Modelo 3 somente quando Modelo 1 e Modelo 2 divergem.
- Modelo 3 atuando apenas como árbitro textual, recebendo requisito, resposta e justificativa dos dois primeiros modelos.
- Resultado final consolidado com indicação de concordância, divergência ou revisão humana necessária.
- Interface Streamlit mostrando respostas, justificativas, decisão do árbitro quando aplicável e resultado final.
- Campo seguro na barra lateral para informar a chave OpenRouter na sessão atual.
- Listas suspensas carregadas a partir do catálogo de modelos disponíveis no OpenRouter.
- Tratamento básico para ausência de chave, falhas de API, timeout, resposta vazia e JSON fora do formato esperado.

## Variáveis de ambiente

Você pode informar a chave diretamente na barra lateral do Streamlit, no campo `Chave API OpenRouter`.

Se preferir deixar a chave configurada localmente, crie um arquivo `.env` com base em `.env.example`:

```env
OPENROUTER_API_KEY=sk-or-v1-sua-chave-aqui
OPENROUTER_MODEL_1=google/gemini-2.0-flash-001
OPENROUTER_MODEL_2=openai/gpt-4o-mini
OPENROUTER_MODEL_3=anthropic/claude-3.5-haiku
OPENROUTER_TIMEOUT=90
```

`OPENROUTER_HTTP_REFERER` é opcional e pode ser usado para identificar a aplicação no OpenRouter.

## Como rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run M7-T1.py
```

No Linux/macOS, use `source .venv/bin/activate` no lugar do comando de ativação do Windows.

## Como testar o fluxo

1. Informe a chave no campo `Chave API OpenRouter` ou configure `OPENROUTER_API_KEY` no arquivo `.env`.
2. Escolha os modelos nas listas suspensas carregadas do OpenRouter.
3. Rode `streamlit run M7-T1.py`.
4. Faça upload de uma imagem ou PDF de prancha técnica.
5. Clique em `Executar Análise com IA`.
6. Verifique, em cada requisito, as respostas dos Modelos 1 e 2.
7. Confirme que o Modelo 3 só aparece em itens com divergência ou necessidade de revisão.
8. Baixe o PDF e confira o resultado final consolidado.

## Arquivos alterados

- `M7-T1.py`: fluxo OpenRouter com dois modelos iniciais, árbitro sob demanda, chave via sidebar e listas suspensas de modelos.
- `requirements.txt`: troca da dependência Gemini por `requests` e `python-dotenv`.
- `.env.example`: variáveis esperadas para OpenRouter.
- `README.md`: documentação curta de uso e teste.

## Limitações conhecidas

- A análise usa apenas a primeira página de PDFs, mantendo o comportamento anterior.
- Os Modelos 1 e 2 precisam aceitar entrada visual para analisar imagem/PDF convertido.
- O Modelo 3 não recebe a imagem nem o PDF, apenas as respostas textuais dos dois primeiros modelos.
- A consolidação depende de respostas em JSON no formato solicitado.
- Se a lista online de modelos do OpenRouter não carregar, a aplicação usa uma lista padrão de fallback.
- Divergências por justificativa com o mesmo status ainda são tratadas como concordância de resultado.

## Pontos de atenção para apresentação acadêmica

- Explique que o Modelo 3 foi desenhado como árbitro, não como terceiro avaliador completo.
- Destaque a economia de chamadas: o árbitro só é acionado quando há discordância.
- Mostre um requisito com concordância e outro com divergência para evidenciar o fluxo.
- Reforce que casos incertos são marcados para revisão humana, preservando rastreabilidade.
