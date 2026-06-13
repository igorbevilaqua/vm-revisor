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

    # Segunda camada de defesa: se `correcao` chegou como instrução editorial
    # (agente ignorou o prompt), ela não é substituível — move a instrução para o
    # `porque` e mantém o trecho como âncora. O achado vira NOTA (abaixo).
    if _correcao_e_instrucao(correcao):
        porque = f"{porque} [Sugestão do agente: {correcao}]".strip()
        correcao = ""

    # Tipo da linha:
    #   correcao → Antes→Depois decidível (inclui inserções: sem trecho, com correção)
    #   nota     → conselho sem texto substituto (com ou sem âncora no roteiro);
    #              não entra no fluxo de decisão — vira sinal ✎ lateral na linha
    #              do trecho (ou nota geral no topo). Ver marcarNotas() no front.
    tipo = "correcao" if correcao else "nota"

    return {
        "id": f"c{idx:03d}",
        "tipo": tipo,
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
    notas = []
    descartados = 0
    for i, a in enumerate(achados, 1):
        t = (a.get("trecho_original") or "").strip()
        c = (a.get("correcao") or "").strip()
        p = (a.get("porque") or "").strip()
        if not t and not c and not p:
            descartados += 1
            continue
        item = transformar_achado(a, i)
        # NOTA (sem texto substituto): não entra no fluxo de decisão nem na
        # consolidação — vai para a margem da linha do trecho (sinal ✎).
        # Nota sem justificativa não tem o que mostrar — descarta.
        if item["tipo"] == "nota":
            if not item["porque"]:
                descartados += 1
                continue
            item["_para_idx"] = (
                _para_idx_de_achado(item["trecho_original"], texto, para_offsets)
                if item["trecho_original"] else len(para_offsets)
            )
            notas.append(item)
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
        print(f"   🧹 {descartados} achado(s) sem conteúdo aproveitável descartado(s) da tabela")

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
        pi_it = it.get("_para_idx")
        linhas.append({"tipo": "correcao", "id": it["id"],
                       "pi": pi_it if (pi_it is not None and pi_it < n_par) else None})

    for pi, par in enumerate(paragrafos_raw):
        achs = [it for it in itens if it["_para_idx"] == pi]
        dentro = [a for a in achs if a["trecho_original"] and a["trecho_original"] in par]
        _ids_dentro = {id(a) for a in dentro}
        fora = [a for a in achs if id(a) not in _ids_dentro]
        if not dentro:
            linhas.append({"tipo": "leitura", "texto": par, "pi": pi})
        else:
            segs = _segmentar_paragrafo(par, [a["trecho_original"] for a in dentro])
            usados = set()
            for seg in segs:
                seg_achs = [a for a in dentro
                            if id(a) not in usados and a["trecho_original"] in seg]
                for a in seg_achs:
                    usados.add(id(a))
                if not seg_achs:
                    linhas.append({"tipo": "leitura", "texto": seg, "pi": pi})
                else:
                    restantes, row = _consolidar_segmento(seg, seg_achs, pi)
                    correcoes.append(row)
                    linhas.append({"tipo": "correcao", "id": row["id"], "pi": pi})
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

    # Notas entram em `correcoes` (mesma fonte de dados: decisão/persistência/
    # localStorage funcionam igual), mas NUNCA viram linha — o front as renderiza
    # como sinal ✎ na margem da linha do trecho + painel lateral.
    correcoes.extend(notas)

    veredicto = cons.get("veredicto", "—")
    return {
        "roteiro": {
            "titulo": roteiro_raw.get("titulo", "Roteiro"),
            "cliente": roteiro_raw.get("cliente") or "",
            "id": f"rot_{roteiro_raw.get('numero', 1):02d}",
            "veredicto": veredicto,
            "score_geral": cons.get("nota_geral", 0),
        },
        "url_gdocs": url_gdocs or "",
        "contexto": roteiro_raw.get("contexto") or {},
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
            ).replace("__SESSAO_ID__", server.sessao_id
            ).replace("__LAUNCHER_URL__",
                      os.environ.get("VML_LAUNCHER_URL", ""))
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

        @app.route("/api/bob", methods=["POST"])
        def api_bob():
            """Acionamento do ✦ Bob: reescreve um trecho a partir do feedback do
            revisor. Registra o evento no ledger (sinal cru); o aprendizado
            destilado entra na janela do fim da sessão, com aval do editor."""
            data = request.get_json() or {}
            trecho = (data.get("trecho_original") or "").strip()
            feedback = (data.get("feedback") or "").strip()
            if not feedback:
                return jsonify({"error": "Feedback é obrigatório para o Bob reescrever."}), 400
            sugestao = (data.get("sugestao_anterior") or "").strip()
            agente = (data.get("agente") or "").strip()
            cliente = server.dados_atual.get("roteiro", {}).get("cliente", "") or ""
            ctx = server.dados_atual.get("contexto") or {}
            try:
                from agentes.bob import AgenteBob
                res = AgenteBob().reescrever(
                    trecho_original=trecho, sugestao_anterior=sugestao, feedback=feedback,
                    agente_origem=agente, cliente=cliente,
                    tema=ctx.get("tema", "") or "", estrutura=ctx.get("estrutura", "") or "",
                )
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            # Ledger: sinal cru do acionamento (fundação do aprendizado)
            try:
                import ledger
                ledger.registrar({
                    "origem": "bob",
                    "cliente": cliente,
                    "roteiro_titulo": server.dados_atual.get("roteiro", {}).get("titulo", ""),
                    "estrutura_codex": ctx.get("estrutura", "") or "",
                    "camada": agente,
                    "trecho": trecho,
                    "correcao_agente": sugestao,
                    "versao_usuario": res.get("reescrita", ""),
                    "decisao": "esclarecer" if res.get("precisa_esclarecer") else "bob_reescreveu",
                    "motivo": feedback,
                })
            except Exception:
                pass
            return jsonify(res)

        @app.route("/api/aprendizados/candidatos", methods=["POST"])
        def api_aprendizados_candidatos():
            """Compila os sinais da sessão inteira (pular/editar/aplicar dos achados
            + edições de linhas de leitura §) e extrai a lição de cada um (1 LLM
            call). Chamado pelo front no Gravar do último roteiro."""
            data = request.get_json() or {}
            # Edições de linha de leitura vêm do front (vivem no localStorage, não
            # nos achados). Anexa o contexto do roteiro atual (1 cliente/doc).
            rot = server.dados_atual.get("roteiro", {})
            ctx = server.dados_atual.get("contexto") or {}
            edicoes = []
            for e in (data.get("edicoes_leitura") or []):
                if isinstance(e, dict) and e.get("trecho_original") and e.get("decisao"):
                    edicoes.append({**e, "cliente": rot.get("cliente", ""),
                                    "tema": ctx.get("tema", ""), "estrutura": ctx.get("estrutura", "")})
            try:
                import aprendizados
                sinais = aprendizados.compilar_sinais(server._roteiros_decididos(), edicoes)
                if not sinais:
                    return jsonify({"candidatos": [], "sinais": 0})
                candidatos = aprendizados.destilar(sinais)
                return jsonify({"candidatos": candidatos, "sinais": len(sinais)})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/aprendizados/salvar", methods=["POST"])
        def api_aprendizados_salvar():
            """Grava os aprendizados confirmados pelo revisor na janela."""
            data = request.get_json() or {}
            itens = data.get("aprendizados", [])
            if not isinstance(itens, list):
                return jsonify({"error": "formato inválido"}), 400
            try:
                import aprendizados
                salvos = aprendizados.adicionar(itens)
                if salvos:
                    try:
                        import git_sync
                        git_sync.enviar(mensagem=f"aprendizados: +{len(salvos)} (sessão)")
                    except Exception:
                        pass  # sync é best-effort, nunca derruba a gravação
                return jsonify({"ok": True, "salvos": len(salvos),
                                "ids": [s["id"] for s in salvos]})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/aprendizados/promocoes", methods=["POST"])
        def api_aprendizados_promocoes():
            """Detecta aprendizados de cliente que se repetem entre clientes
            diferentes (candidatos a virar global). `novos_ids` = os recém-salvos
            nesta sessão, para não re-sugerir o que já foi ignorado."""
            data = request.get_json() or {}
            try:
                import aprendizados
                novos = data.get("novos_ids") or None
                return jsonify({"promocoes": aprendizados.detectar_promocoes(novos)})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/aprendizados/promover", methods=["POST"])
        def api_aprendizados_promover():
            """Aplica as promoções confirmadas pelo revisor (cliente → global)."""
            data = request.get_json() or {}
            try:
                import aprendizados
                n = 0
                for p in data.get("promover", []):
                    if aprendizados.promover(p.get("ids", []), p.get("texto_global", ""),
                                             p.get("camada")):
                        n += 1
                if n:
                    try:
                        import git_sync
                        git_sync.enviar(mensagem=f"aprendizados: {n} promovido(s) a global")
                    except Exception:
                        pass
                return jsonify({"ok": True, "promovidos": n})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

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

    # ── Sinais da sessão (para a janela de aprendizados) ───────────────────
    def _roteiros_decididos(self) -> list:
        """Roteiros do documento com as decisões mais frescas carimbadas.
        Fonte: o revisao_*.json (persistido a cada clique) + self.decisoes em
        memória (cobre o intervalo entre o clique e a releitura do arquivo)."""
        if not self.json_path or not self.json_path.exists():
            return []
        try:
            with self._lock_json:
                dados = json.loads(self.json_path.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                dados = [dados]
            return aplicar_decisoes_no_payload(dados, self.decisoes, self.motivos)
        except Exception:
            return []

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
    # Aprendizado: absorvido pela janela de revisão de aprendizados (abre no
    # Gravar do último roteiro) — sem prompt de terminal aqui.


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
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script>
// Tema antes do primeiro paint (evita flash). Padrão: claro.
// sessionStorage: toda aba nova abre no claro; o toggle vale só para a sessão
document.documentElement.dataset.theme=sessionStorage.getItem('vml_tema')||'claro';
</script>
<style>
:root{
  /* ── Tema CLARO (padrão) — tokens do handoff design_handoff_revisor_vm ─── */
  --bg:#F4F4F5;--card:#FFFFFF;--subtle:#FCFCFD;--box:#FAFAFA;
  --bd:#E4E4E7;--bd2:#EFEFF1;--bd3:#F0F0F2;--bd4:#F4F4F5;
  --tx:#18181B;--tx-2:#52525B;--tx-3:#71717A;--tx-4:#A1A1AA;--tx-5:#B4B4BB;
  --tx-dis:#C4C4C8;--ctx:#9CA3AF;
  --green:#16A34A;--green-h:#15803D;--gravar:#15803D;--gravar-h:#166534;
  --ins-bg:rgba(22,163,74,.14);--ins-tx:#15803D;
  --antes-bd:#F4C2C2;--depois-bd:#A7E8BE;
  --sev-b:#DC2626;--sev-b-bg:#FEF2F2;--sev-b-tx:#B91C1C;
  --sev-a:#E0A106;--sev-a-bg:#FEFBEB;--sev-a-tx:#B45309;
  --sev-s:#2563EB;--sev-s-bg:#EFF6FF;--sev-s-tx:#1D4ED8;
  --sev-n:#A1A1AA;--sev-n-bg:#F4F4F5;--sev-n-tx:#52525B;
  --bob:#7C3AED;--bob-bg:#F5F3FF;--bob-bd:#DDD6FE;
  --blue:#1D4ED8;--blue-bd:#BFDBFE;--blue-bg:#EFF6FF;
  --amber:#A16207;--amber-bg:#FEFCE8;--amber-bd:#FDE68A;--amber-dot:#CA8A04;
  --edit-bg:#F6FBF7;--edit-bd:#D6F0DE;
  --avatar-bg:#DDD6FE;--avatar-tx:#6D28D9;
  --btn-tx:#3F3F46;--hover-row:#FAFAFA;
  --card-shadow:0 1px 2px rgba(0,0,0,.04),0 16px 40px -28px rgba(0,0,0,.18);
  --overlay:rgba(244,244,245,.85);
  --toast-bg:#18181B;--toast-tx:#FFFFFF;
  --logo-bg:#18181B;--logo-tx:#FFFFFF;
  --sans:'Geist',-apple-system,sans-serif;--mono:'Geist Mono',monospace;
}
:root[data-theme="escuro"]{
  --bg:#101013;--card:#18181B;--subtle:#1B1B1F;--box:#1F1F23;
  --bd:#2E2E33;--bd2:#27272B;--bd3:#252529;--bd4:#222226;
  --tx:#FAFAFA;--tx-2:#D4D4D8;--tx-3:#A1A1AA;--tx-4:#7C7C85;--tx-5:#636369;
  --tx-dis:#4A4A52;--ctx:#71717A;
  --green:#22C55E;--green-h:#16A34A;--gravar:#15803D;--gravar-h:#166534;
  --ins-bg:rgba(34,197,94,.16);--ins-tx:#4ADE80;
  --antes-bd:#6B3030;--depois-bd:#245C3C;
  --sev-b:#F87171;--sev-b-bg:rgba(248,113,113,.1);--sev-b-tx:#FCA5A5;
  --sev-a:#FBBF24;--sev-a-bg:rgba(251,191,36,.1);--sev-a-tx:#FCD34D;
  --sev-s:#60A5FA;--sev-s-bg:rgba(96,165,250,.1);--sev-s-tx:#93C5FD;
  --sev-n:#71717A;--sev-n-bg:#26262B;--sev-n-tx:#A1A1AA;
  --bob:#C084FC;--bob-bg:rgba(192,132,252,.1);--bob-bd:#4C2A6E;
  --blue:#60A5FA;--blue-bd:#1E3A5F;--blue-bg:rgba(96,165,250,.08);
  --amber:#FCD34D;--amber-bg:rgba(202,138,4,.12);--amber-bd:rgba(202,138,4,.35);--amber-dot:#CA8A04;
  --edit-bg:#14201A;--edit-bd:#1F4D33;
  --avatar-bg:#3B2A66;--avatar-tx:#C4B5FD;
  --btn-tx:#D4D4D8;--hover-row:#1C1C20;
  --card-shadow:0 1px 2px rgba(0,0,0,.4),0 16px 40px -28px rgba(0,0,0,.6);
  --overlay:rgba(16,16,19,.85);
  --toast-bg:#FAFAFA;--toast-tx:#18181B;
  --logo-bg:#FAFAFA;--logo-tx:#18181B;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:var(--sans);font-size:13px;
  line-height:1.5;padding:26px 28px 48px}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px}
button{font-family:var(--sans)}

.page{max-width:1280px;margin:0 auto}

/* ── Cabeçalho da página ─── */
.page-head{margin-bottom:18px}
.brand-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.brand{display:flex;align-items:center;gap:9px}
.logo{width:26px;height:26px;border-radius:7px;background:var(--logo-bg);color:var(--logo-tx);
  display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;
  letter-spacing:.02em}
.brand-label{font-size:12px;font-weight:600;color:var(--tx-4);letter-spacing:.16em}
.page-title{font-size:24px;font-weight:700;letter-spacing:-.02em;color:var(--tx)}

/* Toggle de tema (☀ claro / ☾ escuro) */
#tema-toggle{display:flex;padding:2px;gap:2px;border:1px solid var(--bd);
  border-radius:8px;background:var(--card);cursor:pointer;user-select:none}
