# Revisor de Roteiros — Viral Media Labs

Sistema multi-agente para revisão de roteiros de Reels.
5 agentes especializados rodam em paralelo e um consolidador gera o relatório final.

---

## Instalação (primeira vez)

### Pré-requisitos
- Mac com macOS 13+
- Python 3.10 ou superior
- Conta Anthropic com API key ([obter aqui](https://console.anthropic.com/settings/keys))
- Claude Code instalado

### Passos

```bash
# 1. Abra o Terminal (Cmd + Espaço → "Terminal")

# 2. Navegue até a pasta do projeto
cd ~/roteiro-revisor    # ou onde você colocou a pasta

# 3. Execute o setup (só precisa fazer uma vez)
bash setup.sh
```

O setup vai:
- Verificar o Python
- Instalar as dependências (anthropic, pdfplumber)
- Configurar sua API key
- Verificar os PDFs

---

## Adicionando os PDFs

Copie seus PDFs para a pasta `pdfs/` com estes nomes exatos:

| Arquivo | Descrição |
|---------|-----------|
| `pdfs/checklist.pdf` | Checklist de qualidade VML |
| `pdfs/storytelling.pdf` | Playbook de storytelling |
| `pdfs/hooks.pdf` | Guia de hooks |

Se os PDFs não forem encontrados, o sistema usa critérios padrão (ainda funciona, mas é menos personalizado).

---

## Como usar

### Modo 1 — Cole o texto (uso principal)

```bash
python3 revisar.py
```

O sistema vai pedir para você colar os roteiros. Cole e pressione `Ctrl+D` para iniciar.

### Modo 2 — Arquivo com múltiplos roteiros

```bash
python3 revisar.py --arquivo roteiros/meu_arquivo.txt
```

### Modo 3 — Testar com exemplos

```bash
python3 revisar.py --arquivo roteiros/exemplo.txt
```

---

## Formato do documento com múltiplos roteiros

Para revisar vários roteiros de uma vez, separe-os com `---`:

```
ROTEIRO 1
Título do primeiro roteiro

Texto do primeiro roteiro...

---

ROTEIRO 2
Título do segundo roteiro

Texto do segundo roteiro...
```

O sistema detecta automaticamente e processa cada um individualmente.

---

## Entendendo o relatório

Cada roteiro recebe um relatório com:

```
VEREDICTO: APROVADO / APROVADO COM AJUSTES / REPROVADO

PAINEL DOS AGENTES (5 agentes):
- Checklist        ✅ / ❌ + nota
- Storytelling     ✅ / ❌ + nota
- Fact-Check       ✅ / ❌ + nota
- Hook             ✅ / ❌ + nota
- Potencial Viral  X/10

CORREÇÕES OBRIGATÓRIAS (o que impede a publicação)
OTIMIZAÇÕES RECOMENDADAS (melhorias opcionais)
HOOK RECOMENDADO (versão melhorada do gancho)
DIAGNÓSTICO VIRAL
```

Os relatórios são salvos automaticamente em `relatorios/` com timestamp.

---

## Usando com Claude Code

Abra a pasta do projeto no terminal e inicie o Claude Code:

```bash
cd ~/roteiro-revisor
claude
```

Dentro do Claude Code você pode pedir:
- "Revisa o arquivo roteiros/semana1.txt"
- "Adiciona um agente que verifica o CTA do roteiro"
- "Mostra o histórico dos últimos relatórios"
- "Conecta com Google Docs"

---

## Estrutura do projeto

```
roteiro-revisor/
├── CLAUDE.md              ← instruções para o Claude Code
├── revisar.py             ← script principal
├── setup.sh               ← configuração inicial
├── requirements.txt       ← dependências Python
├── agentes/
│   ├── __init__.py        ← classe base dos agentes
│   ├── checklist.py       ← Agente 1: checklist VML
│   ├── storytelling.py    ← Agente 2: estrutura narrativa
│   ├── factcheck.py       ← Agente 3: verificação de fatos
│   ├── hook.py            ← Agente 4: análise e otimização do hook
│   ├── viral.py           ← Agente 5: potencial viral (CODEX)
│   ├── cta.py             ← Agente 6: avalia e otimiza o CTA
│   └── consolidador.py    ← Agente final: relatório unificado
├── pdfs/
│   ├── checklist.pdf      ← coloque aqui
│   ├── storytelling.pdf   ← coloque aqui
│   └── hooks.pdf          ← coloque aqui
├── roteiros/
│   └── exemplo.txt        ← roteiros de exemplo para teste
└── relatorios/            ← relatórios gerados (criado automaticamente)
```

---

## Roadmap

- [x] Fase 1: Sistema funcionando no terminal
- [ ] Fase 2: Interface web (sem precisar do terminal)
- [ ] Fase 3: Integração com Google Docs
- [ ] Fase 4: Conexão com base de dados viral (resultados históricos)
