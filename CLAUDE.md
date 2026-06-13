# Sistema de Revisão de Roteiros — Viral Media Labs

## O que é este projeto
Sistema multi-agente para revisão de roteiros de Reels (vídeos curtos).
Cada roteiro passa por **9 agentes especializados em paralelo**; um agente consolidador
sintetiza tudo, emite o veredicto e gera os relatórios.

A saída principal é um **relatório de correções em tabela** (Google Docs nativo, com
fallback `.md` local): cada achado tem linha, ponto exato, tipo, sugestão de correção,
importância % e prioridade (⛔ Obrigatória / ✨ Opcional).

## Estrutura do projeto
```
roteiro-revisor/
├── CLAUDE.md                ← este arquivo (instruções para você, Claude Code)
├── ATUALIZACOES.md          ← changelog: PENDENTES→PUBLICADAS; "gerar mensagem de update" anuncia aos sócios e zera pendentes (protocolo no topo do arquivo)
├── preferencias.md          ← REGRAS DA CASA: guia de estilo do editor, injetado em todo agente
├── revisar.py               ← script principal — PONTO DE ENTRADA
├── interface.py             ← interface gráfica: URL do Doc + progresso real dos agentes → Tabela Interativa
├── Revisor.bat              ← duplo clique no Windows: abre a interface gráfica
├── Revisor.command          ← duplo clique no Mac: abre a interface gráfica
├── relatorio_correcoes.py   ← gera a tabela de correções em .md
├── relatorio_gdocs.py       ← gera a tabela de correções como Google Doc nativo
├── aplicar_gdocs.py         ← (alternativo) escreve notas no corpo de uma cópia do Doc
├── feedback.py              ← suas rejeições viram regras novas no preferencias.md
├── ledger.py                ← ledger de decisões (decisoes.jsonl) — fundação do aprendizado
├── roadmap_aprendizado.md   ← plano em camadas para elevar o aprendizado do sistema
├── google_docs.py           ← leitura de roteiros de Google Docs + auth OAuth
├── agentes/
│   ├── __init__.py          ← AgenteBase: contrato de achados estruturados (JSON via tool use)
│   ├── ortografia.py        ← Ortografia/Gramática PT-BR (objetivo)
│   ├── clareza.py           ← Clareza/Ritmo para locução
│   ├── coerencia.py         ← Coerência/Continuidade: entendimento E sentimento (usa o playbook)
│   ├── checklist.py         ← Critérios do checklist VML
│   ├── storytelling.py      ← Estrutura narrativa (playbook + CODEX)
│   ├── factcheck.py         ← Verifica fatos, dados, datas
│   ├── hook.py              ← Avalia e otimiza o hook
│   ├── cta.py               ← Avalia e otimiza o CTA (CTA com Esteróides)
│   ├── viral.py             ← Potencial viral (CODEX Narrativas)
│   └── consolidador.py      ← Dedup + veredicto por regra + relatório
├── pdfs/                     ← fonte da verdade (NÃO modificar)
│   ├── Checklist Codex V1.pdf
│   ├── Playbook Storytelling.pdf
│   ├── Playbook Hooks.pdf
│   └── Playbook Comandos.pdf
├── roteiros/                 ← roteiros em .txt
├── relatorios/              ← saídas: revisao_*.txt, revisao_*.json, correcoes_*.md
└── credentials/             ← OAuth do Google (token.pickle leitura, token_write.pickle escrita)
```

## Como usar
```bash
python3 interface.py                                 # interface gráfica (ou duplo clique em Revisor.bat / Revisor.command)
python3 revisar.py                                   # modo interativo (cola o texto)
python3 revisar.py --arquivo roteiros/exemplo.txt    # arquivo .txt
python3 revisar.py --gdocs "<link do Google Doc>"    # lê do Google Docs
# No fim, gera automaticamente a tabela de correções (Google Doc).

python3 relatorio_gdocs.py relatorios/revisao_X.json     # (re)gerar a tabela no Docs
python3 feedback.py                                       # ensinar o gosto (rejeições → regras)
```

## Arquitetura — como funciona
1. `carregar_pdfs()` extrai os PDFs (busca pelos nomes reais; fallback p/ critérios padrão).
2. Cada agente recebe o roteiro e devolve **achados ESTRUTURADOS** (não texto livre):
   `{severidade, natureza, confianca, trecho_original, correcao, porque}` — formato forçado
   via tool use. A `camada` é carimbada pelo agente. O `preferencias.md` entra no system prompt.
3. `consolidador.py` é DETERMINÍSTICO: deduplica achados pelo trecho, ordena por
   severidade×confiança, e calcula o veredicto POR REGRA. Só uma LLM call no fim, para a síntese.
4. Relatórios salvos em `relatorios/` (txt + json) e a tabela de correções no Google Docs.

## Filosofia de calibração (IMPORTANTE)
- **Só ERRO OBJETIVO de alta confiança (≥70%) bloqueia** o veredicto. Sugestão subjetiva é
  sempre menu opcional — nunca empurrar gosto como se fosse regra.
- Cada achado é `objetivo` (indiscutível: ortografia, fato, gap referencial) ou `subjetivo`
  (estilo, intensidade emocional). Mantenha essa separação.
- **Calibração vive no `preferencias.md`**, não nos prompts. Antes de mudar o comportamento
  de um agente, prefira ajustar o `preferencias.md` (ou rodar `feedback.py`).
- Ao sugerir storytelling/hook/cta/coerência: **nunca reescrever a voz do autor** — cortar
  gordura e apontar o que falta, sem deixar o roteiro genérico.

## Camada de Coerência (entendimento + sentimento)
O agente `coerencia.py` audita coesão em duas dimensões e marca cada achado com
`[Entendimento]` (lógica: entidade usada antes de introduzir, salto causal, setup sem payoff)
ou `[Sentimento]`. A parte de SENTIMENTO usa o Playbook de Storytelling: cada estrutura do
CODEX só dispara sua emoção se beats específicos existirem (ex.: Jornada do Herói sem decisão
contraintuitiva = história comum; Davi-Golias sem Golias quantificado = sem catarse). Roteiros
precisam DESPERTAR SENTIMENTO, não só fazer sentido.

## Regras importantes para o Claude Code
- NUNCA modifique os arquivos da pasta `pdfs/` — são a fonte da verdade.
- Sempre preserve os relatórios anteriores em `relatorios/`.
- O `preferencias.md` é editável pelo usuário e tem prioridade sobre recomendações genéricas.
- O Playbook de Storytelling é a fonte de verdade do CODEX: 14 estruturas VALIDADAS +
  5 SUGERIDAS em 6 macrogrupos (Arquétipos de Herói; Batalha e Poder; Revelação e Segredo;
  Alarme e Impacto; Insight e Contradição; Ruptura e Consequência Pessoal). A lista vive em
  `agentes/codex.py` (fonte ÚNICA — nunca duplicar em prompts; storytelling, viral e
  contexto importam de lá).
- `ledger.py` + `decisoes.jsonl`: toda decisão do editor (aplicar/editar/pular, com motivo,
  cliente e estrutura CODEX) é registrada em log append-only — fundação do aprendizado
  (ver `roadmap_aprendizado.md`). NUNCA apagar o `decisoes.jsonl`.
# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