#tema-toggle .tt-opt{padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;
  color:var(--tx-4);transition:all .18s}
#tema-toggle .tt-opt.ativo{background:var(--bd4);color:var(--tx)}
#tema-toggle:hover .tt-opt:not(.ativo){color:var(--tx-2)}

/* ── Card do painel ─── */
.card{background:var(--card);border:1px solid var(--bd);border-radius:16px;
  box-shadow:var(--card-shadow);overflow:hidden}

/* Header do card */
.card-head{padding:13px 20px;background:var(--subtle);border-bottom:1px solid var(--bd2);
  display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.ch-left{display:flex;align-items:center;gap:10px;min-width:0}
.ch-label{font-size:12px;font-weight:600;color:var(--tx-4);letter-spacing:.12em}
.vdiv{width:1px;height:18px;background:var(--bd);flex-shrink:0}
.rot-sel{display:flex;align-items:center;gap:7px;border:1px solid var(--bd);border-radius:9px;
  padding:6px 11px;min-width:0;background:var(--card)}
.rot-sel #rot-nome{font-size:13px;font-weight:600;color:var(--tx-2);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;max-width:340px}
.rot-sel .chev{font-size:10px;color:var(--tx-4)}
.rot-pos{font-size:11px;font-weight:600;color:var(--tx-4);white-space:nowrap}
.autor-chip{display:flex;align-items:center;gap:6px;background:var(--bd4);border-radius:999px;
  padding:3px 10px 3px 3px;max-width:200px}
.autor-chip .avatar{width:19px;height:19px;border-radius:50%;background:var(--avatar-bg);
  color:var(--avatar-tx);display:flex;align-items:center;justify-content:center;
  font-size:8.5px;font-weight:700;flex-shrink:0}
.autor-chip span:last-child{font-size:12px;font-weight:500;color:var(--tx-2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ch-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.legend{display:flex;align-items:center;gap:12px;background:var(--box);
  border:1px solid var(--bd3);border-radius:10px;padding:6px 12px}
.legend:empty{display:none}
.lg-item{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--tx-4)}
.lg-item b{font-weight:600;color:var(--tx-2)}
.lg-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.chip-nota{display:flex;align-items:center;gap:5px;font-size:12px;font-weight:600;
  background:var(--amber-bg);border:1px solid var(--amber-bd);color:var(--amber);
  border-radius:999px;padding:4px 11px;cursor:pointer;transition:filter .15s}
.chip-nota:hover{filter:brightness(.96)}
.verd{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 12px;
  font-size:12px;font-weight:600;white-space:nowrap}
.verd::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor}
.verd-ajuste{background:var(--amber-bg);border:1px solid var(--amber-bd);color:var(--amber)}
.verd-ajuste::before{background:var(--amber-dot)}
.verd-rep{background:var(--sev-b-bg);border:1px solid var(--antes-bd);color:var(--sev-b-tx)}
.verd-ok{background:var(--edit-bg);border:1px solid var(--edit-bd);color:var(--ins-tx)}

/* Barra de progresso */
.prog-row{padding:11px 20px;background:var(--card);border-bottom:1px solid var(--bd3);
  display:flex;align-items:center;gap:14px}
.prog-label{font-size:12.5px;font-weight:600;color:var(--tx-2);white-space:nowrap}
.prog-label b{color:var(--green);font-weight:600}
.prog-track{flex:1;height:6px;border-radius:999px;background:var(--bd3);overflow:hidden}
.prog-fill{height:100%;background:var(--green);border-radius:999px;width:0;
  transition:width .35s ease}
.prog-pend{font-size:12.5px;color:var(--tx-4);white-space:nowrap}
.prog-pend.blocked{color:var(--sev-b-tx);font-weight:600}

/* Filtros */
#filtros{padding:9px 20px;border-bottom:1px solid var(--bd3);display:flex;
  align-items:center;gap:6px;flex-wrap:wrap}
.f-label{font-size:10.5px;font-weight:600;color:var(--tx-5);letter-spacing:.08em;
  text-transform:uppercase;margin-right:4px}
.fbtn{padding:4px 11px;border-radius:7px;border:1px solid var(--bd);background:transparent;
  color:var(--tx-3);font-size:12px;font-weight:500;cursor:pointer;transition:all .15s}
.fbtn:hover{border-color:var(--tx-5);color:var(--tx)}
.fbtn.fa{border-color:var(--blue-bd);background:var(--blue-bg);color:var(--blue)}
.fbtn.fa-b{border-color:var(--antes-bd);background:var(--sev-b-bg);color:var(--sev-b-tx)}
.fbtn.fa-a{border-color:var(--amber-bd);background:var(--sev-a-bg);color:var(--sev-a-tx)}
.fbtn.fa-v{border-color:var(--edit-bd);background:var(--edit-bg);color:var(--ins-tx)}

/* Cabeçalho de colunas */
.cols-head{display:grid;grid-template-columns:50px 162px 1fr 1fr 104px;gap:18px;
  padding:9px 20px;border-bottom:1px solid var(--bd3)}
.cols-head span{font-size:10.5px;font-weight:600;color:var(--tx-5);letter-spacing:.08em;
  text-transform:uppercase}
.cols-head .ca-r{text-align:right}

/* ── Linhas ─── */
.row-wrap{border-bottom:1px solid var(--bd4)}
.row-hidden{display:none}
.frow{position:relative;display:grid;grid-template-columns:50px 162px 1fr 1fr 104px;
  gap:18px;padding:17px 20px;align-items:start;transition:background .15s}
.frow:hover{background:var(--hover-row)}
.frow::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px}
.frow.sev-b::before{background:var(--sev-b)}
.frow.sev-a::before{background:var(--sev-a)}
.frow.sev-s::before{background:var(--sev-s)}
.frow.applied .fantes{opacity:.4;transition:opacity .2s}
.frow.skipped{opacity:.5}
@keyframes approvalFlash{0%{background:var(--ins-bg)}100%{background:transparent}}
.frow.flash{animation:approvalFlash .55s ease-out}
.row-focus .frow,.ctx-row.row-focus{outline:2px solid var(--sev-s);outline-offset:-2px}

.fnum{font-size:13px;font-weight:600;color:var(--tx-4)}
.fcat{display:flex;flex-direction:column;align-items:flex-start;gap:6px}
.sev-pill{display:inline-flex;align-items:center;gap:5px;border-radius:999px;
  padding:3px 10px;font-size:11px;font-weight:600;white-space:nowrap}
.sev-pill::before{content:'';width:6px;height:6px;border-radius:50%;flex-shrink:0}
.sp-b{background:var(--sev-b-bg);color:var(--sev-b-tx)}.sp-b::before{background:var(--sev-b)}
.sp-a{background:var(--sev-a-bg);color:var(--sev-a-tx)}.sp-a::before{background:var(--sev-a)}
.sp-s{background:var(--sev-s-bg);color:var(--sev-s-tx)}.sp-s::before{background:var(--sev-s)}
.sp-n{background:var(--sev-n-bg);color:var(--sev-n-tx)}.sp-n::before{background:var(--sev-n)}
.cat-chips{display:flex;flex-wrap:wrap;gap:4px}
.tag-c{display:inline-block;padding:2px 7px;border-radius:6px;font-size:11px;font-weight:500;
  background:var(--box);color:var(--tx-2);border:1px solid var(--bd2)}
.ins-label{font-size:11px;color:var(--ins-tx);line-height:1.4}

