#!/usr/bin/env python3
"""
Tabela Interativa — Viral Media Labs
Servidor local + interface web de revisão de correções.

Uso standalone:
    python3 tabela_interativa.py                                 # JSON mais recente
    python3 tabela_interativa.py relatorios/revisao_X.json
    python3 tabela_interativa.py relatorios/revisao_X.json --gdocs "URL"

Integrado via revisar.py → modo [3] Tabela Interativa.
"""

import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

RAIZ = Path(__file__).parent
PASTA_RELATORIOS = RAIZ / "relatorios"

CAMADA_DISPLAY = {
    "ortografia": "Ortografia",
    "clareza": "Clareza/Ritmo",
    "coerencia": "Coerência",
    "checklist": "Checklist",
    "storytelling": "Storytelling",
    "factcheck": "Fact-check",
    "hook": "Hook",
    "viral": "Potencial Viral",
    "cta": "CTA",
    "contexto": "Contexto",
}


# ─── Transformação de dados ───────────────────────────────────────────────────

def _diff_inline(trecho: str, correcao: str) -> bool:
    """True se a mudança real é ≤ 3 palavras (candidato a diff inline)."""
    if not trecho or not correcao or trecho == correcao:
        return False
    pref = 0
    while pref < min(len(trecho), len(correcao)) and trecho[pref] == correcao[pref]:
        pref += 1
    t_rest, c_rest = trecho[pref:], correcao[pref:]
    suf = 0
    while suf < min(len(t_rest), len(c_rest)) and t_rest[-(suf+1)] == c_rest[-(suf+1)]:
        suf += 1
    t_core = t_rest[:len(t_rest)-suf] if suf else t_rest
    c_core = c_rest[:len(c_rest)-suf] if suf else c_rest
    tw = len(t_core.strip().split()) if t_core.strip() else 0
    cw = len(c_core.strip().split()) if c_core.strip() else 0
    return max(tw, cw) <= 3


_VERBOS_INSTRUCAO = {
    "remover", "remove", "substituir", "substitua", "substituindo",
    "reduzir", "reduza", "reduzindo",
    "verificar", "verifique", "verificando",
    "ajustar", "ajuste", "ajustando",
    "reordenar", "reordene",
    "inserir", "insira", "inserindo",
    "trocar", "troque", "trocando",
    "corrigir", "corrija", "corrigindo",
    "adicionar", "adicione", "adicionando",
    "excluir", "exclua", "excluindo",
    "eliminar", "elimine", "eliminando",
    "incluir", "inclua", "incluindo",
    "reescrever", "reescreva", "reescrevendo",
}


import re as _re


def _correcao_e_instrucao(texto):
    """True se o texto é instrução editorial e não um substituto literal.
    Detecta dois padrões:
    1. Começa com verbo de instrução (ex.: 'Verificar o valor...')
    2. Contém placeholder entre colchetes (ex.: 'gastou [verificar: X]')
    """
    if not texto:
        return False
    if texto.strip().split()[0].lower().rstrip(".,;:)") in _VERBOS_INSTRUCAO:
        return True
    if _re.search(r"\[.+?\]", texto):
        return True
    return False


def transformar_achado(achado, idx):
    trecho = (achado.get("trecho_original") or "").strip()
    correcao = (achado.get("correcao") or "").strip()
    porque = (achado.get("porque") or "").strip()

    # Segunda camada de defesa: se `correcao` ainda chegou como instrução editorial
    # (agente ignorou o prompt), zera os dois campos e preserva a nota em `porque`.
    # Achados com trecho="" e correcao="" são descartados em transformar_roteiro.
    if _correcao_e_instrucao(correcao):
        porque = f"{porque} [Sugestão estrutural: {correcao}]".strip()
        trecho = ""
        correcao = ""

    return {
        "id": f"c{idx:03d}",
        "tipo": "correcao",
        "severidade": achado.get("severidade", "sugestao"),
        "natureza": achado.get("natureza", "subjetivo"),
        "camada": CAMADA_DISPLAY.get(achado.get("camada", ""), achado.get("camada", "")),
        "trecho_original": trecho,
        "correcao": correcao,
        "porque": porque,
        "confianca": achado.get("confianca", 0),
        "diff_inline": _diff_inline(trecho, correcao),
        "relacionado_a": None,
        "decisao": None,
    }


def _para_idx_de_achado(trecho: str, texto: str, para_offsets: list[int]) -> int:
    """Retorna o índice do parágrafo onde trecho_original aparece.
    Usa o offset de caracteres no texto inteiro mapeado aos parágrafos.
    Achados sem trecho ou não encontrados ficam no índice len(para_offsets) (fim)."""
    if not trecho or not texto:
        return len(para_offsets)
    pos = texto.find(trecho)
    if pos == -1:
        # Tenta com trecho normalizado (colapsa espaços/quebras)
        trecho_n = " ".join(trecho.split())
        texto_n = " ".join(texto.split())
        pos_n = texto_n.find(trecho_n)
        if pos_n == -1:
            return len(para_offsets)
        # Mapeia posição normalizada de volta ao índice do parágrafo
        pos = pos_n
        offsets = para_offsets  # aproximação aceitável
    else:
        offsets = para_offsets
    for i in range(len(offsets) - 1, -1, -1):
        if pos >= offsets[i]:
            return i
    return 0


MAX_SEG_CHARS = 220  # ~3 linhas visuais por campo Antes/Depois

_SEV_ORD = {"erro": 0, "aviso": 1, "sugestao": 2}
_NAT_ORD = {"objetivo": 0, "subjetivo": 1}


def _chave_prioridade(item):
    """Prioridade de um achado: severidade > natureza objetiva > confiança."""
    return (
        _SEV_ORD.get(item.get("severidade", "sugestao"), 2),
        _NAT_ORD.get(item.get("natureza", "subjetivo"), 1),
        -(item.get("confianca") or 0),
    )


# Inferência de posição para achados de INSERÇÃO (trecho vazio, correção com texto
# novo). Um CTA de compartilhamento vai ao final; pistas no `porque` também contam.
_RE_INS_CTA = _re.compile(
    r"compartilh|coment[ae]|marca alguém|marque\b|me segue|segue (o|a|nosso)|siga\b|salv[ae] (esse|este|o vídeo)",
    _re.IGNORECASE)
_RE_INS_FIM = _re.compile(
    r"\b(final do roteiro|fim do roteiro|encerramento|último parágrafo|depois do cta|antes do cta|conclus)",
    _re.IGNORECASE)
_RE_INS_INICIO = _re.compile(
    r"\b(início do roteiro|inicio do roteiro|abertura|primeiro parágrafo|logo após o hook|ap[oó]s o hook|sub-?hook)",
    _re.IGNORECASE)


def _inferir_posicao_insercao(item) -> str:
    """Retorna 'final', 'inicio' ou '' (indefinida) para um achado de inserção."""
    if (item.get("camada") or "").lower() == "cta":
        return "final"
    if _RE_INS_CTA.search(item.get("correcao", "")):
        return "final"
    pq = item.get("porque", "")
    if _RE_INS_FIM.search(pq):
        return "final"
    if _RE_INS_INICIO.search(pq):
        return "inicio"
    return ""


def _frases_slices(s: str) -> list:
    """Retorna as fatias (start, end) de cada frase de `s`, preservando o texto
    literal (incluindo o espaçamento que segue a pontuação)."""
    cortes = [0] + [m.end() for m in _re.finditer(r"[.!?…]+\s+", s)] + [len(s)]
    return [(cortes[k], cortes[k + 1]) for k in range(len(cortes) - 1)
            if s[cortes[k]:cortes[k + 1]].strip()]


def _estreitar_achado(t: str, c: str):
    """Divisão na origem: quando trecho_original e correcao compartilham frases
    inalteradas no início e/ou no fim, estreita o achado para apenas as frases que
    realmente mudaram. Um achado de parágrafo inteiro onde só uma frase foi alterada
    vira um achado curto (cabe em 3 linhas), e o resto do parágrafo volta a ser
    linha de leitura. As fatias são literais — o trecho estreitado continua
    substituível no Google Doc."""
    st, sc = _frases_slices(t), _frases_slices(c)
    if len(st) < 2 or not sc:
        return t, c
    n = min(len(st), len(sc))
    i = 0
    while i < n and t[st[i][0]:st[i][1]].strip() == c[sc[i][0]:sc[i][1]].strip():
        i += 1
    j = 0
    while j < n - i and (t[st[len(st)-1-j][0]:st[len(st)-1-j][1]].strip()
                         == c[sc[len(sc)-1-j][0]:sc[len(sc)-1-j][1]].strip()):
        j += 1
    if i == 0 and j == 0:
        return t, c  # nenhuma frase em comum nas pontas — diff é o trecho todo
    ti, tj = i, len(st) - 1 - j  # faixa de frases alteradas em t
    ci, cj = i, len(sc) - 1 - j  # faixa em c
    if ti > tj and ci > cj:
        # Conteúdo das frases idêntico, mas t != c: diff de espaçamento puro
        # (ex.: PARAGRAFO_DENSO insere quebra de parágrafo). Estreita para o par
        # de frases ao redor do ponto onde o espaçamento muda.
        if t != c and len(st) == len(sc):
            for k in range(len(st)):
                if t[st[k][0]:st[k][1]] != c[sc[k][0]:sc[k][1]]:
                    if k + 1 < len(st):
                        nt = t[st[k][0]:st[k + 1][1]].strip()
                        nc = c[sc[k][0]:sc[k + 1][1]].strip()
                        if nt and nc and nt != nc:
                            return nt, nc
                    break
        return t, c
    if ti > tj or ci > cj:
        # Inserção/remoção pura de frase: inclui uma frase-âncora inalterada para
        # o trecho continuar substituível no Doc.
        if i > 0:
            ti, ci = ti - 1, ci - 1
        else:
            tj, cj = tj + 1, cj + 1
        if ti > tj or tj >= len(st) or ci > cj or cj >= len(sc):
            return t, c
    nt = t[st[ti][0]:st[tj][1]].strip()
    nc = c[sc[ci][0]:sc[cj][1]].strip()
    if not nt or not nc or nt == nc:
        return t, c
    return nt, nc


