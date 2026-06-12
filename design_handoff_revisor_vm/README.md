# Handoff: Painel de Revisão de Roteiros — VML Revisor (redesenho)

## Overview
Este pacote documenta o redesenho do **painel de revisão de roteiros do VML Revisor**. É a tela onde **agentes de IA apontam "achados"** (correções e sugestões por categoria) em um roteiro, e um **revisor humano** decide, achado por achado, se **Aplica / Edita / Pula / Ensina** a mudança — sempre comparando o texto **ANTES × DEPOIS** lado a lado. Ao final, o roteiro revisado é **gravado no Google Docs**, e o revisor navega para o **próximo roteiro**.

Objetivo do redesenho: manter toda a densidade de informação do sistema atual, mas com a clareza de um produto SaaS moderno (estilo Linear/Notion) — tirando o ruído do terminal monoespaçado e usando cor **só onde ela informa** (o diff e a severidade).

> **Layout único.** Esta versão entrega **uma proposta final** — o layout em **colunas Antes × Depois** (uma tabela limpa, leitura lado a lado, evolução direta do sistema atual). Versões anteriores deste handoff mostravam 3 variações; foram descartadas.

## About the Design Files
Os arquivos deste bundle são **referências de design feitas em HTML** — um protótipo que mostra o visual e o comportamento pretendidos, **não código de produção para copiar diretamente**.

A tarefa é **recriar este design no ambiente do código-alvo** (React, Vue, etc.), usando os padrões, componentes e bibliotecas já estabelecidos no projeto. Se ainda não existe um front-end, escolha o framework mais adequado e implemente lá. O HTML aqui usa um runtime de protótipo próprio (`support.js`, tags `<x-dc>`, `<sc-for>`, `<sc-if>`) que **não deve ir para produção** — é só o motor que faz o protótipo rodar no navegador. Ignore-o e reimplemente a lógica de estado de forma idiomática no seu stack.

## Fidelity
**Alta fidelidade (hifi).** Cores, tipografia, espaçamentos, raios, sombras e interações estão finais. Recrie a UI fielmente usando as bibliotecas/padrões do seu código. Os valores exatos estão na seção **Design Tokens**.

---

## Modelo de dados (o que é um "achado")
Cada achado (`finding`) tem:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | string | Identificador único (ex.: `"f1"`). |
| `n` | number | Número de ordem exibido (1, 2, 3…). |
| `sev` | enum | Severidade: `bloqueante` \| `aviso` \| `sugestao` \| `nota`. Dirige a cor. |
| `cats` | string[] | Categorias/camadas do achado (ex.: `["Hook"]`, `["Coerência","Clareza/Ritmo","Fact-check"]`). |
| `why` | string | Justificativa do agente — por que sugeriu a mudança. |
| `seg` | Segment[] | O diff em si: array de trechos do texto (ver abaixo). |
| `paraAfter` | string? | Opcional. Parágrafo de contexto do roteiro **que vem depois deste achado** e não foi alterado — renderizado em cinza, precedido do separador `§`. |

**Segment** (item de `seg`) — é assim que o diff ANTES/DEPOIS é construído:
```
{ k: 'same' | 'del' | 'ins', t: string }
```
- `same` → texto inalterado (aparece nos dois lados).
- `del` → texto **removido** (só aparece no ANTES).
- `ins` → texto **inserido** (só aparece no DEPOIS; destacado em verde).

A partir de `seg` derivam-se:
- **ANTES** = concatena segmentos `same` + `del`.
- **DEPOIS** = concatena segmentos `same` + `ins` (os `ins` destacados em verde via `<mark>`).
- **Texto puro do DEPOIS** (para preencher o campo de edição) = `same` + `ins` concatenados sem marcação.

> Nota: o layout final usa **colunas separadas** ANTES (esquerda) e DEPOIS (direita). O DEPOIS destaca apenas as inserções em verde. (Não há diff unificado riscado nesta versão — só nas variações descartadas.)

### Severidades (ordem de prioridade e cores)
| Severidade | Rótulo | Accent (barra/ponto) | Fundo do chip | Texto do chip |
|---|---|---|---|---|
| `bloqueante` | Bloqueante | `#DC2626` | `#FEF2F2` | `#B91C1C` |
| `aviso` | Aviso | `#E0A106` | `#FEFBEB` | `#B45309` |
| `sugestao` | Sugestão | `#2563EB` | `#EFF6FF` | `#1D4ED8` |
| `nota` | Nota | `#A1A1AA` | `#F4F4F5` | `#52525B` |

