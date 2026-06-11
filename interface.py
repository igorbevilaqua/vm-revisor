#!/usr/bin/env python3
"""
Interface Gráfica — Revisor de Roteiros VML
Launcher web: o usuário cola a URL do Google Docs, acompanha o progresso REAL
do pipeline (9 agentes, consolidação) e é redirecionado para a Tabela Interativa.

Uso:
    python3 interface.py
    (ou duplo clique em Revisor.bat / Revisor.command)

Como funciona:
    1. Sobe um servidor Flask local com a tela inicial (URL do Google Docs).
    2. Ao iniciar, roda `revisar.py --gdocs URL --modo tabela` como subprocesso,
       lendo a saída linha a linha — cada status exibido é um evento REAL do
       pipeline (ex.: "✅ storytelling: 4 achado(s)").
    3. Quando a Tabela Interativa sobe (porta própria), o browser é redirecionado.
    A saída do pipeline também é espelhada neste terminal — o loop de
    aprendizado do final (input s/n) continua funcionando aqui.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

RAIZ = Path(__file__).parent

# ─── Estado da revisão (alimentado pelo parser da saída do pipeline) ──────────

AGENTES = ["ortografia", "clareza", "coerencia", "checklist", "storytelling",
           "factcheck", "hook", "viral", "cta"]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_RE_ROTEIROS   = re.compile(r"(\d+)\s+roteiro\(?s?\)?\s+(?:carregado|detectado)")
_RE_ANALISANDO = re.compile(r"\[(\d+)/(\d+)\]\s+(?:Analisando|Carregando):\s*(.+)")
_RE_RODANDO    = re.compile(r"Rodando\s+(\d+)\s+agentes? em paralelo")
_RE_AGENTE_OK  = re.compile(r"(?:✅|\[OK\])\s+([a-z]+):\s*(\d+)\s+achado")
_RE_FALHOU     = re.compile(r"Agente\s+([a-z]+)\s+falhou")
_RE_TABELA_URL = re.compile(r"Tabela Interativa\s*(?:→|->)\s*(http://\S+)")


class Revisao:
    """Mantém o estado da revisão em andamento, derivado da saída real do pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self.proc = None
        self.url_interface = ""   # URL deste launcher (botão ⟳ Nova Revisão na tabela)
        self.reset()

    def reset(self):
        self.fase = "ocioso"   # ocioso|iniciando|base|doc|contexto|agentes|consolidando|pronto|erro|encerrado
        self.url_gdocs = ""
        self.roteiro = {"num": 0, "total": 0, "titulo": ""}
        self.agentes = {k: "pendente" for k in AGENTES}   # pendente|rodando|ok|falhou|pulado
        self.contexto = "pendente"
        self.achados = {}
        self.log = deque(maxlen=60)
        self.tabela_url = ""
        self.erro = ""

    # ── Ciclo de vida do subprocesso ─────────────────────────────────────────
    def rodando(self):
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self, url: str):
        with self._lock:
            if self.rodando():
                if not self.tabela_url:
                    return False, "Já existe uma revisão em andamento."
                # Sessão anterior já entregou a tabela (usuário pediu Nova
                # Revisão): encerra o pipeline antigo para liberar a porta.
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            self.reset()
            self.url_gdocs = url
            self.fase = "iniciando"
            self.log.append("Iniciando o pipeline de revisão...")

        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["VML_LAUNCHER"] = "1"   # tabela_interativa não abre 2ª aba — nós redirecionamos
        if self.url_interface:
            env["VML_LAUNCHER_URL"] = self.url_interface  # botão ⟳ Nova Revisão na tabela

        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(RAIZ / "revisar.py"),
             "--gdocs", url, "--modo", "tabela"],
            cwd=RAIZ, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            # stdin herdado do terminal: o loop de aprendizado (s/n) do final
            # continua respondível na janela do .bat/.command.
        )
        threading.Thread(target=self._ler_saida, args=(self.proc,), daemon=True).start()
        return True, ""

    def _ler_saida(self, proc):
        """Lê a saída do pipeline conforme chega, espelha no terminal e alimenta o parser.
        os.read devolve o que estiver disponível — prompts sem \n (ex.: o [s/n] do
        loop de aprendizado) aparecem no terminal imediatamente."""
        fd = proc.stdout.fileno()
        buf = b""
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            if self.proc is not proc:
                return   # sessão substituída por uma Nova Revisão: parar de alimentar o estado
            self._tee(chunk)
            buf += chunk
            while b"\n" in buf:
                linha, buf = buf.split(b"\n", 1)
                self._processar_linha(linha.decode("utf-8", "replace"))
            if len(buf) > 16384:   # linha anormalmente longa: só para o parser
                buf = b""
        if buf and self.proc is proc:
            self._processar_linha(buf.decode("utf-8", "replace"))

        codigo = proc.wait()
        with self._lock:
            if self.proc is not proc:
                return   # estado já pertence à nova revisão
            if self.fase not in ("pronto",) or codigo != 0:
                if codigo != 0 and not self.tabela_url:
                    self.fase = "erro"
                    if not self.erro:
                        self.erro = ("O pipeline terminou com erro. "
                                     "Veja os detalhes na janela do terminal.")
                elif self.fase != "erro":
                    self.fase = "encerrado"
            elif not self.rodando():
                self.fase = "encerrado"

    @staticmethod
    def _tee(raw: bytes):
        try:
            sys.stdout.buffer.write(raw)
            sys.stdout.flush()
        except Exception:
            pass

    # ── Parser: cada linha do pipeline vira evento de status ─────────────────
    def _processar_linha(self, raw: str):
        linha = _ANSI.sub("", raw).strip()
        if not linha:
            return
        with self._lock:
            self.log.append(linha)

            if "Carregando base de conhecimento" in linha:
                self.fase = "base"
            elif _RE_ROTEIROS.search(linha):
                self.fase = "doc"
                m = _RE_ROTEIROS.search(linha)
                self.roteiro["total"] = int(m.group(1))
            elif _RE_ANALISANDO.search(linha):
                m = _RE_ANALISANDO.search(linha)
                self.roteiro = {"num": int(m.group(1)), "total": int(m.group(2)),
                                "titulo": m.group(3).strip()}
                # Novo roteiro: agentes voltam a pendente (relevante antes do redirect)
                if not self.tabela_url:
                    self.agentes = {k: "pendente" for k in AGENTES}
                    self.contexto = "pendente"
                    self.achados = {}
            elif "Extraindo contexto narrativo" in linha:
                self.fase = "contexto"
                self.contexto = "rodando"
            elif "fact-check pulado" in linha:
                self.agentes["factcheck"] = "pulado"
            elif _RE_RODANDO.search(linha):
                self.fase = "agentes"
                if self.contexto == "rodando":
                    self.contexto = "ok"
                for k in self.agentes:
                    if self.agentes[k] == "pendente":
                        self.agentes[k] = "rodando"
            elif _RE_AGENTE_OK.search(linha):
                m = _RE_AGENTE_OK.search(linha)
                nome = m.group(1)
                if nome in self.agentes:
                    self.agentes[nome] = "ok"
                    self.achados[nome] = int(m.group(2))
            elif _RE_FALHOU.search(linha):
                nome = _RE_FALHOU.search(linha).group(1)
                if nome in self.agentes:
                    self.agentes[nome] = "falhou"
            elif "Consolidando relatório final" in linha:
                self.fase = "consolidando"
                # Garantia: agentes ainda "rodando" terminaram (linha pode ter se perdido)
                for k in self.agentes:
                    if self.agentes[k] == "rodando":
                        self.agentes[k] = "ok"
            elif _RE_TABELA_URL.search(linha):
                self.tabela_url = _RE_TABELA_URL.search(linha).group(1)
                self.fase = "pronto"
            elif linha.startswith(("❌", "[ERRO]")) and not self.tabela_url:
                self.erro = linha.lstrip("❌").replace("[ERRO]", "").strip()

    # ── Snapshot para o front-end ─────────────────────────────────────────────
    def status(self):
        with self._lock:
            ativos = [k for k in AGENTES if self.agentes[k] != "pulado"]
            done = sum(1 for k in ativos if self.agentes[k] in ("ok", "falhou"))
            pct = {"ocioso": 0, "iniciando": 4, "base": 9, "doc": 15,
                   "contexto": 20, "consolidando": 88, "pronto": 100,
                   "encerrado": 100, "erro": 0}.get(self.fase, 0)
            if self.fase == "agentes":
                pct = 24 + int(62 * done / max(1, len(ativos)))
            return {
                "fase": self.fase,
                "pct": pct,
                "roteiro": self.roteiro,
                "contexto": self.contexto,
                "agentes": self.agentes,
                "achados": self.achados,
                "log": list(self.log)[-14:],
                "tabela_url": self.tabela_url,
                "erro": self.erro,
            }


