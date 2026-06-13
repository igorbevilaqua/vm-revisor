#!/usr/bin/env python3
"""
Sincronização automática dos aprendizados via git — Viral Media Labs.

Vários revisores usam o sistema em máquinas diferentes. O conhecimento
compartilhado vive no `aprendizados.jsonl` (versionado, append-only, merge=union).
Para o aprendizado de um chegar aos outros sem ninguém precisar rodar git na mão:

  - ao SALVAR aprendizados → commit + pull + push do aprendizados.jsonl (background);
  - ao INICIAR uma revisão  → pull, para já injetar o que os outros aprenderam.

Princípios:
  - BEST-EFFORT: qualquer falha (sem rede, sem credencial, working tree sujo) é
    engolida — nunca derruba a revisão. O commit local persiste e sincroniza depois.
  - CIRÚRGICO: só faz stage/commit do(s) arquivo(s) alvo (nunca `git add -A`) —
    não toca em código, config.txt nem em nada que o usuário tenha local.
  - SEM TRAVAR: GIT_TERMINAL_PROMPT=0 faz o git falhar na hora se faltar credencial,
    em vez de pendurar esperando senha; e a escrita roda em thread de background.

Desligar: variável de ambiente VML_NO_GIT_SYNC=1.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

RAIZ = Path(__file__).parent
ARQ_PADRAO = ["aprendizados.jsonl"]

# Serializa as operações de escrita git (add/commit/pull/push). Sem isto, dois
# enviar() concorrentes (ex.: /salvar e logo /promover na janela) colidem no
# .git/index.lock e um dos commits é engolido silenciosamente.
import threading as _threading
_sync_lock = _threading.Lock()


def _env():
    # Nunca abrir prompt interativo de credencial (travaria o servidor).
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _git(*args, timeout=90):
    return subprocess.run(
        ["git", *args], cwd=RAIZ, env=_env(),
        capture_output=True, text=True, timeout=timeout,
    )


def _ligado() -> bool:
    if os.environ.get("VML_NO_GIT_SYNC"):
        return False
    if not (RAIZ / ".git").exists():
        return False
    try:
        r = _git("remote", timeout=10)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def puxar(timeout: int = 25) -> bool:
    """Pull best-effort, para receber os aprendizados dos outros antes de revisar.
    Síncrono e rápido (timeout curto): se a rede travar, segue sem bloquear."""
    try:
        if not _ligado():
            return False
        r = _git("pull", "--no-rebase", "--no-edit", timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def _enviar(arquivos: list[str], mensagem: str):
    # Lock serializa commits concorrentes no mesmo repo (evita colisão de index.lock)
    with _sync_lock:
        _enviar_locked(arquivos, mensagem)


def _enviar_locked(arquivos: list[str], mensagem: str):
    try:
        if not _ligado():
            return
        if _git("add", "--", *arquivos).returncode != 0:
            return
        # Há algo de fato staged nesses arquivos? (--quiet: 0 = sem diff)
        if _git("diff", "--cached", "--quiet", "--", *arquivos).returncode == 0:
            puxar()  # nada novo a enviar, mas aproveita para receber dos outros
            return
        _git("commit", "-m", mensagem)
        # Integra o remoto (merge=union junta o .jsonl) e envia. 1 retry cobre o
        # caso de alguém ter pushado no meio do caminho.
        for _ in range(2):
            puxar(timeout=90)
            if _git("push", timeout=90).returncode == 0:
                return
    except Exception:
        pass  # commit local (se houve) persiste — sincroniza na próxima


def enviar(arquivos: list[str] | None = None, mensagem: str = "aprendizados: sync automático",
           em_background: bool = True):
    """Commit + pull + push dos arquivos de aprendizado. Em background por padrão
    (não trava a resposta HTTP nem a interface)."""
    arquivos = arquivos or ARQ_PADRAO
    if em_background:
        threading.Thread(target=_enviar, args=(arquivos, mensagem), daemon=True).start()
    else:
        _enviar(arquivos, mensagem)
