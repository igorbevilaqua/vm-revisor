#!/usr/bin/env python3
"""
Relatório de Correções no Google Docs — Viral Media Labs

Gera um Google Doc NOVO por revisão, com uma TABELA NATIVA por roteiro
(linha, ponto exato, tipo, sugestão, importância %, prioridade), ordenada
pela linha do roteiro. Limpo, colorido e compartilhável.

Uso:
    python3 relatorio_gdocs.py                          # usa o .json mais recente
    python3 relatorio_gdocs.py relatorios/revisao_X.json
"""

from __future__ import annotations

import re
import sys
import json
from pathlib import Path
from datetime import datetime

from google_docs import autenticar
from aplicar_gdocs import SCOPES_WRITE, TOKEN_WRITE
from relatorio_correcoes import (
    montar_linhas, COLUNAS, e_bloqueante, json_mais_recente,
    linha_do_trecho, importancia, _tipo,
)

COR_OBRIGATORIA = {"color": {"rgbColor": {"red": 0.70, "green": 0.10, "blue": 0.10}}}
COR_OPCIONAL = {"color": {"rgbColor": {"red": 0.15, "green": 0.35, "blue": 0.60}}}
LABELS_BOLD = ("Trecho:", "Trocar por:", "Sugestão:", "Porquê:")

CINZA_HEADER = {"color": {"rgbColor": {"red": 0.16, "green": 0.16, "blue": 0.16}}}
FUNDO_HEADER = {"color": {"rgbColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}}


# ─── Localização de tabelas e parágrafos no documento ────────────────────────

def _encontrar_tabelas(doc) -> list[dict]:
    return [el for el in doc.get("body", {}).get("content", []) if "table" in el]


def _intervalo_texto(doc, alvo: str):
    """Retorna (start, end) do primeiro parágrafo cujo texto começa com `alvo`."""
    for el in doc.get("body", {}).get("content", []):
        par = el.get("paragraph")
        if not par:
            continue
        txt = "".join(r.get("textRun", {}).get("content", "") for r in par.get("elements", []))
        if txt.strip().startswith(alvo.strip()) and alvo.strip():
            return el.get("startIndex"), el.get("endIndex")
    return None, None


# ─── Geração ─────────────────────────────────────────────────────────────────

def gerar_doc(json_path) -> str:
    from googleapiclient.discovery import build

    dados = json.loads(Path(json_path).read_text(encoding="utf-8"))
    creds = autenticar(scopes=SCOPES_WRITE, token_path=TOKEN_WRITE)
    docs = build("docs", "v1", credentials=creds)

    data_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    doc = docs.documents().create(
        body={"title": f"Correções VML — {data_str}"}
    ).execute()
    doc_id = doc["documentId"]

    # ── 1. Esqueleto: títulos + tabelas vazias (append no fim) ───────────────
    reqs = []
    titulos_roteiro = []
    tabelas_dados = []  # cabeçalho + linhas, por roteiro

    def append(text):
        reqs.append({"insertText": {"endOfSegmentLocation": {}, "text": text}})

    append("Relatório de Correções — Viral Media Labs\n")
    append(f"Gerado em {data_str}\n\n")

    for rot in dados:
        cons = rot.get("consolidado", {})
        texto = rot.get("texto", "")
        achados = cons.get("achados", [])
        rows = montar_linhas(texto, achados)
        n_obrig = sum(1 for a in achados if e_bloqueante(a))

        titulo = f"Roteiro {rot.get('numero','')}: {rot.get('titulo','')}"
        titulos_roteiro.append(titulo)
        append(titulo + "\n")
        append(
            f"Veredicto: {cons.get('veredicto','—')}  ·  "
            f"Nota {cons.get('nota_geral','—')}/10  ·  Viral {cons.get('nota_viral','—')}/10  ·  "
            f"{n_obrig} obrigatórias / {len(achados) - n_obrig} opcionais\n"
        )

        tabela = [COLUNAS] + rows
        tabelas_dados.append(tabela)
        reqs.append({"insertTable": {
            "endOfSegmentLocation": {}, "rows": len(tabela), "columns": len(COLUNAS),
        }})
        append("\n")

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": reqs}).execute()

    # ── 2. Preenche as células (índices maiores primeiro p/ não deslocar) ────
    doc2 = docs.documents().get(documentId=doc_id).execute()
    tabelas = _encontrar_tabelas(doc2)
    inserts = []
    for tbl_el, dados_tbl in zip(tabelas, tabelas_dados):
        for r, row in enumerate(tbl_el["table"].get("tableRows", [])):
            for c, cell in enumerate(row.get("tableCells", [])):
                idx = cell["content"][0]["startIndex"]
                texto_cel = str(dados_tbl[r][c]) if r < len(dados_tbl) and c < len(dados_tbl[r]) else ""
                if texto_cel:
                    inserts.append((idx, texto_cel))
    inserts.sort(key=lambda x: x[0], reverse=True)
    if inserts:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
            {"insertText": {"location": {"index": idx}, "text": txt}} for idx, txt in inserts
        ]}).execute()

    # ── 3. Estilo: cabeçalho da tabela (negrito + fundo), títulos em negrito ──
    doc3 = docs.documents().get(documentId=doc_id).execute()
    estilo = []
    for tbl_el in _encontrar_tabelas(doc3):
        tbl_start = tbl_el["startIndex"]
        header = tbl_el["table"]["tableRows"][0]
        for cell in header.get("tableCells", []):
            ini = cell["content"][0]["startIndex"]
            fim = cell["content"][0].get("endIndex", ini + 1)
            estilo.append({"updateTextStyle": {
                "range": {"startIndex": ini, "endIndex": max(fim - 1, ini + 1)},
                "textStyle": {"bold": True, "foregroundColor": CINZA_HEADER},
                "fields": "bold,foregroundColor",
            }})
        estilo.append({"updateTableCellStyle": {
            "tableRange": {
                "tableCellLocation": {
                    "tableStartLocation": {"index": tbl_start},
                    "rowIndex": 0, "columnIndex": 0,
                },
                "rowSpan": 1, "columnSpan": len(COLUNAS),
            },
            "tableCellStyle": {"backgroundColor": FUNDO_HEADER},
            "fields": "backgroundColor",
        }})

    # Títulos (documento + roteiros) em negrito/maiores
    t0, t1 = _intervalo_texto(doc3, "Relatório de Correções")
    if t0 is not None:
        estilo.append({"updateParagraphStyle": {
            "range": {"startIndex": t0, "endIndex": t1},
            "paragraphStyle": {"namedStyleType": "TITLE"},
            "fields": "namedStyleType",
        }})
    for titulo in titulos_roteiro:
        a, b = _intervalo_texto(doc3, titulo)
        if a is not None:
            estilo.append({"updateParagraphStyle": {
                "range": {"startIndex": a, "endIndex": b},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }})

    if estilo:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": estilo}).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"