.fantes{font-size:13.5px;line-height:1.6;color:var(--tx-2);
  border-left:2px solid var(--antes-bd);padding-left:12px}
.fdepois{border-left:2px solid var(--depois-bd);padding-left:12px}
.dep-text{font-size:13.5px;line-height:1.6;color:var(--tx)}
mark.ins{background:var(--ins-bg);color:var(--ins-tx);font-weight:600;border-radius:3px;
  padding:0 2px;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.tag-c[data-w]{cursor:help}
.tag-c[data-w]:hover{border-color:var(--tx-5);color:var(--tx)}
.diff-null{color:var(--tx-4);font-size:12px;font-style:italic}

/* Clamp de 3 linhas + "ver tudo" (conteúdo nunca fica inacessível) */
.clamp{overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.clamp.aberto{display:block;-webkit-line-clamp:initial;overflow:visible}
.ver-mais{display:block;margin-top:4px;padding:1px 8px;border:1px solid var(--bd);
  border-radius:6px;background:transparent;color:var(--tx-4);cursor:pointer;
  font-size:11px;transition:all .15s}
.ver-mais:hover{color:var(--tx-2);border-color:var(--tx-5)}

/* Coluna AÇÃO */
.facao{display:flex;flex-direction:column;gap:6px;align-items:stretch}
.btn{border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer;
  padding:6px 10px;border:1px solid transparent;transition:all .15s;white-space:nowrap;
  text-align:center}
.btn:active{transform:scale(.97)}
.btn-aplicar{background:var(--green);color:#fff;border-color:var(--green)}
.btn-aplicar:hover{background:var(--green-h);border-color:var(--green-h)}
.btn-outline{background:var(--card);color:var(--btn-tx);border-color:var(--bd)}
.btn-outline:hover{background:var(--box)}
.selo{font-size:12.5px;font-weight:600;text-align:center;padding:4px 0}
.selo-ap{color:var(--green)}
.selo-pu{color:var(--tx-4)}
.lnk{background:none;border:none;font-size:12px;color:var(--tx-3);text-decoration:underline;
  cursor:pointer;padding:2px 0}
.lnk:hover{color:var(--tx)}
/* ✦ Bob: reescritor sob demanda (roxo) */
.btn-bob{background:var(--bob-bg);color:var(--bob);border-color:var(--bob-bd)}
.btn-bob:hover{filter:brightness(.97)}
.lnk-bob{color:var(--bob);text-decoration:none;font-weight:600}
.lnk-bob:hover{color:var(--bob);text-decoration:underline}
.ctx-btn.is-bob{color:var(--bob);border-color:var(--bob-bd)}
.ctx-btn.is-bob:hover{color:var(--bob);background:var(--bob-bg)}
/* Comentário do Bob acima da reescrita (itálico, roxo) */
.bob-comment{font-size:12px;font-style:italic;color:var(--bob);line-height:1.5;
  margin-bottom:6px;display:flex;gap:5px}
.bob-comment::before{content:'✦';font-style:normal}

/* Painel edit/bob (linha cheia abaixo do achado) */
.panel{margin:0 20px 14px;padding:13px 16px 13px 48px;border-radius:10px}
.panel-edit{background:var(--edit-bg);border:1px solid var(--edit-bd)}
.panel-bob{background:var(--bob-bg);border:1px solid var(--bob-bd)}
.p-label{font-size:10.5px;font-weight:700;letter-spacing:.08em;margin-bottom:8px}
.panel-edit .p-label{color:var(--ins-tx)}
.panel-bob .p-label{color:var(--bob)}
.p-ta{width:100%;min-height:66px;padding:8px 10px;background:var(--card);
  border:1px solid var(--bd);border-radius:8px;color:var(--tx);font-family:var(--sans);
  font-size:13px;line-height:1.55;resize:vertical;outline:none}
.panel-edit .p-ta:focus{border-color:var(--edit-bd)}
.panel-bob .p-ta:focus{border-color:var(--bob-bd)}
.bob-pergunta{font-size:12.5px;font-style:italic;color:var(--bob);line-height:1.5;margin-bottom:8px}
.btn-bob-go{background:var(--bob);color:#fff;border-color:var(--bob)}
.btn-bob-go:hover{filter:brightness(.93)}
.btn-bob-go:disabled{opacity:.5;cursor:not-allowed}
.p-btns{display:flex;gap:8px;margin-top:9px}

/* Parágrafo de contexto (leitura sequencial — separador §) */
.ctx-row{display:grid;grid-template-columns:50px 1fr auto;gap:18px;padding:10px 20px;
  background:var(--subtle);border-bottom:1px solid var(--bd4)}
.ctx-row .fnum{color:var(--tx-dis)}
.ctx-text{font-size:13px;line-height:1.65;color:var(--ctx);grid-column:2}
.ctx-row.ctx-editada .ctx-text{color:var(--tx-2)}
/* Ações discretas das linhas de leitura: visíveis, mas com peso menor que as
   das linhas com correção — não competem com a leitura sequencial */
.ctx-acts{display:flex;gap:6px;align-items:center;align-self:start}
.ctx-btn{padding:2px 9px;border:1px solid var(--bd2);border-radius:6px;background:transparent;
  color:var(--tx-4);font-size:11px;font-weight:500;cursor:pointer;white-space:nowrap;
  transition:all .15s}
.ctx-btn:hover{color:var(--tx-2);border-color:var(--tx-5);background:var(--card)}
.ctx-selo{font-size:11px;font-weight:600;color:var(--green);white-space:nowrap}

/* Separador de seção (filtros por severidade) */
.sec-row{padding:10px 20px;background:var(--box);border-bottom:1px solid var(--bd3);
  font-size:10.5px;font-weight:700;color:var(--tx-3);letter-spacing:.1em;
  text-transform:uppercase}

/* Sinal de nota ✎ na margem */
.nota-mark{display:flex;align-items:center;justify-content:center;margin-top:8px;
  width:22px;height:18px;border-radius:5px;cursor:pointer;font-size:10.5px;font-weight:600;
  color:var(--amber);background:var(--amber-bg);border:1px solid var(--amber-bd);
  transition:transform .15s;user-select:none}
.nota-mark:hover{transform:scale(1.1)}
.nota-mark.nm-ok{color:var(--ins-tx);background:var(--edit-bg);border-color:var(--edit-bd)}

/* Rodapé do card */
.card-foot{padding:14px 20px;background:var(--subtle);border-top:1px solid var(--bd2);
  display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.cf-kbd{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--tx-4);
  white-space:nowrap}
kbd{font-family:var(--mono);font-size:11px;border:1px solid var(--bd);border-radius:5px;
  background:var(--card);color:var(--tx-3);padding:1px 6px}
.cf-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.vdiv-foot{height:24px}
.btn-gravar{display:inline-flex;align-items:center;gap:7px;background:var(--gravar);
  color:#fff;border-color:var(--gravar);font-size:13px;font-weight:600;padding:7px 14px}
.btn-gravar:hover:not(:disabled){background:var(--gravar-h);border-color:var(--gravar-h)}
.btn-gravar:disabled{opacity:.4;cursor:not-allowed}
.btn-gravar .dico{width:17px;height:17px;border-radius:4px;background:rgba(255,255,255,.22);
  display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700}
.btn-next{background:var(--card);border-color:var(--blue-bd);color:var(--blue);
  max-width:260px;overflow:hidden;text-overflow:ellipsis}
.btn-next:hover:not(:disabled){background:var(--blue-bg)}
.btn-next:disabled{opacity:.5;cursor:not-allowed}
.btn-prev:disabled{background:var(--box);border-color:var(--bd2);color:var(--tx-dis);
  cursor:not-allowed}

/* Toast (escuro, embaixo-centro) */
#toast{position:fixed;bottom:26px;left:50%;transform:translate(-50%,12px);z-index:200;
  background:var(--toast-bg);color:var(--toast-tx);border-radius:10px;padding:10px 18px;
  font-size:13px;font-weight:500;opacity:0;pointer-events:none;max-width:80vw;
  box-shadow:0 8px 30px rgba(0,0,0,.25);
  transition:opacity .22s,transform .3s cubic-bezier(.34,1.56,.64,1)}
#toast.show{opacity:1;transform:translate(-50%,0)}
#toast.te{box-shadow:0 8px 30px rgba(0,0,0,.25),0 0 0 1px var(--sev-b)}

/* Tooltip flutuante */
#tt{display:none;position:fixed;z-index:500;background:var(--card);
  border:1px solid var(--bd);color:var(--tx-2);padding:9px 13px;border-radius:8px;
  font-size:12px;line-height:1.55;max-width:320px;max-height:220px;overflow-y:auto;
  pointer-events:none;box-shadow:0 4px 20px rgba(0,0,0,.12);
  white-space:pre-wrap;word-break:break-word}

/* Loading overlay */
#loading{display:none;position:fixed;inset:0;z-index:300;background:var(--overlay);
  flex-direction:column;align-items:center;justify-content:center;gap:16px}
#loading.show{display:flex}
.spin{width:32px;height:32px;border:2px solid var(--bd);border-top-color:var(--green);
  border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-msg{font-size:13px;color:var(--tx-2)}

/* Painel lateral de notas ✎ */
#npanel{position:fixed;top:0;right:-400px;bottom:0;width:372px;z-index:150;
  background:var(--card);border-left:1px solid var(--bd);
  box-shadow:-14px 0 44px rgba(0,0,0,.14);display:flex;flex-direction:column;
  transition:right .26s cubic-bezier(.22,1,.36,1)}
#npanel.aberto{right:0}
.np-head{display:flex;align-items:center;justify-content:space-between;
  padding:14px 18px;border-bottom:1px solid var(--bd2);flex-shrink:0}
.np-head .np-t{font-size:11px;font-weight:700;color:var(--amber);
  text-transform:uppercase;letter-spacing:.08em}
.np-close{background:transparent;border:1px solid var(--bd);border-radius:7px;
  color:var(--tx-4);font-size:11px;padding:3px 10px;cursor:pointer;transition:all .15s}
.np-close:hover{color:var(--tx);border-color:var(--tx-5)}
.np-body{flex:1;overflow-y:auto;padding:14px 18px;display:flex;
  flex-direction:column;gap:12px}
.np-card{background:var(--box);border:1px solid var(--bd2);border-radius:9px;
  padding:12px 14px;border-left:3px solid var(--amber-dot)}
.np-card.np-decidida{border-left-color:var(--green)}
.np-meta{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.np-conf{font-size:11px;color:var(--tx-4);margin-left:auto}
.np-trecho{font-size:12px;color:var(--tx-3);line-height:1.6;
  border-left:2px solid var(--bd);padding-left:9px;margin-bottom:8px;word-break:break-word}
.np-trecho.np-geral{font-style:italic;border-left-color:var(--amber-bd)}
.np-porque{font-size:12.5px;color:var(--tx);line-height:1.6;margin-bottom:10px;
  white-space:pre-wrap;word-break:break-word}
.np-acoes{display:flex;flex-direction:column;gap:6px}
.np-ok-msg{font-size:11.5px;color:var(--green);line-height:1.5}
.np-edit{margin-top:8px}
.np-vazio{font-size:12px;color:var(--tx-4);text-align:center;padding:30px 0}

/* Janela de revisão de aprendizados (abre no Gravar do último roteiro) */
#apr-modal{display:none;position:fixed;inset:0;z-index:300;background:var(--overlay);
  align-items:center;justify-content:center;padding:30px}
#apr-modal.show{display:flex}
.apr-card{background:var(--card);border:1px solid var(--bd);border-radius:14px;
  width:min(680px,100%);max-height:86vh;display:flex;flex-direction:column;
  box-shadow:var(--card-shadow)}
.apr-head{padding:16px 20px 14px;border-bottom:1px solid var(--bd2)}
.apr-t{font-size:14px;font-weight:700}
.apr-sub{font-size:12px;color:var(--tx-3);margin-top:4px;line-height:1.55}
.apr-body{flex:1;overflow-y:auto;padding:14px 20px;display:flex;
  flex-direction:column;gap:10px}
.apr-item{display:grid;grid-template-columns:auto 1fr;gap:10px;background:var(--box);
  border:1px solid var(--bd2);border-radius:10px;padding:11px 13px}
.apr-item.off{opacity:.45}
.apr-check{margin-top:5px;width:15px;height:15px;accent-color:var(--green);cursor:pointer}
.apr-tx{width:100%;min-height:46px;padding:7px 9px;background:var(--card);
  border:1px solid var(--bd);border-radius:7px;color:var(--tx);font-family:var(--sans);
  font-size:12.5px;line-height:1.55;resize:vertical;outline:none}
.apr-tx:focus{border-color:var(--depois-bd)}
.apr-meta{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:7px}
.apr-esc{padding:3px 7px;border-radius:6px;border:1px solid var(--bd);background:var(--card);
  color:var(--tx-2);font-size:11px;font-family:var(--sans);outline:none;cursor:pointer}
.apr-origem{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:999px;
  margin-left:auto;white-space:nowrap}
.apr-o-pular{background:var(--sev-b-bg);color:var(--sev-b-tx)}
.apr-o-editar{background:var(--blue-bg);color:var(--blue)}
.apr-o-aplicar{background:var(--edit-bg);color:var(--ins-tx)}
.apr-o-manual{background:var(--box);color:var(--tx-3);border:1px solid var(--bd2)}
.apr-add{display:flex;gap:8px;padding:4px 20px 12px}
.apr-add input{flex:1;padding:8px 10px;background:var(--card);border:1px solid var(--bd);
  border-radius:8px;color:var(--tx);font-family:var(--sans);font-size:12.5px;outline:none}
.apr-add input:focus{border-color:var(--depois-bd)}
.apr-foot{padding:13px 20px;border-top:1px solid var(--bd2);display:flex;gap:8px;
  align-items:center;justify-content:flex-end}
.apr-count{font-size:12px;color:var(--tx-3);margin-right:auto}
.apr-exs{margin-top:8px;display:flex;flex-direction:column;gap:4px}
.apr-ex{font-size:11.5px;color:var(--tx-3);line-height:1.5;border-left:2px solid var(--bd);
  padding-left:9px;word-break:break-word}
.apr-ex b{color:var(--tx-2);font-weight:600}
/* Lição por edição: motivação + trecho de âncora */
.apr-motiv{font-size:11.5px;color:var(--tx-3);font-style:italic;line-height:1.5;margin-top:6px}
.apr-trecho{font-size:11px;color:var(--tx-4);line-height:1.5;margin-top:6px;
  border-left:2px solid var(--bd);padding-left:8px;word-break:break-word}
/* Bloco recolhido das edições pontuais (não viram regra) */
.apr-pontuais{margin-top:4px;border-top:1px dashed var(--bd);padding-top:10px}
.apr-pontuais>summary{font-size:12px;font-weight:600;color:var(--tx-3);cursor:pointer;
  padding:4px 0;list-style:revert;user-select:none}
.apr-pontuais>summary:hover{color:var(--tx)}
.apr-pontuais .apr-item{margin-top:10px}

/* Responsivo: colunas empilham em telas estreitas */
@media (max-width:920px){
  body{padding:18px 14px 40px}
  .cols-head{display:none}
  .frow{grid-template-columns:40px 1fr 110px;gap:12px;
    grid-template-areas:"num cat acao" "num antes acao" "num depois acao"}
  .fnum{grid-area:num}
  .fcat{grid-area:cat;flex-direction:row;flex-wrap:wrap;align-items:center}
  .fantes{grid-area:antes}
  .fdepois{grid-area:depois}
  .facao{grid-area:acao}
  .ctx-row{grid-template-columns:40px 1fr;gap:12px}
  .panel{padding-left:16px}
}
</style>
</head>
<body>

<div class="page">
  <div class="page-head">
    <div class="brand-row">
      <div class="brand"><div class="logo">VM</div><span class="brand-label">VML · REVISOR</span></div>
      <div id="tema-toggle" onclick="alternarTema()" title="Alternar tema claro/escuro">
        <span class="tt-opt" data-t="claro">☀ Claro</span>
        <span class="tt-opt" data-t="escuro">☾ Escuro</span>
      </div>
    </div>
    <h1 class="page-title">Revisão de roteiro</h1>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="ch-left">
        <span class="ch-label">REVISOR</span>
        <span class="vdiv"></span>
        <div class="rot-sel"><span id="rot-nome">—</span><span class="chev">▾</span></div>
        <span class="rot-pos" id="rot-pos" style="display:none"></span>
        <div class="autor-chip" id="cli-chip" style="display:none" title="Cliente">
          <span class="avatar" id="cli-avatar"></span><span id="cli-nome"></span>
        </div>
      </div>
      <div class="ch-right">
        <div class="legend" id="legend"></div>
        <div class="chip-nota" id="chip-n" style="display:none" onclick="abrirPainelNotas(null)"
          title="Notas dos agentes — observações sem correção automática">✎ <span id="n-n">0</span> nota(s)</div>
        <span class="verd" id="verd-badge">—</span>
      </div>
    </div>

    <div class="prog-row">
      <span class="prog-label"><b id="n-ap">0</b> de <span id="n-tot">0</span> aplicadas</span>
      <div class="prog-track"><div class="prog-fill" id="prog-fill"></div></div>
      <span class="prog-pend" id="prog-pend">0 pendentes</span>
    </div>

    <div id="filtros">
      <span class="f-label">Ver</span>
      <button class="fbtn fa" onclick="setF(this,'roteiro')">Roteiro</button>
      <button class="fbtn" onclick="setF(this,'todos')">Todos os achados</button>
      <button class="fbtn" onclick="setF(this,'bloqueantes','fa-b')">Bloqueantes</button>
      <button class="fbtn" onclick="setF(this,'avisos','fa-a')">Avisos</button>
      <button class="fbtn" onclick="setF(this,'sugestoes')">Sugestões</button>
      <button class="fbtn" onclick="setF(this,'pendentes')">Pendentes</button>
      <button class="fbtn" onclick="setF(this,'aprovados','fa-v')">Aplicados</button>
    </div>

    <div class="cols-head">
      <span>#</span><span>Categoria</span><span>Antes</span><span>Depois</span><span class="ca-r">Ação</span>
    </div>

    <div id="rows"></div>

    <div class="card-foot">
      <div class="cf-kbd"><kbd>J</kbd><kbd>K</kbd> navegar · <kbd>A</kbd> aplicar · <kbd>E</kbd> editar · <kbd>P</kbd> pular</div>
      <div class="cf-actions">
        <button class="btn btn-outline" id="btn-nova" onclick="novaRevisao()" style="display:none">↻ Nova Revisão</button>
        <button class="btn btn-outline" onclick="resetar()">Resetar</button>
        <button class="btn btn-outline" onclick="exportar()">Exportar JSON</button>
        <button class="btn btn-gravar" id="btn-gravar" onclick="gravar()" disabled><span class="dico">D</span><span id="btn-gravar-txt">Gravar no Google Docs</span></button>
        <span class="vdiv vdiv-foot" id="nav-div" style="display:none"></span>
        <button class="btn btn-outline btn-prev" id="btn-volt" onclick="voltar()" style="display:none" disabled>← Roteiro anterior</button>
        <button class="btn btn-next" id="btn-cont" onclick="continuar()" style="display:none">Próximo roteiro →</button>
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>
<div id="tt"></div>
<div id="loading"><div class="spin"></div><div class="loading-msg" id="loading-msg">Aguarde...</div></div>

<div id="npanel">
  <div class="np-head"><span class="np-t" id="np-titulo">✎ Notas</span>
    <button class="np-close" onclick="fecharPainelNotas()">✕ fechar</button></div>
  <div class="np-body" id="np-body"></div>
</div>

<div id="apr-modal">
  <div class="apr-card">
    <div class="apr-head">
      <div class="apr-t" id="apr-t">🧠 Aprendizados desta sessão</div>
      <div class="apr-sub" id="apr-sub">O sistema destilou as suas decisões neste documento em regras
        candidatas. Edite o texto, ajuste o escopo e desmarque o que não deve virar regra
        permanente. Os itens marcados são salvos e passam a valer nas próximas revisões;
        os desmarcados são descartados.</div>
    </div>
    <div class="apr-body" id="apr-lista"></div>
    <div class="apr-add" id="apr-add">
      <input id="apr-novo" placeholder="Adicionar aprendizado manualmente…"
        onkeydown="if(event.key==='Enter'){event.preventDefault();aprAdicionar()}">
      <button class="btn btn-outline" onclick="aprAdicionar()">+ Adicionar</button>
    </div>
    <div class="apr-foot">
      <span class="apr-count" id="apr-count"></span>
      <button class="btn btn-outline" id="apr-sec" onclick="aprPular()">Gravar sem salvar</button>
      <button class="btn btn-aplicar" id="apr-pri" onclick="aprConfirmar()">Salvar e gravar no Docs</button>
    </div>
  </div>
</div>

<script>
// ── Dados iniciais (embedded no primeiro load) ───────────────────────────────
let D = __DADOS_JSON__;
const SESSAO = '__SESSAO_ID__';
// URL do launcher (interface.py) — vazio quando rodando sem a interface gráfica
const LAUNCHER = '__LAUNCHER_URL__';
let filtro = 'roteiro';
// Painel aberto por achado: null | 'edit' | 'bob'
const panels = {};
// Estado do ✦ Bob
const _bobState = {};      // id -> {pergunta, busy} (painel de feedback)
const _bobFeedback = {};   // id -> último feedback dado ao Bob (vira motivo ao aplicar)
const _bobReescrita = {};  // id de linha de leitura (ed-*) -> {comment, reescrita} p/ pré-preencher a edição

// ── Tema claro/escuro ────────────────────────────────────────────────────────
function aplicarTema(t){
  document.documentElement.dataset.theme=t;
  sessionStorage.setItem('vml_tema',t);
  document.querySelectorAll('#tema-toggle .tt-opt')
    .forEach(o=>o.classList.toggle('ativo',o.dataset.t===t));
}
function alternarTema(){
  aplicarTema(document.documentElement.dataset.theme==='escuro'?'claro':'escuro');
}

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
  // Edições manuais de linhas de leitura: objetos sintéticos, não existem no
  // payload do servidor — precisam ser guardados inteiros para sobreviver ao reload
  const eds=D.correcoes.filter(c=>c.tipo==='edicao'&&c.decisao)
    .map(c=>({id:c.id,trecho_original:c.trecho_original,decisao:c.decisao,motivo:c._motivo||''}));
  if(eds.length)localStorage.setItem(k+'_ed',JSON.stringify(eds));
  else localStorage.removeItem(k+'_ed');
}
function carregar(){
  const k=`vml_${SESSAO}_${D.roteiro.id}`;
  const s=localStorage.getItem(k);
  if(s){
    const m=JSON.parse(s);
    D.correcoes.forEach(c=>{if(c.id in m)c.decisao=m[c.id]});
  }
  const se=localStorage.getItem(k+'_ed');
  if(se){
    try{
      JSON.parse(se).forEach(e=>{
        if(e.decisao&&!getC(e.id))
          D.correcoes.push({id:e.id,tipo:'edicao',camada:'Editor',
            trecho_original:e.trecho_original,decisao:e.decisao,_motivo:e.motivo||''});
      });
    }catch(_){}
  }
}

// ── Diff ─────────────────────────────────────────────────────────────────────
function diff(b,a){
  if(!b||!a)return{pfx:'',del:b||'',ins:a||'',sfx:'',inline:false};
  let i=0;const l=Math.min(b.length,a.length);
  while(i<l&&b[i]===a[i])i++;
  const br=b.slice(i),ar=a.slice(i);
  let j=0;const l2=Math.min(br.length,ar.length);
  while(j<l2&&br[br.length-1-j]===ar[ar.length-1-j])j++;
  let pfx=b.slice(0,i),del=j?br.slice(0,-j):br,ins=j?ar.slice(0,-j):ar,sfx=j?br.slice(-j):'';
  // Alinha o destaque a palavras inteiras (evita cortar "segundo|s")
  if(del||ins){
    const k=pfx.search(/\S+$/);
    if(k>=0&&(/^\S/.test(del)||/^\S/.test(ins))){
      del=pfx.slice(k)+del;ins=pfx.slice(k)+ins;pfx=pfx.slice(0,k);
    }
    const m=sfx.match(/^\S+/);
    if(m&&(/\S$/.test(del)||/\S$/.test(ins))){
      del+=m[0];ins+=m[0];sfx=sfx.slice(m[0].length);
    }
  }
  return{pfx,del,ins,sfx};
}

// ── Renderização ─────────────────────────────────────────────────────────────
const SEV_KEY={erro:'b',aviso:'a',sugestao:'s'};
const SEV_LABEL={erro:'Bloqueante',aviso:'Aviso',sugestao:'Sugestão'};

// ANTES = texto original puro · DEPOIS = texto final com as inserções em <mark>
function renderDiff(c){
  const t=c.trecho_original;
  const decidida=(typeof c.decisao==='string'&&c.decisao!=='pular'&&c.decisao!=='aplicado');
  // Enquanto não decidida, uma reescrita do Bob substitui a sugestão do agente
  const base=(c._bob&&!decidida)?c._bob.reescrita:c.correcao;
  const d=decidida?c.decisao:base;
  // Comentário do Bob aparece acima da reescrita (só na proposta, antes de decidir)
  const bobC=(c._bob&&!decidida)?`<div class="bob-comment">${esc(c._bob.comment)}</div>`:'';
  const wrap=h=>bobC+h;
  if(!t&&!d)return['<span class="diff-null">—</span>',wrap('<span class="diff-null">—</span>')];
  if(!t){
    const ant=c.insercao_indefinida
      ?'<span class="diff-null">Posição: a definir pelo editor</span>'
      :'<span class="diff-null">—</span>';
    return[ant,wrap(`<div class="dep-text clamp"><mark class="ins">${esc(d)}</mark></div>`)];
  }
  if(!d)return[`<div class="clamp">${esc(t)}</div>`,wrap('<span class="diff-null">—</span>')];
  const r=diff(t,d);
  // Destaque verde só nas inserções, ancorado no contexto comum (prefixo/sufixo)
  const depH=(r.pfx||r.sfx)&&r.ins
    ?`<div class="dep-text clamp">${esc(r.pfx)}<mark class="ins">${esc(r.ins)}</mark>${esc(r.sfx)}</div>`
    :`<div class="dep-text clamp">${esc(d)}</div>`;
  return[`<div class="clamp">${esc(t)}</div>`,wrap(depH)];
}

// Justificativa da camada: linha consolidada tem porque combinado no formato
// "[Camada] texto\n\n[Camada2] texto" — cada chip mostra só a sua parte no hover
function whyDe(c,t){
  if(!c.porque)return'';
  const sec=c.porque.split(/\n\n(?=\[)/).find(s=>s.startsWith(`[${t}]`));
  return sec?sec.slice(t.length+3):c.porque;
}

function renderCat(c){
  const k=SEV_KEY[c.severidade]||'s';
  const pill=`<span class="sev-pill sp-${k}">${SEV_LABEL[c.severidade]||'Sugestão'}</span>`;
  const tags=(c.camadas&&c.camadas.length?c.camadas:[c.camada])
    .map(t=>{
      const w=whyDe(c,t);
      return`<span class="tag-c"${w?` data-w="${esc(w)}"`:''}>${esc(t)}</span>`;
    }).join('');
  const ins=c.insercao_label?`<div class="ins-label">${esc(c.insercao_label)}</div>`:'';
  return`${pill}<div class="cat-chips">${tags}</div>${ins}`;
}

function renderAcao(c){
  const d=c.decisao;
  if(d==='pular')return`<div class="selo selo-pu">Pulado</div>
    <button class="lnk" onclick="desfazer('${c.id}')">Retomar</button>
    <button class="lnk lnk-bob" onclick="bob('${c.id}')">✦ Bob</button>`;
  if(d&&d!=='pular')return`<div class="selo selo-ap">✓ Aplicado</div>
    <button class="lnk" onclick="desfazer('${c.id}')">Desfazer</button>
    <button class="lnk lnk-bob" onclick="bob('${c.id}')">✦ Bob</button>`;
  // Inserção sem posição: Aplicar fica fora (não há onde aplicar); Editar decide
  const btnAp=c.insercao_indefinida?'':
    `<button class="btn btn-aplicar" onclick="aplicar('${c.id}')">✓ Aplicar</button>`;
  return`${btnAp}
    <button class="btn btn-outline" onclick="editar('${c.id}')">Editar</button>
    <button class="btn btn-outline" onclick="pular('${c.id}')">Pular</button>
    <button class="btn btn-bob" onclick="bob('${c.id}')">✦ Bob</button>`;
}

function renderPanel(c){
  const p=panels[c.id];
  if(p==='edit'){
    const decidida=typeof c.decisao==='string'&&c.decisao!=='pular'&&c.decisao!=='aplicado';
    // Editar parte da reescrita do Bob quando ela é a proposta corrente
    const doBob=c._bob&&!decidida;
    const txt=decidida?c.decisao:(doBob?c._bob.reescrita:(c.correcao||''));
    const coment=doBob?`<div class="bob-comment">${esc(c._bob.comment)}</div>`:'';
    return`<div class="panel ${doBob?'panel-bob':'panel-edit'}">
      <div class="p-label">${doBob?'✦ AJUSTAR A REESCRITA DO BOB':'EDITAR TEXTO REVISADO'}</div>
      ${coment}
      <textarea class="p-ta" id="ta-${c.id}">${esc(txt)}</textarea>
      <div class="p-btns">
        <button class="btn btn-aplicar" onclick="conf('${c.id}')">Salvar e aplicar</button>
        <button class="btn btn-outline" onclick="fecharPanel('${c.id}')">Cancelar</button>
      </div></div>`;
  }
  if(p==='bob')return bobPanelHTML(c.id);
  return'';
}

// Painel de feedback do Bob (reusado em linha de correção e de leitura)
function bobPanelHTML(id){
  const st=_bobState[id]||{};
  const perg=st.pergunta?`<div class="bob-pergunta">✦ ${esc(st.pergunta)}</div>`:'';
  const txtBtn=st.busy?'✦ Bob está reescrevendo…':'Mandar pro Bob';
  return`<div class="panel panel-bob">
    <div class="p-label">✦ PEDIR AO BOB</div>
    ${perg}
    <textarea class="p-ta" id="bobfb-${id}" ${st.busy?'disabled':''}
      placeholder="O que não funcionou? (ex.: formal demais, longo, palavra difícil)"></textarea>
    <div class="p-btns">
      <button class="btn btn-bob-go" id="bobgo-${id}" onclick="bobEnviar('${id}')" ${st.busy?'disabled':''}>${txtBtn}</button>
      <button class="btn btn-outline" onclick="bobFechar('${id}')">Cancelar</button>
    </div></div>`;
}

function rowInner(c){
  const k=SEV_KEY[c.severidade]||'s';
  let cls=`frow sev-${k}`;
  if(c.decisao&&c.decisao!=='pular')cls+=' applied';
  else if(c.decisao==='pular')cls+=' skipped';
  const[antH,depH]=renderDiff(c);
  return`<div class="${cls}">
    <div class="fnum">${c._num||''}</div>
    <div class="fcat">${renderCat(c)}</div>
    <div class="fantes" id="ant-${c.id}">${antH}</div>
    <div class="fdepois" id="dep-${c.id}">${depH}</div>
    <div class="facao" id="ac-${c.id}">${renderAcao(c)}</div>
  </div>${renderPanel(c)}`;
}

function renderTudo(){
  const r=D.roteiro,cs=D.correcoes,m=D.meta||{};
  $id('rot-nome').textContent=r.titulo;
  const pos=$id('rot-pos');
  if(m.total>1){pos.textContent=`${m.atual} de ${m.total}`;pos.style.display=''}
  else pos.style.display='none';
  const chip=$id('cli-chip');
  if(r.cliente){
    chip.style.display='';
    $id('cli-nome').textContent=r.cliente;
    $id('cli-avatar').textContent=r.cliente.split(/\s+/).map(p=>p[0]).join('').slice(0,2).toUpperCase();
  } else chip.style.display='none';

  // Legenda de severidades (só correções; notas têm chip e fluxo próprios)
  const corr=cs.filter(c=>c.tipo!=='nota');
  const notas=cs.filter(c=>c.tipo==='nota');
  const cnt={erro:0,aviso:0,sugestao:0};
  corr.forEach(c=>{if(c.severidade in cnt)cnt[c.severidade]++});
  const NOMES={erro:['bloqueante','bloqueantes'],aviso:['aviso','avisos'],
    sugestao:['sugestão','sugestões']};
  $id('legend').innerHTML=['erro','aviso','sugestao']
    .filter(s=>cnt[s]>0)
    .map(s=>`<span class="lg-item"><span class="lg-dot" style="background:var(--sev-${SEV_KEY[s]})"></span><b>${cnt[s]}</b> ${NOMES[s][cnt[s]>1?1:0]}</span>`)
    .join('');
  $id('n-n').textContent=notas.length;
  $id('chip-n').style.display=notas.length?'':'none';

  const v=r.veredicto||'';
  const vb=$id('verd-badge');vb.textContent=v||'—';
  vb.className='verd '+(v.includes('REPROV')||v.includes('BLOQ')?'verd-rep':
    v.includes('AJUSTE')||v.includes('AVISO')?'verd-ajuste':'verd-ok');

  const btnCont=$id('btn-cont'),btnVolt=$id('btn-volt');
  if(m.proximo_titulo){
    btnCont.style.display='';
    btnCont.textContent=`Próximo roteiro · ${m.proximo_titulo.slice(0,26)} →`;
  } else if(m.total>1){
    btnCont.style.display='';btnCont.textContent='✓ Concluir';
  } else {
    btnCont.style.display='none';
  }
  // Voltar: visível em sessões multi-roteiro; desabilitado no primeiro
  btnVolt.style.display=m.total>1?'':'none';
  $id('nav-div').style.display=m.total>1?'':'none';
  if(m.hist_idx>0&&m.anterior_titulo){
    btnVolt.disabled=false;
    btnVolt.title=m.anterior_titulo;
  } else {
    btnVolt.disabled=true;btnVolt.title='';
  }

  const rows=$id('rows');rows.innerHTML='';
  let num=1;

  function addCtx(texto,li){
    const id=`ed-${li}`;
    const c=getC(id);
    const editada=!!(c&&c.decisao);
    const div=document.createElement('div');
    div.id=`row-leitura-${li}`;
    div.className='ctx-row'+(editada?' ctx-editada':'');
    const acts=editada
      ?`<span class="ctx-selo">✓ Editado</span>
        <button class="ctx-btn" onclick="ctxEditar(${li})">Editar</button>
        <button class="ctx-btn" onclick="ctxDesfazer(${li})">Desfazer</button>`
      :`<button class="ctx-btn" onclick="ctxEditar(${li})">Editar</button>
        <button class="ctx-btn is-bob" onclick="bob('${id}')">✦ Bob</button>`;
    div.innerHTML=`<div class="fnum">§</div>
      <div class="ctx-text">${esc(editada?c.decisao:texto)}</div>
      <div class="ctx-acts">${acts}</div>`;
    rows.appendChild(div);
    if(panels[id]==='bob'){
      const p=document.createElement('div');
      p.id=`panel-${id}`;
      p.innerHTML=bobPanelHTML(id);
      rows.appendChild(p.firstChild);
    } else if(panels[id]==='edit'){
      // Edição da linha; se veio do Bob, vem pré-preenchida com a reescrita + comentário
      const bobR=_bobReescrita[id];
      const valor=bobR?bobR.reescrita:(editada?c.decisao:texto);
      const coment=bobR?`<div class="bob-comment">${esc(bobR.comment)}</div>`:'';
      const p=document.createElement('div');
      p.id=`panel-${id}`;
      p.className='panel '+(bobR?'panel-bob':'panel-edit');
      p.innerHTML=`<div class="p-label">${bobR?'✦ REESCRITA DO BOB':'EDITAR TRECHO'}</div>
        ${coment}
        <textarea class="p-ta" id="ta-${id}">${esc(valor)}</textarea>
        <div class="p-btns">
          <button class="btn btn-aplicar" onclick="ctxConf(${li})">Salvar e aplicar</button>
          <button class="btn btn-outline" onclick="ctxFechar(${li})">Cancelar</button>
        </div>`;
      rows.appendChild(p);
    }
  }

  function addSec(label){
    const div=document.createElement('div');
    div.className='sec-row';div.textContent=label;
    rows.appendChild(div);
  }

  function addRow(c){
    c._num=num++;
    const div=document.createElement('div');
    div.id=`row-${c.id}`;
    div.className='row-wrap'+(filtro!=='roteiro'&&!matchF(c)?' row-hidden':'');
    div.innerHTML=rowInner(c);
    rows.appendChild(div);
  }

  if(filtro==='roteiro'){
    // Leitura sequencial: D.linhas reproduz o roteiro na ordem original do texto
    (D.linhas||[]).forEach((l,li)=>{
      if(l.tipo==='leitura')addCtx(l.texto,li);
      else if(l.tipo==='secao')addSec(l.label);
      else{const c=getC(l.id);if(c)addRow(c);}
    });
  } else {
    const bloq=cs.filter(c=>c.severidade==='erro'&&c.tipo==='correcao');
    const avis=cs.filter(c=>c.severidade==='aviso'&&c.tipo==='correcao');
    const sug=cs.filter(c=>c.severidade==='sugestao'&&c.tipo==='correcao');
    if(bloq.length){addSec('Bloqueantes');bloq.forEach(addRow)}
    if(avis.length){addSec('Avisos');avis.forEach(addRow)}
    if(sug.length){addSec('Sugestões');sug.forEach(addRow)}
    document.querySelectorAll('#rows .sec-row').forEach(sr=>{
      let nx=sr.nextElementSibling,vis=false;
      while(nx&&!nx.classList.contains('sec-row')){
        if(!nx.classList.contains('row-hidden')){vis=true;break}
        nx=nx.nextElementSibling;
      }
      sr.style.display=vis?'':'none';
    });
  }

  if(filtro==='roteiro')marcarNotas();
  atualizarFooter();
  aplicarFoco();
  marcarOverflow();
}

// ── Notas (✎): sinal lateral + painel ────────────────────────────────────────
// Nota = conselho do agente sem texto substituto. Nunca vira linha da tabela:
// aparece como um ✎ discreto na margem da linha que contém o trecho.
// Hover = preview (tooltip). Clique = painel lateral com citação + justificativa
// + ação opcional de transformar em correção (o revisor escreve o substituto).
let _npIds=null; // ids exibidos no painel aberto (null = todas)

function marcarNotas(){
  // Idempotente: atualizarLinha re-chama após reconstruir uma linha
  document.querySelectorAll('#rows .nota-mark').forEach(m=>m.remove());
  const notas=D.correcoes.filter(c=>c.tipo==='nota');
  if(!notas.length)return;
  const porLinha=new Map(); // rowEl → [notas]
  notas.forEach(n=>{
    let alvo=null;
    const L=D.linhas||[];
    // 1º: linha cujo texto contém o trecho da nota
    if(n.trecho_original){
      for(let li=0;li<L.length&&!alvo;li++){
        const l=L[li];
        const txt=l.tipo==='leitura'?(l.texto||''):((getC(l.id)||{}).trecho_original||'');
        if(txt&&txt.includes(n.trecho_original))alvo=rowDe(l,li);
      }
    }
    // 2º: primeira linha do mesmo parágrafo
    if(!alvo&&n._para_idx!=null){
      for(let li=0;li<L.length&&!alvo;li++){
        if(L[li].pi===n._para_idx)alvo=rowDe(L[li],li);
      }
    }
    // 3º: sem âncora — acessível pelo chip ✎ do topo
    if(alvo){
      if(!porLinha.has(alvo))porLinha.set(alvo,[]);
      porLinha.get(alvo).push(n);
    }
  });
  porLinha.forEach((ns,el)=>{
    const cell=el.querySelector('.fnum');if(!cell)return;
    const decididas=ns.every(n=>n.decisao&&n.decisao!=='pular');
    const m=document.createElement('div');
    m.className='nota-mark'+(decididas?' nm-ok':'');
    m.textContent='✎'+(ns.length>1?ns.length:'');
    m.setAttribute('data-w',ns.map(n=>`[${n.camada}] ${n.porque}`).join('\n\n').slice(0,420));
    m.onclick=e=>{e.stopPropagation();abrirPainelNotas(ns.map(n=>n.id));};
    cell.appendChild(m);
  });
}

function rowDe(l,li){
  return l.tipo==='leitura'?$id(`row-leitura-${li}`):$id(`row-${l.id}`);
}

function abrirPainelNotas(ids){
  _npIds=ids;
  const todas=D.correcoes.filter(c=>c.tipo==='nota');
  const notas=ids?ids.map(getC).filter(Boolean):todas;
  $id('np-titulo').textContent=`✎ ${notas.length} nota(s) dos agentes`;
  $id('np-body').innerHTML=notas.map(cardNota).join('')
    ||'<div class="np-vazio">Sem notas neste roteiro.</div>';
  $id('npanel').classList.add('aberto');
}

function fecharPainelNotas(){$id('npanel').classList.remove('aberto');_npIds=null;}

function cardNota(n){
  const decidida=n.decisao&&n.decisao!=='pular';
  const trecho=n.trecho_original
    ?`<div class="np-trecho">“${esc(n.trecho_original)}”</div>`
    :'<div class="np-trecho np-geral">Nota geral — sem trecho específico</div>';
  const acoes=decidida
    ?`<div class="np-ok-msg">✓ Transformada em correção — entra no Gravar:<br>«${esc(n.decisao.slice(0,90))}»</div>`
    :(n.trecho_original?`<button class="btn btn-outline" onclick="npEditar('${n.id}')">Transformar em correção</button>`:'');
  return `<div class="np-card${decidida?' np-decidida':''}" id="npc-${n.id}">
    <div class="np-meta"><span class="tag-c">${esc(n.camada)}</span>
      <span class="np-conf">${n.confianca||0}%</span></div>
    ${trecho}
    <div class="np-porque">${esc(n.porque)}</div>
    <div class="np-acoes">${acoes}</div>
    <div class="np-edit" id="np-edit-${n.id}"></div>
  </div>`;
}

function npEditar(id){
  const c=getC(id);if(!c)return;
  const box=$id(`np-edit-${id}`);if(!box)return;
  box.innerHTML=`<textarea class="p-ta" id="np-ta-${id}">${esc(c.trecho_original)}</textarea>
    <div class="p-btns">
      <button class="btn btn-aplicar" onclick="npConf('${id}')">Salvar e aplicar</button>
      <button class="btn btn-outline" onclick="npCanc('${id}')">Cancelar</button></div>`;
  const ta=$id(`np-ta-${id}`);ta.focus();ta.select();
}

function npConf(id){
  const ta=$id(`np-ta-${id}`);if(!ta)return;
  const novo=ta.value.trim();
  const c=getC(id);if(!c)return;
  if(!novo||novo===c.trecho_original){npCanc(id);return;}
  c.decisao=novo;salvar();sync(id);
  toast('Nota transformada em correção — entra no Gravar ✓');
  renderTudo();abrirPainelNotas(_npIds);
}

function npCanc(id){const box=$id(`np-edit-${id}`);if(box)box.innerHTML='';}

// ── Overflow dos blocos Antes/Depois/Porquê ──────────────────────────────────
// Conteúdo nunca fica inacessível: bloco que excede as 3 linhas do clamp ganha
// um botão explícito "ver tudo" que expande a linha (sem corte silencioso).
function marcarOverflow(){
  document.querySelectorAll('#rows .clamp').forEach(el=>{
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
  return [...document.querySelectorAll('#rows [id^="row-"]')]
    .filter(r=>!r.classList.contains('row-hidden'))
    .map(r=>r.id.replace('row-',''));
}

function aplicarFoco(){
  document.querySelectorAll('#rows .row-focus').forEach(r=>r.classList.remove('row-focus'));
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
  if(e.key==='Escape'){
    if($id('apr-modal').classList.contains('show'))return; // janela decide por botões
    fecharPainelNotas();
    Object.keys(panels).forEach(id=>{if(panels[id])fecharPanel(id)});
    return;
  }
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
  // Se há uma reescrita do Bob pendente, é ela que se aplica (não a do agente)
  c.decisao=(c._bob?c._bob.reescrita:c.correcao)||'aplicado';
  panels[id]=null;
  salvar();sync(id,_bobFeedback[id]||'');atualizarLinha(id,true);atualizarFooter();
  const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
}

function pular(id){
  const c=getC(id);if(!c)return;
  // Toggle: pular de novo retoma
  c.decisao=c.decisao==='pular'?null:'pular';
  panels[id]=null;
  salvar();sync(id,'');atualizarLinha(id);atualizarFooter();
  if(c.decisao==='pular'){
    const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
  }
}

function desfazer(id){
  const c=getC(id);if(!c)return;
  // Volta ao estado neutro: descarta também a reescrita pendente do Bob, senão a
  // linha "gruda" na versão do Bob ao retomar (não dá pra voltar à do agente).
  c.decisao=null;c._bob=null;delete _bobFeedback[id];panels[id]=null;
  salvar();sync(id);atualizarLinha(id);atualizarFooter();
}

function editar(id){
  panels[id]=panels[id]==='edit'?null:'edit';
  atualizarLinha(id);
  const ta=$id(`ta-${id}`);
  if(ta){
    ta.focus();ta.select();
    ta.addEventListener('keydown',ev=>{
      if(ev.key==='Escape'){ev.preventDefault();fecharPanel(id)}
      else if((ev.metaKey||ev.ctrlKey)&&ev.key==='Enter'){ev.preventDefault();conf(id)}
    });
  }
}

function conf(id){
  const ta=$id(`ta-${id}`);if(!ta)return;
  const novo=ta.value.trim();if(!novo)return;
  const c=getC(id);if(!c)return;
  c.decisao=novo;panels[id]=null;
  salvar();sync(id,_bobFeedback[id]||'');atualizarLinha(id,true);atualizarFooter();
  const nx=nextPendingAfter(id);if(nx){focoId=nx;aplicarFoco();}
}

// ── ✦ Bob: reescritor sob demanda ────────────────────────────────────────────
function bob(id){
  const aberto=panels[id]==='bob';
  panels[id]=aberto?null:'bob';
  if(!aberto)_bobState[id]={};
  if(id.startsWith('ed-'))renderTudo();else atualizarLinha(id);
  bobFocoTextarea(id);
}

function bobFocoTextarea(id){
  const ta=$id(`bobfb-${id}`);
  if(!ta)return;
  ta.focus();
  ta.addEventListener('keydown',ev=>{
    if(ev.key==='Escape'){ev.preventDefault();bobFechar(id);}
    else if((ev.metaKey||ev.ctrlKey)&&ev.key==='Enter'){ev.preventDefault();bobEnviar(id);}
  });
}

function bobFechar(id){
  panels[id]=null;_bobState[id]={};
  if(id.startsWith('ed-'))renderTudo();else atualizarLinha(id);
}

function _bobRerender(id){
  if(id.startsWith('ed-'))renderTudo();else atualizarLinha(id);
  if(!(_bobState[id]||{}).busy)bobFocoTextarea(id);
}

async function bobEnviar(id){
  const ta=$id(`bobfb-${id}`);if(!ta)return;
  const fb=ta.value.trim();
  if(!fb){ta.focus();toast('O Bob precisa do seu feedback pra reescrever.','e');return;}
  const ehLeitura=id.startsWith('ed-');
  const c=getC(id);
  let trecho,sugestao,agente;
  if(ehLeitura){
    const li=parseInt(id.slice(3),10);
    trecho=(c&&c.decisao)?c.decisao:(((D.linhas||[])[li]||{}).texto||'');
    sugestao='';agente='';
  }else{
    if(!c)return;
    trecho=c.trecho_original||'';
    sugestao=c._bob?c._bob.reescrita:(c.correcao||''); // no loop, a "anterior" é a última do Bob
    agente=c.camada||'';
  }
  _bobState[id]={...(_bobState[id]||{}),busy:true};
  _bobRerender(id);
  try{
    const r=await fetch('/api/bob',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({trecho_original:trecho,sugestao_anterior:sugestao,feedback:fb,agente:agente})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){toast(d.error||'O Bob não conseguiu responder','e');_bobState[id]={};_bobRerender(id);return;}
    if(d.precisa_esclarecer){            // feedback vago: Bob devolve uma pergunta
      _bobState[id]={pergunta:d.bob_comment,busy:false};
      _bobRerender(id);return;
    }
    _bobFeedback[id]=fb;_bobState[id]={};
    if(ehLeitura){
      // Linha de leitura: a reescrita abre na edição da linha, pronta para salvar
      _bobReescrita[id]={comment:d.bob_comment,reescrita:d.reescrita};
      panels[id]='edit';renderTudo();
    }else{
      c._bob={comment:d.bob_comment,reescrita:d.reescrita};
      panels[id]=null;atualizarLinha(id,true);
    }
    toast('✦ Bob reescreveu','s');
  }catch(e){toast('Erro de conexão com o Bob','e');_bobState[id]={};_bobRerender(id);}
}

// Painéis de linha de leitura (ed-*) não têm linha própria p/ atualizarLinha:
// re-renderiza tudo para o painel sumir junto
function fecharPanel(id){
  panels[id]=null;
  if(id.startsWith('ed-'))renderTudo();
  else atualizarLinha(id);
}

// ── Linhas de leitura (§): edição manual do trecho ───────────────────────────
// O trecho editado vira uma correção sintética (tipo 'edicao') que entra no
// Gravar como qualquer outra: trecho_original → decisao.
function ctxEditar(li){
  const id=`ed-${li}`;
  panels[id]=panels[id]==='edit'?null:'edit';
  renderTudo();
  const ta=$id(`ta-${id}`);
  if(ta){
    ta.focus();ta.select();
    ta.addEventListener('keydown',ev=>{
      if(ev.key==='Escape'){ev.preventDefault();ctxFechar(li)}
      else if((ev.metaKey||ev.ctrlKey)&&ev.key==='Enter'){ev.preventDefault();ctxConf(li)}
    });
  }
}

function ctxConf(li){
  const id=`ed-${li}`;
  const ta=$id(`ta-${id}`);if(!ta)return;
  const novo=ta.value.trim();
  const l=(D.linhas||[])[li];if(!l)return;
  panels[id]=null;
  const feedbackBob=_bobFeedback[id];delete _bobReescrita[id];
  if(!novo||novo===l.texto){renderTudo();return;}
  let c=getC(id);
  if(!c){
    c={id:id,tipo:'edicao',camada:'Editor',trecho_original:l.texto,decisao:novo};
    D.correcoes.push(c);
  } else c.decisao=novo;
  if(feedbackBob)c._motivo=feedbackBob; // motivação real (feedback dado ao Bob)
  salvar();renderTudo();
  toast(feedbackBob?'✦ Reescrita do Bob aplicada':'Trecho editado, entra no Gravar ✓');
}

function ctxDesfazer(li){
  const id=`ed-${li}`;
  const i=D.correcoes.findIndex(c=>c.id===id);
  if(i>=0)D.correcoes.splice(i,1);
  panels[id]=null;
  salvar();renderTudo();
}

function ctxFechar(li){delete _bobReescrita[`ed-${li}`];fecharPanel(`ed-${li}`)}

function atualizarLinha(id,flash){
  const c=getC(id);if(!c)return;
  const wrap=$id(`row-${id}`);if(!wrap)return;
  wrap.innerHTML=rowInner(c);
  if(flash){const fr=wrap.querySelector('.frow');if(fr)fr.classList.add('flash');}
  if(filtro==='roteiro')marcarNotas();
  marcarOverflow();
}

// ── Progresso + Gravar ────────────────────────────────────────────────────────
function atualizarFooter(){
  const cs=D.correcoes.filter(c=>c.tipo==='correcao');
  const ap=cs.filter(c=>c.decisao&&c.decisao!=='pular').length;
  const tot=cs.length;
  const pend=cs.filter(c=>!c.decisao).length;
  const bPend=cs.filter(c=>c.severidade==='erro'&&!c.decisao).length;
  $id('n-ap').textContent=ap;$id('n-tot').textContent=tot;
  $id('prog-fill').style.width=tot?`${ap/tot*100}%`:'0';
  const pe=$id('prog-pend'),btn=$id('btn-gravar');
  if(bPend>0){
    pe.className='prog-pend blocked';
    pe.textContent=`${pend} pendentes · ${bPend} bloqueante(s) — não publicável`;
    btn.disabled=true;
  } else if(pend>0){
    pe.className='prog-pend';pe.textContent=`${pend} pendentes`;btn.disabled=false;
  } else {
    pe.className='prog-pend';pe.textContent='✓ pronto para publicação';btn.disabled=false;
  }
}

// ── Gravar no Google Docs ─────────────────────────────────────────────────────
async function gravar(){
  if(!D.url_gdocs){toast('Sem URL do Google Docs. Reinicie: python3 revisar.py --gdocs "URL"','e');return;}
  // Inclui notas transformadas em correção e edições manuais de linhas de leitura
  const aprovadas=D.correcoes.filter(c=>(c.tipo==='correcao'||c.tipo==='nota'||c.tipo==='edicao')
      &&c.decisao&&c.decisao!=='pular'&&c.trecho_original)
    .map(c=>({trecho_original:c.trecho_original,decisao:c.decisao}));
  if(!aprovadas.length){toast('Nenhuma correção aprovada.','e');return}
  // Fim do documento (último roteiro): a janela de aprendizados abre ANTES de
  // gravar. Confirmar/descartar na janela rechama gravar() com o flag resolvido.
  if(!(D.meta||{}).proximo_titulo&&!_aprChecado){
    await checarAprendizados();
    if(!_aprChecado)return;
  }
  const btn=$id('btn-gravar'),txt=$id('btn-gravar-txt');
  btn.disabled=true;txt.textContent='Gravando...';
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
    txt.textContent='Gravar no Google Docs';
    const bp=D.correcoes.filter(c=>c.severidade==='erro'&&!c.decisao).length;
    btn.disabled=bp>0;
  }
}

// ── Janela de aprendizados (fim do documento) ────────────────────────────────
// Compila os sinais da sessão inteira (pular/editar/aplicar) e mostra os
// aprendizados candidatos para o revisor confirmar antes de gravar no Docs.
let _aprChecado=false; // resolvido (confirmado/descartado/sem candidatos) → gravar segue
let _aprCands=null;    // cache dos candidatos (reabrir a janela não re-chama a LLM)

async function checarAprendizados(){
  if(_aprCands){renderAprendizados();return;}
  const loading=$id('loading');
  $id('loading-msg').textContent='Compilando os aprendizados da sessão...';
  loading.classList.add('show');
  try{
    const r=await fetch('/api/aprendizados/candidatos',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({edicoes_leitura:coletarEdicoesLeitura()})});
    const d=await r.json().catch(()=>({}));
    const cands=(r.ok&&d&&d.candidatos)||[];
    if(!cands.length){_aprChecado=true;return;} // sem aprendizados → grava direto
    // Generalizáveis vêm marcadas (viram regra); pontuais desmarcadas (registro)
    _aprCands=cands.map((c,i)=>({...c,_i:i,_on:c.generalizavel!==false}));
    renderAprendizados();
  }catch(e){_aprChecado=true} // falha na compilação nunca trava a gravação
  finally{loading.classList.remove('show')}
}

// Edições de linhas de leitura § de TODOS os roteiros da sessão (vivem no
// localStorage, não nos achados) — entram na destilação como edições do usuário.
function coletarEdicoesLeitura(){
  const out=[];
  for(let i=0;i<localStorage.length;i++){
    const k=localStorage.key(i);
    if(k&&k.startsWith(`vml_${SESSAO}_`)&&k.endsWith('_ed')){
      try{(JSON.parse(localStorage.getItem(k))||[]).forEach(e=>{
        if(e.trecho_original&&e.decisao)
          out.push({trecho_original:e.trecho_original,decisao:e.decisao,motivo:e.motivo||''});
      });}catch(_){}
    }
  }
  return out;
}

const APR_ORIGEM={pular:'de um Pular',editar:'de uma Edição',aplicar:'de Aplicados',manual:'Manual'};

function aprItemHTML(c){
  const cli=D.roteiro.cliente||'';
  const chips=[c.camada?`<span class="tag-c">${esc(c.camada)}</span>`:'',
    c.tema?`<span class="tag-c">tema: ${esc(c.tema)}</span>`:'',
    c.estrutura_codex?`<span class="tag-c">${esc(c.estrutura_codex)}</span>`:''].join('');
  const escopo=cli
    ?`<select class="apr-esc" id="apr-esc-${c._i}">
        <option value="global"${c.escopo!=='cliente'?' selected':''}>Global</option>
        <option value="cliente"${c.escopo==='cliente'?' selected':''}>Só ${esc(cli)}</option>
      </select>`
    :'<span class="tag-c">Global</span>';
  const trecho=c.trecho?`<div class="apr-trecho">sobre: “${esc(c.trecho)}”</div>`:'';
  const motiv=c.motivacao?`<div class="apr-motiv">Motivação: ${esc(c.motivacao)}</div>`:'';
  return`<div class="apr-item${c._on?'':' off'}" id="apr-it-${c._i}">
    <input type="checkbox" class="apr-check"${c._on?' checked':''}
      onchange="aprToggle(${c._i},this.checked)">
    <div>
      <textarea class="apr-tx" id="apr-tx-${c._i}">${esc(c.texto)}</textarea>
      ${trecho}${motiv}
      <div class="apr-meta">${escopo}${chips}
        <span class="apr-origem apr-o-${c.origem}">${APR_ORIGEM[c.origem]||c.origem}</span></div>
    </div></div>`;
}

function renderAprendizados(){
  // Restaura o modo candidato (a janela pode ter ficado em modo promoção)
  $id('apr-t').textContent='🧠 Aprendizados desta sessão';
  $id('apr-add').style.display='';
  const sec=$id('apr-sec'),pri=$id('apr-pri');
  sec.textContent='Gravar sem salvar';sec.onclick=aprPular;
  pri.textContent='Salvar e gravar no Docs';pri.onclick=aprConfirmar;
  // Generalizáveis (viram regra, marcadas) no topo; pontuais num bloco recolhido
  const ger=_aprCands.filter(c=>c.generalizavel!==false);
  const pon=_aprCands.filter(c=>c.generalizavel===false);
  let html=ger.length?ger.map(aprItemHTML).join(''):'<div class="np-vazio">Nenhuma regra nova desta vez.</div>';
  if(pon.length){
    html+=`<details class="apr-pontuais"><summary>${pon.length} ajuste(s) pontual(is): `
      +`a lição de cada edição específica. Não viram regra; marque se quiser guardar.</summary>`
      +pon.map(aprItemHTML).join('')+`</details>`;
  }
  $id('apr-lista').innerHTML=html;
  aprContagem();
  $id('apr-modal').classList.add('show');
}

function aprToggle(i,on){
  const c=_aprCands.find(c=>c._i===i);if(c)c._on=on;
  const it=$id(`apr-it-${i}`);if(it)it.classList.toggle('off',!on);
  aprContagem();
}

function aprContagem(){
  const n=_aprCands.filter(c=>c._on).length;
  $id('apr-count').textContent=`${n} de ${_aprCands.length} selecionado(s)`;
}

// Sincroniza texto/escopo editados no DOM de volta aos candidatos
function aprSync(){
  _aprCands.forEach(c=>{
    const ta=$id(`apr-tx-${c._i}`);if(ta)c.texto=ta.value;
    const se=$id(`apr-esc-${c._i}`);if(se)c.escopo=se.value;
  });
}

function aprAdicionar(){
  const inp=$id('apr-novo');
  const t=(inp.value||'').trim();if(!t)return;
  aprSync();
  _aprCands.push({texto:t,motivacao:'',generalizavel:true,trecho:'',escopo:'global',
    tema:'',estrutura_codex:'',camada:'',origem:'manual',_i:_aprCands.length,_on:true});
  inp.value='';
  renderAprendizados();
}

async function aprConfirmar(){
  aprSync();
  const cli=D.roteiro.cliente||'';
  const sel=_aprCands.filter(c=>c._on&&c.texto.trim()).map(c=>({
    texto:c.texto.trim(),
    motivacao:c.motivacao||'',
    escopo:(c.escopo==='cliente'&&cli)?'cliente':'global',
    cliente:(c.escopo==='cliente'&&cli)?cli:null,
    tema:c.tema||null,
    estrutura_codex:c.estrutura_codex||null,
    camada:c.camada||null,
    origem:c.origem||'manual',
  }));
  let novosIds=[];
  if(sel.length){
    try{
      const r=await fetch('/api/aprendizados/salvar',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({aprendizados:sel})});
      const d=await r.json().catch(()=>({}));
      if(r.ok){toast(`🧠 ${sel.length} aprendizado(s) salvo(s)`,'s');novosIds=d.ids||[];}
      else toast('Erro ao salvar aprendizados, a gravação segue','e');
    }catch(e){toast('Erro ao salvar aprendizados, a gravação segue','e')}
  }
  // Promoção sugerida: a mesma preferência ensinada a clientes diferentes pode
  // virar global. Só checa se algo foi salvo agora (senão não há o que repetir).
  const promos=novosIds.length?await checarPromocoes(novosIds):[];
  if(promos.length){
    _aprPromos=promos.map((p,i)=>({...p,_i:i,_on:true}));
    renderPromocoes(); // 2ª etapa na mesma janela; gravar só depois
    return;
  }
  aprFinalizar();
}

function aprPular(){
  // Descarta os candidatos (não voltam — são compilados por sessão) e grava
  aprFinalizar();
}

function aprFinalizar(){
  _aprChecado=true;
  $id('apr-modal').classList.remove('show');
  gravar(); // segue o fluxo normal: grava no Docs e avança
}

// ── 2ª etapa: promoção de aprendizados de cliente → global ───────────────────
let _aprPromos=null;

async function checarPromocoes(novosIds){
  const loading=$id('loading');
  $id('loading-msg').textContent='Procurando preferências repetidas entre clientes...';
  loading.classList.add('show');
  try{
    const r=await fetch('/api/aprendizados/promocoes',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({novos_ids:novosIds})});
    const d=await r.json().catch(()=>({}));
    return (r.ok&&d.promocoes)||[];
  }catch(e){return[]}      // falha na detecção nunca trava a gravação
  finally{loading.classList.remove('show')}
}

