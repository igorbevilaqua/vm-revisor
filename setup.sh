#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Setup do Revisor de Roteiros — Viral Media Labs
#  Execute uma vez antes de usar o sistema
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Para imediatamente se qualquer comando falhar

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Configurando Revisor de Roteiros — Viral Media Labs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Verifica Python ────────────────────────────────────────────────────────
echo "▶ Verificando Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado."
    echo "   Instale em: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "   ✅ Python $PYTHON_VERSION encontrado"

# ── 2. Instala dependências ───────────────────────────────────────────────────
echo ""
echo "▶ Instalando dependências Python..."
pip3 install -r requirements.txt --quiet
echo "   ✅ anthropic instalado"
echo "   ✅ pdfplumber instalado"

# ── 3. Verifica ANTHROPIC_API_KEY ─────────────────────────────────────────────
echo ""
echo "▶ Verificando API key da Anthropic..."

if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "   ✅ ANTHROPIC_API_KEY encontrada nas variáveis de ambiente"
else
    echo ""
    echo "   ⚠️  ANTHROPIC_API_KEY não encontrada."
    echo ""
    echo "   Você precisa configurar sua API key. Escolha uma opção:"
    echo ""
    echo "   OPÇÃO A — Temporária (só para esta sessão do terminal):"
    echo "   export ANTHROPIC_API_KEY='sua-chave-aqui'"
    echo ""
    echo "   OPÇÃO B — Permanente (recomendado):"
    echo "   Adicione esta linha ao seu ~/.zshrc:"
    echo "   export ANTHROPIC_API_KEY='sua-chave-aqui'"
    echo "   Depois execute: source ~/.zshrc"
    echo ""
    echo "   Sua API key está em: https://console.anthropic.com/settings/keys"
    echo ""
    
    # Pergunta se quer configurar agora
    read -p "   Deseja colar sua API key agora? (s/n): " resposta
    if [[ "$resposta" =~ ^[Ss]$ ]]; then
        read -s -p "   Cole sua API key (não aparecerá na tela): " api_key
        echo ""
        
        if [ -n "$api_key" ]; then
            export ANTHROPIC_API_KEY="$api_key"
            
            # Adiciona ao .zshrc para ser permanente
            ZSHRC="$HOME/.zshrc"
            if grep -q "ANTHROPIC_API_KEY" "$ZSHRC" 2>/dev/null; then
                echo "   ℹ️  Chave já existe no .zshrc — atualizando..."
                sed -i '' "s/export ANTHROPIC_API_KEY=.*/export ANTHROPIC_API_KEY='$api_key'/" "$ZSHRC"
            else
                echo "" >> "$ZSHRC"
                echo "# Anthropic API Key — Revisor VML" >> "$ZSHRC"
                echo "export ANTHROPIC_API_KEY='$api_key'" >> "$ZSHRC"
            fi
            
            echo "   ✅ API key configurada e salva no ~/.zshrc"
        fi
    fi
fi

# ── 4. Verifica estrutura de pastas ───────────────────────────────────────────
echo ""
echo "▶ Verificando estrutura de pastas..."
mkdir -p pdfs roteiros relatorios
echo "   ✅ Pastas pdfs/, roteiros/, relatorios/ prontas"

# ── 5. Verifica PDFs ──────────────────────────────────────────────────────────
echo ""
echo "▶ Verificando PDFs..."
PDFS_ENCONTRADOS=0

for nome in "checklist.pdf" "storytelling.pdf" "hooks.pdf" "cta.pdf"; do
    if [ -f "pdfs/$nome" ]; then
        echo "   ✅ pdfs/$nome encontrado"
        PDFS_ENCONTRADOS=$((PDFS_ENCONTRADOS + 1))
    else
        echo "   ⚠️  pdfs/$nome NÃO encontrado"
    fi
done

if [ $PDFS_ENCONTRADOS -eq 0 ]; then
    echo ""
    echo "   ℹ️  Nenhum PDF encontrado. O sistema funcionará com critérios padrão."
    echo "   Para adicionar seus PDFs:"
    echo "   - Copie checklist.pdf para a pasta pdfs/"
    echo "   - Copie storytelling.pdf (ou playbook.pdf) para a pasta pdfs/"
    echo "   - Copie hooks.pdf para a pasta pdfs/
   - Copie cta.pdf para a pasta pdfs/"
fi

# ── 6. Teste rápido ───────────────────────────────────────────────────────────
echo ""
echo "▶ Fazendo teste de importação..."
python3 -c "
import anthropic
import pdfplumber
print('   ✅ Todas as dependências importadas com sucesso')
" 2>&1

# ── 7. Conclusão ──────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Setup concluído!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  COMO USAR:"
echo ""
echo "  1. Revisar roteiro no modo interativo (cole o texto):"
echo "     python3 revisar.py"
echo ""
echo "  2. Revisar um arquivo com múltiplos roteiros:"
echo "     python3 revisar.py --arquivo roteiros/meu_arquivo.txt"
echo ""
echo "  3. Testar com os roteiros de exemplo:"
echo "     python3 revisar.py --arquivo roteiros/exemplo.txt"
echo ""
echo "  Os relatórios são salvos automaticamente em relatorios/"
echo ""
