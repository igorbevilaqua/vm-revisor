#!/usr/bin/env python3
"""
Aprendizados do editor — armazenamento estruturado, indexado por contexto.

Substitui a injeção monolítica do preferencias.md: cada aprendizado é um
registro com metadados de contexto (escopo global/cliente, tema, estrutura
CODEX, camada, origem), e cada agente recebe na injeção SÓ o que é relevante
para a camada dele e para o contexto do roteiro em revisão.

Armazenamento: aprendizados.json (lista de registros, versionável em git).
JSON em vez de SQLite: volume esperado de centenas de registros curtos,
escritos uma vez por sessão por um único editor — sem consulta relacional
além de filtro linear, sem concorrência de escrita. JSON dá diff legível no
git e edição manual (mesma filosofia do preferencias.md); SQLite só pagaria
com milhares de registros + escritores concorrentes.

Formato de cada registro:
    {"id": "apr_2026_0142",
     "texto": "Siglas tributárias avançadas precisam de aposto explicativo",
     "escopo": "global" | "cliente",
     "cliente": "Dilson Peres" | null,
     "tema": "tributário" | null,
     "estrutura_codex": "Davi e Golias" | null,
     "camada": "clareza" | null (= todas),
     "origem": "pular" | "editar" | "aplicar" | "manual",
     "criado_em": "2026-06-12",
     "ativo": true}

Enquanto aprendizados.json NÃO existir, os agentes continuam injetando o
preferencias.md inteiro (fallback automático — nada muda sem a migração).

Uso CLI:
    python3 aprendizados.py --migrar   # importa as regras do preferencias.md
    python3 aprendizados.py --listar   # mostra os aprendizados ativos
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).parent
# Log append-only (um snapshot de registro por linha), NÃO um array reescrito.
# Motivo: o arquivo é versionado em git e usado por várias pessoas. Append-only
# + `merge=union` no .gitattributes faz os aprendizados de cada um SOMAREM no
# merge, em vez de um commit sobrescrever o do outro. Mesma filosofia do ledger.
ARQUIVO = RAIZ / "aprendizados.jsonl"
PREFERENCIAS_PATH = RAIZ / "preferencias.md"


def _legado() -> Path:
    """Caminho do formato antigo (array .json), para conversão automática."""
    return ARQUIVO.with_suffix(".json")

_lock = threading.Lock()

CAMADAS = {"ortografia", "clareza", "coerencia", "checklist", "storytelling",
           "factcheck", "hook", "cta", "viral"}

# ─── Carrega API key do config.txt se não estiver no ambiente ─────────────────
_CONFIG_PATH = RAIZ / "config.txt"
if not os.environ.get("ANTHROPIC_API_KEY") and _CONFIG_PATH.exists():
    for _linha in _CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        if _linha.startswith("ANTHROPIC_API_KEY="):
            _valor = _linha.split("=", 1)[1].strip()
            if _valor and _valor != "cole-sua-chave-aqui":
                os.environ["ANTHROPIC_API_KEY"] = _valor
            break


# ─── Armazenamento ────────────────────────────────────────────────────────────

def existe() -> bool:
    return ARQUIVO.exists() or _legado().exists()


def _novo_id() -> str:
    """Id globalmente único (não sequencial) — evita colisão entre pessoas
    diferentes que adicionam aprendizados no mesmo período, antes do merge."""
    import uuid
    return f"apr_{date.today().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def _ler_snapshots() -> list[dict]:
    """Snapshots na ordem do arquivo. Prefere o .jsonl; cai no .json legado."""
    if ARQUIVO.exists():
        out = []
        for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                out.append(json.loads(linha))
            except ValueError:
                continue
        return out
    leg = _legado()
    if leg.exists():
        try:
            dados = json.loads(leg.read_text(encoding="utf-8"))
            return dados if isinstance(dados, list) else []
        except (ValueError, OSError):
            return []
    return []


def carregar() -> list[dict]:
    """Estado atual: o ÚLTIMO snapshot de cada id vence (igual ao ledger). Como
    cada mudança (criar, desativar, promover, recusar) é um append do registro
    inteiro, ler é dobrar o log por id. Ordem = primeira aparição de cada id."""
    por_id, ordem = {}, []
    for reg in _ler_snapshots():
        rid = reg.get("id")
        if not rid:
            continue
        if rid not in por_id:
            ordem.append(rid)
        por_id[rid] = reg
    return [por_id[i] for i in ordem]


def _append(registros: list[dict]):
    """Acrescenta snapshots ao fim do log (append-only → merge git somável).
    Na primeira escrita, converte o array .json legado para .jsonl sem perder nada."""
    if not registros:
        return
    leg = _legado()
    if not ARQUIVO.exists() and leg.exists():
        base = _ler_snapshots()  # lê do legado antes de criar o .jsonl
        with ARQUIVO.open("w", encoding="utf-8") as f:
            for r in base:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        leg.rename(leg.with_suffix(".json.migrado"))  # backup do formato antigo
    with ARQUIVO.open("a", encoding="utf-8") as f:
        for r in registros:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _normalizar(item: dict) -> dict | None:
    """Normaliza um registro de entrada; None se não tem texto aproveitável."""
    texto = (item.get("texto") or "").strip()
    if not texto:
        return None
    escopo = item.get("escopo") if item.get("escopo") in ("global", "cliente") else "global"
    cliente = (item.get("cliente") or "").strip() or None
    if escopo == "cliente" and not cliente:
        escopo = "global"  # escopo cliente sem cliente identificado não filtra nada
    camada = (item.get("camada") or "").strip().lower() or None
    if camada and camada not in CAMADAS:
        camada = None
    reg = {
        "texto": texto,
        "escopo": escopo,
        "cliente": cliente if escopo == "cliente" else None,
        "tema": (item.get("tema") or "").strip() or None,
        "estrutura_codex": (item.get("estrutura_codex") or "").strip() or None,
        "camada": camada,
        "origem": item.get("origem") if item.get("origem") in
                  ("pular", "editar", "aplicar", "manual", "promocao") else "manual",
        "criado_em": item.get("criado_em") or date.today().isoformat(),
        "ativo": True,
    }
    mot = (item.get("motivacao") or "").strip()
    if mot:
        reg["motivacao"] = mot  # por que o editor fez a mudança (auditoria/contexto)
    return reg


def adicionar(novos: list[dict]) -> list[dict]:
    """Acrescenta registros ao log (atribui ids únicos). Retorna os salvos."""
    with _lock:
        salvos = []
        for item in novos:
            reg = _normalizar(item)
            if reg is None:
                continue
            salvos.append({"id": _novo_id(), **reg})
        _append(salvos)
        return salvos


# ─── Injeção nos agentes (filtro por contexto) ────────────────────────────────

def _bate(valor_registro: str | None, valor_contexto: str | None) -> bool:
    """Um registro com dimensão preenchida só entra quando o contexto bate
    (match frouxo: substring, sem caixa). Dimensão vazia = vale sempre."""
    if not valor_registro:
        return True
    if not valor_contexto:
        return False
    a, b = valor_registro.strip().lower(), valor_contexto.strip().lower()
    return a in b or b in a


def filtrar(camada: str = "", cliente: str = "", tema: str = "",
            estrutura: str = "") -> list[dict]:
    """Aprendizados ativos relevantes para o agente `camada` no contexto dado:
    globais + do cliente atual + do tema/estrutura quando identificáveis."""
    if estrutura and estrutura.strip().lower() == "indefinida":
        estrutura = ""
    out = []
    for a in carregar():
        if not a.get("ativo", True):
            continue
        if a.get("camada") and camada and a["camada"] != camada:
            continue
        if a.get("escopo") == "cliente" and not _bate(a.get("cliente"), cliente):
            continue
        if not _bate(a.get("tema"), tema):
            continue
        if not _bate(a.get("estrutura_codex"), estrutura):
            continue
        out.append(a)
    return out


def corpo_para_prompt(camada: str = "", cliente: str = "", tema: str = "",
                      estrutura: str = "") -> str | None:
    """Bloco de texto dos aprendizados relevantes, para o system prompt.
    None = armazenamento ainda não existe (chamador usa o preferencias.md legado).
    String vazia = existe mas nada se aplica a este contexto."""
    if not existe():
        return None
    itens = filtrar(camada=camada, cliente=cliente, tema=tema, estrutura=estrutura)
    linhas = []
    for a in itens:
        texto = a["texto"].strip()
        # Multi-linha: continuação indentada para manter o item legível como bullet
        texto = texto.replace("\n", "\n  ")
        ctx = []
        if a.get("escopo") == "cliente" and a.get("cliente"):
            ctx.append(f"cliente {a['cliente']}")
        if a.get("tema"):
            ctx.append(f"tema {a['tema']}")
        if a.get("estrutura_codex"):
            ctx.append(f"estrutura {a['estrutura_codex']}")
        sufixo = f"  [{' · '.join(ctx)}]" if ctx else ""
        linhas.append(f"- {texto}{sufixo}")
    return "\n".join(linhas)


# ─── Parte 2: sinais da sessão → aprendizados candidatos ─────────────────────

def compilar_sinais(roteiros_raw: list[dict], edicoes_avulsas: list[dict] = None) -> list[dict]:
    """Extrai os três tipos de sinal das decisões persistidas nos roteiros:
      pular   → sinal negativo (sugestão descartada)
      editar  → refinamento (sugerido vs versão final do editor — o mais rico)
      aplicar → reforço positivo (o agente acertou)
    `edicoes_avulsas`: edições de linhas de leitura § (texto original → versão do
    editor) que não são achados de agente, mas também são edições do usuário."""
    import ledger
    sinais = []
    for e in edicoes_avulsas or []:
        if not isinstance(e, dict):
            continue
        orig = (e.get("trecho_original") or "").strip()
        nova = (e.get("decisao") or e.get("versao_editor") or "").strip()
        if not orig or not nova or orig == nova:
            continue
        sinais.append({
            "cliente": e.get("cliente") or "", "tema": e.get("tema") or "",
            "estrutura": e.get("estrutura") or "", "roteiro": e.get("roteiro") or "",
            "tipo": "editar", "camada": "", "natureza": "subjetivo", "severidade": "",
            "trecho": orig, "correcao_agente": "",  # sem sugestão de agente: reescrita do zero
            "versao_editor": nova, "porque_agente": "",
            "motivo": e.get("motivo") or "",
        })
    for rot in roteiros_raw or []:
        if not isinstance(rot, dict):
            continue
        ctx = rot.get("contexto") or {}
        base = {
            "cliente": rot.get("cliente") or "",
            "tema": ctx.get("tema") or "",
            "estrutura": ctx.get("estrutura") or "",
            "roteiro": rot.get("titulo", ""),
        }
        for a in rot.get("consolidado", {}).get("achados", []):
            if not isinstance(a, dict) or "decisao" not in a:
                continue
            dec, versao = ledger.normalizar_decisao(a.get("decisao"), a.get("correcao", ""))
            if dec == "resetado":
                continue
            tipo = {"pulado": "pular", "editado": "editar", "aplicado": "aplicar"}[dec]
            sinais.append({
                **base,
                "tipo": tipo,
                "camada": a.get("camada", ""),
                "natureza": a.get("natureza", ""),
                "severidade": a.get("severidade", ""),
                "trecho": a.get("trecho_original", ""),
                "correcao_agente": a.get("correcao", ""),
                "versao_editor": versao,
                "porque_agente": a.get("porque", ""),
                "motivo": a.get("motivo_decisao", ""),
            })
    return sinais


_SCHEMA_CANDIDATOS = {
    "type": "object",
    "properties": {
        "aprendizados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string",
                              "description": "A LIÇÃO em 1-2 frases, PT-BR, acionável. Para generalizável é a regra; para pontual é o que aquela edição específica ensina."},
                    "motivacao": {"type": "string",
                                  "description": "A provável MOTIVAÇÃO do editor para a mudança, em 1 frase. Se houver 'motivo do editor' no sinal (feedback real que ele deu), use-o em vez de inferir."},
                    "generalizavel": {"type": "boolean",
                                      "description": "true = a lição vira REGRA para roteiros futuros (preferência de estilo/voz/calibração que se repete). false = ajuste PONTUAL, vale só aquele trecho (ex.: corrigir um nome, um dado específico)."},
                    "trecho": {"type": "string",
                               "description": "Trecho curto (≤80 car.) a que a lição se refere, para ancorar visualmente. '' se a lição é geral."},
                    "escopo": {"type": "string", "enum": ["global", "cliente"],
                               "description": "cliente = gosto/voz deste cliente; global = vale para qualquer roteiro."},
                    "tema": {"type": "string",
                             "description": "Tema de conteúdo a que se restringe (ex.: 'tributário'), ou '' se geral."},
                    "estrutura_codex": {"type": "string",
                                        "description": "Estrutura CODEX a que se restringe, ou ''."},
                    "camada": {"type": "string",
                               "description": "Agente a que se aplica (ortografia|clareza|coerencia|checklist|storytelling|factcheck|hook|cta|viral) ou '' para todos."},
                    "origem": {"type": "string", "enum": ["pular", "editar", "aplicar"],
                               "description": "Tipo de sinal predominante que gerou esta lição."},
                },
                "required": ["texto", "motivacao", "generalizavel", "trecho", "escopo", "tema", "estrutura_codex", "camada", "origem"],
            },
        },
    },
    "required": ["aprendizados"],
}

_SYSTEM_DESTILAR = """Você analisa as decisões de um editor de roteiros de Reels e extrai a LIÇÃO de cada mudança que ele fez, com a provável MOTIVAÇÃO. O editor vai revisar tudo numa tela antes de salvar.