REVISAO = Revisao()


# ─── Servidor Flask ────────────────────────────────────────────────────────────

def _porta_livre(inicio: int = 7401) -> int:
    for p in range(inicio, inicio + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return inicio


def criar_app():
    from flask import Flask, request, jsonify, Response
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    app = Flask(__name__)

    @app.route("/")
    def index():
        return Response(_HTML, mimetype="text/html; charset=utf-8")

    @app.route("/api/status")
    def api_status():
        return jsonify(REVISAO.status())

    @app.route("/api/iniciar", methods=["POST"])
    def api_iniciar():
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        if "docs.google.com/document" not in url:
            return jsonify({"error": "Cole um link válido do Google Docs "
                                     "(docs.google.com/document/d/...)."}), 400
        ok, msg = REVISAO.iniciar(url)
        if not ok:
            return jsonify({"error": msg}), 409
        return jsonify({"ok": True})

    return app


def main():
    try:
        app = criar_app()
    except ImportError:
        print("❌ Flask não instalado. Execute:")
        print("   pip install -r requirements.txt")
        sys.exit(1)

    porta = _porta_livre()
    url = f"http://localhost:{porta}"
    REVISAO.url_interface = url
    print("═" * 56)
    print("  REVISOR DE ROTEIROS — Viral Media Labs")
    print("═" * 56)
    print(f"\n🌐 Interface → {url}")
    print("   Cole a URL do Google Docs na janela do navegador.")
    print("   (mantenha esta janela aberta durante a revisão)\n")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        app.run(host="127.0.0.1", port=porta, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        if REVISAO.rodando():
            REVISAO.proc.terminate()


# ─── HTML ──────────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Revisor — VML</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0D0F12;--surface:#141720;--surface-2:#1C2030;--surface-3:#242840;
  --border:#2A2F45;--border-light:#333A55;
  --bloqueante:#FF4545;--bloqueante-bg:rgba(255,69,69,.08);--bloqueante-border:rgba(255,69,69,.3);
  --aviso:#F5A623;--aviso-bg:rgba(245,166,35,.08);--aviso-border:rgba(245,166,35,.3);
  --sugestao:#4B9EFF;--sugestao-bg:rgba(75,158,255,.08);--sugestao-border:rgba(75,158,255,.25);
  --aprovado:#00C97F;--aprovado-bg:rgba(0,201,127,.08);
  --text:#E8ECF5;--text-2:#9BA3BB;--text-3:#5C6480;
  --mono:'IBM Plex Mono',monospace;--sans:'Plus Jakarta Sans',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:13px;
  line-height:1.5;overflow-x:hidden}
/* Atmosfera: grid técnico + glow — mesmo universo industrial da tabela */
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(820px 420px at 50% -8%,rgba(75,158,255,.07),transparent 65%),
    radial-gradient(640px 380px at 88% 110%,rgba(0,201,127,.045),transparent 60%),
    repeating-linear-gradient(0deg,transparent 0 47px,rgba(42,47,69,.28) 47px 48px),
    repeating-linear-gradient(90deg,transparent 0 47px,rgba(42,47,69,.28) 47px 48px);
}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border-light);border-radius:3px}