def _segmentar_paragrafo(par: str, trechos: list) -> list:
    """Divide um parágrafo longo em segmentos menores para a tabela, respeitando
    fronteiras de frase — nunca corta no meio de uma frase. Cada segmento é uma
    fatia LITERAL do parágrafo (substituível no Google Doc). Não divide se algum
    trecho de achado cruzaria a fronteira (o trecho precisa caber inteiro em um
    segmento)."""
    if len(par) <= MAX_SEG_CHARS:
        return [par]
    cortes = [0] + [m.end() for m in _re.finditer(r"[.!?…]+\s+", par)] + [len(par)]
    frases = [par[cortes[i]:cortes[i + 1]] for i in range(len(cortes) - 1)]
    frases = [f for f in frases if f.strip()]
    if len(frases) < 2:
        return [par]
    segs, atual = [], ""
    for f in frases:
        if atual and len(atual) + len(f) > MAX_SEG_CHARS:
            segs.append(atual.strip())
            atual = f
        else:
            atual += f
    if atual.strip():
        segs.append(atual.strip())
    if len(segs) < 2:
        return [par]
    for t in trechos:
        if t and t in par and not any(t in s for s in segs):
            return [par]  # trecho cruzaria a fronteira — mantém o parágrafo inteiro
    return segs


