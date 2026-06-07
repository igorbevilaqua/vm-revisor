# Sistema de Revisão de Roteiros — VML — Documento de Arquitetura

> Handoff técnico para outra LLM (ou dev). Descreve como o sistema funciona, as relações
> e hierarquias entre componentes. Para instruções de uso/regras de edição, ver `CLAUDE.md`.
> Para calibração de gosto, ver `preferencias.md`.

## 1. Propósito e formato de saída
Sistema multi-agente que revisa roteiros de Reels (vídeos curtos falados). Cada roteiro passa
por **9 agentes especializados em paralelo**; um **consolidador determinístico** funde os
achados, calcula o veredicto por regra e gera relatórios. A saída de valor é uma **tabela de
correções** (Google Doc nativo, fallback `.md` local), onde cada achado tem trecho, sugestão,
tipo, confiança e prioridade (⛔ obrigatória / ✨ opcional).

## 2. Princípio de calibração (a "constituição" do sistema)
- **Só ERRO + OBJETIVO + confiança ≥70% BLOQUEIA** o veredicto. Todo o resto é menu opcional.
- Cada achado é `objetivo` (indiscutível: ortografia, fato, gap referencial) ou `subjetivo`
  (estilo, intensidade emocional). Nunca empurrar gosto como regra.
- **A calibração vive no `preferencias.md`**, não nos prompts dos agentes. Mudar comportamento
  = editar `preferencias.md` (ou rodar `feedback.py`), não reescrever o agente.

## 3. Fluxo de execução (hierarquia de chamadas)
Ponto de entrada único: **`revisar.py`** → `main()`.

```
revisar.py main()
├── carregar_pdfs()              # carrega base de conhecimento (ver §4)
├── coletar_texto(args)          # --gdocs | --arquivo | --roteiro | stdin
│   └── (gdocs) google_docs.carregar_roteiros_do_gdoc() → lista de roteiros
│   └── (texto) separar_roteiros() → divide por "---", "ROTEIRO N", etc.
├── pula roteiros com "revisado" no título
├── para cada roteiro: processar_roteiro()      # SEQUENCIAL entre roteiros
│   ├── detectar_cliente()       # --cliente > título gdoc > rótulo no texto
│   ├── instancia 9 agentes (alguns recebem fatia da base de conhecimento)
│   ├── factcheck é REMOVIDO se tem_fato_verificavel(texto) == False
│   ├── asyncio.gather(ag.analisar(...) for ag in agentes)   # PARALELO entre agentes
│   │   └── cada agente → dict {achados[], resumo, nota}
│   └── AgenteConsolidador.consolidar(analises)  # ver §7
├── salvar_relatorio() → relatorios/revisao_<ts>.txt + .json
└── relatorio_gdocs.gerar_doc_lista(json) → Google Doc (fallback relatorio_correcoes → .md)
```

**Importante:** roteiros são processados **um a um** (loop sequencial); os **agentes** de um
mesmo roteiro rodam **em paralelo** (`asyncio.gather`).

## 4. Base de conhecimento (`conhecimento/*.md` → fallback `pdfs/`)
`carregar_pdfs()` (nome legado) carrega **markdown limpo** de `conhecimento/`:
- `checklist.md` → agente checklist
- `storytelling.md` → agentes coerência e storytelling
- `hooks.md` → agente hook
- `comandos.md` → agente cta

Se algum `.md` faltar, faz fallback extraindo o PDF correspondente em `pdfs/` via `pdfplumber`.

> ⚠️ Divergência com `CLAUDE.md`: o doc diz que extrai PDFs a cada run; na prática a fonte
> primária hoje é `conhecimento/*.md` (os PDFs são só fallback). Os PDFs em `pdfs/` continuam
> sendo fonte-da-verdade conceitual, mas não são lidos quando o `.md` existe.

## 5. Contrato dos agentes (`agentes/__init__.py` → `AgenteBase`)
Todo agente herda de `AgenteBase`.
- **Modelo:** `claude-sonnet-4-5`, `max_tokens=3000`.
- **Saída FORÇADA via tool use:** a API é chamada com `tool_choice` obrigatório na tool
  `registrar_achados`, cujo `input_schema` é `SCHEMA_ACHADOS`. Garante JSON válido, não texto livre.