#wrap{position:relative;z-index:1;min-height:100%;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:48px 24px 64px}

/* ── Marca ─── */
.brand{display:flex;align-items:center;gap:10px;font-family:var(--mono);
  font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--text-3)}
.brand .pulse{width:7px;height:7px;border-radius:50%;background:var(--aprovado);
  box-shadow:0 0 8px rgba(0,201,127,.8);animation:brandPulse 2.2s ease-in-out infinite}
@keyframes brandPulse{0%,100%{opacity:1}50%{opacity:.35}}
.brand .sep{color:var(--border-light)}

/* ── Painel ─── */
.panel{width:100%;max-width:620px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;
  box-shadow:0 24px 60px rgba(0,0,0,.5),0 0 0 1px rgba(75,158,255,.04);
  overflow:hidden;animation:panelIn .5s cubic-bezier(.22,1,.36,1)}
@keyframes panelIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.panel-head{padding:26px 30px 0;display:flex;flex-direction:column;gap:14px}
.panel-body{padding:24px 30px 30px}
h1{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1.15}
h1 .thin{color:var(--text-3);font-weight:500}
.sub{font-family:var(--mono);font-size:11.5px;color:var(--text-2);line-height:1.7}

/* ── Form ─── */
.campo-label{font-family:var(--mono);font-size:10px;font-weight:600;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:7px;display:block}
.url-row{display:flex;gap:8px}
.url-input{flex:1;background:var(--surface-2);border:1px solid var(--border);
  border-radius:6px;padding:12px 14px;color:var(--text);font-family:var(--mono);
  font-size:12px;outline:none;transition:border-color .15s,box-shadow .15s}