O sinal mais rico é a EDIÇÃO: a diferença entre o que o agente sugeriu e a versão final do editor revela a preferência dele (o que preservou, suavizou, cortou, reescreveu, e por quê).

Para CADA edição, gere uma lição. Decida se ela é:
- generalizavel=true: uma PREFERÊNCIA que se repete (estilo, voz, calibração de um agente) e vale para roteiros futuros. Ex.: "manter 'pra' em vez de 'para', registro informal é intencional"; "o agente de clareza quebra frases longas demais quando o ritmo é proposital".
- generalizavel=false: um ajuste PONTUAL, que vale só naquele trecho. Ex.: corrigir um nome próprio, trocar um dado específico, um acerto que não vira regra. A lição ainda é registrada (transparência), mas não vira regra dos agentes.

MOTIVAÇÃO: diga por que o editor provavelmente fez a mudança. IMPORTANTE: se o sinal trouxer "motivo do editor" (o feedback real que ele deu, ex.: via Bob), use esse motivo REAL em vez de inferir.

PULADO (sugestão descartada) e APLICADO (agente acertou): contribuem para lições generalizáveis de calibração. Não gere lição pontual de cada pulo/aplicado isolado.

AGRUPE: se várias edições ensinam a MESMA preferência generalizável, funda numa lição só (não repita). Lições pontuais ficam separadas, uma por edição.