- **`SCHEMA_ACHADOS`** — cada achado tem:
  - `severidade`: `erro | aviso | sugestao`
  - `natureza`: `objetivo | subjetivo`
  - `confianca`: 0–100
  - `trecho_original`: **citação literal** do roteiro (âncora p/ substituição no doc). Vazio = global.
  - `correcao`: texto exato que substitui o trecho (ou adição, se trecho vazio).
  - `porque`: justificativa em 1 frase.
  - (+ `resumo` e `nota` 0–10 por camada)
- **`preferencias.md` é injetado em TODO system prompt** via `_bloco_preferencias()`, com
  cabeçalho "REGRAS DA CASA — prioridade máxima". Mecanismo central de calibração.
- **Prompt caching:** system+tools marcados `cache_control: ephemeral` (~5 min).
- **`CAMADA`:** cada agente carimba sua camada em cada achado (em `_rodar`).
- **`SEVERIDADE_MAX`:** capa a severidade de agentes que NÃO são eliminadores (ex.: clareza,
  storytelling, hook, viral, cta tendem a ter teto `aviso`). Por design, **só ortografia,
  factcheck, checklist e coerência-[Entendimento] podem produzir um `erro` bloqueante**. Cada
  agente define seu próprio `SEVERIDADE_MAX`.

## 6. Os 9 agentes (camadas)
Arquivos em `agentes/`. Cada um sobrescreve `analisar()` e tem system prompt próprio.

| Camada | Foco | Pode bloquear? |
|---|---|---|
| `ortografia` | Gramática/ortografia PT-BR (objetivo) | sim |
| `clareza` | Clareza/ritmo para locução | não (otimização) |
| `coerencia` | Coesão em 2 eixos: **[Entendimento]** (lógica) e **[Sentimento]** (emoção via CODEX) | só [Entendimento] |
| `checklist` | Critérios formais do Checklist Codex (ex.: headline ≤9 palavras, fontes) | sim |
| `storytelling` | Estrutura narrativa magnética (CODEX) | não |
| `factcheck` | Verifica fatos/dados/datas; só roda se há fato verificável | sim |
| `hook` | Avalia/otimiza o gancho (lacuna de curiosidade) | não |
| `viral` | Potencial viral (gera `nota_viral`) | não |
| `cta` | Comando final ("CTA com Esteróides"); recebe `cliente` | não |

### Detalhe do agente `coerencia` (o mais sofisticado)
Audita em duas dimensões, marcando cada achado no `porque` com `[Entendimento]` ou `[Sentimento]`:
- **[Entendimento]** = lógica/referencial: entidade usada antes de introduzida, salto causal,
  referência pendurada, setup sem payoff, **e a regra nomeada `COESÃO_ENTRE_FRASES`** (oposição
  de carga semântica entre frases consecutivas sem conectivo adversativo — exceção: soma/reforço).
  É objetivo; pode bloquear se impedir compreensão.
- **[Sentimento]** = emoção: usa o Playbook de Storytelling. Cada estrutura CODEX só dispara sua
  emoção se beats específicos existirem (ex.: Davi-Golias sem Golias quantificado = sem catarse).
  **[Sentimento] NUNCA bloqueia** — `analisar()` rebaixa qualquer `[Sentimento]` com severidade
  `erro` para `aviso`.

## 7. Consolidador (`agentes/consolidador.py`) — DETERMINÍSTICO
Recebe `analises` (dict camada→resultado) e produz o resultado final. **Quase tudo é Python
puro**; só a síntese em prosa usa LLM (Haiku).
- **Dedup (`_deduplicar`):** agrupa achados pelo `trecho_original` normalizado. Funde cada grupo
  usando o achado **dominante** (maior severidade × objetivo × confiança) para motivo/correção;
  severidade/natureza/confiança do merge = **pior caso** do grupo; acumula `camadas` (lista).
  Achados globais (trecho vazio) não são fundidos.
- **Bloqueante (`_e_bloqueante`):** `severidade=="erro" AND natureza=="objetivo" AND confianca>=70`.
- **Notas:** `nota_geral` = média de todas as camadas **exceto viral** (1 casa decimal).
  `nota_viral` = nota do agente viral (separada).
