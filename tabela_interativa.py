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


def _correcao_e_instrucao(texto):
    """True se o texto começa com verbo de instrução editorial — não é substituto literal."""
    if not texto:
        return False
    return texto.strip().split()[0].lower().rstrip(".,;:)") in _VERBOS_INSTRUCAO


def transformar_achado(achado, idx):
    trecho = (achado.get("trecho_original") or "").strip()
    correcao = (achado.get("correcao") or "").strip()
    porque = (achado.get("porque") or "").strip()

    # Segunda camada de defesa: se `correcao` ainda chegou como instrução editorial
    # (agente ignorou o prompt), zera os dois campos e preserva a nota em `porque`.
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


def transformar_roteiro(roteiro_raw, url_gdocs="", meta=None):
    cons = roteiro_raw.get("consolidado", {})
    achados = cons.get("achados", [])
    correcoes = []
    for i, a in enumerate(achados, 1):
        t = (a.get("trecho_original") or "").strip()
        c = (a.get("correcao") or "").strip()
        if not t and not c:
            continue
        correcoes.append(transformar_achado(a, i))

    veredicto = cons.get("veredicto", "—")
    return {
        "roteiro": {
            "titulo": roteiro_raw.get("titulo", "Roteiro"),
            "id": f"rot_{roteiro_raw.get('numero', 1):02d}",
            "veredicto": veredicto,
            "score_geral": cons.get("nota_geral", 0),
        },
        "url_gdocs": url_gdocs or "",
        "correcoes": correcoes,
        "meta": meta or {"total": 1, "atual": 1, "proximo_titulo": None},
    }


def json_mais_recente():
    jsons = sorted(PASTA_RELATORIOS.glob("revisao_*.json"))
    return jsons[-1] if jsons else None


# ─── Servidor Flask ───────────────────────────────────────────────────────────

class TabelaServer:
    """Servidor Flask de vida longa: um único processo por sessão.

    O browser mantém a mesma aba. Ao clicar em 'Continuar', o Python
    processa o próximo roteiro, atualiza `dados_atual` e o JS refaz
    fetch em /api/dados para re-renderizar sem recarregar a página.
    """

    def __init__(self, url_gdocs: str = "", porta: int = 7432):
        import uuid as _uuid
        self.url_gdocs = url_gdocs
        self.porta = porta
        self.dados_atual: dict = {}
        self._done_event = threading.Event()
        self._next_event = threading.Event()
        self._app = None
        self._thread = None
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
                n = aplicar_correcoes(url, correcoes)
                return jsonify({"aplicadas": n})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

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

    # ── Controle público ───────────────────────────────────────────────────
    def iniciar(self, dados: dict):
        """Inicia o servidor Flask com os dados do primeiro roteiro."""
        self.dados_atual = dados
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
        self._next_event.set()

    def finalizar(self):
        """Sinaliza que acabaram os roteiros (handler retorna recarregar: false)."""
        self._next_event.set()


# ─── Entrada pública (usada por revisar.py) ───────────────────────────────────

def executar_sessao(roteiros_raw, url_gdocs="", porta=7432):
    """Processa os roteiros um por vez com a interface de tabela.

    Esta função é chamada pelo revisar.py depois que os agentes já rodaram.
    `roteiros_raw` é a lista de dicts no formato do consolidador.
    """
    try:
        from flask import Flask  # noqa — apenas verifica disponibilidade
    except ImportError:
        print("❌ Flask não instalado. Execute: pip install flask")
        return

    server = TabelaServer(url_gdocs=url_gdocs, porta=porta)

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


# ─── Entrada standalone (CLI) ─────────────────────────────────────────────────

def iniciar_standalone(json_path, url_gdocs="", porta=7432):
    """Abre a tabela a partir de um JSON já existente (sem rodar os agentes)."""
    dados_raw = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(dados_raw, dict):
        dados_raw = [dados_raw]

    print(f"\n📋 {len(dados_raw)} roteiro(s) carregado(s) de {json_path.name}")
    executar_sessao(dados_raw, url_gdocs=url_gdocs, porta=porta)