Regras:
- escopo: gosto/estilo/voz deste cliente → "cliente"; calibração que vale para qualquer roteiro → "global".
- NUNCA invente preferência que os sinais não sustentam. Não use travessão (—); use vírgula, dois pontos ou conectivo natural.
- Português, direto, começando pelo conteúdo (sem "O editor...")."""


def _fmt_sinal(s: dict) -> str:
    ctx = " · ".join(x for x in (
        f"cliente: {s['cliente']}" if s.get("cliente") else "",
        f"tema: {s['tema']}" if s.get("tema") else "",
        f"estrutura: {s['estrutura']}" if s.get("estrutura") and
        s["estrutura"].lower() != "indefinida" else "",
    ) if x)
    cab = f"[{s.get('camada')} · {s.get('natureza')}" + (f" · {ctx}" if ctx else "") + "]"
    linhas = [f"{cab}"]
    if s.get("trecho"):
        linhas.append(f"  trecho: «{s['trecho'][:160]}»")
    if s.get("correcao_agente"):
        linhas.append(f"  agente sugeriu: «{s['correcao_agente'][:160]}»")
    if s["tipo"] == "editar" and s.get("versao_editor"):
        linhas.append(f"  editor preferiu: «{s['versao_editor'][:160]}»")
    if s.get("motivo"):
        linhas.append(f"  motivo do editor: {s['motivo'][:120]}")
    return "\n".join(linhas)


# Teto de edições por chamada à LLM. Cada edição vira uma lição (~100 tokens de
# saída); acima disso o tool_use poderia truncar e PERDER lições silenciosamente.
# Sessão com mais edições é processada em lotes (1 chamada cada) — nada se perde.
_MAX_EDICOES_POR_LOTE = 20


def _destilar_lote(sinais: list[dict]) -> list[dict]:
    """Uma chamada à LLM para um lote de sinais → lições candidatas (sem ordenar)."""
    import anthropic

    grupos = {"editar": [], "pular": [], "aplicar": []}
    for s in sinais:
        grupos.setdefault(s.get("tipo"), []).append(s)
    blocos = []
    for tipo, titulo in (("editar", "EDITADOS (sugestão do agente vs versão final do editor)"),
                         ("pular", "PULADOS (sugestões descartadas)"),
                         ("aplicar", "APLICADOS (o agente acertou)")):
        if grupos.get(tipo):
            blocos.append(f"## {titulo}\n" + "\n".join(_fmt_sinal(s) for s in grupos[tipo]))
    user = ("Decisões do editor nesta sessão de revisão:\n\n" + "\n\n".join(blocos) +
            "\n\nExtraia a lição de cada edição (e os padrões de pulos/aplicados).")

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        system=_SYSTEM_DESTILAR,
        tools=[{
            "name": "registrar_aprendizados",
            "description": "Registra as lições extraídas das decisões da sessão.",
            "input_schema": _SCHEMA_CANDIDATOS,
        }],
        tool_choice={"type": "tool", "name": "registrar_aprendizados"},
        messages=[{"role": "user", "content": user}],
    )
    candidatos = []
    for bloco in resp.content:
        if bloco.type == "tool_use":
            brutos = bloco.input.get("aprendizados", [])
            if isinstance(brutos, list):
                for c in brutos:
                    if isinstance(c, dict) and (c.get("texto") or "").strip():
                        candidatos.append({
                            "texto": c["texto"].strip(),
                            "motivacao": (c.get("motivacao") or "").strip(),
                            "generalizavel": bool(c.get("generalizavel", True)),
                            "trecho": (c.get("trecho") or "").strip(),
                            "escopo": c.get("escopo") if c.get("escopo") in
                                      ("global", "cliente") else "global",
                            "tema": (c.get("tema") or "").strip(),
                            "estrutura_codex": (c.get("estrutura_codex") or "").strip(),
                            "camada": (c.get("camada") or "").strip().lower(),
                            "origem": c.get("origem") if c.get("origem") in
                                      ("pular", "editar", "aplicar") else "editar",
                        })
            break
    return candidatos


def destilar(sinais: list[dict]) -> list[dict]:
    """Sinais brutos da sessão → lições candidatas (1 lição por edição). Uma
    chamada à LLM no caso comum; se houver muitas edições, processa em lotes
    para não estourar o limite de tokens e perder lições silenciosamente."""
    if not sinais:
        return []
    edicoes = [s for s in sinais if s.get("tipo") == "editar"]
    outros = [s for s in sinais if s.get("tipo") != "editar"]  # pulos/aplicados: agregados
    candidatos = []
    if len(edicoes) <= _MAX_EDICOES_POR_LOTE:
        candidatos = _destilar_lote(edicoes + outros)
    else:
        lotes = [edicoes[i:i + _MAX_EDICOES_POR_LOTE]
                 for i in range(0, len(edicoes), _MAX_EDICOES_POR_LOTE)]
        print(f"  🧠 {len(edicoes)} edições → {len(lotes)} lotes (evita truncar)")
        for idx, lote in enumerate(lotes):
            # pulos/aplicados (poucos, agregados) entram só no 1º lote
            candidatos.extend(_destilar_lote(lote + (outros if idx == 0 else [])))
    # Generalizáveis primeiro (viram regra, pré-marcadas); pontuais depois (recolhidas)
    candidatos.sort(key=lambda c: not c["generalizavel"])
    return candidatos


# ─── Promoção sugerida (aprendizado de cliente que vira global) ──────────────
# Quando a MESMA preferência foi ensinada para clientes DIFERENTES, ela
# provavelmente é um gosto do editor — não específica de um cliente. O sistema
# sugere consolidá-la num único aprendizado global; a decisão é do editor.

def _por_id(id_: str) -> dict | None:
    for a in carregar():
        if a.get("id") == id_:
            return a
    return None


def _atualizar(ids: list[str], **campos):
    """Atualiza campos de registros por id: relê o estado atual e faz APPEND do
    snapshot modificado (a leitura last-wins resolve para a versão nova)."""
    with _lock:
        atual = {a["id"]: a for a in carregar()}
        novos = [{**atual[i], **campos} for i in ids if i in atual]
        _append(novos)


_SCHEMA_CLUSTERS = {
    "type": "object",
    "properties": {
        "grupos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "string"},
                            "description": "ids dos aprendizados que dizem ESSENCIALMENTE a mesma coisa."},
                    "texto_global": {"type": "string",
                                     "description": "A regra reescrita de forma genérica (SEM citar cliente), para valer globalmente."},
                    "camada": {"type": "string",
                               "description": "Camada/agente a que se aplica, ou '' para todos."},
                },
                "required": ["ids", "texto_global", "camada"],
            },
        },
    },
    "required": ["grupos"],
}

_SYSTEM_AGRUPAR = """Você recebe aprendizados que um editor de roteiros ensinou ao revisor, \
cada um associado a um CLIENTE específico. Sua tarefa: agrupar os que expressam \
ESSENCIALMENTE a mesma preferência ou regra, mesmo escritos de forma diferente.