def _fundir_llm(seg_texto: str, itens: list):
    """Integra correções sobrepostas (camadas diferentes) num texto único e fluido,
    preservando a voz do autor. Retorna o texto fundido, ou None se indisponível ou
    implausível (caller usa o fallback mecânico)."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        lista = "\n".join(
            f"- [{i['camada']}] \"{i['trecho_original']}\" → \"{i['correcao']}\"\n"
            f"  Motivo: {(i['porque'] or '')[:200]}"
            for i in itens
        )
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=700,
            system=("Você é um editor de roteiros de vídeos curtos. Integre TODAS as "
                    "correções listadas no trecho original, produzindo UM texto final "
                    "coeso e natural, na voz do autor — como um editor humano que "
                    "incorporou todas as mudanças numa única reescrita. Responda APENAS "
                    "com o texto final, sem comentários, prefixos nem aspas."),
            messages=[{"role": "user", "content":
                       f"TRECHO ORIGINAL:\n{seg_texto}\n\nCORREÇÕES A INTEGRAR:\n{lista}"}],
        )
        out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if not out or not (0.4 * len(seg_texto) <= len(out) <= 3 * len(seg_texto) + 200):
            return None
        return out
    except Exception:
        return None


def _consolidar_segmento(seg_texto: str, itens: list, para_idx: int) -> dict:
    """Consolida todos os achados de um mesmo segmento em UMA linha da tabela.

    ANTES = o segmento inteiro; DEPOIS = o segmento com todas as correções
    compatíveis aplicadas em conjunto:
      - Compatíveis (spans que não se sobrepõem) → fusão mecânica, da direita
        para a esquerda, cada `correcao` no lugar do seu `trecho_original`.
      - Sobreposição entre camadas DIFERENTES (ex.: fact-check corrige um dado e
        storytelling reescreve o parágrafo) → complementares: fusão via LLM.
      - Sobreposição na MESMA camada = reescritas alternativas concorrentes →
        só a de maior prioridade entra; as descartadas não aparecem.

    A linha resultante carrega `camadas` (todas que contribuíram), `porque`
    combinado (justificativa de cada achado incorporado) e `ids` (para persistir
    a decisão única em todos os achados incorporados)."""
    ordenados = sorted(itens, key=_chave_prioridade)
    aceitos = []      # [(start, end, item)] — spans sem sobreposição
    sobrepostos = []  # sobreposição com camada diferente → candidatos a fusão LLM
    for it in ordenados:
        t = it["trecho_original"]
        pos = seg_texto.find(t)
        span = (pos, pos + len(t))
        conflito = [a for a in aceitos if not (span[1] <= a[0] or span[0] >= a[1])]
        if not conflito:
            aceitos.append((span[0], span[1], it))
        elif all(a[2]["camada"] != it["camada"] for a in conflito):
            sobrepostos.append(it)
        # mesma camada no mesmo span = alternativa concorrente — descarta

    depois = seg_texto
    for s, e, it in sorted(aceitos, key=lambda x: -x[0]):
        depois = depois[:s] + it["correcao"] + depois[e:]

    incorporados = [it for _, _, it in sorted(aceitos, key=lambda x: x[0])]
    nao_incorporados = []
    if sobrepostos:
        fundido = _fundir_llm(seg_texto, incorporados + sobrepostos)
        if fundido:
            depois = fundido
            incorporados = incorporados + sobrepostos
        else:
            # Fusão indisponível/implausível: complementares de outra camada NÃO
            # podem sumir — voltam ao caller para virar linhas individuais.
            nao_incorporados = sobrepostos

    primario = min(incorporados, key=_chave_prioridade)
    camadas = []
    for it in incorporados:
        if it["camada"] not in camadas:
            camadas.append(it["camada"])
    if len(incorporados) > 1:
        porque = "\n\n".join(f"[{it['camada']}] {it['porque']}" for it in incorporados)
    else:
        porque = primario["porque"]

    ins_label = next((it.get("insercao_label") for it in incorporados
                      if it.get("insercao_label")), None)
    return nao_incorporados, {
        "id": primario["id"],
        "ids": [it["id"] for it in incorporados],
        "insercao_label": ins_label,
        "tipo": "correcao",
        "severidade": primario["severidade"],
        "natureza": primario["natureza"],
        "camada": primario["camada"],
        "camadas": camadas,
        "trecho_original": seg_texto,
        "correcao": depois,
        "porque": porque,
        "confianca": max((it.get("confianca") or 0) for it in incorporados),
        "diff_inline": _diff_inline(seg_texto, depois),
        "relacionado_a": None,
        "decisao": None,
        "_para_idx": para_idx,
    }


def transformar_roteiro(roteiro_raw, url_gdocs="", meta=None):
    cons = roteiro_raw.get("consolidado", {})
    achados = cons.get("achados", [])
    texto = roteiro_raw.get("texto", "")

    # Parágrafos na ordem do roteiro (a 1ª linha é sempre a headline)
    paragrafos_raw = [p.strip() for p in texto.split("\n") if p.strip()]

    # Offsets de cada parágrafo no texto inteiro (para posicionamento dos achados)
    para_offsets: list[int] = []
    offset = 0
    for p in paragrafos_raw:
        idx = texto.find(p, offset)
        para_offsets.append(idx if idx != -1 else offset)
        offset = (idx if idx != -1 else offset) + len(p)

    itens = []
    descartados = 0
    for i, a in enumerate(achados, 1):
        t = (a.get("trecho_original") or "").strip()
        c = (a.get("correcao") or "").strip()
        if not t and not c:
            descartados += 1
            continue
        item = transformar_achado(a, i)
        # A sanitização pode ter zerado os dois campos (correção era instrução
        # editorial): sem trecho E sem correção não há nada para decidir — descarta.
        if not item["trecho_original"] and not item["correcao"]:
            descartados += 1
            continue
        # INSERÇÃO (trecho vazio, correção com texto novo): ancora no parágrafo
        # vizinho do ponto de inserção. Vira uma substituição real — o Antes mostra
        # o contexto do entorno, a linha entra na posição certa do fluxo sequencial
        # e o Aplicar grava de verdade no Doc (parágrafo → parágrafo + inserção).
        if not item["trecho_original"] and item["correcao"] and paragrafos_raw:
            pos = _inferir_posicao_insercao(item)
            if pos == "final":
                ancora = paragrafos_raw[-1]
                item["trecho_original"] = ancora
                item["correcao"] = f"{ancora}\n\n{item['correcao']}"
                item["insercao_label"] = "✚ Inserção — ao final do roteiro"
            elif pos == "inicio":
                ancora = paragrafos_raw[1] if len(paragrafos_raw) > 1 else paragrafos_raw[0]
                item["trecho_original"] = ancora
                item["correcao"] = f"{ancora}\n\n{item['correcao']}"
                item["insercao_label"] = "✚ Inserção — no início do roteiro (após o hook)"
            else:
                # Posição não inferível: o editor decide onde entra (Aplicar
                # desabilitado na interface; Editar continua disponível).
                item["insercao_indefinida"] = True
                item["insercao_label"] = "✚ Inserção — posição a definir pelo editor"
        # Divisão na origem: estreita achados longos para as frases que mudaram
        if item["trecho_original"] and item["correcao"]:
            nt, nc = _estreitar_achado(item["trecho_original"], item["correcao"])
            if nt != item["trecho_original"]:
                item["trecho_original"] = nt
                item["correcao"] = nc
                item["diff_inline"] = _diff_inline(nt, nc)
        item["_para_idx"] = _para_idx_de_achado(item["trecho_original"], texto, para_offsets)
        itens.append(item)
    if descartados:
        print(f"   🧹 {descartados} achado(s) sem trecho e sem correção descartado(s) da tabela")

    # ── Leitura sequencial: a tabela reproduz o roteiro do início ao fim ──────
    # `linhas` é o plano de renderização, na ordem original do texto:
    #   {tipo: "leitura", texto}   → parágrafo/segmento sem achado
    #   {tipo: "correcao", id}     → linha consolidada (referencia `correcoes`)
    #   {tipo: "secao", label}     → separador (achados sem trecho, no fim)
    correcoes = []
    linhas = []
    n_par = len(paragrafos_raw)

    def _linha_individual(it):
        """Achado que não consolida (trecho não-literal no parágrafo): vira linha
        própria, mantendo o fragmento original como Antes."""
        it["ids"] = [it["id"]]
        it["camadas"] = [it["camada"]]
        correcoes.append(it)
        linhas.append({"tipo": "correcao", "id": it["id"]})

    for pi, par in enumerate(paragrafos_raw):
        achs = [it for it in itens if it["_para_idx"] == pi]
        dentro = [a for a in achs if a["trecho_original"] and a["trecho_original"] in par]
        _ids_dentro = {id(a) for a in dentro}
        fora = [a for a in achs if id(a) not in _ids_dentro]
        if not dentro:
            linhas.append({"tipo": "leitura", "texto": par})
        else:
            segs = _segmentar_paragrafo(par, [a["trecho_original"] for a in dentro])
            usados = set()
            for seg in segs:
                seg_achs = [a for a in dentro
                            if id(a) not in usados and a["trecho_original"] in seg]
                for a in seg_achs:
                    usados.add(id(a))
                if not seg_achs:
                    linhas.append({"tipo": "leitura", "texto": seg})
                else:
                    restantes, row = _consolidar_segmento(seg, seg_achs, pi)
                    correcoes.append(row)
                    linhas.append({"tipo": "correcao", "id": row["id"]})
                    # Complementares cuja fusão LLM falhou: linhas próprias logo
                    # após a consolidada — nunca somem silenciosamente.
                    for a in restantes:
                        _linha_individual(a)
        # Trecho localizado no parágrafo só com match normalizado (espaços): linha
        # individual logo após o parágrafo, preservando a posição na leitura.
        for a in fora:
            _linha_individual(a)

    # Restantes sem posição no texto (inserção indefinida, trecho não localizado):
    # entram no fim do fluxo, sem seção separada — a leitura sequencial não quebra.
    finais = [it for it in itens if it["_para_idx"] >= n_par]
    for a in sorted(finais, key=_chave_prioridade):
        _linha_individual(a)

    veredicto = cons.get("veredicto", "—")
    return {
        "roteiro": {
            "titulo": roteiro_raw.get("titulo", "Roteiro"),
            "id": f"rot_{roteiro_raw.get('numero', 1):02d}",
            "veredicto": veredicto,
            "score_geral": cons.get("nota_geral", 0),
        },
        "url_gdocs": url_gdocs or "",
        "paragrafos": paragrafos_raw,
        "linhas": linhas,
        "correcoes": correcoes,
        "meta": meta or {"total": 1, "atual": 1, "proximo_titulo": None},
    }


def json_mais_recente():
    jsons = sorted(PASTA_RELATORIOS.glob("revisao_*.json"))
    return jsons[-1] if jsons else None


def aplicar_decisoes_no_payload(payload, decisoes, motivos=None):
    """Carimba as decisões acumuladas pelo server nos achados do payload (in-place).
    Usado antes de regravar o JSON incremental para não apagar decisões já persistidas."""
    motivos = motivos or {}
    for rot in payload:
        rid = f"rot_{rot.get('numero', 1):02d}"
        achados = rot.get("consolidado", {}).get("achados", [])
        for aid, dec in (decisoes.get(rid) or {}).items():
            try:
                idx = int(aid.lstrip("c")) - 1
            except ValueError:
                continue
            if 0 <= idx < len(achados):
                achados[idx]["decisao"] = dec
                m = (motivos.get(rid) or {}).get(aid)
                if m:
                    achados[idx]["motivo_decisao"] = m
    return payload


def decisoes_para_ensinamentos(roteiros_raw, decisoes, motivos=None):
    """Converte as decisões da sessão da tabela em ensinamentos no MESMO formato do
    modo dinâmica (consumidos por revisar_dinamico.loop_aprendizado):
      - pular                       → {**achado, "_tipo_decisao": "pular", "_motivo": ...}
      - editada (≠ correcao, ≠ 'aplicado') → {**achado, "_tipo_decisao": "editar", ...}
    Aplicar sem mudança não vira ensinamento (não tem sinal)."""
    motivos = motivos or {}
    ensinamentos = []
    for rot in roteiros_raw:
        rid = f"rot_{rot.get('numero', 1):02d}"
        dec_map = decisoes.get(rid) or {}
        if not dec_map:
            continue
        achados = rot.get("consolidado", {}).get("achados", [])
        for aid, decisao in dec_map.items():
            try:
                idx = int(aid.lstrip("c")) - 1
            except ValueError:
                continue
            if not (0 <= idx < len(achados)):
                continue
            achado = achados[idx]
            motivo = (motivos.get(rid) or {}).get(aid, "")
            correcao = (achado.get("correcao") or "").strip()
            if decisao == "pular":
                ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": motivo})
            elif decisao and decisao != "aplicado" and decisao.strip() != correcao:
                ensinamentos.append({
                    **achado,
                    "_tipo_decisao": "editar",
                    "_correcao_original": correcao,
                    "_versao_usuario": decisao,
                    "_motivo": motivo,
                })
    return ensinamentos


# ─── Servidor Flask ───────────────────────────────────────────────────────────

class TabelaServer:
    """Servidor Flask de vida longa: um único processo por sessão.

    O browser mantém a mesma aba. Ao clicar em 'Continuar', o Python
    processa o próximo roteiro, atualiza `dados_atual` e o JS refaz
    fetch em /api/dados para re-renderizar sem recarregar a página.
    """

    def __init__(self, url_gdocs: str = "", porta: int = 7432, json_path=None):
        import uuid as _uuid
        self.url_gdocs = url_gdocs
        self.porta = porta
        self.dados_atual: dict = {}
        # Histórico de roteiros já transformados na sessão (para navegação Voltar/
        # Avançar entre roteiros já revisados, sem reprocessar nada).
        self.historico: list = []
        self.idx_hist: int = 0
        self._done_event = threading.Event()
        self._next_event = threading.Event()
        self._app = None
        self._thread = None
        # Decisões acumuladas na sessão: {roteiro_id: {achado_id: decisao}}.
        # Persistidas a cada clique (rota /api/decisao) — fechar a aba não perde nada.
        self.json_path = Path(json_path) if json_path else None
        self.decisoes: dict = {}
        self.motivos: dict = {}  # {roteiro_id: {achado_id: motivo do pulo/edição}}
        self._lock_json = threading.Lock()
        # ID único por processo — impede que o localStorage de uma sessão anterior
        # contamine a sessão atual quando roteiros têm o mesmo id sequencial (rot_01...).
        # uuid4 garante unicidade mesmo com múltiplas execuções no mesmo segundo.
        self.sessao_id = _uuid.uuid4().hex

    # ── Setup Flask ────────────────────────────────────────────────────────
    def _criar_app(self):
        try:
            from flask import Flask, request, jsonify, Response
        except ImportError:
            return None

        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        app = Flask(__name__)
        server = self  # capture self for closures

        @app.route("/")
        def index():
            html = _HTML.replace(
                "__DADOS_JSON__",
                json.dumps(server.dados_atual, ensure_ascii=False)
            ).replace("__SESSAO_ID__", server.sessao_id)
            return Response(html, mimetype="text/html; charset=utf-8")

        @app.route("/api/dados")
        def api_dados():
            return jsonify(server.dados_atual)

        @app.route("/api/apply", methods=["POST"])
        def api_apply():
            data = request.get_json() or {}
            url = server.url_gdocs or data.get("url_gdocs") or ""
            if not url:
                return jsonify({
                    "error": "URL do Google Docs não fornecida. "
                             "Reinicie com: python3 revisar.py --gdocs \"URL\""
                }), 400
            correcoes_req = data.get("correcoes", [])
            # "aplicado" é sentinel de "aprovado sem substituição" — não escrever no doc
            correcoes = [
                (c["trecho_original"], c["decisao"])
                for c in correcoes_req
                if c.get("trecho_original") and c.get("decisao") and c["decisao"] != "aplicado"
            ]
            if not correcoes:
                return jsonify({"aplicadas": 0})
            try:
                from revisar_dinamico import aplicar_correcoes
                # interativo=False: roda em thread Flask — nunca pode chamar input()
                res = aplicar_correcoes(url, correcoes, interativo=False)
                return jsonify({"aplicadas": res["aplicadas"], "avisos": res.get("avisos", [])})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/decisao", methods=["POST"])
        def api_decisao():
            """Registra cada decisão (aplicar/editar/pular) no servidor a cada clique."""
            data = request.get_json() or {}
            aid = data.get("id")
            if not aid:
                return jsonify({"error": "id ausente"}), 400
            decisao = data.get("decisao")  # None = decisão resetada
            motivo = (data.get("motivo") or "").strip()
            rid = server.dados_atual.get("roteiro", {}).get("id", "")
            server.decisoes.setdefault(rid, {})[aid] = decisao
            if motivo:
                server.motivos.setdefault(rid, {})[aid] = motivo
            else:
                server.motivos.get(rid, {}).pop(aid, None)
            server._persistir_decisao(rid, aid, decisao, motivo)
            return jsonify({"ok": True})

        @app.route("/api/navegar", methods=["POST"])
        def api_navegar():
            """Navega entre roteiros já revisados (histórico da sessão).
            Não toca nos events do loop Python — o pipeline continua aguardando
            no roteiro da fronteira; aqui só trocamos a 'página' exibida."""
            data = request.get_json() or {}
            try:
                delta = int(data.get("delta", 0))
            except (TypeError, ValueError):
                return jsonify({"error": "delta inválido"}), 400
            novo = server.idx_hist + delta
            if not (0 <= novo < len(server.historico)):
                return jsonify({"error": "fora do histórico"}), 400
            server.idx_hist = novo
            server.dados_atual = server.historico[novo]
            server._stamp_nav()
            return jsonify(server.dados_atual)

        @app.route("/api/continuar", methods=["POST"])
        def api_continuar():
            """Usuário concluiu este roteiro. Bloqueia até o próximo estar pronto."""
            server._done_event.set()
            server._next_event.clear()
            # Aguarda Python preparar o próximo roteiro (ou sinalizar que acabou)
            pronto = server._next_event.wait(timeout=300)
            if pronto and server.dados_atual.get("meta", {}).get("proximo_titulo") is not None:
                return jsonify({"ok": True, "recarregar": True})
            return jsonify({"ok": True, "recarregar": False})

        @app.route("/api/pular", methods=["POST"])
        def api_pular():
            server._done_event.set()
            server._next_event.set()  # desbloqueia sem esperar
            return jsonify({"ok": True})

        return app

    # ── Persistência de decisões ───────────────────────────────────────────
    def _persistir_decisao(self, rid: str, aid: str, decisao, motivo: str = ""):
        """Grava a decisão no campo `decisao` do achado correspondente no JSON do
        relatório (revisao_*.json) E registra o evento no ledger de decisões.
        Best-effort: falha aqui não derruba a sessão."""
        if not self.json_path or not self.json_path.exists():
            return
        try:
            numero = int(rid.rsplit("_", 1)[-1])
            idx = int(aid.lstrip("c")) - 1
        except ValueError:
            return
        with self._lock_json:
            try:
                dados = json.loads(self.json_path.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    dados = [dados]
                for rot in dados:
                    if rot.get("numero") != numero:
                        continue
                    achados = rot.get("consolidado", {}).get("achados", [])
                    if 0 <= idx < len(achados):
                        achados[idx]["decisao"] = decisao
                        if motivo:
                            achados[idx]["motivo_decisao"] = motivo
                        else:
                            achados[idx].pop("motivo_decisao", None)
                        self.json_path.write_text(
                            json.dumps(dados, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        # Ledger: todo evento de decisão vira memória permanente —
                        # inclusive "aplicado" (reforço positivo) e "resetado".
                        try:
                            import ledger
                            dec_norm, versao = ledger.normalizar_decisao(
                                decisao, achados[idx].get("correcao", ""))
                            ledger.registrar_decisao(
                                achados[idx], dec_norm,
                                motivo=motivo, versao_usuario=versao,
                                cliente=rot.get("cliente") or "",
                                roteiro_titulo=rot.get("titulo", ""),
                                estrutura=(rot.get("contexto") or {}).get("estrutura", ""),
                                origem="tabela",
                                chave=f"{self.json_path.name}:{numero}:{idx}",
                            )
                        except Exception:
                            pass
                    break
            except Exception:
                pass  # self.decisoes em memória segue valendo para o aprendizado

    # ── Navegação entre roteiros já revisados ──────────────────────────────
    def _stamp_nav(self):
        """Carimba no `dados_atual` a posição no histórico e as decisões já
        tomadas (de `self.decisoes`) — assim, ao voltar para um roteiro
        anterior, a tabela reabre com tudo que o revisor já decidiu."""
        dados = self.dados_atual
        if not dados:
            return
        rid = dados.get("roteiro", {}).get("id", "")
        dec = self.decisoes.get(rid) or {}
        for c in dados.get("correcoes", []):
            if c.get("id") in dec:
                c["decisao"] = dec[c["id"]]
        meta = dados.setdefault("meta", {})
        meta["hist_idx"] = self.idx_hist
        meta["hist_total"] = len(self.historico)
        meta["anterior_titulo"] = (
            self.historico[self.idx_hist - 1].get("roteiro", {}).get("titulo")
            if self.idx_hist > 0 else None
        )

    # ── Controle público ───────────────────────────────────────────────────
    def iniciar(self, dados: dict):
        """Inicia o servidor Flask com os dados do primeiro roteiro."""
        self.dados_atual = dados
        self.historico = [dados]
        self.idx_hist = 0
        self._stamp_nav()
        self._app = self._criar_app()
        if self._app is None:
            return False
        self._thread = threading.Thread(
            target=lambda: self._app.run(
                host="127.0.0.1", port=self.porta,
                debug=False, use_reloader=False
            ),
            daemon=True,
        )
        self._thread.start()
        url = f"http://localhost:{self.porta}"
        # Lançado pela interface gráfica (interface.py): a própria página do
        # launcher redireciona para cá — não abrir uma segunda aba.
        if not os.environ.get("VML_LAUNCHER"):
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        print(f"\n🌐 Tabela Interativa → {url}")
        print(f"   Revise as correções no browser.")
        return True

    def esperar_decisao(self, timeout: float = 7200.0):
        """Bloqueia até o usuário clicar em 'Continuar', ou timeout (padrão 2 h).
        Retorna True se o usuário agiu, False se expirou."""
        print("   Aguardando decisão no browser... (Ctrl+C cancela)")
        self._done_event.clear()
        ok = self._done_event.wait(timeout=timeout)
        if not ok:
            print("\n⚠️  Timeout na Tabela Interativa — avançando automaticamente.")
            self._next_event.set()
        return ok

    def avancar(self, novos_dados: dict):
        """Atualiza dados para o próximo roteiro e libera o handler /api/continuar."""
        self.dados_atual = novos_dados
        self.historico.append(novos_dados)
        self.idx_hist = len(self.historico) - 1
        self._stamp_nav()
        self._next_event.set()

    def finalizar(self):
        """Sinaliza que acabaram os roteiros (handler retorna recarregar: false)."""
        self._next_event.set()


# ─── Entrada pública (usada por revisar.py) ───────────────────────────────────

def executar_sessao(roteiros_raw, url_gdocs="", porta=7432, json_path=None):
    """Processa os roteiros um por vez com a interface de tabela.

    Esta função é chamada pelo revisar.py depois que os agentes já rodaram.
    `roteiros_raw` é a lista de dicts no formato do consolidador.
    """
    try:
        from flask import Flask  # noqa — apenas verifica disponibilidade
    except ImportError:
        print("❌ Flask não instalado. Execute: pip install flask")
        return

    server = TabelaServer(url_gdocs=url_gdocs, porta=porta, json_path=json_path)

    for i, roteiro_raw in enumerate(roteiros_raw):
        meta = {
            "total": len(roteiros_raw),
            "atual": i + 1,
            "proximo_titulo": roteiros_raw[i + 1]["titulo"] if i + 1 < len(roteiros_raw) else None,
        }
        dados = transformar_roteiro(roteiro_raw, url_gdocs=url_gdocs, meta=meta)

        if i == 0:
            ok = server.iniciar(dados)
            if not ok:
                print("❌ Erro ao iniciar o servidor. Verifique se Flask está instalado.")
                return
            print(f"   [{i+1}/{len(roteiros_raw)}] {roteiro_raw.get('titulo', '')}")
        else:
            print(f"\n   [{i+1}/{len(roteiros_raw)}] {roteiro_raw.get('titulo', '')} — aguardando no browser...")
            server.avancar(dados)

        server.esperar_decisao()

    server.finalizar()
    print("\n🎉 Tabela Interativa encerrada.")

    # Decisões da tabela alimentam o loop de aprendizado (igual ao modo dinâmica)
    ensinamentos = decisoes_para_ensinamentos(roteiros_raw, server.decisoes, server.motivos)
    if ensinamentos:
        from revisar_dinamico import loop_aprendizado
        loop_aprendizado(ensinamentos)


# ─── Entrada standalone (CLI) ─────────────────────────────────────────────────

def iniciar_standalone(json_path, url_gdocs="", porta=7432):
    """Abre a tabela a partir de um JSON já existente (sem rodar os agentes)."""
    dados_raw = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(dados_raw, dict):
        dados_raw = [dados_raw]

    print(f"\n📋 {len(dados_raw)} roteiro(s) carregado(s) de {json_path.name}")
    executar_sessao(dados_raw, url_gdocs=url_gdocs, porta=porta, json_path=json_path)


# ─── HTML ─────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Revisor — VML</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0D0F12;--surface:#141720;--surface-2:#1C2030;--surface-3:#242840;
  --border:#2A2F45;--border-light:#333A55;
  --bloqueante:#FF4545;--bloqueante-bg:rgba(255,69,69,.08);--bloqueante-border:rgba(255,69,69,.3);
  --aviso:#F5A623;--aviso-bg:rgba(245,166,35,.08);--aviso-border:rgba(245,166,35,.3);
  --sugestao:#4B9EFF;--sugestao-bg:rgba(75,158,255,.08);--sugestao-border:rgba(75,158,255,.25);
  --aprovado:#00C97F;--aprovado-bg:rgba(0,201,127,.08);
  --text:#E8ECF5;--text-2:#9BA3BB;--text-3:#5C6480;
  --antes:rgba(255,69,69,.12);--antes-text:#FF8080;
  --depois:rgba(0,201,127,.12);--depois-text:#4FFFB0;
  --mono:'IBM Plex Mono',monospace;--sans:'Plus Jakarta Sans',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:13px;
  line-height:1.5;padding-bottom:72px}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border-light);border-radius:3px}

/* ── Topbar ─── */
#topbar{position:sticky;top:0;z-index:100;background:var(--surface);
  border-bottom:1px solid var(--border);padding:0 24px;height:52px;
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  box-shadow:0 2px 20px rgba(0,0,0,.45)}
.topbar-left{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:12px}
.topbar-brand{color:var(--text-3);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.topbar-sep{color:var(--border-light)}
.roteiro-badge{background:var(--surface-2);border:1px solid var(--border);border-radius:4px;
  padding:3px 10px;font-size:12px;color:var(--text);max-width:340px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.topbar-right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.stat-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;
  border-radius:4px;font-family:var(--mono);font-size:11px;font-weight:600;
  letter-spacing:.04em;border:1px solid transparent}
.stat-chip .dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}
.chip-b{background:var(--bloqueante-bg);border-color:var(--bloqueante-border);color:var(--bloqueante)}
.chip-a{background:var(--aviso-bg);border-color:var(--aviso-border);color:var(--aviso)}
.chip-s{background:var(--sugestao-bg);border-color:var(--sugestao-border);color:var(--sugestao)}
.verd-badge{padding:3px 10px;border-radius:4px;font-family:var(--mono);font-size:11px;
  font-weight:700;text-transform:uppercase;letter-spacing:.05em;border:1px solid transparent}
.verd-rep{background:var(--bloqueante-bg);border-color:var(--bloqueante-border);color:var(--bloqueante)}
.verd-ajuste{background:var(--aviso-bg);border-color:var(--aviso-border);color:var(--aviso)}
.verd-ok{background:var(--aprovado-bg);border-color:rgba(0,201,127,.3);color:var(--aprovado)}

/* ── Filtros ─── */
#filtros{position:sticky;top:52px;z-index:99;background:var(--surface);
  border-bottom:1px solid var(--border);padding:9px 24px;display:flex;align-items:center;gap:6px}
.filtro-label{font-family:var(--mono);font-size:11px;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.04em;margin-right:4px}
.fbtn{padding:4px 11px;border-radius:4px;border:1px solid var(--border);background:transparent;
  color:var(--text-2);font-family:var(--mono);font-size:11px;cursor:pointer;transition:all .15s}
.fbtn:hover{border-color:var(--border-light);color:var(--text)}
.fbtn.fa{border-color:var(--sugestao-border);background:var(--sugestao-bg);color:var(--sugestao)}
.fbtn.fa-b{border-color:var(--bloqueante-border);background:var(--bloqueante-bg);color:var(--bloqueante)}
.fbtn.fa-a{border-color:var(--aviso-border);background:var(--aviso-bg);color:var(--aviso)}
.fbtn.fa-v{border-color:rgba(0,201,127,.3);background:var(--aprovado-bg);color:var(--aprovado)}

/* ── Tabela ─── */
#tabela-wrap{padding:0 24px 16px}
.tabela{width:100%;border-collapse:collapse;table-layout:fixed}
.tabela colgroup col.col-n{width:36px}
.tabela colgroup col.col-tipo{width:110px}
.tabela colgroup col.col-ac{width:100px}
.tabela th{position:sticky;top:90px;z-index:90;background:var(--surface-2);
  border:1px solid var(--border);padding:8px 10px;text-align:left;
  font-family:var(--mono);font-size:10px;font-weight:600;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;overflow:hidden}
.tabela th:first-child{text-align:center}
.tabela td{border:1px solid var(--border);padding:8px 10px;vertical-align:top;
  transition:background .15s,box-shadow .15s}

/* Row types */
.rb{background:var(--bloqueante-bg);border-left:3px solid var(--bloqueante)!important}
.ra{background:var(--aviso-bg);border-left:3px solid var(--aviso)!important}
.rs{border-left:3px solid var(--sugestao)!important}
.sec-row{background:var(--surface-2)}
.sec-row td{border-top:2px solid var(--border-light)!important;padding:10px 14px;
  font-family:var(--mono);font-size:11px;font-weight:700;color:var(--text-2);
  text-transform:uppercase;letter-spacing:.1em;
  background:linear-gradient(to right,var(--surface-3),var(--surface-2))!important}
.row-aprov{background:var(--aprovado-bg)!important}
.row-pulada{opacity:.4}
.row-hidden{display:none}

/* Leitura row */
.lr-row td{border-top:1px solid var(--border);border-bottom:1px solid var(--border);
  border-left:1px solid var(--border);border-right:1px solid var(--border);padding:9px 12px}
.lr-n{font-family:var(--mono);font-size:10px;color:var(--text-3);text-align:center;
  vertical-align:middle}
.lr-texto{font-size:13px;color:var(--text-2);line-height:1.65}

/* Num cell */
.nc{font-family:var(--mono);font-size:11px;color:var(--text-3);text-align:center}

/* Badge + camada */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 7px;border-radius:3px;
  font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;border:1px solid transparent;white-space:nowrap}
.badge-e{background:var(--bloqueante-bg);border-color:var(--bloqueante-border);color:var(--bloqueante)}
.badge-a{background:var(--aviso-bg);border-color:var(--aviso-border);color:var(--aviso)}
.badge-s{background:var(--sugestao-bg);border-color:var(--sugestao-border);color:var(--sugestao)}
.tag-row{display:flex;align-items:center;gap:5px;margin-top:5px;flex-wrap:wrap}
.ins-label{margin-top:5px;font-family:var(--mono);font-size:9px;color:var(--aprovado);
  letter-spacing:.03em;line-height:1.4}
.tag-c{display:inline-block;padding:2px 6px;border-radius:2px;
  font-family:var(--mono);font-size:9px;font-weight:500;background:var(--surface-3);
  color:var(--text-3);border:1px solid var(--border);letter-spacing:.04em}

/* Info icon (i) — tooltip trigger */
.ii{cursor:help;color:var(--text-3);font-size:12px;opacity:.65;transition:opacity .15s;
  user-select:none;line-height:1}
.ii:hover{opacity:1;color:var(--sugestao)}

/* Tooltip flutuante */
#tt{display:none;position:fixed;z-index:500;background:var(--surface-3);
  border:1px solid var(--border-light);color:var(--text);
  padding:9px 13px;border-radius:5px;font-family:var(--sans);font-size:12px;
  line-height:1.55;max-width:320px;max-height:220px;overflow-y:auto;
  pointer-events:none;box-shadow:0 4px 20px rgba(0,0,0,.45);
  white-space:pre-wrap;word-break:break-word}

/* Diff blocks — colapsa em 3 linhas, mas NUNCA esconde conteúdo sem controle:
   quando o texto excede, o JS injeta o botão "ver tudo" (marcarOverflow) */
.diff-blk{border-radius:4px;padding:6px 9px;font-family:var(--mono);font-size:12px;
  line-height:1.55;border:1px solid transparent;word-break:break-word;
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.diff-blk.aberto{display:block;-webkit-line-clamp:initial;overflow:visible}
.ver-mais{display:block;margin-top:3px;padding:1px 7px;border:1px solid var(--border);
  border-radius:3px;background:transparent;color:var(--text-3);cursor:pointer;
  font-family:var(--mono);font-size:10px;transition:all .15s}
.ver-mais:hover{color:var(--text);border-color:var(--border-light)}
.db-ant{background:var(--antes);border-color:rgba(255,69,69,.2);color:var(--antes-text)}
.db-dep{background:var(--depois);border-color:rgba(0,201,127,.2);color:var(--depois-text)}
.diff-null{color:var(--text-3);font-size:11px;font-style:italic;font-family:var(--mono)}
.del{background:rgba(255,69,69,.22);color:var(--antes-text);text-decoration:line-through;
  border-radius:2px;padding:0 2px}
.ins{background:rgba(0,201,127,.22);color:var(--depois-text);border-radius:2px;padding:0 2px}

/* Botões ação */
.acao-wrap{display:flex;flex-direction:column;gap:4px}
.btn-ac{width:100%;padding:5px 0;border-radius:4px;font-family:var(--mono);font-size:11px;
  font-weight:600;cursor:pointer;border:1px solid transparent;transition:all .15s;
  letter-spacing:.03em;text-align:center}
.btn-ap{background:var(--aprovado-bg);color:var(--aprovado);border-color:rgba(0,201,127,.3)}
.btn-ap:hover{background:rgba(0,201,127,.18)}
.btn-ed{background:var(--aviso-bg);color:var(--aviso);border-color:var(--aviso-border)}
.btn-ed:hover{background:rgba(245,166,35,.15)}
.btn-pu{background:transparent;color:var(--text-3);border-color:var(--border)}
.btn-pu:hover{color:var(--text-2);border-color:var(--border-light)}
.btn-cf{background:var(--aprovado-bg);color:var(--aprovado);border-color:rgba(0,201,127,.3)}
.btn-cf:hover{background:rgba(0,201,127,.18)}
.btn-ca{background:transparent;color:var(--text-3);border-color:var(--border)}
.btn-ca:hover{color:var(--text-2);border-color:var(--border-light)}
.btn-en{background:transparent;color:var(--text-3);border-color:var(--border);
  font-size:10px;padding:3px 0}
.btn-en:hover{color:var(--text-2);border-color:var(--border-light)}
.ensinar-wrap{margin-top:6px;display:none}
.ensinar-wrap.aberto{display:block}
.ensinar-ta{width:100%;min-height:52px;padding:6px 8px;background:var(--surface-3);
  border:1px solid var(--border);border-radius:4px;color:var(--text);
  font-family:var(--mono);font-size:11px;line-height:1.5;resize:vertical;outline:none;
  box-sizing:border-box}
.ensinar-ta:focus{border-color:var(--sugestao-border)}
.ensinar-btns{display:flex;gap:4px;margin-top:4px}
.btn-en-cf{flex:1;padding:4px 0;border-radius:4px;font-family:var(--mono);font-size:10px;
  font-weight:600;cursor:pointer;border:1px solid rgba(0,201,127,.3);
  background:var(--aprovado-bg);color:var(--aprovado)}
.btn-en-ca{flex:1;padding:4px 0;border-radius:4px;font-family:var(--mono);font-size:10px;
  cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--text-3)}

/* Estados */
.st-ap{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--aprovado);
  text-align:center;padding:4px}
.st-pu{font-family:var(--mono);font-size:11px;color:var(--text-3);text-align:center;padding:4px}
.st-na{font-family:var(--mono);font-size:10px;color:var(--text-3);font-style:italic;text-align:center}

/* Edit textarea */
.edit-ta{width:100%;min-height:68px;padding:6px 8px;background:var(--surface-3);
  border:1px solid var(--sugestao-border);border-radius:4px;color:var(--text);
  font-family:var(--mono);font-size:11px;line-height:1.5;resize:vertical;outline:none}

/* Footer */
#footer{position:fixed;bottom:0;left:0;right:0;z-index:100;background:var(--surface);
  border-top:1px solid var(--border);padding:12px 24px;display:flex;
  align-items:center;justify-content:space-between;gap:16px}
.footer-l{font-family:var(--mono);font-size:12px;color:var(--text-2);white-space:nowrap}
.footer-l .naplic{color:var(--aprovado);font-weight:600}
.footer-c{font-family:var(--mono);font-size:11px;color:var(--text-3);flex:1;text-align:center}
.footer-c.pronto{color:var(--aprovado)}
.footer-r{display:flex;align-items:center;gap:8px;flex-shrink:0}
.btn-sec{padding:8px 14px;background:transparent;color:var(--text-2);
  border:1px solid var(--border);border-radius:5px;font-family:var(--mono);font-size:11px;
  cursor:pointer;transition:all .15s;white-space:nowrap}
.btn-sec:hover{border-color:var(--border-light);color:var(--text)}
.btn-gravar{padding:9px 20px;background:var(--aprovado);color:#000;border:none;
  border-radius:5px;font-family:var(--mono);font-size:12px;font-weight:700;
  letter-spacing:.05em;cursor:pointer;transition:opacity .15s;white-space:nowrap}
.btn-gravar:hover:not(:disabled){opacity:.85}
.btn-gravar:disabled{opacity:.3;cursor:not-allowed}
.btn-continuar{padding:9px 20px;background:var(--sugestao-bg);color:var(--sugestao);
  border:1px solid var(--sugestao-border);border-radius:5px;font-family:var(--mono);
  font-size:12px;font-weight:700;letter-spacing:.05em;cursor:pointer;
  transition:all .15s;white-space:nowrap}
.btn-continuar:hover{background:rgba(75,158,255,.15)}
.btn-voltar{padding:9px 16px;background:transparent;color:var(--text-2);
  border:1px solid var(--border);border-radius:5px;font-family:var(--mono);
  font-size:12px;font-weight:700;letter-spacing:.05em;cursor:pointer;
  transition:all .15s;white-space:nowrap}
.btn-voltar:hover:not(:disabled){border-color:var(--border-light);color:var(--text)}
.btn-voltar:disabled{opacity:.3;cursor:not-allowed}

/* Toast */
#toast{position:fixed;top:66px;right:24px;z-index:200;padding:10px 18px;border-radius:6px;
  font-family:var(--mono);font-size:12px;font-weight:600;opacity:0;
  transform:translateX(10px);
  transition:opacity .22s,transform .3s cubic-bezier(.34,1.56,.64,1);pointer-events:none}
#toast.ts{background:var(--aprovado-bg);border:1px solid rgba(0,201,127,.3);color:var(--aprovado)}
#toast.te{background:var(--bloqueante-bg);border:1px solid var(--bloqueante-border);color:var(--bloqueante)}
#toast.show{opacity:1;transform:translateX(0)}

/* Loading overlay */
#loading{display:none;position:fixed;inset:0;z-index:300;background:rgba(13,15,18,.85);
  flex-direction:column;align-items:center;justify-content:center;gap:16px}
#loading.show{display:flex}
.spin{width:32px;height:32px;border:2px solid var(--border);
  border-top-color:var(--sugestao);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-msg{font-family:var(--mono);font-size:13px;color:var(--text-2)}

/* ── Hover & microinterações ─── */
.tabela tbody tr.rb:hover td{background:rgba(255,69,69,.13)!important}
.tabela tbody tr.ra:hover td{background:rgba(245,166,35,.13)!important}
.tabela tbody tr.rs:hover td{background:rgba(75,158,255,.05)!important}
.tabela tbody tr.lr-row:hover td{background:rgba(136,145,170,.06)!important}
.btn-ac:active{transform:scale(0.95);transition:transform .08s}
.btn-gravar:active,.btn-continuar:active,.btn-sec:active{transform:scale(0.97);transition:transform .08s}

/* ── Animação de aprovação ─── */
@keyframes approvalFlash{
  0%{box-shadow:inset 0 0 0 100px rgba(0,201,127,.18)}
  100%{box-shadow:inset 0 0 0 100px rgba(0,0,0,0)}
}
.row-aprov td{animation:approvalFlash .55s ease-out}

/* ── Foco de teclado (J/K) ─── */
tr.row-focus{outline:2px solid var(--sugestao);outline-offset:-2px}
tr.row-focus td{background:rgba(75,158,255,.06)!important}
.kbd-legend{font-family:var(--mono);font-size:10px;color:var(--text-3);
  margin-left:12px;white-space:nowrap}
</style>
</head>
<body>

<div id="topbar">
  <div class="topbar-left">
    <span class="topbar-brand">VML — REVISOR</span>
    <span class="topbar-sep">/</span>
    <span class="roteiro-badge" id="rot-nome">—</span>
  </div>
  <div class="topbar-right">
    <div class="stat-chip chip-b" id="chip-b"><span class="dot"></span><span id="n-b">0</span> bloqueante(s)</div>
    <div class="stat-chip chip-a" id="chip-a"><span class="dot"></span><span id="n-a">0</span> aviso(s)</div>
    <div class="stat-chip chip-s" id="chip-s"><span class="dot"></span><span id="n-s">0</span> sugestão(ões)</div>
    <span class="verd-badge" id="verd-badge">—</span>
  </div>
</div>

<div id="filtros">
  <span class="filtro-label">Ver:</span>
  <button class="fbtn fa" onclick="setF(this,'roteiro')">Roteiro</button>
  <button class="fbtn" onclick="setF(this,'todos')">Todos os achados</button>
  <button class="fbtn" onclick="setF(this,'bloqueantes','fa-b')">Bloqueantes</button>
  <button class="fbtn" onclick="setF(this,'avisos','fa-a')">Avisos</button>
  <button class="fbtn" onclick="setF(this,'sugestoes')">Sugestões</button>
  <button class="fbtn" onclick="setF(this,'pendentes')">Pendentes</button>
  <button class="fbtn" onclick="setF(this,'aprovados','fa-v')">Aprovados</button>
</div>

<div id="tabela-wrap">
  <table class="tabela" id="tbl">
    <colgroup>
      <col class="col-n">
      <col class="col-tipo">
      <col>
      <col>
      <col class="col-ac">
    </colgroup>
    <thead><tr>
      <th>#</th>
      <th>Tipo / Camada</th>
      <th>Antes</th>
      <th>Depois</th>
      <th>Ação</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div id="footer">
  <div class="footer-l"><span class="naplic" id="n-ap">0</span> de <span id="n-tot">0</span> aplicadas<span class="kbd-legend">J/K navegar · A aplicar · E editar · P pular</span></div>
  <div class="footer-c" id="footer-st">—</div>
  <div class="footer-r">
    <button class="btn-sec" onclick="resetar()">Resetar</button>
    <button class="btn-sec" onclick="exportar()">Exportar JSON</button>
    <button class="btn-gravar" id="btn-gravar" onclick="gravar()" disabled>Gravar no Google Docs</button>
    <button class="btn-voltar" id="btn-volt" onclick="voltar()" style="display:none" disabled>← Voltar</button>
    <button class="btn-continuar" id="btn-cont" onclick="continuar()" style="display:none">Continuar →</button>
  </div>
</div>

<div id="toast"></div>
<div id="tt"></div>
<div id="loading"><div class="spin"></div><div class="loading-msg" id="loading-msg">Aguarde...</div></div>

<script>
// ── Dados iniciais (embedded no primeiro load) ───────────────────────────────
let D = __DADOS_JSON__;
const SESSAO = '__SESSAO_ID__';
let filtro = 'roteiro';

// ── Tooltip flutuante ────────────────────────────────────────────────────────
(function(){
  const tt=document.getElementById('tt');
  let cur=null;
  document.addEventListener('mouseover',e=>{
    const el=e.target.closest('[data-w]');
    if(!el){tt.style.display='none';cur=null;return;}
    if(el===cur)return;
    cur=el;tt.textContent=el.dataset.w||'';tt.style.display='block';place(e);
  });
  document.addEventListener('mousemove',e=>{if(tt.style.display==='block')place(e);});
  document.addEventListener('mouseout',e=>{
    if(!e.relatedTarget||!e.relatedTarget.closest('[data-w]')){tt.style.display='none';cur=null;}
  });
  function place(e){
    const pad=14,mw=320;
    let x=e.clientX+pad,y=e.clientY+pad;
    if(x+mw>window.innerWidth)x=e.clientX-mw-pad;
    tt.style.left=Math.max(0,x)+'px';tt.style.top=Math.max(0,y)+'px';
  }
})();

// ── Utilitários ──────────────────────────────────────────────────────────────
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function $id(id){return document.getElementById(id)}

function salvar(){
  const k=`vml_${SESSAO}_${D.roteiro.id}`;
  const m={};D.correcoes.forEach(c=>{m[c.id]=c.decisao});
  localStorage.setItem(k,JSON.stringify(m));
}
function carregar(){
  const k=`vml_${SESSAO}_${D.roteiro.id}`;
  const s=localStorage.getItem(k);if(!s)return;
  const m=JSON.parse(s);
  D.correcoes.forEach(c=>{if(c.id in m)c.decisao=m[c.id]});
}

// ── Diff ─────────────────────────────────────────────────────────────────────
function diff(b,a){
  if(!b||!a)return{pfx:'',del:b||'',ins:a||'',sfx:'',inline:false};
  let i=0;const l=Math.min(b.length,a.length);
  while(i<l&&b[i]===a[i])i++;
  const br=b.slice(i),ar=a.slice(i);
  let j=0;const l2=Math.min(br.length,ar.length);
  while(j<l2&&br[br.length-1-j]===ar[ar.length-1-j])j++;
  const del=j?br.slice(0,-j):br,ins=j?ar.slice(0,-j):ar,sfx=j?br.slice(-j):'';
  const dw=del.trim()?del.trim().split(/\s+/).length:0;
  const iw=ins.trim()?ins.trim().split(/\s+/).length:0;
  return{pfx:b.slice(0,i),del,ins,sfx,inline:Math.max(dw,iw)<=3};
}

// ── Renderização ─────────────────────────────────────────────────────────────
function renderDiff(c){
  const t=c.trecho_original,d=c.correcao;
  if(!t&&!d)return['<span class="diff-null">—</span>','<span class="diff-null">—</span>'];
  if(!t){
    const ant=c.insercao_indefinida
      ?'<span class="diff-null">Posição: a definir pelo editor</span>'
      :'<span class="diff-null">—</span>';
    return[ant,`<div class="diff-blk db-dep">${esc(d)}</div>`];
  }
  if(!d)return[`<div class="diff-blk db-ant">${esc(t)}</div>`,'<span class="diff-null">— Ver ⓘ</span>'];
  const r=diff(t,d);
  if((r.inline||c.diff_inline)&&r.inline){
    return[
      `<div class="diff-blk db-ant">${esc(r.pfx)}<span class="del">${esc(r.del)}</span>${esc(r.sfx)}</div>`,
      `<div class="diff-blk db-dep">${esc(r.pfx)}<span class="ins">${esc(r.ins)}</span>${esc(r.sfx)}</div>`
    ];
  }
  return[`<div class="diff-blk db-ant">${esc(t)}</div>`,`<div class="diff-blk db-dep">${esc(d)}</div>`];
}

function renderBadge(c){
  const cls=c.severidade==='erro'?'badge-e':c.severidade==='aviso'?'badge-a':'badge-s';
  const lbl=c.severidade==='erro'?'⛔ Erro':c.severidade==='aviso'?'⚠ Aviso':'💡 Sugest.';
  const info=c.porque?`<span class="ii" data-w="${esc(c.porque)}">ⓘ</span>`:'';
  // Linha consolidada mostra as tags de TODAS as camadas que contribuíram
  const tags=(c.camadas&&c.camadas.length?c.camadas:[c.camada])
    .map(t=>`<span class="tag-c">${esc(t)}</span>`).join('');
  // Inserção: onde entra fica visível na linha, sem precisar de hover
  const ins=c.insercao_label?`<div class="ins-label">${esc(c.insercao_label)}</div>`:'';
  return`<div class="badge ${cls}">${lbl}</div>
    <div class="tag-row">${tags}${info}</div>${ins}`;
}

function renderAcao(c){
  const d=c.decisao;
  const ensinarBlk=`<div class="ensinar-wrap" id="ensinar-${c.id}">
    <textarea class="ensinar-ta" id="ensinar-ta-${c.id}" placeholder="Ex.: linguagem informal intencional."></textarea>
    <div class="ensinar-btns">
      <button class="btn-en-cf" onclick="confirmarEnsinar('${c.id}')">✓ Enviar</button>
      <button class="btn-en-ca" onclick="fecharEnsinar('${c.id}')">✕</button>
    </div>
  </div>`;
  if(d==='pular')return`<div class="st-pu">— Pulado</div>
    <button class="btn-ac btn-en" onclick="abrirEnsinar('${c.id}')">✦ Ensinar</button>${ensinarBlk}`;
  if(d&&d!=='pular')return`<div class="st-ap">✓ Aplicado</div>
    <button class="btn-ac btn-en" onclick="abrirEnsinar('${c.id}')">✦ Ensinar</button>${ensinarBlk}`;
  // Inserção sem posição: Aplicar fica fora (não há onde aplicar); Editar decide
  const btnAp=c.insercao_indefinida?'':
    `<button class="btn-ac btn-ap" onclick="aplicar('${c.id}')">✓ Aplicar</button>`;
  return`<div class="acao-wrap">
    ${btnAp}
    <button class="btn-ac btn-ed" onclick="editar('${c.id}')">✎ Editar</button>
    <button class="btn-ac btn-pu" onclick="pular('${c.id}')">✕ Pular</button>
    <button class="btn-ac btn-en" onclick="abrirEnsinar('${c.id}')">✦ Ensinar</button>
  </div>${ensinarBlk}`;
}

function renderTudo(){
  const r=D.roteiro,cs=D.correcoes,m=D.meta||{};
  $id('rot-nome').textContent=r.titulo;
  const nb=cs.filter(c=>c.severidade==='erro').length;
  const na=cs.filter(c=>c.severidade==='aviso').length;
  const ns=cs.filter(c=>c.severidade==='sugestao').length;
  $id('n-b').textContent=nb;$id('n-a').textContent=na;$id('n-s').textContent=ns;
  $id('chip-b').style.display=nb?'':'none';
  $id('chip-a').style.display=na?'':'none';
  $id('chip-s').style.display=ns?'':'none';

  const v=r.veredicto||'';
  const vb=$id('verd-badge');vb.textContent=v;
  vb.className='verd-badge '+(v.includes('REPROV')||v.includes('BLOQ')?'verd-rep':
    v.includes('AJUSTE')||v.includes('AVISO')?'verd-ajuste':'verd-ok');

  const btnCont=$id('btn-cont');
  if(m.proximo_titulo){
    btnCont.style.display='';btnCont.textContent=`→ ${m.proximo_titulo.slice(0,30)}`;
  } else if(m.total>1){
    btnCont.style.display='';btnCont.textContent='✓ Concluir';
  } else {
    btnCont.style.display='none';
  }

  // Voltar: visível em sessões multi-roteiro; desabilitado no primeiro,
  // habilitado a partir do segundo (navega pelos roteiros já revisados).
  const btnVolt=$id('btn-volt');
  btnVolt.style.display=m.total>1?'':'none';
  if(m.hist_idx>0&&m.anterior_titulo){
    btnVolt.disabled=false;
    btnVolt.textContent=`← ${m.anterior_titulo.slice(0,30)}`;
  } else {
    btnVolt.disabled=true;
    btnVolt.textContent='← Voltar';
  }

  const tbody=$id('tbody');tbody.innerHTML='';
  let num=1;

  function addLeituraRow(texto,pi){
    const tr=document.createElement('tr');
    tr.id=`row-leitura-${pi}`;
    tr.className='lr-row';
    tr.setAttribute('data-tipo','leitura');
    tr.innerHTML=`<td class="nc lr-n">§</td><td colspan="4" class="lr-texto">${esc(texto)}</td>`;
    tbody.appendChild(tr);
  }

  function addSec(label){
    const tr=document.createElement('tr');tr.className='sec-row';
    const td=document.createElement('td');td.colSpan=5;td.textContent=label;
    tr.appendChild(td);tbody.appendChild(tr);
  }

  function addRow(c){
    const tr=document.createElement('tr');
    tr.id=`row-${c.id}`;
    tr.setAttribute('data-sev',c.severidade||'');
    tr.setAttribute('data-tipo',c.tipo||'correcao');
    let rc=c.severidade==='erro'?'rb':c.severidade==='aviso'?'ra':'rs';
    if(c.decisao&&c.decisao!=='pular')rc+=' row-aprov';
    else if(c.decisao==='pular')rc+=' row-pulada';
    if(filtro!=='roteiro'&&!matchF(c))rc+=' row-hidden';
    tr.className=rc;
    const[antH,depH]=renderDiff(c);
    tr.innerHTML=`<td class="nc">${num++}</td>
      <td>${renderBadge(c)}</td>
      <td id="ant-${c.id}">${antH}</td>
      <td id="dep-${c.id}">${depH}</td>
      <td id="ac-${c.id}">${renderAcao(c)}</td>`;
    tbody.appendChild(tr);
  }

  if(filtro==='roteiro'){
    // Leitura sequencial: D.linhas reproduz o roteiro na ordem original do texto
    (D.linhas||[]).forEach((l,li)=>{
      if(l.tipo==='leitura')addLeituraRow(l.texto,li);
      else if(l.tipo==='secao')addSec(l.label);
      else{const c=getC(l.id);if(c)addRow(c);}
    });
  } else {
    const bloq=cs.filter(c=>c.severidade==='erro'&&c.tipo!=='contexto');
    const avis=cs.filter(c=>c.severidade==='aviso'&&c.tipo!=='contexto');
    const sug=cs.filter(c=>c.severidade==='sugestao'&&c.tipo!=='contexto');
    if(bloq.length){addSec('⛔  ERROS BLOQUEANTES');bloq.forEach(addRow)}
    if(avis.length){addSec('⚠  AVISOS');avis.forEach(addRow)}
    if(sug.length){addSec('💡  SUGESTÕES');sug.forEach(addRow)}
    document.querySelectorAll('.sec-row').forEach(sr=>{
      let nx=sr.nextElementSibling,vis=false;
      while(nx&&!nx.classList.contains('sec-row')){
        if(!nx.classList.contains('row-hidden')){vis=true;break}
        nx=nx.nextElementSibling;
      }
      sr.style.display=vis?'':'none';
    });
  }

  atualizarFooter();
  aplicarFoco();
  marcarOverflow();
}

// ── Overflow dos blocos Antes/Depois ─────────────────────────────────────────
// Conteúdo nunca fica inacessível: bloco que excede as 3 linhas do clamp ganha
// um botão explícito "ver tudo" que expande a linha (sem corte silencioso).
function marcarOverflow(){
  document.querySelectorAll('#tbody .diff-blk').forEach(el=>{
    const next=el.nextElementSibling;
    const temBtn=next&&next.classList&&next.classList.contains('ver-mais');
    if(el.classList.contains('aberto'))return;
    if(el.scrollHeight>el.clientHeight+2){
      if(!temBtn){
        const b=document.createElement('button');
        b.className='ver-mais';b.textContent='▾ ver tudo';
        b.onclick=()=>{
          const ab=el.classList.toggle('aberto');
          b.textContent=ab?'▴ recolher':'▾ ver tudo';
        };
        el.after(b);
      }
    } else if(temBtn){next.remove()}
  });
}
let _ovTimer=null;
window.addEventListener('resize',()=>{
  clearTimeout(_ovTimer);_ovTimer=setTimeout(marcarOverflow,150);
});

// ── Teclado (J/K navegar · A aplicar · E editar · P pular) ──────────────────
let focoId=null;

function allVisRowIds(){
  return [...document.querySelectorAll('#tbody tr[id]')]
    .filter(r=>!r.classList.contains('row-hidden'))
    .map(r=>r.id.replace('row-',''));
}

function aplicarFoco(){
  document.querySelectorAll('tr.row-focus').forEach(r=>r.classList.remove('row-focus'));
  if(!focoId)return;
  const r=$id(`row-${focoId}`);
  if(r&&!r.classList.contains('row-hidden')){
    r.classList.add('row-focus');
    r.scrollIntoView({block:'center',behavior:'smooth'});
  }
}

function mover(d){
  const ids=allVisRowIds();if(!ids.length)return;
  let i=ids.indexOf(focoId);
  i=i<0?(d>0?0:ids.length-1):Math.min(ids.length-1,Math.max(0,i+d));
  focoId=ids[i];aplicarFoco();
}

function nextPendingAfter(id){
  const ids=allVisRowIds();
  let i=ids.indexOf(id);
  for(let j=i+1;j<ids.length;j++){
    if(ids[j].startsWith('leitura-'))continue;
    const c=getC(ids[j]);
    if(c&&!c.decisao)return ids[j];
  }
  return null;
}

document.addEventListener('keydown',e=>{
  const tag=(e.target.tagName||'').toLowerCase();
  if(tag==='textarea'||tag==='input'||e.metaKey||e.ctrlKey||e.altKey)return;
  const k=e.key.toLowerCase();
  const isCorr=focoId&&!focoId.startsWith('leitura-');
  if(k==='j'||e.key==='ArrowDown'){e.preventDefault();mover(1)}
  else if(k==='k'||e.key==='ArrowUp'){e.preventDefault();mover(-1)}
  else if(k==='a'&&isCorr){e.preventDefault();aplicar(focoId)}
  else if(k==='e'&&isCorr){e.preventDefault();editar(focoId)}
  else if(k==='p'&&isCorr){e.preventDefault();pular(focoId)}
});

// ── Filtro ────────────────────────────────────────────────────────────────────
function matchF(c){
  if(filtro==='roteiro')return true;
  if(filtro==='todos')return true;
  if(filtro==='bloqueantes')return c.severidade==='erro';
  if(filtro==='avisos')return c.severidade==='aviso';
  if(filtro==='sugestoes')return c.severidade==='sugestao';
  if(filtro==='pendentes')return!c.decisao&&c.tipo==='correcao';
  if(filtro==='aprovados')return c.decisao&&c.decisao!=='pular';
  return true;
}

function setF(btn,f,activeClass){
  filtro=f;
  document.querySelectorAll('.fbtn').forEach(b=>b.className='fbtn');
  btn.className='fbtn '+(activeClass||'fa');
  renderTudo();
}

// ── Ações ─────────────────────────────────────────────────────────────────────
function getC(id){return D.correcoes.find(c=>c.id===id)}

function sync(id,motivo){
  const c=getC(id);if(!c)return;
  // Linha consolidada: a decisão única vale para todos os achados incorporados
  (c.ids&&c.ids.length?c.ids:[id]).forEach(aid=>{
    fetch('/api/decisao',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:aid,decisao:c.decisao,motivo:motivo||''})}).catch(()=>{});
  });
}

function aplicar(id){
  const c=getC(id);if(!c||c.insercao_indefinida)return;
  c.decisao=c.correcao||'aplicado';
  salvar();sync(id);atualizarLinha(id);atualizarFooter();
  const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
}

function pular(id){
  const c=getC(id);if(!c)return;
  c.decisao='pular';
  salvar();sync(id,'');atualizarLinha(id);atualizarFooter();
  const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
}

function abrirEnsinar(id){
  const wrap=$id(`ensinar-${id}`);if(!wrap)return;
  wrap.classList.toggle('aberto');
  if(wrap.classList.contains('aberto')){const ta=$id(`ensinar-ta-${id}`);if(ta)ta.focus();}
}

function fecharEnsinar(id){
  const wrap=$id(`ensinar-${id}`);if(wrap)wrap.classList.remove('aberto');
  const ta=$id(`ensinar-ta-${id}`);if(ta)ta.value='';
}

function confirmarEnsinar(id){
  const ta=$id(`ensinar-ta-${id}`);if(!ta)return;
  const texto=ta.value.trim();if(!texto)return;
  const c=getC(id);if(!c)return;
  fetch('/api/decisao',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:id,decisao:c.decisao||'ensinar',motivo:texto})}).catch(()=>{});
  fecharEnsinar(id);toast('Ensinamento registrado');
}

function editar(id){
  const c=getC(id);if(!c)return;
  const txt=typeof c.decisao==='string'&&c.decisao!=='pular'?c.decisao:(c.correcao||'');
  const dep=$id(`dep-${id}`),ac=$id(`ac-${id}`);
  dep.innerHTML=`<textarea class="edit-ta" id="ta-${id}">${esc(txt)}</textarea>`;
  ac.innerHTML=`<div class="acao-wrap">
    <button class="btn-ac btn-cf" onclick="conf('${id}')">✓ Confirmar</button>
    <button class="btn-ac btn-ca" onclick="canc('${id}')">✕ Cancelar</button>
  </div>`;
  const ta=$id(`ta-${id}`);
  if(ta){
    ta.focus();ta.select();
    ta.addEventListener('keydown',ev=>{
      if(ev.key==='Escape'){ev.preventDefault();canc(id)}
      else if((ev.metaKey||ev.ctrlKey)&&ev.key==='Enter'){ev.preventDefault();conf(id)}
    });
  }
}

function conf(id){
  const ta=$id(`ta-${id}`);if(!ta)return;
  const novo=ta.value.trim();if(!novo)return;
  const c=getC(id);if(!c)return;
  c.decisao=novo;salvar();sync(id);atualizarLinha(id);atualizarFooter();
  const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
}

function canc(id){atualizarLinha(id)}

function atualizarLinha(id){
  const c=getC(id);if(!c)return;
  const row=$id(`row-${id}`);
  if(row){
    row.classList.remove('row-aprov','row-pulada');
    if(c.decisao&&c.decisao!=='pular')row.classList.add('row-aprov');
    else if(c.decisao==='pular')row.classList.add('row-pulada');
  }
  const dep=$id(`dep-${id}`);
  if(dep){
    const mostrar={...c,correcao:c.decisao&&c.decisao!=='pular'?c.decisao:c.correcao};
    dep.innerHTML=renderDiff(mostrar)[1];
  }
  const ac=$id(`ac-${id}`);if(ac)ac.innerHTML=renderAcao(c);
  marcarOverflow();
}

// ── Footer ────────────────────────────────────────────────────────────────────
function atualizarFooter(){
  const cs=D.correcoes.filter(c=>c.tipo==='correcao');
  const ap=cs.filter(c=>c.decisao&&c.decisao!=='pular').length;
  const tot=cs.length;
  const bPend=cs.filter(c=>c.severidade==='erro'&&!c.decisao).length;
  $id('n-ap').textContent=ap;$id('n-tot').textContent=tot;
  const st=$id('footer-st'),btn=$id('btn-gravar');
  if(bPend>0){
    st.className='footer-c';
    st.textContent=`${bPend} bloqueante(s) pendente(s) · não publicável`;
    btn.disabled=true;
  } else {
    const pend=cs.filter(c=>!c.decisao).length;
    if(pend>0){st.className='footer-c';st.textContent=`${pend} pendente(s)`;btn.disabled=false}
    else{st.className='footer-c pronto';st.textContent='✓ Pronto para publicação';btn.disabled=false}
  }
}

// ── Gravar no Google Docs ─────────────────────────────────────────────────────
async function gravar(){
  if(!D.url_gdocs){toast('Sem URL do Google Docs. Reinicie: python3 revisar.py --gdocs "URL"','e');return;}
  const aprovadas=D.correcoes.filter(c=>c.tipo==='correcao'&&c.decisao&&c.decisao!=='pular')
    .map(c=>({trecho_original:c.trecho_original,decisao:c.decisao}));
  if(!aprovadas.length){toast('Nenhuma correção aprovada.','e');return}
  const btn=$id('btn-gravar');btn.disabled=true;btn.textContent='Gravando...';
  try{
    const r=await fetch('/api/apply',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url_gdocs:D.url_gdocs||'',correcoes:aprovadas})});
    const d=await r.json();
    if(r.ok){
      let msg=`✓ ${d.aplicadas} substituição(ões) gravada(s) no Google Docs`;
      if(d.avisos&&d.avisos.length)msg+=` · ⚠ ${d.avisos.join(' · ')}`;
      toast(msg,'s');
    } else toast(d.error||'Erro ao gravar','e');
  }catch(e){toast('Erro de conexão com o servidor local','e')}
  finally{
    btn.disabled=false;btn.textContent='Gravar no Google Docs';
    const bp=D.correcoes.filter(c=>c.severidade==='erro'&&!c.decisao).length;
    btn.disabled=bp>0;
  }
}

// ── Navegação entre roteiros já revisados (Voltar / re-Avançar) ──────────────
async function navegar(delta){
  try{
    const r=await fetch('/api/navegar',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({delta})});
    if(!r.ok){toast('Não foi possível navegar','e');return;}
    D=await r.json();
    focoId=null;
    carregar();renderTudo();window.scrollTo(0,0);
    toast(`${delta<0?'←':'→'} ${D.roteiro.titulo.slice(0,40)}`,'s');
  }catch(e){toast('Erro de conexão com o servidor local','e')}
}

function voltar(){
  const m=D.meta||{};
  if(m.hist_idx>0)navegar(-1);
}

// ── Continuar para o próximo roteiro ─────────────────────────────────────────
async function continuar(){
  // Se o próximo roteiro já foi revisado nesta sessão (voltamos no histórico),
  // só navega pelo cache — o pipeline Python continua parado na fronteira.
  const m=D.meta||{};
  if(m.hist_total&&m.hist_idx<m.hist_total-1){navegar(1);return;}
  const loading=$id('loading');
  $id('loading-msg').textContent='Processando próximo roteiro...';
  loading.classList.add('show');
  try{
    const r=await fetch('/api/continuar',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    if(d.recarregar){
      const r2=await fetch('/api/dados');D=await r2.json();
      localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}`);
      carregar();renderTudo();window.scrollTo(0,0);
      toast(`✓ ${D.roteiro.titulo.slice(0,40)}...`,'s');
    } else {
      toast('Revisão concluída! Pode fechar esta aba.','s');
      $id('btn-cont').disabled=true;$id('btn-cont').textContent='✓ Concluído';
    }
  }catch(e){toast('Erro ao avançar para o próximo roteiro','e')}
  finally{loading.classList.remove('show')}
}

// ── Resetar / Exportar ────────────────────────────────────────────────────────
function resetar(){
  if(!confirm('Resetar todas as decisões?'))return;
  D.correcoes.forEach(c=>{if(c.decisao!==null){c.decisao=null;sync(c.id)}});
  localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}`);renderTudo();
}

function exportar(){
  const payload={roteiro:D.roteiro,correcoes:D.correcoes,exportado_em:new Date().toISOString()};
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;
  a.download=`roteiro_${D.roteiro.id}_decisoes.json`;a.click();
  URL.revokeObjectURL(url);toast('JSON exportado!','s');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer=null;
function toast(msg,tipo){
  const t=$id('toast');t.textContent=msg;
  t.className=(tipo==='s'?'ts':'te')+' show';
  clearTimeout(_toastTimer);_toastTimer=setTimeout(()=>t.classList.remove('show'),3500);
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded',()=>{carregar();renderTudo()});
</script>
</body>
</html>"""


# ─── Entry point CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import socket

    def porta_disponivel(inicio: int = 7432) -> int:
        for p in range(inicio, inicio + 20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
        return inicio

    parser = argparse.ArgumentParser(description="Tabela Interativa — VML")
    parser.add_argument("json", nargs="?", help="Caminho do JSON de revisão")
    parser.add_argument("--gdocs", "-g", help="URL do Google Doc (para gravar correções)")
    parser.add_argument("--porta", "-p", type=int, default=7432)
    args = parser.parse_args()

    json_path = Path(args.json) if args.json else json_mais_recente()
    if not json_path or not json_path.exists():
        print("❌ Nenhum JSON de revisão encontrado. Rode revisar.py primeiro.")
        sys.exit(1)

    porta = porta_disponivel(args.porta)
    iniciar_standalone(json_path, url_gdocs=args.gdocs or "", porta=porta)