# ─── HTML ─────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Tabela Interativa — VML</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0D0F12;--surface:#141720;--surface-2:#1C2030;--surface-3:#242840;
  --border:#2A2F45;--border-light:#333A55;
  --bloqueante:#FF4545;--bloqueante-bg:rgba(255,69,69,.08);--bloqueante-border:rgba(255,69,69,.3);
  --aviso:#F5A623;--aviso-bg:rgba(245,166,35,.08);--aviso-border:rgba(245,166,35,.3);
  --sugestao:#4B9EFF;--sugestao-bg:rgba(75,158,255,.08);--sugestao-border:rgba(75,158,255,.25);
  --leitura:#8891AA;--leitura-bg:rgba(136,145,170,.06);--leitura-border:rgba(136,145,170,.15);
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
.tabela th{position:sticky;top:93px;z-index:90;background:var(--surface-2);
  border:1px solid var(--border);padding:9px 10px;text-align:left;
  font-family:var(--mono);font-size:10px;font-weight:600;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;overflow:hidden}
.tabela th:first-child{text-align:center}
.col-n{width:40px}.col-t{width:108px}.col-tr{width:170px}
.col-a{width:195px}.col-d{width:195px}.col-j{width:185px}.col-ac{width:118px}
.tabela td{border:1px solid var(--border);padding:9px 10px;vertical-align:top;transition:background .15s,box-shadow .15s}

/* Row types */
.rb{background:var(--bloqueante-bg);border-left:3px solid var(--bloqueante)!important}
.ra{background:var(--aviso-bg);border-left:3px solid var(--aviso)!important}
.rs{border-left:3px solid var(--sugestao)!important}
.rl{background:var(--leitura-bg);border-left:3px solid var(--leitura-border)!important}
.sec-row{background:var(--surface-2)}
.sec-row td{border-top:2px solid var(--border-light)!important;padding:10px 14px;
  font-family:var(--mono);font-size:11px;font-weight:700;color:var(--text-2);
  text-transform:uppercase;letter-spacing:.1em;
  background:linear-gradient(to right,var(--surface-3),var(--surface-2))!important}
.row-aprov{background:var(--aprovado-bg)!important}
.row-pulada{opacity:.4}
.row-hidden{display:none}

/* Num cell */
.nc{font-family:var(--mono);font-size:11px;color:var(--text-3);text-align:center}

/* Badge */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:3px;
  font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;border:1px solid transparent}
.badge-e{background:var(--bloqueante-bg);border-color:var(--bloqueante-border);color:var(--bloqueante)}
.badge-a{background:var(--aviso-bg);border-color:var(--aviso-border);color:var(--aviso)}
.badge-s{background:var(--sugestao-bg);border-color:var(--sugestao-border);color:var(--sugestao)}
.tag-c{display:inline-block;margin-top:5px;padding:2px 6px;border-radius:2px;
  font-family:var(--mono);font-size:9px;font-weight:500;background:var(--surface-3);
  color:var(--text-3);border:1px solid var(--border);letter-spacing:.04em}

/* Trecho */
.tr-text{font-size:12px;color:var(--text-2);font-style:italic;line-height:1.5;
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical}

/* Diff blocks */
.diff-blk{border-radius:4px;padding:7px 9px;font-family:var(--mono);font-size:12px;
  line-height:1.6;border:1px solid transparent;word-break:break-word}
.db-ant{background:var(--antes);border-color:rgba(255,69,69,.2);color:var(--antes-text)}
.db-dep{background:var(--depois);border-color:rgba(0,201,127,.2);color:var(--depois-text)}
.diff-null{color:var(--text-3);font-size:11px;font-style:italic;font-family:var(--mono)}
.del{background:rgba(255,69,69,.22);color:var(--antes-text);text-decoration:line-through;
  border-radius:2px;padding:0 2px}
.ins{background:rgba(0,201,127,.22);color:var(--depois-text);border-radius:2px;padding:0 2px}

/* Justificativa */
.jt{font-size:12px;color:var(--text-2);line-height:1.5;margin-bottom:7px}
.conf-wrap{display:flex;align-items:center;gap:6px;margin-top:5px}
.conf-lbl{font-family:var(--mono);font-size:9px;color:var(--text-3);white-space:nowrap}
.conf-track{flex:1;height:3px;background:var(--surface-3);border-radius:2px;overflow:hidden}
.conf-fill{height:100%;border-radius:2px;transition:width .3s}
.cf-hi{background:var(--aprovado)}.cf-md{background:var(--sugestao)}.cf-lo{background:var(--aviso)}
.conf-val{font-family:var(--mono);font-size:9px;color:var(--text-3);width:26px;text-align:right}

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
.tabela tbody tr.rl:hover td{background:rgba(136,145,170,.10)!important}
.btn-ac:active{transform:scale(0.95);transition:transform .08s}
.btn-gravar:active,.btn-continuar:active,.btn-sec:active{transform:scale(0.97);transition:transform .08s}

