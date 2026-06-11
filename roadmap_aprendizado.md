# Roadmap — Tornar o revisor um sistema que APRENDE

> Auditoria de 11/06/2026. Missão: elevar a capacidade do sistema de compreender
> a metodologia e as preferências de revisão — por cliente, por padrão, por contexto.

---

## 1. Diagnóstico central

**O sistema decide bem, mas esquece quase tudo o que vive.**

A cada sessão são gerados sinais riquíssimos — aplicar, editar (com a versão do
editor!), pular, motivos, notas por camada, cliente — e hoje:

| Sinal | Onde nasce | O que acontece com ele |
|---|---|---|
| Aplicar sem edição (acerto do agente) | tabela/dinâmica | **Descartado** (`tabela_interativa.py` — `decisoes_para_ensinamentos` ignora `"aplicado"`) |
| Pular SEM motivo | tabela/dinâmica | **Descartado** (`revisar_dinamico.py:405` exige motivo) |
| Editar (versão do usuário) | tabela/dinâmica | Vira 1 regra textual global, depois o par antes/depois é perdido |
| Cliente | `revisar.py:80`, `google_docs.py:97` | Vai ao JSON e ao CTA; **não entra no aprendizado** |
| 37+ relatórios históricos em `relatorios/` | pipeline | **Nunca relidos** para nada |
| Taxa de aceitação por camada/regra | — | **Não existe** (zero telemetria) |

O único mecanismo de aprendizado é: rejeição+motivo → LLM generaliza → regra de
1 linha no `preferencias.md` seção [10] → injetada em todo agente. Problemas:

1. **Sem cliente**: regra aprendida com a Drielle vale para todos os clientes.
2. **Sem medição**: nenhuma regra sabe quantas vezes "pegou". Cresce sem aposentadoria.
3. **Sem reforço positivo**: o sistema nunca aprende com o que ACERTOU.
4. **Sem padrões**: 5 edições idênticas viram 5 eventos isolados, não um padrão.
5. **Conflitos só na entrada**: regras existentes nunca são re-verificadas entre si.
6. **Regra abstrata > exemplo concreto**: LLMs aprendem melhor com exemplos
   (few-shot) do que com regras genéricas — e o sistema só usa regras.

---

## 2. Princípio de arquitetura

**Toda decisão do editor é um dado. Um dado nunca é descartado — é registrado
uma vez, num formato único, e todas as formas de aprendizado derivam dele.**

```
                       ┌──────────────────────────────┐
  tabela interativa ──▶│                              │──▶ regras (preferencias.md
  revisão dinâmica  ──▶│   LEDGER DE DECISÕES         │     global + por cliente)
  feedback.py       ──▶│   decisoes.jsonl             │──▶ few-shot por agente/cliente
                       │   (append-only, 1 evento     │──▶ padrões recorrentes
                       │    por decisão)              │──▶ telemetria/ciclo de vida
                       └──────────────────────────────┘──▶ calibração do consolidador
```

---

## 3. As camadas

### Camada 0 — Ledger de decisões (`decisoes.jsonl`) — FUNDAÇÃO
Append-only, um evento JSON por decisão, gravado nos mesmos pontos que hoje já
capturam (rota `/api/decisao` da tabela; loop do modo dinâmico; feedback.py):

```json
{"ts": "2026-06-11T15:32:01", "cliente": "drielle", "roteiro_titulo": "...",
 "estrutura_codex": "Davi e Golias", "camada": "hook", "severidade": "aviso",
 "natureza": "subjetivo", "confianca": 85,
 "trecho": "...", "correcao_agente": "...", 
 "decisao": "editar", "versao_usuario": "...", "motivo": "..."}
```

- Inclui **TODAS** as decisões: `aplicado` (reforço positivo), `pular` sem motivo,
  `editar`, `ensinar`. Nada é descartado.
- `estrutura_codex` vem do AgenteContexto (contexto semelhante → padrão semelhante).
- Custo: zero LLM calls. ~50 linhas de código. **Destrava todas as outras camadas.**
- Bootstrap: os `revisao_*.json` históricos que já têm `decisao`/`motivo_decisao`
  (persistidos pela tabela) podem ser importados retroativamente.

### Camada 1 — Cliente como entidade de primeira classe
```
clientes/
├── drielle/
│   ├── perfil.md      ← voz, tom, público, formato, vetos (editável à mão)
│   └── aprendido.md   ← regras aprendidas SÓ deste cliente (mesmo formato da seção [10])
└── _global → preferencias.md continua sendo as regras da casa
```
- Injeção nos agentes: `preferencias.md` (casa) **+** `clientes/<slug>/` (cliente ativo).
  Mesmo mecanismo do `_bloco_preferencias()` — só muda a composição.
- No fim do `loop_aprendizado`, cada regra nova pergunta (1 tecla): **[c]asa ou
  [s]ó este cliente?** — ou infere pela natureza (objetivo → casa; subjetivo → cliente).
- `detectar_cliente` já existe e funciona; falta só normalizar slug e propagar.
- Médio prazo: `perfil.md` alimentado pela entrevista de preferências (já planejada
  em `preferencias_perguntas.md`), seção por seção, sem generalizar além do dito.

