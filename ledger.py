#!/usr/bin/env python3
"""
Ledger de decisões — memória permanente de TUDO que o editor decide.

Cada decisão (aplicar, editar, pular, ensinar) vira UM evento JSON numa linha do
`decisoes.jsonl` (append-only). Nada é descartado — inclusive "aplicado sem edição",
que é reforço positivo (o agente acertou).

Todas as formas de aprendizado derivam daqui (ver roadmap_aprendizado.md):
regras por cliente, mineração de padrões recorrentes, few-shot por agente,
telemetria de regras e calibração do consolidador.

Formato do evento:
    {"ts": "...", "origem": "tabela|dinamica|bootstrap", "chave": "...",
     "cliente": "...", "roteiro_titulo": "...", "estrutura_codex": "...",
     "camada": "...", "severidade": "...", "natureza": "...", "confianca": 0-100,
     "trecho": "...", "correcao_agente": "...",
     "decisao": "aplicado|editado|pulado|resetado", "versao_usuario": "...",
     "motivo": "..."}

`chave` (quando presente) identifica o achado na origem (arquivo:roteiro:idx) e
permite reimportação idempotente (bootstrap não duplica eventos já registrados).

Uso CLI:
    python3 ledger.py --bootstrap   # importa decisões dos revisao_*.json históricos
    python3 ledger.py --stats       # estatísticas de decisões por camada
"""

import json
import threading
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
ARQUIVO = RAIZ / "decisoes.jsonl"
PASTA_RELATORIOS = RAIZ / "relatorios"

_lock = threading.Lock()


# ─── Escrita ─────────────────────────────────────────────────────────────────