/* ── Animação de aprovação ─── */
@keyframes approvalFlash{
  0%{box-shadow:inset 0 0 0 100px rgba(0,201,127,.18)}
  100%{box-shadow:inset 0 0 0 100px rgba(0,0,0,0)}
}
.row-aprov td{animation:approvalFlash .55s ease-out}
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
  <span class="filtro-label">Filtrar:</span>
  <button class="fbtn fa" onclick="setF(this,'todos')">Todos</button>
  <button class="fbtn" onclick="setF(this,'bloqueantes','fa-b')">Bloqueantes</button>
  <button class="fbtn" onclick="setF(this,'avisos','fa-a')">Avisos</button>
  <button class="fbtn" onclick="setF(this,'sugestoes')">Sugestões</button>
  <button class="fbtn" onclick="setF(this,'pendentes')">Pendentes</button>
  <button class="fbtn" onclick="setF(this,'aprovados','fa-v')">Aprovados</button>
</div>

<div id="tabela-wrap">
  <table class="tabela" id="tbl">
    <thead><tr>
      <th class="col-n">#</th>
      <th class="col-t">Tipo / Camada</th>
      <th class="col-tr">Trecho do Roteiro</th>
      <th class="col-a">Antes</th>
      <th class="col-d">Depois</th>
      <th class="col-j">Justificativa</th>
      <th class="col-ac">Ação</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div id="footer">
  <div class="footer-l"><span class="naplic" id="n-ap">0</span> de <span id="n-tot">0</span> aplicadas</div>
  <div class="footer-c" id="footer-st">—</div>
  <div class="footer-r">
    <button class="btn-sec" onclick="resetar()">Resetar</button>
    <button class="btn-sec" onclick="exportar()">Exportar JSON</button>
    <button class="btn-gravar" id="btn-gravar" onclick="gravar()" disabled>Gravar no Google Docs</button>
    <button class="btn-continuar" id="btn-cont" onclick="continuar()" style="display:none">Continuar →</button>
  </div>
</div>

<div id="toast"></div>
<div id="loading"><div class="spin"></div><div class="loading-msg" id="loading-msg">Aguarde...</div></div>

<script>
// ── Dados iniciais (embedded no primeiro load) ───────────────────────────────
let D = __DADOS_JSON__;
const SESSAO = '__SESSAO_ID__';
let filtro = 'todos';
let numFiltroBtn = null;

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
  const s=localStorage.getItem(k);
  if(!s)return;
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
  if(!t)return['<span class="diff-null">— Não se aplica</span>',`<div class="diff-blk db-dep">${esc(d)}</div>`];
  if(!d)return[`<div class="diff-blk db-ant">${esc(t)}</div>`,'<span class="diff-null">— Sugestão estrutural<br><small>Ver justificativa</small></span>'];
  const r=diff(t,d);
  if((r.inline||c.diff_inline)&&r.inline){
    return[
      `<div class="diff-blk db-ant">${esc(r.pfx)}<span class="del">${esc(r.del)}</span>${esc(r.sfx)}</div>`,
      `<div class="diff-blk db-dep">${esc(r.pfx)}<span class="ins">${esc(r.ins)}</span>${esc(r.sfx)}</div>`
    ];
  }
  return[`<div class="diff-blk db-ant">${esc(t)}</div>`,`<div class="diff-blk db-dep">${esc(d)}</div>`];
}

function renderConf(v){
  const cls=v>=85?'cf-hi':v>=60?'cf-md':'cf-lo';
  return`<div class="conf-wrap"><span class="conf-lbl">Conf.</span>
    <div class="conf-track"><div class="conf-fill ${cls}" style="width:${v}%"></div></div>
    <span class="conf-val">${v}%</span></div>`;
}

function renderBadge(c){
  const cls=c.severidade==='erro'?'badge-e':c.severidade==='aviso'?'badge-a':'badge-s';
  const lbl=c.severidade==='erro'?'⛔ Erro':c.severidade==='aviso'?'⚠ Aviso':'💡 Sugestão';
  return`<div class="badge ${cls}">${lbl}</div><div><span class="tag-c">${esc(c.camada)}</span></div>`;
}