# ─── Geração em LISTA (mais legível que a tabela) ────────────────────────────

def _ordenar_por_linha(achados, texto):
    def chave(a):
        ln, _ = linha_do_trecho(texto, a.get("trecho_original", ""))
        return (ln is None, ln or 0, -importancia(a))
    return sorted(achados, key=chave)


def _bloco_achado(n, a, texto, papel_item="ITEM_OPC"):
    """Retorna lista de (texto_paragrafo, papel) para um achado."""
    trecho = (a.get("trecho_original") or "").strip()
    ln, _ = linha_do_trecho(texto, trecho) if trecho else (None, None)
    local = f"Linha {ln}" if ln else "Geral"
    cabecalho = f"{n}. {local}  ·  {_tipo(a)}  ·  importância {importancia(a)}%"
    paras = [(cabecalho, papel_item)]
    if trecho:
        paras.append((f"Trecho: «{trecho}»", "BODY"))
        paras.append((f"Trocar por: «{(a.get('correcao') or '').strip()}»", "BODY"))
    else:
        paras.append((f"Sugestão: {(a.get('correcao') or '').strip()}", "BODY"))
    paras.append((f"Porquê: {(a.get('porque') or '').strip()}", "BODY"))
    paras.append(("", "BODY"))  # espaço entre itens
    return paras