Regras:
- Só agrupe quando for de fato a MESMA ideia (mesma direção, mesmo critério). Na dúvida, \
não agrupe — itens isolados ficam de fora (não precisam de grupo).
- Para cada grupo, reescreva um `texto_global`: a regra de forma genérica, sem citar nenhum \
cliente, pronta para valer em qualquer roteiro.
- Use os ids EXATOS que recebeu. Nunca invente ids.
- Devolva só grupos com 2+ ids. Sessão sem repetição real → 'grupos' vazio."""


def _agrupar_equivalentes(itens: list[dict]) -> list[dict]:
    """LLM: agrupa aprendizados de cliente por equivalência semântica."""
    import anthropic
    lista = "\n".join(
        f"- id={a['id']} | cliente={a.get('cliente')} | camada={a.get('camada') or 'todas'} "
        f"| texto: {a['texto'][:200]}"
        for a in itens
    )
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1200,
        system=_SYSTEM_AGRUPAR,
        tools=[{"name": "registrar_grupos",
                "description": "Registra os grupos de aprendizados equivalentes.",
                "input_schema": _SCHEMA_CLUSTERS}],
        tool_choice={"type": "tool", "name": "registrar_grupos"},
        messages=[{"role": "user", "content":
                   f"Aprendizados (cada um de um cliente):\n{lista}\n\nAgrupe os equivalentes."}],
    )
    ids_validos = {a["id"] for a in itens}
    grupos = []
    for bloco in resp.content:
        if bloco.type == "tool_use":
            for g in bloco.input.get("grupos", []):
                if not isinstance(g, dict):
                    continue
                ids = [i for i in (g.get("ids") or []) if i in ids_validos]
                texto = (g.get("texto_global") or "").strip()
                if len(set(ids)) >= 2 and texto:
                    grupos.append({"ids": list(dict.fromkeys(ids)), "texto_global": texto,
                                   "camada": (g.get("camada") or "").strip().lower() or None})
            break
    return grupos


def detectar_promocoes(novos_ids: list[str] | None = None) -> list[dict]:
    """Sugere aprendizados de cliente que deveriam virar globais — clusters da
    mesma preferência em clientes DIFERENTES. Custo: 1 LLM call, e só quando há
    ≥2 aprendizados de cliente de ≥2 clientes distintos (pré-filtro barato).

    `novos_ids`: quando passado, só retorna clusters que envolvem algum
    aprendizado recém-salvo — assim uma sugestão ignorada não volta toda sessão;
    só reaparece quando a evidência cresce (um cliente novo repete a regra)."""
    itens = [a for a in carregar()
             if a.get("ativo", True) and a.get("escopo") == "cliente"
             and a.get("cliente") and not a.get("nao_promover")]
    if len(itens) < 2 or len({a["cliente"] for a in itens}) < 2:
        return []
    saida = []
    for g in _agrupar_equivalentes(itens):
        membros = [a for a in itens if a["id"] in g["ids"]]
        clientes = sorted({m["cliente"] for m in membros})
        if len(clientes) < 2:
            continue  # mesmo cliente repetindo não é caso de promoção
        if novos_ids and not any(m["id"] in set(novos_ids) for m in membros):
            continue
        saida.append({
            "ids": [m["id"] for m in membros],
            "clientes": clientes,
            "texto_global": g["texto_global"],
            "camada": g["camada"] or (membros[0].get("camada")),
            "exemplos": [{"cliente": m["cliente"], "texto": m["texto"]} for m in membros],
        })
    return saida


def promover(ids: list[str], texto_global: str, camada: str | None = None) -> dict | None:
    """Cria um aprendizado GLOBAL a partir do cluster e desativa os de cliente
    que ele absorve (ficam com `promovido_para` apontando para o novo)."""
    texto_global = (texto_global or "").strip()
    if not texto_global or not ids:
        return None
    with _lock:
        atual = {a["id"]: a for a in carregar()}
        novo = {"id": _novo_id(),
                **_normalizar({"texto": texto_global, "escopo": "global",
                               "camada": camada, "origem": "promocao"})}
        novo["promovido_de"] = list(ids)
        # global novo + snapshots dos de cliente já desativados (absorvidos)
        snapshots = [novo] + [
            {**atual[i], "ativo": False, "promovido_para": novo["id"]}
            for i in ids if i in atual
        ]
        _append(snapshots)
        return novo


def recusar_promocao(ids: list[str]):
    """Marca o cluster como 'não promover' — usado pela varredura CLI para não
    re-sugerir o que o editor já recusou. (Na janela isso é desnecessário: o
    filtro por novos_ids já evita a re-sugestão.)"""
    _atualizar(ids, nao_promover=True)


# ─── Migração do preferencias.md ──────────────────────────────────────────────

# Camada inferida pela seção. None = vale para todos (seções com regras que
# cruzam agentes — [2] fala com factcheck E coerência; [4] vale para todos).
_CAMADA_POR_SECAO = {
    1: None, 2: None, 3: "ortografia", 4: None, 5: "hook",
    6: "cta", 7: "storytelling", 8: "coerencia", 9: None,
}

_RE_SECAO = re.compile(r"^## \[(\d+)\]\s*(.+?)\s*$", re.MULTILINE)
_RE_LINHA_10 = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s*(?:\[([a-zA-Z]+)\]\s*)?(.+)$")


def _e_placeholder(texto: str) -> bool:
    return "placeholder" in texto.lower()


def migrar_preferencias() -> list[dict]:
    """Importa as regras do preferencias.md para a nova estrutura:
    - seções [1]-[9]: cada subseção ### vira UM aprendizado (escopo global,
      camada inferida pela seção); seção sem ### entra inteira como um item.
    - seção [10]: cada linha '- [data] [tag?] regra' vira um aprendizado
      individual (camada da tag, data original preservada).
    O preferencias.md NÃO é alterado — mas deixa de ser injetado nos agentes
    assim que o aprendizados.json passa a existir."""
    if not PREFERENCIAS_PATH.exists():
        print("❌ preferencias.md não encontrado.")
        return []
    texto = PREFERENCIAS_PATH.read_text(encoding="utf-8")

    secoes = []  # (numero, titulo, corpo)
    matches = list(_RE_SECAO.finditer(texto))
    for i, m in enumerate(matches):
        fim = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
        corpo = texto[m.end():fim].strip().strip("-").strip()
        secoes.append((int(m.group(1)), m.group(2).strip(), corpo))

    hoje = date.today().isoformat()
    novos = []
    for num, titulo, corpo in secoes:
        if num == 10:
            for linha in corpo.splitlines():
                m = _RE_LINHA_10.match(linha.strip())
                if not m or _e_placeholder(m.group(3)):
                    continue
                tag = (m.group(2) or "").lower()
                novos.append({
                    "texto": m.group(3).strip(),
                    "escopo": "global",
                    "camada": tag if tag in CAMADAS else None,
                    "origem": "pular",
                    "criado_em": m.group(1),
                })
            continue
        camada = _CAMADA_POR_SECAO.get(num)
        partes = re.split(r"^### ", corpo, flags=re.MULTILINE)
        intro = partes[0].strip()
        subsecoes = [f"### {p.strip()}" for p in partes[1:] if p.strip()]
        if not subsecoes:
            # Seção sem subdivisão (ex.: [1] ESTRUTURA) — entra inteira
            if intro and not _e_placeholder(intro):
                novos.append({"texto": f"{titulo}:\n{intro}", "escopo": "global",
                              "camada": camada, "origem": "manual", "criado_em": hoje})
            continue
        for sub in subsecoes:
            # Remove linhas-placeholder de dentro da subseção
            linhas = [l for l in sub.splitlines() if not _e_placeholder(l)]
            corpo_sub = "\n".join(linhas).strip()
            # Subseção que ficou só com o título (### ...) não tem regra
            if len([l for l in corpo_sub.splitlines() if l.strip()]) <= 1:
                continue
            novos.append({"texto": corpo_sub, "escopo": "global",
                          "camada": camada, "origem": "manual", "criado_em": hoje})

    salvos = adicionar(novos)
    return salvos


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Aprendizados do editor — VML")
    parser.add_argument("--migrar", action="store_true",
                        help="Importa as regras do preferencias.md para aprendizados.json")
    parser.add_argument("--listar", action="store_true",
                        help="Lista os aprendizados ativos")
    parser.add_argument("--promover", action="store_true",
                        help="Varre o acervo e sugere aprendizados de cliente para virar globais")
    args = parser.parse_args()

    if args.migrar:
        if existe() and any(a.get("origem") == "manual" for a in carregar()):
            resp = input(f"⚠️  {ARQUIVO.name} já tem itens. Migrar mesmo assim "
                         "(pode duplicar)? [s/n] → ").strip().lower()
            if resp != "s":
                print("Migração cancelada.")
                raise SystemExit(0)
        salvos = migrar_preferencias()
        print(f"✅ {len(salvos)} aprendizado(s) migrados do preferencias.md → {ARQUIVO.name}")
        print("   A partir de agora os agentes injetam do aprendizados.json (filtrado por")
        print("   camada/cliente/tema). O preferencias.md deixou de ser lido — edições")
        print("   futuras de regras devem ser feitas no aprendizados.json ou pela janela")
        print("   de aprendizados ao fim de cada documento.")
    elif args.promover:
        promos = detectar_promocoes()
        if not promos:
            print("Nenhuma promoção sugerida — não há a mesma preferência repetida "
                  "entre clientes diferentes (ou já foram tratadas).")
            raise SystemExit(0)
        print(f"\n💡 {len(promos)} promoção(ões) sugerida(s):\n")
        for p in promos:
            print(f"   Clientes: {', '.join(p['clientes'])}  ·  camada: {p['camada'] or 'todas'}")
            for e in p["exemplos"]:
                print(f"     – [{e['cliente']}] {e['texto'].splitlines()[0][:80]}")
            print(f"   → global proposto: {p['texto_global']}")
            resp = input("   Promover a global? [s/n] → ").strip().lower()
            if resp == "s":
                novo = promover(p["ids"], p["texto_global"], p["camada"])
                print(f"   ✅ promovido → {novo['id']} (os de cliente foram desativados)\n")
            else:
                recusar_promocao(p["ids"])
                print("   ↪ mantidos separados (não será sugerido de novo)\n")
    elif args.listar or True:
        itens = [a for a in carregar() if a.get("ativo", True)]
        if not itens:
            print("(vazio — rode --migrar ou finalize uma sessão de revisão)")
        for a in itens:
            ctx = " · ".join(x for x in (
                a.get("camada") or "todas",
                f"cliente {a['cliente']}" if a.get("cliente") else "global",
                a.get("tema") or "", a.get("estrutura_codex") or "") if x)
            primeira = a["texto"].splitlines()[0][:90]
            print(f"  {a['id']}  [{ctx}]  {primeira}")
        print(f"\n{len(itens)} aprendizado(s) ativo(s) em {ARQUIVO.name}")
