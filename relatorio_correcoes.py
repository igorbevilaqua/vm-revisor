#!/usr/bin/env python3
"""
Relatório de Correções — Viral Media Labs

Gera, para CADA roteiro, uma TABELA de correções limpa e escaneável, com:
  - Linha e ponto exato a corrigir
  - Tipo de correção (camada)
  - Sugestão de correção
  - Importância (%) — prioridade calculada
  - Prioridade (Obrigatória / Opcional) e consenso entre agentes

Lê o .json estruturado salvo por revisar.py e escreve um .md em relatorios/.

Uso:
    python3 relatorio_correcoes.py                          # usa o .json mais recente
    python3 relatorio_correcoes.py relatorios/revisao_X.json
"""

from __future__ import annotations

import re
import sys
import json
from pathlib import Path

PASTA_RELATORIOS = Path(__file__).parent / "relatorios"

ROTULO_CAMADA = {
    "ortografia":   "Ortografia",
    "clareza":      "Clareza/Ritmo",
    "coerencia":    "Coerência",
    "checklist":    "Checklist",
    "storytelling": "Storytelling",
    "factcheck":    "Fato",
    "hook":         "Hook",
    "cta":          "CTA",
    "viral":        "Viral",
}

PESO_SEV = {"erro": 30, "aviso": 18, "sugestao": 8}


# ─── Localização da linha exata ──────────────────────────────────────────────

def linha_do_trecho(texto: str, trecho: str):
    """Retorna (numero_da_linha, trecho_da_linha) onde o trecho aparece, ou (None, None).
    Tolerante a diferenças de espaço/quebra de linha."""
    t = (trecho or "").strip()
    if not t:
        return None, None
    pos = texto.find(t)
    if pos == -1:
        tokens = [re.escape(tok) for tok in t.split()]
        m = re.search(r"\s+".join(tokens), texto) if tokens else None
        if not m:
            return None, None
        pos = m.start()
    linha_num = texto.count("\n", 0, pos) + 1
    linha_txt = texto.splitlines()[linha_num - 1].strip() if texto.splitlines() else ""
    return linha_num, linha_txt


# ─── Importância (prioridade calculada 0-100) ────────────────────────────────

def importancia(a: dict) -> int:
    n_camadas = len(set(a.get("camadas", [a.get("camada")])))
    score = (
        a.get("confianca", 0) * 0.6
        + PESO_SEV.get(a.get("severidade"), 0)
        + (8 if a.get("natureza") == "objetivo" else 0)
        + min((n_camadas - 1) * 4, 12)   # consenso entre agentes
    )
    return max(0, min(100, round(score)))


def e_bloqueante(a: dict) -> bool:
    return (a.get("severidade") == "erro" and a.get("natureza") == "objetivo"
            and a.get("confianca", 0) >= 70)


# ─── Montagem da tabela ──────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def _tipo(a: dict) -> str:
    camadas = list(dict.fromkeys(a.get("camadas", [a.get("camada")])))
    rotulos = [ROTULO_CAMADA.get(c, c) for c in camadas]
    base = " + ".join(rotulos)
    if len(camadas) > 1:
        base += f" ⚑{len(camadas)}"   # consenso: vários agentes apontaram
    return base


# Cabeçalho das colunas — reutilizado pelo relatório .md e pela tabela do Google Docs
COLUNAS = ["Linha", "Ponto exato a corrigir", "Tipo", "Sugestão de correção", "Imp.", "Prioridade"]


def _ponto_plano(a: dict, texto: str) -> tuple[str, str]:
    """(numero_da_linha, trecho) em texto puro, sem aspas/markdown."""
    trecho = (a.get("trecho_original") or "").strip()
    if not trecho:
        return "—", "— (geral)"
    linha, _ = linha_do_trecho(texto, trecho)
    ln = str(linha) if linha else "?"
    ponto = trecho if len(trecho) <= 80 else trecho[:77] + "…"
    return ln, ponto


def montar_linhas(texto: str, achados: list[dict]) -> list[list[str]]:
    """Linhas da tabela (sem cabeçalho), ordenadas por linha do roteiro.
    Cada linha: [Linha, Ponto, Tipo, Sugestão, Imp., Prioridade]. Texto puro."""
    def chave(a):
        linha, _ = linha_do_trecho(texto, a.get("trecho_original", ""))
        return (linha is None, linha or 0, -importancia(a))

    rows = []
    for a in sorted(achados, key=chave):
        ln, ponto = _ponto_plano(a, texto)
        prio = "⛔ Obrigatória" if e_bloqueante(a) else "✨ Opcional"
        rows.append([ln, ponto, _tipo(a), (a.get("correcao") or "").strip(),
                     f"{importancia(a)}%", prio])
    return rows


def gerar_tabela(texto: str, achados: list[dict]) -> str:
    linhas = ["| " + " | ".join(COLUNAS) + " |", "|:---:|:---|:---|:---|:---:|:---:|"]
    for r in montar_linhas(texto, achados):
        cells = list(r)
        cells[1] = f'"{cells[1]}"' if cells[1] != "— (geral)" else "_(geral)_"
        linhas.append("| " + " | ".join(_esc(str(c)) for c in cells) + " |")
    return "\n".join(linhas)


def gerar_secao(roteiro: dict) -> str:
    cons = roteiro.get("consolidado", {})
    texto = roteiro.get("texto", "")
    achados = cons.get("achados", [])
    n_obrig = sum(1 for a in achados if e_bloqueante(a))

    L = []
    L.append(f"## Roteiro {roteiro.get('numero','')}: {roteiro.get('titulo','')}")
    L.append("")
    L.append(f"**Veredicto:** {cons.get('veredicto','—')}  ·  "
             f"**Nota geral:** {cons.get('nota_geral','—')}/10  ·  "
             f"**Potencial viral:** {cons.get('nota_viral','—')}/10")
    L.append(f"**Correções obrigatórias:** {n_obrig}  ·  "
             f"**Otimizações opcionais:** {len(achados) - n_obrig}")
    L.append("")
    if cons.get("diagnostico"):
        L.append(f"> {_esc(cons['diagnostico'])[:600]}")
        L.append("")
    if achados:
        L.append(gerar_tabela(texto, achados))
    else:
        L.append("_Nenhuma correção — roteiro limpo._")
    L.append("")
    L.append("**Legenda:** Imp. = importância calculada (severidade + confiança + consenso "
             "entre agentes). ⚑N = N agentes apontaram o mesmo ponto. "
             "⛔ Obrigatória = erro objetivo que impede a publicação. ✨ Opcional = melhoria.")
    L.append("\n---\n")
    return "\n".join(L)


def gerar_relatorio(json_path: Path) -> Path:
    dados = json.loads(json_path.read_text(encoding="utf-8"))
    partes = ["# Relatório de Correções — Viral Media Labs", ""]
    for roteiro in dados:
        partes.append(gerar_secao(roteiro))
    saida = json_path.with_name(json_path.stem.replace("revisao", "correcoes") + ".md")
    saida.write_text("\n".join(partes), encoding="utf-8")
    return saida


def json_mais_recente() -> Path | None:
    arquivos = sorted(PASTA_RELATORIOS.glob("revisao_*.json"))
    return arquivos[-1] if arquivos else None


if __name__ == "__main__":
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else json_mais_recente()
    if not caminho or not caminho.exists():
        print("❌ Nenhum .json de revisão encontrado. Rode revisar.py primeiro.")
        sys.exit(1)
    saida = gerar_relatorio(caminho)
    print(f"✅ Relatório de correções gerado: {saida}")