Um achado **bloqueante** representa risco factual alto e, na lógica de negócio, deve travar a aprovação final até ser resolvido.

---

## Estados de cada achado
Cada achado tem um **status** e, opcionalmente, um **painel aberto**:

- **status[id]**: `'pending'` (padrão) → `'applied'` | `'skipped'`. Reversível ("Desfazer"/"Retomar" volta para `pending`).
- **panel[id]**: `null` (padrão) | `'edit'` | `'teach'` — abre uma área extra abaixo do achado.
- **edited[id]**: texto editado pelo revisor. Quando ausente, usa o "texto puro do DEPOIS".

> Em produção há **um único estado por achado** (não há mais a dimensão A/B/C das variações antigas).

### Ações (na coluna AÇÃO de cada linha)
| Ação | Botão | Efeito |
|---|---|---|
| Aplicar | `✓ Aplicar` (verde sólido) | status → `applied`. O texto ANTES esmaece. |
| Editar | `Editar` (outline) | abre painel `edit` com `<textarea>` pré-preenchido com o texto DEPOIS. "Salvar e aplicar" grava a edição e marca `applied`. |
| Pular | `Pular` (outline) | status → `skipped` (toggle: clicar de novo volta a `pending`). Todo o achado esmaece. |
| Ensinar | `Ensinar` (outline roxo) | abre painel `teach` com um `<input>`. Salvar registra uma **preferência do revisor** que torna o agente mais inteligente (deixa de sugerir / passa a sugerir aquele tipo de mudança). Dispara toast de confirmação. |
| Desfazer / Retomar | link sublinhado | volta status para `pending`. |

O botão **Ensinar** é estratégico: alimenta o aprendizado do agente com a preferência do revisor. Recebe um destaque visual sutil (roxo) que o diferencia das ações de aplicação.

---

## Screen / View — Painel de revisão (layout em colunas)

### Estrutura geral
Página com fundo `#F4F4F5`. Conteúdo centrado com `max-width: 1280px` e `padding` lateral 28px.
1. **Cabeçalho da página** (acima do card): logo "VM" (quadrado 26px, fundo `#18181B`, texto branco, raio 7px) + rótulo `VML · REVISOR` (12px, 600, `#A1A1AA`, `letter-spacing:.16em`). Abaixo, título **"Revisão de roteiro"** (24px, 700, `letter-spacing:-.02em`).
2. **Card do painel**: fundo branco, borda `1px solid #E4E4E7`, raio 16px, sombra `0 1px 2px rgba(0,0,0,0.04), 0 16px 40px -28px rgba(0,0,0,0.18)`, `overflow:hidden`. Contém: header → barra de progresso → cabeçalho de colunas → linhas de achados → rodapé.

### Header do card
`padding: 13px 20px`, fundo `#FCFCFD`, borda inferior `1px solid #EFEFF1`, `flex-wrap`.
- **Esquerda:** rótulo `REVISOR` (12px, 600, `#A1A1AA`, `letter-spacing:.12em`) · divisor vertical 1×18px `#E4E4E7` · **seletor de roteiro** (caixa borda `#E4E4E7`, raio 9px, padding `6px 11px`): título do roteiro (13px, 600, `#27272A`, truncado com ellipsis) + chevron `▾`. · **chip de autor**: avatar circular 19px com iniciais (fundo `#DDD6FE`, texto `#6D28D9`) + nome (12px, 500, `#52525B`), tudo num pill `#F4F4F5`.
- **Direita:** **legenda de severidades** (caixa `#FAFAFA`, borda `#F0F0F2`, raio 10px): para cada severidade presente, ponto colorido 7px + contagem (12px, 600) + rótulo (12px, `#A1A1AA`), na ordem bloqueante→aviso→sugestao→nota. · **chip de status geral** "Aprovado com ajustes" (pill amarelo: fundo `#FEFCE8`, borda `#FDE68A`, texto `#A16207`, ponto `#CA8A04`).

