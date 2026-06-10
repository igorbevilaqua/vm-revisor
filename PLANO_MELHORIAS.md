# Plano de Melhorias — Auditoria de 2026-06-09

Resultado de auditoria completa do projeto. Executar os 5 itens NA ORDEM.
Cada item é independente; commitar separadamente após validar.

---

## Item 1 — CRÍTICO: `input()` dentro de handler HTTP trava o "Gravar no Google Docs"

**Onde:** `revisar_dinamico.py:aplicar_correcoes()` chama
`input("Continuar mesmo assim? [s/n]")` quando um trecho aparece 2+ vezes no doc
(bloco `if avisos:`). Essa função é chamada por `tabela_interativa.py` rota
`/api/apply` — dentro do thread Flask. O prompt aparece no terminal, o usuário
está no browser, o fetch fica pendurado em "Gravando..." para sempre.

**Fix:**
- Adicionar parâmetro `interativo: bool = True` em `aplicar_correcoes()`.
- Se `interativo=False` e houver avisos de múltiplas ocorrências: NÃO chamar
  `input()`. Em vez disso, retornar os avisos junto com o resultado
  (mudar retorno para dict `{"aplicadas": n, "avisos": [...]}` ou similar —
  manter compatibilidade com o chamador do modo dinâmica).
- Em `/api/apply` (tabela_interativa.py), chamar com `interativo=False` e
  devolver os avisos no JSON para o front exibir no toast.

---

## Item 2 — ALTO: veredicto "APROVADO" com agente eliminador morto

**Onde:** `revisar.py:processar_roteiro()` — agente que lança exceção vira
`analises[nome] = "ERRO: ..."`. O `agentes/consolidador.py:consolidar()` só
registra em `falhas_agentes` e calcula o veredicto SEM aquela camada.
Se `ortografia` ou `factcheck` falham (ex.: rate limit 429), o roteiro pode
sair "APROVADO" sem revisão ortográfica/factual.

**Fix em `consolidador.py`:**
- Definir camadas eliminadoras: `{"ortografia", "factcheck", "checklist", "coerencia"}`.
- Se alguma falhou (`falhas_agentes`), o veredicto NUNCA pode ser "APROVADO" —
  rebaixar para "APROVADO COM AJUSTES" e prefixar o diagnóstico com aviso claro:
  "⚠️ Camada X falhou — revisão incompleta, veredicto provisório".
- A função `_veredicto()` deve receber a lista de eliminadores falhos.

---

## Item 3 — ALTO: persistir decisões no servidor + aprendizado na Tabela Interativa

Duas partes complementares:

**3a. Decisões hoje vivem só no localStorage** — fechar a aba antes de "Gravar"
perde tudo. Fix: nova rota `POST /api/decisao` em `tabela_interativa.py`
(payload: `{id, decisao}`), chamada pelo JS a cada clique (aplicar/editar/pular).
O servidor guarda em `self.decisoes` (dict por roteiro) e persiste no JSON do
relatório (campo `decisao` em cada achado do arquivo `revisao_*.json`).

**3b. A Tabela não alimenta o loop de aprendizado** — o modo Dinâmica coleta
`ensinamentos` (pular com motivo, editar com versão do usuário) e roda
`revisar_dinamico.py:loop_aprendizado()`; a Tabela descarta tudo.
Fix: ao final da sessão (em `executar_sessao` / `modo_tabela`), converter as
decisões acumuladas em ensinamentos no MESMO formato do modo dinâmica:
- `pular` → `{**achado, "_tipo_decisao": "pular", "_motivo": ""}`
- decisão editada (decisao != correcao original e != 'aplicado') →
  `{**achado, "_tipo_decisao": "editar", "_correcao_original": correcao,
    "_versao_usuario": decisao, "_motivo": ""}`
- Chamar `loop_aprendizado(ensinamentos)` no fim da sessão da tabela
  (após `server.finalizar()`), igual ao modo dinâmica.

Opcional (se rápido): campo de motivo opcional ao pular no front (prompt
pequeno, Esc ignora) — alimenta `_motivo`.

---

## Item 4 — ALTO: cortes de tokens (~ -43% input por roteiro)

**4a. `agentes/coerencia.py` recebe o playbook storytelling.md inteiro (52KB ≈
14k tokens) E TAMBÉM tem o destilado `MECANISMOS_EMOCIONAIS`** (que existe para
substituí-lo). Fix: em `revisar.py:processar_roteiro()`, instanciar
`AgenteCoerencia("")` (sem o PDF) — o destilado já cobre. `storytelling.py`
continua recebendo a íntegra.

**4b. `bloco_cliente` no system prompt do CTA invalida o cache por cliente.**
`agentes/cta.py:montar_system()` embute `bloco_cliente(cliente)` no system.
Fix: mover o bloco do cliente para o USER prompt (em `analisar()`), mantendo o
system idêntico entre clientes → cache estável.

**4c. Preferências filtradas por camada.** `agentes/__init__.py:_bloco_preferencias()`
injeta o preferencias.md inteiro (12.7KB ≈ 3.4k tokens) em toda chamada.
Fix: convenção de tag por camada nas regras da seção [10] (ex.: `- [2026-06-09]
[ortografia] regra...`); `_bloco_preferencias()` filtra: regras com tag da
própria camada (`self.CAMADA`) + regras sem tag (gerais). Seções [1]-[9] do
arquivo continuam inteiras (são regras gerais da casa).
ATENÇÃO: não quebrar `feedback.py:carregar_regras_existentes()`.

**4d. Modelo por camada:** trocar em 2 agentes:
- `agentes/ortografia.py`: Haiku → Sonnet (`claude-sonnet-4-5`) — é camada
  ELIMINADORA; falso erro de crase do Haiku com confiança 90 reprova o roteiro.
- `agentes/viral.py`: adicionar `MODELO = "claude-haiku-4-5"` — só gera nota e
  sugestões subjetivas que nunca bloqueiam.

---

## Item 5 — ALTO (UX): atalhos de teclado na Tabela Interativa

**Onde:** `tabela_interativa.py`, bloco `<script>` do `_HTML`.

**Fix:** navegação estilo Gmail:
- `J` / `K` (ou ↓/↑): mover foco para a próxima/anterior linha de correção
  (ignorar linhas de seção e contexto). Linha focada ganha classe `.row-focus`
  com borda/outline visível e `scrollIntoView({block:'center'})`.
- `A`: aplicar a correção da linha focada.
- `E`: abrir edição da linha focada (focar o textarea; Esc cancela, Cmd/Ctrl+Enter confirma).
- `P`: pular a linha focada.
- Ignorar atalhos quando o foco está em textarea/input.
- Pequena legenda fixa no footer: `J/K navegar · A aplicar · E editar · P pular`.

---

## Validação ao final de cada item
- `python3 -c "import revisar, tabela_interativa, revisar_dinamico"` (sanity de sintaxe)
- Itens 1-3: revisar manualmente o fluxo afetado.
- Commit por item, mensagem em PT-BR no padrão do repo (`fix:`/`feat:`/`perf:`).
- NÃO tocar na pasta `pdfs/`. Preservar relatórios existentes.