def gerar_doc_lista(json_path) -> str:
    from googleapiclient.discovery import build

    dados = json.loads(Path(json_path).read_text(encoding="utf-8"))
    creds = autenticar(scopes=SCOPES_WRITE, token_path=TOKEN_WRITE)
    docs = build("docs", "v1", credentials=creds)

    cliente = next((r.get("cliente") for r in dados if r.get("cliente")), None)
    data_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    titulo_doc = f"Correções — {cliente + ' — ' if cliente else ''}{data_str}"
    doc_id = docs.documents().create(body={"title": titulo_doc}).execute()["documentId"]

    # ── Monta a lista de parágrafos (texto, papel) ───────────────────────────
    paras = [("Relatório de Correções — Viral Media Labs", "TITLE")]
    if cliente:
        paras.append((f"Cliente: {cliente}", "BODY"))
    paras.append((f"Gerado em {data_str}", "BODY"))
    paras.append(("", "BODY"))

    for r in dados:
        cons = r.get("consolidado", {})
        texto = r.get("texto", "")
        bloq = _ordenar_por_linha(cons.get("bloqueantes", []), texto)
        otim = _ordenar_por_linha(cons.get("otimizacoes", []), texto)

        paras.append((f"Roteiro {r.get('numero','')}: {r.get('titulo','')}", "H1"))
        paras.append((
            f"Veredicto: {cons.get('veredicto','—')}  ·  Nota {cons.get('nota_geral','—')}/10  ·  "
            f"Viral {cons.get('nota_viral','—')}/10  ·  {len(bloq)} obrigatórias / {len(otim)} opcionais",
            "BODY",
        ))
        paras.append(("", "BODY"))

        paras.append(("⛔ Correções obrigatórias", "H2"))
        if bloq:
            for i, a in enumerate(bloq, 1):
                paras.extend(_bloco_achado(i, a, texto, "ITEM_OBR"))
        else:
            paras.append(("Nenhuma — nenhum erro objetivo bloqueante.", "BODY"))
            paras.append(("", "BODY"))

        paras.append(("✨ Otimizações opcionais", "H2"))
        if otim:
            for i, a in enumerate(otim, 1):
                paras.extend(_bloco_achado(i, a, texto, "ITEM_OPC"))
        else:
            paras.append(("Nenhuma.", "BODY"))
            paras.append(("", "BODY"))

    # ── Insere todo o texto de uma vez ───────────────────────────────────────
    linhas = [p[0] for p in paras]
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": [
        {"insertText": {"location": {"index": 1}, "text": "\n".join(linhas)}}
    ]}).execute()

    # ── Passe de estilo: detecta o papel pelo CONTEÚDO do parágrafo ──────────
    # (robusto a desalinhamento; toda range é protegida contra vazio)
    doc = docs.documents().get(documentId=doc_id).execute()
    estilo = []
    secao = None  # "OBR" | "OPC" — define a cor dos itens
    for el in doc.get("body", {}).get("content", []):
        par = el.get("paragraph")
        if not par:
            continue
        ini, fim = el.get("startIndex"), el.get("endIndex")
        if ini is None or fim is None or fim <= ini:
            continue
        txt = "".join(r.get("textRun", {}).get("content", "") for r in par.get("elements", [])).rstrip("\n")
        if not txt.strip():
            continue

        def add_par_style(nome):
            estilo.append({"updateParagraphStyle": {
                "range": {"startIndex": ini, "endIndex": fim},
                "paragraphStyle": {"namedStyleType": nome},
                "fields": "namedStyleType",
            }})

        if txt.startswith("Relatório de Correções"):
            add_par_style("TITLE")
        elif re.match(r"^Roteiro\s+\d*\s*:", txt):
            add_par_style("HEADING_1")
        elif txt.startswith("⛔ Correções"):
            secao = "OBR"; add_par_style("HEADING_2")
        elif txt.startswith("✨ Otimizações"):
            secao = "OPC"; add_par_style("HEADING_2")
        elif re.match(r"^\d+\.\s+(Linha|Geral)\b", txt):  # cabeçalho de item
            cor = COR_OBRIGATORIA if secao == "OBR" else COR_OPCIONAL
            if fim - 1 > ini:
                estilo.append({"updateTextStyle": {
                    "range": {"startIndex": ini, "endIndex": fim - 1},
                    "textStyle": {"bold": True, "foregroundColor": cor},
                    "fields": "bold,foregroundColor",
                }})
        else:  # corpo — negrita só o rótulo (Trecho:/Trocar por:/Porquê:)
            for lab in LABELS_BOLD:
                if txt.startswith(lab) and ini + len(lab) < fim:
                    estilo.append({"updateTextStyle": {
                        "range": {"startIndex": ini, "endIndex": ini + len(lab)},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }})
                    break

    if estilo:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": estilo}).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"


if __name__ == "__main__":
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else json_mais_recente()
    if not caminho or not caminho.exists():
        print("❌ Nenhum .json de revisão encontrado. Rode revisar.py primeiro.")
        sys.exit(1)
    link = gerar_doc_lista(caminho)
    print(f"✅ Relatório de correções em lista (Google Docs):\n   {link}")
