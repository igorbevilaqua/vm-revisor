"""
terminal.py — compatibilidade de encoding e emojis entre Mac e Windows.

Uso (nos entry points, antes de qualquer print):
    from terminal import patch_stdout
    patch_stdout()

No resto do código, prints normais funcionam em qualquer OS.
Em Windows clássico (sem WT_SESSION), emojis são substituídos por texto legível.
"""

import builtins
import io
import os
import platform
import sys


# ─── Detecção de ambiente ────────────────────────────────────────────────────

def _eh_windows() -> bool:
    return platform.system() == "Windows"

def _suporta_emoji() -> bool:
    if _eh_windows():
        # Windows Terminal moderno e VSCode terminal suportam emoji
        return "WT_SESSION" in os.environ or "TERM_PROGRAM" in os.environ
    return True  # Mac e Linux: sempre suporta


# ─── Mapa emoji → texto legível ──────────────────────────────────────────────

_MAPA_EMOJI = {
    "✅": "[OK]",
    "❌": "[ERRO]",
    "⚠️": "[AVISO]",
    "⚠":  "[AVISO]",
    "ℹ️": "[i]",
    "ℹ":  "[i]",
    "📄": "[DOC]",
    "📚": "[BASE]",
    "🤖": "[AGENTE]",
    "💾": "[SALVO]",
    "📋": "[REL]",
    "👤": "[USER]",
    "🔗": "[LINK]",
    "🔍": "[BUSCA]",
    "🧠": "[APRENDER]",
    "🎬": "[CENA]",
    "🌐": "[WEB]",
    "📁": "[PASTA]",
    "🧩": "[PECA]",
    "⛔": "[BLOQ]",
    "✨": "[OPC]",
    "🎉": "[FIM]",
    "⏭":  "[PROX]",
    # Caracteres de caixa que cp1252 nao suporta
    "═": "=",
    "─": "-",
    "━": "-",
    "→": "->",
    "↪": "->",
    "«": '"',
    "»": '"',
}


def _sanitizar(texto: str) -> str:
    for emoji, substituto in _MAPA_EMOJI.items():
        texto = texto.replace(emoji, substituto)
    return texto


# ─── Patch principal ─────────────────────────────────────────────────────────

_patch_aplicado = False

def patch_stdout():
    """Aplica o patch de encoding e emoji. Chamar uma vez no inicio de cada entry point."""
    global _patch_aplicado
    if _patch_aplicado:
        return
    _patch_aplicado = True

    if not _eh_windows():
        return  # Mac/Linux: nada a fazer

    # 1. Força UTF-8 no stdout/stderr para nao quebrar com UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    # 2. Em Windows classico (sem suporte a emoji), substitui emojis por texto legivel
    if not _suporta_emoji():
        _orig_print = builtins.print

        def _print_seguro(*args, **kwargs):
            args_limpos = [_sanitizar(a) if isinstance(a, str) else a for a in args]
            _orig_print(*args_limpos, **kwargs)

        builtins.print = _print_seguro


# ─── Utilitario opcional: sym() para quem quiser usar explicitamente ─────────

_SIMBOLOS = {
    "ok":       ("✅",  "[OK]"),
    "erro":     ("❌",  "[ERRO]"),
    "aviso":    ("⚠️",  "[AVISO]"),
    "info":     ("ℹ️",  "[i]"),
    "doc":      ("📄",  "[DOC]"),
    "base":     ("📚",  "[BASE]"),
    "agente":   ("🤖",  "[AGENTE]"),
    "rel":      ("📋",  "[REL]"),
    "usuario":  ("👤",  "[USER]"),
    "link":     ("🔗",  "[LINK]"),
    "busca":    ("🔍",  "[BUSCA]"),
    "cerebro":  ("🧠",  "[APRENDER]"),
    "bloquear": ("⛔",  "[BLOQ]"),
    "opcional": ("✨",  "[OPC]"),
    "fim":      ("🎉",  "[FIM]"),
}

def sym(chave: str) -> str:
    """Retorna emoji ou texto conforme o terminal suportar."""
    emoji, texto = _SIMBOLOS.get(chave, ("?", f"[{chave.upper()}]"))
    return emoji if _suporta_emoji() else texto