.url-input::placeholder{color:var(--text-3)}
.url-input:focus{border-color:var(--sugestao-border);
  box-shadow:0 0 0 3px rgba(75,158,255,.08)}
.btn-go{padding:12px 22px;background:var(--sugestao);color:#06090F;border:none;
  border-radius:6px;font-family:var(--mono);font-size:12px;font-weight:700;
  letter-spacing:.06em;cursor:pointer;white-space:nowrap;transition:all .15s}
.btn-go:hover{filter:brightness(1.12);box-shadow:0 0 18px rgba(75,158,255,.35)}
.btn-go:active{transform:scale(.97)}
.btn-go:disabled{opacity:.4;cursor:not-allowed}
.form-erro{display:none;margin-top:10px;padding:9px 12px;border-radius:5px;
  background:var(--bloqueante-bg);border:1px solid var(--bloqueante-border);
  color:var(--bloqueante);font-family:var(--mono);font-size:11px}
.form-erro.show{display:block}

/* Grade de agentes (tela inicial) */
.agentes-preview{margin-top:24px;border-top:1px solid var(--border);padding-top:18px}
.ag-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.ag-chip{display:flex;align-items:center;gap:7px;padding:7px 10px;border-radius:5px;
  background:var(--surface-2);border:1px solid var(--border);
  font-family:var(--mono);font-size:10.5px;color:var(--text-2);
  animation:chipIn .4s cubic-bezier(.22,1,.36,1) both}