function renderAcao(c){
  if(c.tipo==='contexto')return'<span class="st-na">sem ação</span>';
  const d=c.decisao;
  if(d==='pular')return'<div class="st-pu">— Pulado</div>';
  if(d&&d!=='pular')return'<div class="st-ap">✓ Aplicado</div>';
  return`<div class="acao-wrap">
    <button class="btn-ac btn-ap" onclick="aplicar('${c.id}')">✓ Aplicar</button>
    <button class="btn-ac btn-ed" onclick="editar('${c.id}')">✎ Editar</button>
    <button class="btn-ac btn-pu" onclick="pular('${c.id}')">✕ Pular</button>
  </div>`;
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

  // Botão Continuar
  const btnCont=$id('btn-cont');
  if(m.proximo_titulo){
    btnCont.style.display='';
    btnCont.textContent=`→ ${m.proximo_titulo.slice(0,30)}`;
  } else if(m.total>1){
    btnCont.style.display='';
    btnCont.textContent='✓ Concluir';
  } else {
    btnCont.style.display='none';
  }

  const tbody=$id('tbody');tbody.innerHTML='';
  const bloq=cs.filter(c=>c.severidade==='erro'&&c.tipo!=='contexto');
  const avis=cs.filter(c=>c.severidade==='aviso'&&c.tipo!=='contexto');
  const sug=cs.filter(c=>c.severidade==='sugestao'&&c.tipo!=='contexto');

  function addSec(label){
    const tr=document.createElement('tr');tr.className='sec-row';
    const td=document.createElement('td');td.colSpan=7;td.textContent=label;
    tr.appendChild(td);tbody.appendChild(tr);
  }

  let num=1;
  function addRow(c){
    const ctx=cs.filter(x=>x.tipo==='contexto'&&x.relacionado_a===c.id);
    const tr=document.createElement('tr');
    tr.id=`row-${c.id}`;
    tr.setAttribute('data-sev',c.severidade||'');
    tr.setAttribute('data-tipo',c.tipo||'correcao');
    let rc=c.tipo==='contexto'?'rl':c.severidade==='erro'?'rb':c.severidade==='aviso'?'ra':'rs';
    if(c.decisao&&c.decisao!=='pular')rc+=' row-aprov';
    else if(c.decisao==='pular')rc+=' row-pulada';
    if(!matchF(c))rc+=' row-hidden';
    tr.className=rc;

    if(c.tipo==='contexto'){
      tr.innerHTML=`<td class="nc">—</td><td><span class="tag-c">contexto</span></td>
        <td colspan="4"><div class="tr-text" style="font-style:italic">${esc(c.trecho_original)}</div>
          <div style="font-family:var(--mono);font-size:10px;color:var(--text-3);margin-top:4px">Parágrafo de contexto — sem correção</div></td>
        <td><span class="st-na">sem ação</span></td>`;
    } else {
      const [antH,depH]=renderDiff(c);
      tr.innerHTML=`<td class="nc">${num++}</td>
        <td>${renderBadge(c)}</td>
        <td><div class="tr-text">${esc(c.trecho_original)}</div></td>
        <td>${antH}</td>
        <td id="dep-${c.id}">${depH}</td>
        <td><div class="jt">${esc(c.porque)}</div>${renderConf(c.confianca||0)}</td>
        <td id="ac-${c.id}">${renderAcao(c)}</td>`;
    }
    tbody.appendChild(tr);
    ctx.forEach(x=>{
      const xtr=document.createElement('tr');
      xtr.id=`row-${x.id}`;xtr.className='rl'+(matchF(x)?'':' row-hidden');
      xtr.innerHTML=`<td class="nc">—</td><td><span class="tag-c">contexto</span></td>
        <td colspan="4"><div class="tr-text">${esc(x.trecho_original)}</div></td>
        <td><span class="st-na">sem ação</span></td>`;
      tbody.appendChild(xtr);
    });
  }

  if(bloq.length){addSec('⛔  ERROS BLOQUEANTES');bloq.forEach(addRow)}
  if(avis.length){addSec('⚠  AVISOS');avis.forEach(addRow)}
  if(sug.length){addSec('💡  SUGESTÕES');sug.forEach(addRow)}

  atualizarFooter();
}