- **Veredicto (`_veredicto`), por regra:**
  - `REPROVADO` se bloqueantes ≥ 3 **ou** nota_geral < 5
  - `APROVADO` se bloqueantes == 0 **e** nota_geral ≥ 8
  - senão `APROVADO COM AJUSTES`
- **Síntese executiva:** 1 chamada LLM em **`claude-haiku-4-5`** (`max_tokens=1200`), system
  `SYSTEM_SINTESE`. Recebe o veredicto **já calculado** — não decide nada nem inventa achados.
- **Saída:** dict com `veredicto, nota_geral, nota_viral, painel, bloqueantes[], otimizacoes[],
  achados[], diagnostico, falhas_agentes, relatorio`.

## 8. Saídas e camada Google Docs
- `relatorios/revisao_<ts>.txt` — relatório legível.
- `relatorios/revisao_<ts>.json` — payload por roteiro: `{numero, titulo, texto, cliente,
  consolidado}`. **Este JSON é a interface** consumida pela tabela de correções, pelo feedback
  e pelo fluxo dinâmico.
- `relatorio_gdocs.gerar_doc_lista(json)` → tabela de correções como Google Doc nativo (fallback
  `relatorio_correcoes.gerar_relatorio` → `.md`).
- **`google_docs.py`** — leitura de roteiros do Doc + auth OAuth. Dois tokens em `credentials/`:
  `token.pickle` (leitura), `token_write.pickle` (escrita). `aplicar_gdocs.py` é via alternativa
  que insere notas ancoradas no corpo de uma cópia.

## 9. Loop de aprendizado (calibração viva)
- **`preferencias.md`** = regras da casa, editável pelo humano, injetado em todo agente. Seções:
  estrutura do roteiro, fontes, anti-fabricação, hipérbole vs precisão, registro falado, precisão
  humilde, ponte didática, cheiro de IA, preferências de hook/CTA, etc.
- **`feedback.py`** — pega rejeições do humano e as transforma em novas regras no `preferencias.md`
  (seção "Aprendido com rejeições").
- **Regra anti-fabricação (crítica):** uma `correcao` NUNCA pode introduzir fato novo (número,
  data, nome, causa). Se um gap exige fato real, a correção vira um **pedido de verificação**,
  não uma invenção.

## 10. Camada interativa (skills do Claude Code, acima do batch)
Não fazem parte do `revisar.py`; são orquestradas por um agente (Claude Code), em
`.claude/skills/`:
- **`revisar-dinamico`** — revisão "ao vivo", parágrafo a parágrafo: roda `revisar.py --gdocs`,
  carrega o JSON, conduz decisão item a item (aplica/edita/pula), aprende racionais
  (→ `preferencias.md`), e ao fim de cada roteiro aplica as correções aprovadas no doc original
  via Docs API `replaceAllText` (matchCase, conferindo 1 ocorrência exata). Regras correntes:
  **Sonnet por padrão, 1 roteiro por vez, antes/depois explícito em cada sugestão**.
- **`humanizer`** — reescreve um trecho para soar humano/falável na voz do autor.

## 11. Invariantes que outra LLM deve respeitar
1. Nunca modificar `pdfs/` (fonte da verdade conceitual).
2. Preservar relatórios anteriores em `relatorios/`.
3. `preferencias.md` tem prioridade sobre qualquer recomendação genérica.
4. Só objetivo + erro + ≥70% bloqueia; subjetivo é sempre opcional.
5. Reescrita pode mudar forma, **nunca** fatos (anti-fabricação).
6. Nunca reescrever a voz do autor — cortar gordura e apontar o que falta.
7. `trecho_original` deve ser citação **literal** (senão a substituição no Doc falha).

## 12. Modelos usados (resumo)
- Agentes de revisão: `claude-sonnet-4-5` (`max_tokens=3000`).
- Síntese do consolidador: `claude-haiku-4-5` (`max_tokens=1200`).
- Veredicto e dedup: Python determinístico (sem LLM).

## Pendência conhecida
Alguns agentes ainda referenciam uma lista antiga de 15 estruturas CODEX; o Playbook atual tem
14 em 6 macrogrupos — alinhar é follow-up.