### Camada 2 — Ciclo de vida das regras (medir → promover → aposentar)
- Cada regra da seção [10] (e dos `aprendido.md`) ganha um id curto `#r023`.
- Job pós-sessão (determinístico, sobre o ledger): para cada regra, estima
  "atividade" — achados da camada dela seguem sendo rejeitados pelo mesmo motivo?
  (regra inerte) ou a taxa de rejeição daquele padrão caiu? (regra funcionando).
- `limpar_preferencias.py` deixa de ser manual: roda automático a cada N sessões,
  com relatório ("3 regras redundantes, 1 conflito retroativo, 2 candidatas a
  aposentadoria — aprovar? [s/n]"). Decisão final sempre humana.
- Verificação de conflitos passa a ser **retroativa** (todas × todas, periódica),
  não só na inserção.

### Camada 3 — Padrões de correção recorrentes ★ (pedido explícito)
Minerador determinístico sobre o ledger, classificando cada decisão `editar`/`aplicar`
por **tipo de operação**: troca lexical exata, corte de gordura, quebra de parágrafo,
reordenação, mudança de intensidade, etc.

- **Padrão repetido ≥3× com mesma operação** → promoção em dois níveis:
  1. **Determinístico** (troca exata: "porém"→"mas", remoção de travessão): vira
     entrada num `glossario_correcoes.md` aplicado como **pré-pass sem LLM** antes
     dos agentes — correção automática, custo zero, consistência total.
  2. **Estilístico** (padrão de edição, não literal): vira **exemplo few-shot**
     injetado no agente da camada (ver Camada 4).
- Promoção sempre com confirmação humana (alinhado ao princípio de não generalizar
  sem validação) — o minerador APRESENTA o padrão com as N ocorrências; Igor aprova.
- "Contextos semelhantes": o matching usa `cliente` + `estrutura_codex` + `camada`,
  então um padrão da Drielle em roteiros Davi-Golias tem prioridade quando esse
  contexto se repete.

### Camada 4 — Memória nos agentes (few-shot dinâmico)
O upgrade de inteligência mais direto: cada agente passa a receber, além das regras,
**exemplos concretos do próprio editor**, selecionados do ledger:

```
## COMO ESTE EDITOR DECIDE (exemplos reais recentes — siga o padrão)
ACEITO ✓: «trecho» → «correção»            (hook, Drielle)
EDITADO ✎: agente sugeriu «X», editor preferiu «Y». Motivo: ...
REJEITADO ✕: «sugestão». Motivo: "linguagem informal é intencional"
```

- Top-K (2 aceitos + 2 editados + 2 rejeitados) **da camada do agente**, filtrados
  por cliente quando houver, mais recentes primeiro.
- Exemplo concreto ensina o que regra abstrata não alcança: a VOZ do editor.
- Custo: +~400 tokens/agente (entra no bloco cacheável do system prompt).
- **Calibração do consolidador**: a taxa histórica de aceitação por camada (do
  ledger) entra como peso na `_dominancia()` e na ordenação — camada com 30% de
  aceitação para no fim da fila; com 90%, sobe.

### Camada 5 — Medir a inteligência (senão é fé)
- **Painel pós-sessão** (print no terminal, dados do ledger): taxa de aceitação por
  camada nesta sessão vs média histórica, padrões novos detectados, regras ativadas.
- **Golden set de regressão**: 3-5 roteiros já revisados com decisões conhecidas;
  script `avaliar.py` reprocessa e mede: dos achados que o Igor aceitou, quantos o
  sistema ainda encontra? Dos que rejeitou, quantos o sistema ainda sugere?
  Roda antes/depois de qualquer mudança de prompt ou regra → fim do "achismo".

---

## 4. Quick wins da auditoria (independentes do roadmap)

| # | Item | Onde |
|---|---|---|
| 1 | CODEX duplicado (15 estruturas em 2 arquivos) → constante única | `storytelling.py:10`, `viral.py:15` |
| 2 | CLAUDE.md diz 14 estruturas; código tem 15 → alinhar com o playbook | `CLAUDE.md` |
| 3 | AgenteContexto devolve string livre; se erra a estrutura CODEX, os 9 agentes herdam o erro → forçar tool use com schema + campo de confiança | `agentes/contexto.py` |
| 4 | Modo dinâmico não persiste decisões no JSON (a tabela persiste) → unificar | `revisar_dinamico.py` |
| 5 | Conflito retroativo entre regras existentes nunca verificado | `feedback.py:112` |
| 6 | `porque` do agente diluído com o motivo do editor na geração de regra → separar campos | `revisar_dinamico.py:435` |

---

## 5. Ordem de implementação sugerida

| Fase | Entrega | Esforço | Dependências |
|---|---|---|---|
| **1** | Camada 0 (ledger) + bootstrap dos JSONs históricos + quick wins 1-4 | pequeno | — |
| **2** | Camada 1 (clientes: perfil + aprendido + injeção + pergunta casa/cliente) | médio | Fase 1 |
| **3** | Camada 3 (minerador de padrões + glossário pré-pass) | médio | Fase 1 |
| **4** | Camada 4 (few-shot dinâmico + calibração do consolidador) | médio | Fases 1-3 |
| **5** | Camadas 2 e 5 (ciclo de vida + painel + golden set) | médio | Fase 1 |

Custo operacional: Fases 1-3 não adicionam NENHUMA chamada LLM ao pipeline.
A Fase 4 adiciona ~400 tokens cacheáveis por agente. Filosofia mantida: barato,
determinístico onde der, decisão final sempre do editor.