// ── Filtro ────────────────────────────────────────────────────────────────────
function matchF(c){
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
  D.correcoes.forEach(c=>{
    const r=$id(`row-${c.id}`);if(!r)return;
    if(matchF(c))r.classList.remove('row-hidden');
    else r.classList.add('row-hidden');
  });
  // Hide empty section rows
  document.querySelectorAll('.sec-row').forEach(sr=>{
    let nx=sr.nextElementSibling,vis=false;
    while(nx&&!nx.classList.contains('sec-row')){
      if(!nx.classList.contains('row-hidden')){vis=true;break}
      nx=nx.nextElementSibling;
    }
    sr.style.display=vis?'':'none';
  });
}

// ── Ações ─────────────────────────────────────────────────────────────────────
function getC(id){return D.correcoes.find(c=>c.id===id)}

function aplicar(id){
  const c=getC(id);if(!c)return;
  c.decisao=c.correcao||'aplicado';
  salvar();atualizarLinha(id);atualizarFooter();
}

function pular(id){
  const c=getC(id);if(!c)return;
  c.decisao='pular';
  salvar();atualizarLinha(id);atualizarFooter();
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
  const ta=$id(`ta-${id}`);if(ta){ta.focus();ta.select()}
}

function conf(id){
  const ta=$id(`ta-${id}`);if(!ta)return;
  const novo=ta.value.trim();if(!novo)return;
  const c=getC(id);if(!c)return;
  c.decisao=novo;salvar();atualizarLinha(id);atualizarFooter();
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
  if(!D.url_gdocs){
    toast('Sem URL do Google Docs. Reinicie: python3 revisar.py --gdocs "URL"','e');
    return;
  }
  const aprovadas=D.correcoes.filter(c=>c.tipo==='correcao'&&c.decisao&&c.decisao!=='pular')
    .map(c=>({trecho_original:c.trecho_original,decisao:c.decisao}));
  if(!aprovadas.length){toast('Nenhuma correção aprovada.','e');return}
  const btn=$id('btn-gravar');btn.disabled=true;btn.textContent='Gravando...';
  try{
    const r=await fetch('/api/apply',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url_gdocs:D.url_gdocs||'',correcoes:aprovadas})});
    const d=await r.json();
    if(r.ok)toast(`✓ ${d.aplicadas} substituição(ões) gravada(s) no Google Docs`,'s');
    else toast(d.error||'Erro ao gravar','e');
  }catch(e){toast('Erro de conexão com o servidor local','e')}
  finally{
    btn.disabled=false;btn.textContent='Gravar no Google Docs';
    const bp=D.correcoes.filter(c=>c.severidade==='erro'&&!c.decisao).length;
    btn.disabled=bp>0;
  }
}

// ── Continuar para o próximo roteiro ─────────────────────────────────────────
async function continuar(){
  const loading=$id('loading');
  $id('loading-msg').textContent='Processando próximo roteiro...';
  loading.classList.add('show');
  try{
    const r=await fetch('/api/continuar',{method:'POST',
      headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    if(d.recarregar){
      // Busca novos dados e re-renderiza
      const r2=await fetch('/api/dados');
      D=await r2.json();
      localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}`);
      carregar();
      renderTudo();
      window.scrollTo(0,0);
      toast(`✓ ${D.roteiro.titulo.slice(0,40)}...`,'s');
    } else {
      toast('Revisão concluída! Pode fechar esta aba.','s');
      $id('btn-cont').disabled=true;
      $id('btn-cont').textContent='✓ Concluído';
    }
  }catch(e){toast('Erro ao avançar para o próximo roteiro','e')}
  finally{loading.classList.remove('show')}
}

// ── Resetar / Exportar ────────────────────────────────────────────────────────
function resetar(){
  if(!confirm('Resetar todas as decisões?'))return;
  D.correcoes.forEach(c=>c.decisao=null);
  localStorage.removeItem(`vml_${SESSAO}_${D.roteiro.id}`);
  renderTudo();
}

function exportar(){
  const payload={roteiro:D.roteiro,correcoes:D.correcoes,exportado_em:new Date().toISOString()};
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;
  a.download=`roteiro_${D.roteiro.id}_decisoes.json`;a.click();
  URL.revokeObjectURL(url);
  toast('JSON exportado!','s');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _tt=null;
function toast(msg,tipo){
  const t=$id('toast');t.textContent=msg;
  t.className=(tipo==='s'?'ts':'te')+' show';
  clearTimeout(_tt);_tt=setTimeout(()=>t.classList.remove('show'),3500);
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