### Barra de progresso
`padding: 11px 20px`, fundo branco, borda inferior `1px solid #F0F0F2`.
- `"<done> de <total> aplicadas"` (12.5px, 600; o número `done` em `#16A34A`) · trilho flexível altura 6px raio 999px fundo `#F0F0F2`, preenchimento `#16A34A` (largura = `done/total × 100%`, transição `width .35s ease`) · `"<pending> pendentes"` (12.5px, `#A1A1AA`).

### Cabeçalho de colunas
CSS grid `50px 162px 1fr 1fr 104px`, `gap: 18px`, `padding: 9px 20px`, borda inferior `1px solid #F0F0F2`. Rótulos 10.5px, 600, `#B4B4BB`, `letter-spacing:.08em`: `#` · `CATEGORIA` · `ANTES` · `DEPOIS` · `AÇÃO` (alinhado à direita).

### Linha de achado
Mesmo grid `50px 162px 1fr 1fr 104px`, `gap: 18px`, `padding: 17px 20px`, borda inferior `1px solid #F4F4F5`, `align-items: start`. À esquerda absoluta da linha, **barra vertical de 3px** com a cor da severidade.
- **# (col 1):** número do achado (13px, 600, `#A1A1AA`).
- **CATEGORIA (col 2):** chip de **severidade** (pill colorido com ponto, conforme tabela) empilhado sobre os chips de **categoria** (borda `#E7E7EA`, fundo `#FAFAFA`, raio 6px, texto `#52525B`, 11px, 500).
- **ANTES (col 3):** texto 13.5px / line-height 1.6 / `#52525B`, com **borda esquerda 2px `#F4C2C2`** e `padding-left:12px`. Esmaece (`opacity .4`) quando aplicado.
- **DEPOIS (col 4):** mesmo formato, borda esquerda 2px `#A7E8BE`, cor `#1F2937`; trechos inseridos destacados em verde (ver tokens de diff). Abaixo, a **justificativa** (`why`) em 12px `#A1A1AA`, precedida do glifo `✦` (`#CBCBD0`).
- **AÇÃO (col 5):** botões empilhados (gap 6px) — Aplicar (verde sólido), Editar, Pular, Ensinar. Quando `applied` → selo verde "✓ Aplicado" + link "Desfazer"; quando `skipped` → selo cinza "Pulado" + link "Retomar".
- **Painéis edit/teach:** abrem em linha cheia abaixo do achado, recuados (`padding-left: 68px`), fundo levemente tingido (verde `#F6FBF7`/borda `#D6F0DE` para editar; roxo `#FBF7FE`/borda `#EBD9FB` para ensinar). Cada um tem seu campo + botões "Salvar…" e "Cancelar".
- **Parágrafo de contexto (`paraAfter`):** faixa abaixo do achado, fundo `#FCFCFD`, com separador `§` (`#CBCBD0`) + texto 13px `#9CA3AF`.

### Rodapé do card  *(atualizado)*
`padding: 14px 20px`, fundo `#FCFCFD`, borda superior `1px solid #EFEFF1`, `flex-wrap`, com `justify-content: space-between`.
- **Esquerda — atalhos de teclado:** teclas em "kbd" (Geist Mono 11px, borda `#E4E4E7`, raio 5px, fundo branco, texto `#71717A`): `J / K` navegar · `A` aplicar · `E` editar · `P` pular.
- **Direita — grupo de ações (gap 8px, `flex-wrap`), nesta ordem:**
  1. **`↻ Nova Revisão`** — botão outline (borda `#E4E4E7`, texto `#3F3F46`). Reinicia a sessão (zera status/painéis) e dispara toast.
  2. **`Resetar`** — botão outline (texto `#52525B`). Volta todos os achados a `pending`.
  3. **`Exportar JSON`** — botão outline (texto `#52525B`).
  4. **`Gravar no Google Docs`** — botão **verde sólido** (`#15803D`, hover `#166534`), 13px, 600, com ícone "D" em quadradinho translúcido. Ação primária de saída.
  5. **Divisor vertical** 1×24px `#E4E4E7`.
  6. **`← Roteiro anterior`** — botão outline **desabilitado** quando é o primeiro roteiro (fundo `#FAFAFA`, borda `#EFEFF1`, texto `#C4C4C8`). Habilitado, navega ao roteiro anterior.
  7. **`Próximo roteiro · <nome do próximo>  →`** — botão de **acento azul** (fundo branco, borda `#BFDBFE`, texto `#1D4ED8`, 600, hover fundo `#EFF6FF`), `max-width:260px` com o nome do próximo roteiro truncado. Navega ao próximo roteiro.

