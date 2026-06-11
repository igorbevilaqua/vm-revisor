#!/bin/bash
# Revisor de Roteiros — Viral Media Labs (Mac)
# Duplo clique no Finder abre a interface gráfica no navegador.
cd "$(dirname "$0")"

echo "============================================"
echo " Revisor de Roteiros — Viral Media Labs"
echo "============================================"
echo ""

# ── API key: ambiente → config.txt → ~/.zshrc ────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f config.txt ]; then
    KEY=$(grep -E '^\s*ANTHROPIC_API_KEY\s*=' config.txt | head -1 | cut -d= -f2- | tr -d ' "'"'")
    if [ -n "$KEY" ] && [ "$KEY" != "cole-sua-chave-aqui" ]; then
        export ANTHROPIC_API_KEY="$KEY"
    fi
fi
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "$HOME/.zshrc" ]; then
    KEY=$(grep -E '^\s*export ANTHROPIC_API_KEY=' "$HOME/.zshrc" | tail -1 | cut -d= -f2- | tr -d ' "'"'")
    [ -n "$KEY" ] && export ANTHROPIC_API_KEY="$KEY"
fi
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ANTHROPIC_API_KEY não encontrada."
    echo "   Configure no config.txt (ANTHROPIC_API_KEY=sua-chave)"
    echo "   ou no ~/.zshrc (export ANTHROPIC_API_KEY='sua-chave')."
    echo ""
    read -p "Pressione Enter para fechar..."
    exit 1
fi

echo "Abrindo a interface no navegador..."
echo "(mantenha esta janela aberta durante a revisão)"
echo ""

python3 interface.py

echo ""
read -p "Pressione Enter para fechar..."