function renderPromocoes(){
  $id('apr-t').textContent='💡 Promover a global?';
  $id('apr-sub').innerHTML='Estas preferências você ensinou em <b>clientes diferentes</b>, '+
    'o que sugere um gosto seu, não algo específico de um cliente. Marque as que devem '+
    'valer para <b>todos</b> os clientes: o texto global substitui os de origem. O que '+
    'deixar desmarcado continua como está (cada um no seu cliente).';
  $id('apr-add').style.display='none';
  $id('apr-lista').innerHTML=_aprPromos.map(p=>{
    const exs=p.exemplos.map(e=>
      `<div class="apr-ex"><b>${esc(e.cliente)}:</b> ${esc(e.texto)}</div>`).join('');
    return`<div class="apr-item${p._on?'':' off'}" id="apr-pit-${p._i}">
      <input type="checkbox" class="apr-check"${p._on?' checked':''}
        onchange="aprPromoToggle(${p._i},this.checked)">
      <div>
        <textarea class="apr-tx" id="apr-ptx-${p._i}">${esc(p.texto_global)}</textarea>
        <div class="apr-meta">
          <span class="tag-c">global</span>
          ${p.camada?`<span class="tag-c">${esc(p.camada)}</span>`:''}
          <span class="apr-origem apr-o-manual">${p.clientes.length} clientes</span>
        </div>
        <div class="apr-exs">${exs}</div>
      </div></div>`;
  }).join('');
  $id('apr-count').textContent=
    `${_aprPromos.filter(p=>p._on).length} de ${_aprPromos.length} para promover`;
  const sec=$id('apr-sec'),pri=$id('apr-pri');
  sec.textContent='Agora não — só gravar';sec.onclick=aprPromoPular;
  pri.textContent='Promover e gravar';pri.onclick=aprPromoAplicar;
}