---

## Interactions & Behavior
- **Aplicar:** marca `applied`; ANTES esmaece (`opacity .4`, transição `.2s`); barra de progresso anima.
- **Pular:** marca `skipped` (toggle); achado inteiro esmaece (`opacity .5`).
- **Editar:** abre `<textarea>` (min-height ~66px, redimensionável) pré-preenchido com o DEPOIS em texto puro. "Salvar e aplicar" grava `edited[id]` e marca `applied`.
- **Ensinar:** abre `<input>` para registrar uma preferência. Salvar → fecha o painel e dispara **toast** ("Preferência registrada — o agente vai aprender ✓"). Em produção, persistir essa preferência no perfil/modelo do agente.
- **Nova Revisão:** zera status e painéis de todos os achados; toast "Nova revisão iniciada ✓". (Em produção, defina se "nova revisão" recomeça o mesmo roteiro do zero ou solicita ao agente uma nova rodada de achados.)
- **Resetar:** volta todos os achados a `pending` e fecha painéis.
- **Exportar JSON:** exporta o estado das decisões (toast no protótipo; em produção, baixar/POST do payload).
- **Gravar no Google Docs:** toast "Roteiro gravado no Google Docs ✓". Em produção, integra com a API do Google Docs.
- **Roteiro anterior / Próximo roteiro:** navegação entre roteiros da fila. "Anterior" fica desabilitado no primeiro; "Próximo" mostra o nome do roteiro seguinte. (No protótipo disparam toast.)
- **Toast:** caixa escura (`#18181B`, branco) fixa embaixo-centro, some após ~2.4s.
- **Atalhos de teclado** (desenhados, **ainda não implementados** no protótipo): `J/K` navegar, `A` aplicar, `E` editar, `P` pular — implementar de fato no app.
- **Responsivo:** conteúdo centrado em até 1280px; header e rodapé usam `flex-wrap` para quebrar em telas menores (precisa funcionar em notebook/tablet). Em larguras estreitas, considere empilhar as colunas ANTES/DEPOIS verticalmente.

## State Management
Estado mínimo (um só por achado em produção):
- `status[id]`: `'pending' | 'applied' | 'skipped'`.
- `panel[id]`: `null | 'edit' | 'teach'`.
- `edited[id]`: string com o texto editado (ou ausente → usa o DEPOIS original).
- `toast`: mensagem transitória atual (ou `null`).
- Navegação: índice/id do roteiro atual + lista da fila (para anterior/próximo e nome do próximo).

Derivados (computados): contagem de `applied`/`skipped`/`pending`, percentual de progresso, legenda de severidades (contagem por tipo, na ordem bloqueante→aviso→sugestao→nota).

Persistência (backend): carregar roteiro + lista de achados; persistir cada decisão (aplicar/editar/pular); persistir preferências de "Ensinar"; gravar o resultado no Google Docs; controlar a fila de roteiros.

## Design Tokens

**Tipografia** — família `Geist` (sans) para tudo; `Geist Mono` apenas para as teclas de atalho ("kbd"). Substitua pela sans padrão do seu DS se necessário.
- Título da página: 24px / 700 / `letter-spacing:-.02em`.
- Corpo do diff (ANTES/DEPOIS): 13.5px / line-height 1.6.
- Texto auxiliar / justificativa: 12px, `#A1A1AA`.
- Rótulos de coluna: 10.5px / 600 / `letter-spacing:.08em` / `#B4B4BB`.
- Rótulos de seção ("REVISOR", "EDITAR TEXTO REVISADO"…): 10.5–12px / 600–700 / `letter-spacing:.06–.16em`.
- Botões: 12.5–13px / 500–600.

**Cores neutras**
| Uso | Hex |
|---|---|
| Fundo da página | `#F4F4F5` |
| Superfície / card | `#FFFFFF` |
| Superfície sutil (header/footer) | `#FCFCFD` |
| Texto primário | `#18181B` |
| Texto secundário | `#52525B` |
| Texto terciário / hint | `#71717A` / `#A1A1AA` |
| Texto desabilitado / rótulos | `#B4B4BB` / `#C4C4C8` |
| Borda padrão | `#E4E4E7` |
| Borda sutil (divisórias internas) | `#EFEFF1` / `#F0F0F2` / `#F4F4F5` |
| Texto de parágrafo de contexto | `#9CA3AF` |