.ag-chip .d{width:5px;height:5px;border-radius:50%;background:var(--text-3);flex-shrink:0}
@keyframes chipIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Tela de progresso ─── */
.prog-top{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
.pct{font-family:var(--mono);font-size:46px;font-weight:700;line-height:1;
  color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.pct small{font-size:20px;color:var(--text-3);font-weight:500}
.fase-label{font-family:var(--mono);font-size:11px;color:var(--sugestao);
  text-transform:uppercase;letter-spacing:.1em;text-align:right;line-height:1.6}
.fase-label .rot{display:block;color:var(--text-3);text-transform:none;letter-spacing:.02em;
  max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Barra */
.bar-wrap{margin:18px 0 4px;height:10px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:6px;overflow:hidden;position:relative}
.bar{height:100%;width:0%;border-radius:5px;position:relative;
  background:linear-gradient(90deg,#2D6FD8,var(--sugestao) 60%,#7BC4FF);
  transition:width .6s cubic-bezier(.22,1,.36,1);
  box-shadow:0 0 14px rgba(75,158,255,.45)}
.bar::after{content:'';position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);
  width:60px;animation:sheen 1.4s linear infinite;opacity:.6}
@keyframes sheen{from{transform:translateX(-70px)}to{transform:translateX(620px)}}
.bar.done{background:linear-gradient(90deg,#00935D,var(--aprovado));
  box-shadow:0 0 16px rgba(0,201,127,.5)}

/* Pipeline de passos */
.pipeline{margin-top:20px;border:1px solid var(--border);border-radius:7px;
  overflow:hidden;background:var(--surface-2)}
.passo{display:flex;align-items:center;gap:11px;padding:8px 14px;
  border-bottom:1px solid var(--border);font-family:var(--mono);font-size:11.5px;
  color:var(--text-3);transition:background .2s,color .2s}
.passo:last-child{border-bottom:none}
.passo .nome{flex:1;letter-spacing:.02em}
.passo .extra{font-size:10px;color:var(--text-3)}
.passo .st{width:18px;text-align:center;flex-shrink:0;font-size:11px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  border:1.5px solid var(--border-light);background:transparent}
.passo.rodando{color:var(--text);background:var(--sugestao-bg)}
.passo.rodando .dot{border-color:var(--sugestao);background:var(--sugestao);
  animation:dotPulse 1s ease-in-out infinite;box-shadow:0 0 8px rgba(75,158,255,.7)}
@keyframes dotPulse{0%,100%{opacity:1}50%{opacity:.3}}
.passo.ok{color:var(--text-2)}
.passo.ok .st{color:var(--aprovado)}
.passo.ok .extra{color:var(--aprovado)}
.passo.falhou .st{color:var(--bloqueante)}
.passo.falhou{color:var(--bloqueante)}
.passo.pulado{opacity:.45}
.passo.pulado .st{color:var(--text-3)}

/* Sub-grade dos 9 agentes */
.ag-sec{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--border)}
.ag-sec .passo{border-bottom:1px solid var(--border)}
.ag-sec .passo:nth-child(odd){border-right:1px solid var(--border)}
.ag-sec .passo:nth-last-child(-n+1){border-bottom:none}

/* Log ao vivo */
.log-box{margin-top:14px;background:#0A0C10;border:1px solid var(--border);
  border-radius:7px;padding:11px 14px;font-family:var(--mono);font-size:10.5px;
  line-height:1.75;color:var(--text-3);height:118px;overflow-y:auto;
  white-space:pre-wrap;word-break:break-word}
.log-box .ult{color:var(--text-2)}
.log-title{display:flex;align-items:center;gap:7px;margin-top:18px;
  font-family:var(--mono);font-size:10px;font-weight:600;color:var(--text-3);
  text-transform:uppercase;letter-spacing:.1em}
.log-title .ld{width:5px;height:5px;border-radius:50%;background:var(--aprovado);
  animation:dotPulse 1.2s ease-in-out infinite}

/* Estado final / erro */
.final-banner{display:none;margin-top:16px;padding:13px 16px;border-radius:6px;
  font-family:var(--mono);font-size:12px;line-height:1.6}
.final-banner.show{display:block}
.final-banner.ok{background:var(--aprovado-bg);border:1px solid rgba(0,201,127,.3);
  color:var(--aprovado)}
.final-banner.err{background:var(--bloqueante-bg);border:1px solid var(--bloqueante-border);
  color:var(--bloqueante)}
.final-banner a{color:inherit}
.btn-retry{margin-top:10px;padding:8px 16px;background:transparent;color:var(--text-2);
  border:1px solid var(--border);border-radius:5px;font-family:var(--mono);
  font-size:11px;cursor:pointer}
.btn-retry:hover{border-color:var(--border-light);color:var(--text)}

.rodape{margin-top:22px;font-family:var(--mono);font-size:10px;color:var(--text-3);
  letter-spacing:.04em;text-align:center;line-height:1.8}
.hide{display:none!important}
</style>
</head>
<body>
<div id="wrap">

  <!-- ── Tela inicial ── -->
  <div class="panel" id="view-inicio">
    <div class="panel-head">
      <div class="brand"><span class="pulse"></span>VIRAL MEDIA LABS<span class="sep">/</span>REVISOR DE ROTEIROS</div>
      <h1>Revisão na Tabela Interativa<br><span class="thin">direto do seu Google Docs.</span></h1>
      <div class="sub">9 agentes especializados analisam o roteiro em paralelo.<br>
      Você revisa achado por achado e grava as correções no Doc original.</div>
    </div>
    <div class="panel-body">
      <label class="campo-label" for="url">URL do Google Docs</label>
      <div class="url-row">
        <input class="url-input" id="url" type="url" autofocus spellcheck="false"
          placeholder="https://docs.google.com/document/d/…"
          onkeydown="if(event.key==='Enter')iniciar()">
        <button class="btn-go" id="btn-go" onclick="iniciar()">INICIAR →</button>
      </div>
      <div class="form-erro" id="form-erro"></div>

      <div class="agentes-preview">
        <span class="campo-label">Pipeline de análise</span>
        <div class="ag-grid" id="ag-grid"></div>
      </div>
    </div>
  </div>

  <!-- ── Tela de progresso ── -->
  <div class="panel hide" id="view-prog">
    <div class="panel-head">
      <div class="brand"><span class="pulse"></span>VIRAL MEDIA LABS<span class="sep">/</span>REVISOR — ANÁLISE EM ANDAMENTO</div>
      <div class="prog-top">
        <div class="pct" id="pct">0<small>%</small></div>
        <div class="fase-label"><span id="fase-txt">Iniciando…</span>
          <span class="rot" id="rot-txt"></span></div>
      </div>
    </div>
    <div class="panel-body" style="padding-top:0">
      <div class="bar-wrap"><div class="bar" id="bar"></div></div>

      <div class="pipeline" id="pipeline">
        <div class="passo" data-passo="base"><span class="st"><span class="dot"></span></span>
          <span class="nome">Base de conhecimento</span><span class="extra">playbooks + CODEX</span></div>
        <div class="passo" data-passo="doc"><span class="st"><span class="dot"></span></span>
          <span class="nome">Leitura do Google Docs</span><span class="extra">roteiros do documento</span></div>
        <div class="passo" data-passo="contexto"><span class="st"><span class="dot"></span></span>
          <span class="nome">Contexto narrativo</span><span class="extra">estrutura CODEX</span></div>
        <div class="ag-sec" id="ag-sec"></div>
        <div class="passo" data-passo="consolidando"><span class="st"><span class="dot"></span></span>
          <span class="nome">Consolidação</span><span class="extra">dedup + veredicto</span></div>
        <div class="passo" data-passo="tabela"><span class="st"><span class="dot"></span></span>
          <span class="nome">Tabela Interativa</span><span class="extra">abre nesta aba</span></div>
      </div>

      <div class="log-title"><span class="ld"></span>Saída do sistema — ao vivo</div>
      <div class="log-box" id="log-box"></div>

      <div class="final-banner" id="banner"></div>
    </div>
  </div>

  <div class="rodape" id="rodape">As correções aprovadas são gravadas no Google Doc original.<br>
  Histórico de versões do Doc permite reverter qualquer mudança.</div>
</div>

<script>
const AGENTES=[
  {k:'ortografia',  n:'Ortografia',      d:'gramática PT-BR'},
  {k:'clareza',     n:'Clareza/Ritmo',   d:'locução'},
  {k:'coerencia',   n:'Coerência',       d:'lógica + sentimento'},
  {k:'checklist',   n:'Checklist',       d:'critérios VML'},
  {k:'storytelling',n:'Storytelling',    d:'estruturas CODEX'},
  {k:'factcheck',   n:'Fact-check',      d:'fatos e dados'},
  {k:'hook',        n:'Hook',            d:'primeiros segundos'},
  {k:'viral',       n:'Potencial Viral', d:'narrativas'},
  {k:'cta',         n:'CTA',             d:'comando final'},
];
const FASES={
  iniciando:'Iniciando pipeline', base:'Carregando playbooks',
  doc:'Lendo o Google Docs', contexto:'Extraindo contexto narrativo',
  agentes:'9 agentes em paralelo', consolidando:'Consolidando achados',
  pronto:'Tabela pronta', encerrado:'Sessão encerrada', erro:'Erro'
};
const $=id=>document.getElementById(id);

// Grade de chips da tela inicial (com stagger)
$('ag-grid').innerHTML=AGENTES.map((a,i)=>
  `<div class="ag-chip" style="animation-delay:${i*45}ms"><span class="d"></span>${a.n}</div>`).join('');

// Linhas dos 9 agentes na pipeline
$('ag-sec').innerHTML=AGENTES.map(a=>
  `<div class="passo" data-ag="${a.k}"><span class="st"><span class="dot"></span></span>
   <span class="nome">${a.n}</span><span class="extra" id="ex-${a.k}">${a.d}</span></div>`).join('');

// ?nova=1 — usuário voltou da tabela pelo botão ⟳ Nova Revisão: mostrar o
// formulário limpo em vez de redirecionar de volta à tabela da sessão anterior.
const NOVA=new URLSearchParams(location.search).has('nova');
let polling=null, redirecionando=false, iniciadaNestaPagina=false;

async function iniciar(){
  const url=$('url').value.trim(), err=$('form-erro');
  err.classList.remove('show');
  if(!url.includes('docs.google.com/document')){
    err.textContent='Cole um link válido do Google Docs (docs.google.com/document/d/…).';
    err.classList.add('show');return;
  }
  $('btn-go').disabled=true;
  try{
    const r=await fetch('/api/iniciar',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const j=await r.json();
    if(!r.ok){err.textContent=j.error||'Erro ao iniciar.';err.classList.add('show');
      $('btn-go').disabled=false;return;}
    iniciadaNestaPagina=true;redirecionando=false;
    mostrarProgresso();
  }catch(e){
    err.textContent='Servidor local indisponível. Verifique a janela do terminal.';
    err.classList.add('show');$('btn-go').disabled=false;
  }
}

function mostrarProgresso(){
  $('view-inicio').classList.add('hide');
  $('view-prog').classList.remove('hide');
  $('rodape').textContent='Mantenha a janela do terminal aberta — a saída completa aparece lá.';
  if(!polling)polling=setInterval(poll,650);
  poll();
}

function setPasso(el,estado){
  el.classList.remove('rodando','ok','falhou','pulado');
  if(estado)el.classList.add(estado);
  const st=el.querySelector('.st');
  if(estado==='ok')st.textContent='✓';
  else if(estado==='falhou')st.textContent='✕';
  else if(estado==='pulado')st.textContent='—';
  else st.innerHTML='<span class="dot"></span>';
}

async function poll(){
  let s;
  try{const r=await fetch('/api/status');s=await r.json();}catch(e){return;}
  if(s.fase==='ocioso')return;

  // % e barra
  $('pct').innerHTML=s.pct+'<small>%</small>';
  const bar=$('bar');bar.style.width=s.pct+'%';
  bar.classList.toggle('done',s.fase==='pronto'||s.fase==='encerrado');

  // Fase + roteiro atual
  $('fase-txt').textContent=FASES[s.fase]||s.fase;
  $('rot-txt').textContent=s.roteiro&&s.roteiro.total
    ?`Roteiro ${s.roteiro.num||1}/${s.roteiro.total}${s.roteiro.titulo?' — '+s.roteiro.titulo:''}`:'';

  // Passos fixos
  const ordem=['base','doc','contexto'];
  const idx={iniciando:-1,base:0,doc:1,contexto:2,agentes:3,consolidando:3,pronto:3,encerrado:3}[s.fase]??3;
  ordem.forEach((p,i)=>{
    const el=document.querySelector(`[data-passo="${p}"]`);
    if(p==='contexto'){
      setPasso(el,s.contexto==='rodando'?'rodando':s.contexto==='ok'||idx>2?'ok':i<idx?'ok':i===idx?'rodando':null);
    }else setPasso(el,i<idx?'ok':i===idx?'rodando':null);
  });

  // Agentes
  AGENTES.forEach(a=>{
    const el=document.querySelector(`[data-ag="${a.k}"]`);
    const st=s.agentes[a.k];
    setPasso(el,st==='pendente'?null:st);
    const ex=$('ex-'+a.k);
    if(st==='ok')ex.textContent=(s.achados[a.k]??0)+' achado(s)';
    else if(st==='pulado')ex.textContent='pulado — nada a verificar';
    else if(st==='falhou')ex.textContent='falhou';
    else ex.textContent=a.d;
  });

  // Consolidação + tabela
  setPasso(document.querySelector('[data-passo="consolidando"]'),
    s.fase==='consolidando'?'rodando':(s.fase==='pronto'||s.fase==='encerrado')?'ok':null);
  setPasso(document.querySelector('[data-passo="tabela"]'),
    s.fase==='pronto'||s.fase==='encerrado'?'ok':null);

  // Log ao vivo
  const lb=$('log-box');
  lb.innerHTML=s.log.map((l,i)=>i===s.log.length-1?`<span class="ult">› ${esc(l)}</span>`:`  ${esc(l)}`).join('\n');
  lb.scrollTop=lb.scrollHeight;

  // Final: redirect para a Tabela Interativa
  // (com ?nova=1, só redireciona se a revisão foi iniciada nesta página —
  //  a tabela 'pronta' da sessão anterior não deve puxar o usuário de volta)
  if(s.fase==='pronto'&&s.tabela_url&&!redirecionando&&(!NOVA||iniciadaNestaPagina)){
    redirecionando=true;clearInterval(polling);
    const b=$('banner');b.className='final-banner ok show';
    b.innerHTML='✓ Análise concluída — abrindo a Tabela Interativa…';
    setTimeout(()=>{window.location.href=s.tabela_url;},1100);
  }
  if(s.fase==='erro'){
    clearInterval(polling);polling=null;
    const b=$('banner');b.className='final-banner err show';
    b.innerHTML='✕ '+esc(s.erro||'O pipeline terminou com erro. Veja o terminal.')+
      '<br><button class="btn-retry" onclick="location.reload()">← Tentar novamente</button>';
  }
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// Se já existe revisão em andamento (reload da página), retoma a tela de progresso.
// Exceção: ?nova=1 com tabela já servida — o usuário voltou para revisar outro Doc.
fetch('/api/status').then(r=>r.json()).then(s=>{
  const servida=s.fase==='pronto'&&s.tabela_url;
  if(NOVA&&servida)return;
  if(s.fase&&s.fase!=='ocioso'&&s.fase!=='encerrado'){iniciadaNestaPagina=true;mostrarProgresso();}
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