function aprPromoToggle(i,on){
  const p=_aprPromos.find(p=>p._i===i);if(p)p._on=on;
  const it=$id(`apr-pit-${i}`);if(it)it.classList.toggle('off',!on);
  $id('apr-count').textContent=
    `${_aprPromos.filter(p=>p._on).length} de ${_aprPromos.length} para promover`;
}

function aprPromoSync(){
  _aprPromos.forEach(p=>{const ta=$id(`apr-ptx-${p._i}`);if(ta)p.texto_global=ta.value;});
}

async function aprPromoAplicar(){
  aprPromoSync();
  const promover=_aprPromos.filter(p=>p._on&&p.texto_global.trim())
    .map(p=>({ids:p.ids,texto_global:p.texto_global.trim(),camada:p.camada||null}));
  if(promover.length){
    try{
      const r=await fetch('/api/aprendizados/promover',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({promover})});
      if(r.ok)toast(`⬆ ${promover.length} aprendizado(s) promovido(s) a global`,'s');
      else toast('Erro ao promover — a gravação segue','e');
    }catch(e){toast('Erro ao promover — a gravação segue','e')}
  }
  aprFinalizar();
}

function aprPromoPular(){aprFinalizar()}

// ── Navegação entre roteiros já revisados (Voltar / re-Avançar) ──────────────
async function navegar(delta){
  try{
    const r=await fetch('/api/navegar',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({delta})});
    if(!r.ok){toast('Não foi possível navegar','e');return;}
    D=await r.json();
    focoId=null;
    Object.keys(panels).forEach(k=>delete panels[k]);
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
      localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}_ed`);
      focoId=null;
      Object.keys(panels).forEach(k=>delete panels[k]);
      carregar();renderTudo();window.scrollTo(0,0);
      toast(`✓ ${D.roteiro.titulo.slice(0,40)}...`,'s');
    } else {
      toast('Revisão concluída! Pode fechar esta aba.','s');
      $id('btn-cont').disabled=true;$id('btn-cont').textContent='✓ Concluído';
    }
  }catch(e){toast('Erro ao avançar para o próximo roteiro','e')}
  finally{loading.classList.remove('show')}
}

// ── Nova Revisão (volta ao launcher para revisar outro Doc) ───────────────────
function novaRevisao(){
  const pend=D.correcoes.filter(c=>c.tipo==='correcao'&&!c.decisao).length;
  if(pend>0&&!confirm(`${pend} achado(s) ainda sem decisão neste roteiro. `+
    `As decisões já tomadas estão salvas. Iniciar uma nova revisão mesmo assim?`))return;
  window.location.href=LAUNCHER+'/?nova=1';
}

// ── Resetar / Exportar ────────────────────────────────────────────────────────
function resetar(){
  if(!confirm('Resetar todas as decisões?'))return;
  D.correcoes=D.correcoes.filter(c=>c.tipo!=='edicao');
  D.correcoes.forEach(c=>{if(c.decisao!==null){c.decisao=null;sync(c.id)}});
  Object.keys(panels).forEach(k=>delete panels[k]);
  localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}`);
  localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}_ed`);
  renderTudo();
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
  t.className=(tipo==='e'?'te ':'')+'show';
  clearTimeout(_toastTimer);
  _toastTimer=setTimeout(()=>t.classList.remove('show'),tipo==='e'?3500:2400);
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded',()=>{
  aplicarTema(document.documentElement.dataset.theme||'claro');
  carregar();renderTudo();
  if(LAUNCHER)$id('btn-nova').style.display='';
});
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
