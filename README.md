# ZIGURAT M7-T1 - Validação com OpenRouter

Protótipo acadêmico em Python/Streamlit para auditoria técnica de documentos, desenhos e projetos a partir de PDF ou imagem. A análise usa modelos multimodais via OpenRouter e um JSON normativo enviado pelo usuário.

## O que foi implementado

- Modelos A, B e C pré-configurados com uma composição econômica.
- Seletores editáveis para trocar os modelos manualmente pela interface.
- Upload obrigatório de JSON normativo antes da análise.
- Validação básica do JSON enviado: formato, conteúdo vazio e estrutura mínima.
- Prompt de auditoria genérico, sem norma fixa e sem quantidade fixa de requisitos.
- Fluxo de comparação entre Modelo A e Modelo B.
- Modelo C chamado apenas quando houver divergência entre A e B.
- Modelo C atua como juiz de consistência, sem reavaliar a imagem do zero.

## Modelos padrão

- Modelo A: `openai/gpt-5-mini`
- Modelo B: `google/gemini-2.5-flash`
- Modelo C: `anthropic/claude-haiku-4.5`

Se algum ID não estiver disponível na conta ou no catálogo atual do OpenRouter, selecione outro modelo diretamente na barra lateral.

## Variáveis de ambiente

Crie um arquivo `.env` local com:

```env
OPENROUTER_API_KEY=sk-or-v1-sua-chave-aqui
OPENROUTER_MODEL_1=openai/gpt-5-mini
OPENROUTER_MODEL_2=google/gemini-2.5-flash
OPENROUTER_MODEL_3=anthropic/claude-haiku-4.5
OPENROUTER_TIMEOUT=90
```

A chave também pode ser informada na interface da aplicação, no campo protegido da barra lateral.

## Como rodar localmente

```bash
pip install -r requirements.txt
streamlit run M7-T1.py
```

Para PDFs, o pacote `pdf2image` pode exigir Poppler instalado no sistema.

## Estrutura mínima do JSON normativo

O arquivo pode ser uma lista de requisitos:

```json
[
  {
    "id": "R01",
    "requisito": "Identificação do projeto",
    "descricao": "A prancha deve apresentar identificação clara do projeto."
  }
]
```

Ou um objeto com a chave `requisitos`:

```json
{
  "norma": "Exemplo acadêmico",
  "requisitos": [
    {
      "id": "R01",
      "requisito": "Identificação do projeto",
      "descricao": "A prancha deve apresentar identificação clara do projeto."
    }
  ]
}
```

A estrutura enviada não é transformada; ela é usada como contexto normativo do prompt.

## Como testar o fluxo

1. Abrir a aplicação com `streamlit run M7-T1.py`.
2. Informar a chave OpenRouter na interface ou configurar `OPENROUTER_API_KEY` no `.env`.
3. Confirmar que os modelos A, B e C aparecem preenchidos.
4. Enviar um PDF, JPG ou PNG do documento/projeto.
5. Enviar um JSON normativo válido.
6. Executar a análise.
7. Conferir o resultado do Modelo A, Modelo B, comparação, decisão do Modelo C quando houver divergência e resultado final consolidado.

## Arquivos alterados

- `M7-T1.py`
- `.env.example`
- `README.md`

## Limitações conhecidas

- A disponibilidade dos modelos depende do catálogo e permissões da conta OpenRouter.
- O sistema valida apenas uma estrutura mínima do JSON normativo.
- A comparação automática depende da qualidade e consistência do JSON retornado pelos modelos.
- O Modelo C só compara respostas e justificativas dos modelos A e B; ele não recebe a imagem.
- A auditoria não substitui revisão técnica humana.