**Cores de marca / ação**
| Uso | Hex |
|---|---|
| Verde primário (Aplicar / progresso) | `#16A34A` (hover `#15803D`) |
| Verde "Gravar no Docs" | `#15803D` (hover `#166534`) |
| Roxo "Ensinar" (fundo / borda / texto) | `#FAF5FF` / `#EBD9FB` / `#7E22CE` |
| Azul "Próximo roteiro" (borda / texto / hover) | `#BFDBFE` / `#1D4ED8` / `#EFF6FF` |
| Amarelo "Aprovado com ajustes" | fundo `#FEFCE8`, borda `#FDE68A`, texto `#A16207`, ponto `#CA8A04` |

**Diff (destaque de mudança)** — chave do design:
- **Inserção (`ins`)**: `background: rgba(22,163,74,0.14)`, `color:#15803D`, `font-weight:600`, `border-radius:3px`, `padding:0 2px`, `box-decoration-break:clone`. Render com `<mark>`.
- Borda de coluna ANTES: 2px `#F4C2C2` · DEPOIS: 2px `#A7E8BE`.

**Severidades:** ver tabela na seção "Modelo de dados".

**Raios:** botões 7–8px · chips de categoria 6px · pills/severidade 999px · caixas/painéis 9–12px · cards 16px · kbd 5px.

**Sombra do card:** `0 1px 2px rgba(0,0,0,0.04), 0 16px 40px -28px rgba(0,0,0,0.18)`.

**Espaçamento:** base 20px no padding horizontal das linhas/headers; gaps de grid 18px; respiro vertical das linhas 17px.

## Assets
Nenhuma imagem ou ícone externo. Tudo é tipografia, cor e glifos Unicode (`✓ ✦ § ▾ ↻ ← →`). O avatar do autor é um círculo com iniciais. Substitua os glifos por ícones do conjunto de ícones do seu projeto (check, sparkle, chevron, refresh, setas) na implementação real.

## Files
- `Revisor VM - Redesign.dc.html` — protótipo final (layout em colunas Antes × Depois) com interações funcionais e dados de exemplo (roteiro "O Nordeste resolveu a dengue por R$ 0,36", 7 achados). É a referência visual e comportamental definitiva.
- `support.js` — runtime do protótipo. **Não usar em produção**; é só o que faz o `.dc.html` rodar no navegador.

### Como abrir a referência
Abra `Revisor VM - Redesign.dc.html` em um navegador (com `support.js` na mesma pasta).

---

## Como incorporar (passo a passo para o desenvolvedor / Claude Code)
1. **Coloque esta pasta** (`design_handoff_revisor_vm/`) dentro do repositório do seu sistema.
2. **Abra o protótipo** (`Revisor VM - Redesign.dc.html`) no navegador para ver o comportamento-alvo (aplicar, editar, pular, ensinar, navegar, gravar).
3. **No Claude Code**, aponte para esta pasta e peça, por exemplo:
   > *"Implemente o design descrito em `design_handoff_revisor_vm/README.md` (referência visual em `Revisor VM - Redesign.dc.html`) no nosso front-end. Use nossos componentes e estilos existentes. O HTML é só referência — **não** copie `support.js` nem as tags `<x-dc>/<sc-for>/<sc-if>`; reimplemente o estado de forma idiomática."*
4. **Mapeie o modelo de dados** (`finding`, `Segment`, severidades) para os tipos reais da sua API de achados. Comece pela renderização do diff ANTES/DEPOIS — é o coração da tela.
5. **Implemente o estado** por achado (`status`, `panel`, `edited`) e os derivados (progresso, legenda).
6. **Ligue as ações ao backend:** aplicar/editar/pular → persistir decisão; **Ensinar** → persistir preferência do agente; **Gravar no Google Docs** → integração com a API; **anterior/próximo** → navegação na fila de roteiros.
7. **Implemente os atalhos de teclado** (J/K/A/E/P) — estão documentados mas não existem no protótipo.
8. **Aplique seu design system** onde houver equivalentes (botões, chips, pills, ícones), mantendo os tokens de cor do diff e de severidade, que carregam significado.