def registrar(evento: dict):
    """Acrescenta um evento ao ledger. Best-effort: NUNCA derruba o fluxo chamador."""
    try:
        evento = {"ts": datetime.now().isoformat(timespec="seconds"), **evento}
        linha = json.dumps(evento, ensure_ascii=False)
        with _lock:
            with open(ARQUIVO, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
    except Exception:
        pass


def normalizar_decisao(dec, correcao: str = ""):
    """Converte o valor cru do campo `decisao` (tabela/JSON) em (decisao, versao_usuario).
    Cru: None = resetada · 'pular' · 'aplicado' (aprovado sem substituição) ·
    texto = correção aprovada (igual à do agente) ou editada (diferente)."""
    if dec is None:
        return "resetado", ""
    if dec == "pular":
        return "pulado", ""
    if dec == "aplicado" or dec.strip() == (correcao or "").strip():
        return "aplicado", ""
    return "editado", dec


def evento_de_achado(achado: dict, decisao: str, *, motivo: str = "",
                     versao_usuario: str = "", cliente: str = "",
                     roteiro_titulo: str = "", estrutura: str = "",
                     origem: str = "", chave: str = "") -> dict:
    """Monta um evento do ledger a partir de um achado + decisão do editor."""
    ev = {
        "origem": origem,
        "cliente": cliente or "",
        "roteiro_titulo": roteiro_titulo or "",
        "estrutura_codex": estrutura or "",
        "camada": achado.get("camada", ""),
        "severidade": achado.get("severidade", ""),
        "natureza": achado.get("natureza", ""),
        "confianca": achado.get("confianca", 0),
        "trecho": achado.get("trecho_original", ""),
        "correcao_agente": achado.get("correcao", ""),
        "decisao": decisao,
        "versao_usuario": versao_usuario,
        "motivo": motivo,
    }
    if chave:
        ev["chave"] = chave
    return ev


def registrar_decisao(achado: dict, decisao: str, **kw):
    """Atalho: monta e registra o evento de uma decisão sobre um achado."""
    registrar(evento_de_achado(achado, decisao, **kw))


# ─── Leitura ─────────────────────────────────────────────────────────────────

def carregar(filtro=None) -> list:
    """Lê todos os eventos do ledger. `filtro` opcional: função(evento) -> bool."""
    if not ARQUIVO.exists():
        return []
    eventos = []
    for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            e = json.loads(linha)
        except ValueError:
            continue
        if filtro is None or filtro(e):
            eventos.append(e)
    return eventos


def decisoes_finais(eventos: list = None) -> list:
    """Colapsa o log de eventos na ÚLTIMA decisão de cada achado (por chave).
    Eventos sem chave (modo dinâmico) são todos finais — cada um é uma decisão única.
    Eventos 'resetado' anulam a decisão anterior da mesma chave."""
    eventos = carregar() if eventos is None else eventos
    finais, por_chave = [], {}
    for e in eventos:
        chave = e.get("chave")
        if chave:
            por_chave[chave] = e  # último evento da chave vence (ordem do arquivo)
        else:
            finais.append(e)
    finais.extend(e for e in por_chave.values() if e.get("decisao") != "resetado")
    return finais


# ─── Bootstrap dos JSONs históricos ──────────────────────────────────────────

def bootstrap_relatorios(pasta: Path = PASTA_RELATORIOS) -> int:
    """Importa decisões já persistidas nos revisao_*.json (campo `decisao`, gravado
    pela Tabela Interativa). Idempotente: chaves já presentes no ledger são puladas."""
    existentes = {e.get("chave") for e in carregar() if e.get("chave")}
    importados = 0
    for jp in sorted(pasta.glob("revisao_*.json")):
        try:
            dados = json.loads(jp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(dados, dict):
            dados = [dados]
        for rot in dados:
            if not isinstance(rot, dict):
                continue
            achados = rot.get("consolidado", {}).get("achados", [])
            for idx, a in enumerate(achados):
                if not isinstance(a, dict) or "decisao" not in a:
                    continue
                chave = f"{jp.name}:{rot.get('numero', 0)}:{idx}"
                if chave in existentes:
                    continue
                decisao, versao = normalizar_decisao(a.get("decisao"), a.get("correcao", ""))
                if decisao == "resetado":
                    continue  # decisão anulada — sem sinal
                registrar(evento_de_achado(
                    a, decisao,
                    motivo=a.get("motivo_decisao", ""),
                    versao_usuario=versao,
                    cliente=rot.get("cliente") or "",
                    roteiro_titulo=rot.get("titulo", ""),
                    estrutura=(rot.get("contexto") or {}).get("estrutura", ""),
                    origem="bootstrap",
                    chave=chave,
                ))
                existentes.add(chave)
                importados += 1
    return importados


# ─── Estatísticas ────────────────────────────────────────────────────────────

def stats() -> dict:
    """Resumo das decisões finais: total e taxa de aceitação por camada."""
    finais = decisoes_finais()
    por_camada = {}
    for e in finais:
        cam = e.get("camada") or "?"
        d = por_camada.setdefault(cam, {"aplicado": 0, "editado": 0, "pulado": 0, "outros": 0})
        d[e.get("decisao") if e.get("decisao") in d else "outros"] += 1
    resumo = {}
    for cam, d in sorted(por_camada.items()):
        tot = sum(d.values())
        aceitos = d["aplicado"] + d["editado"]  # editado = aceito com ajuste
        resumo[cam] = {**d, "total": tot,
                       "taxa_aceitacao": round(100 * aceitos / tot) if tot else 0}
    return {"total_eventos": len(carregar()), "decisoes_finais": len(finais),
            "por_camada": resumo}


def imprimir_stats():
    s = stats()
    print(f"\n📊 Ledger: {s['total_eventos']} evento(s) · {s['decisoes_finais']} decisão(ões) final(is)\n")
    if not s["por_camada"]:
        print("   (vazio — rode uma revisão ou python3 ledger.py --bootstrap)")
        return
    print(f"   {'camada':<14}{'total':>6}{'aplic.':>8}{'edit.':>7}{'pulado':>8}{'aceit.':>8}")
    for cam, d in s["por_camada"].items():
        print(f"   {cam:<14}{d['total']:>6}{d['aplicado']:>8}{d['editado']:>7}"
              f"{d['pulado']:>8}{d['taxa_aceitacao']:>7}%")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ledger de decisões — VML")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Importa decisões dos revisao_*.json históricos")
    parser.add_argument("--stats", action="store_true",
                        help="Estatísticas de decisões por camada")
    args = parser.parse_args()

    if args.bootstrap:
        n = bootstrap_relatorios()
        print(f"✅ Bootstrap: {n} decisão(ões) histórica(s) importada(s) → {ARQUIVO.name}")
    if args.stats or not args.bootstrap:
        imprimir_stats()
