"""
Integração com Google Docs — Viral Media Labs
Lê um documento Google Docs a partir do link e extrai os roteiros.

Uso:
    python google_docs.py https://docs.google.com/document/d/SEU_ID/edit
"""

import os
import re
import sys
import json
import pickle
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

# Escopos necessários (somente leitura)
SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CREDENTIALS_PATH = Path(__file__).parent / "credentials" / "client_secret.json"
TOKEN_PATH       = Path(__file__).parent / "credentials" / "token.pickle"


# ─── Autenticação ────────────────────────────────────────────────────────────

def autenticar(scopes=None, token_path=None):
    """
    Autentica com o Google OAuth2.
    - Primeira vez: abre o navegador para autorizar
    - Próximas vezes: usa o token salvo

    scopes/token_path permitem reaproveitar a função para escrita (writeback):
    leitura usa SCOPES + token.pickle; escrita usa escopos amplos + token_write.pickle.
    """
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = scopes or SCOPES
    token_path = token_path or TOKEN_PATH
    creds = None

    # Tenta carregar token salvo
    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    # Se não tem token válido, faz o fluxo OAuth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                print(f"\n❌ Arquivo de credenciais não encontrado em:")
                print(f"   {CREDENTIALS_PATH}")
                print(f"\n   Coloque o client_secret.json baixado do Google Cloud em:")
                print(f"   {CREDENTIALS_PATH.parent}/")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), scopes
            )
            print("\n🌐 Abrindo navegador para autorizar acesso ao Google Docs...")
            print("   (isso só acontece uma vez por nível de permissão)\n")
            creds = flow.run_local_server(port=0)

        # Salva o token para próximas vezes
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        print("✅ Autorização salva — próximas vezes será automático\n")

    return creds


# ─── Extração do nome do cliente a partir do título ──────────────────────────

# Palavras de "ruído" que aparecem em títulos mas não são o nome do cliente.
_RUIDO_TITULO = {
    "roteiro", "roteiros", "script", "scripts", "reel", "reels", "video", "vídeo",
    "vml", "viral", "media", "labs", "semana", "week", "mes", "mês", "final",
    "rascunho", "draft", "revisao", "revisão", "copy", "doc", "documento", "de", "do",
    "da", "para", "v1", "v2", "v3",
    # rótulos que às vezes aparecem no título antes do nome
    "cliente", "canal", "criador", "criadora", "apresentador", "apresentadora",
    "locutor", "locutora", "perfil", "voz", "talento", "tema", "titulo", "título",
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez",
    "janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
}


def extrair_cliente_do_titulo(titulo: str):
    """Extrai o nome do cliente/criador do título do documento (1 cliente por doc).
    Conservador: se não houver candidato com cara de nome próprio, retorna None
    (o agente usa [nome do cliente] em vez de chutar)."""
    if not titulo:
        return None
    segmentos = re.split(r"[-–—|:/•]+", titulo)
    for seg in segmentos:
        tokens = []
        for w in seg.split():
            wl = w.lower().strip(".,()[]")
            if re.fullmatch(r"\d{1,4}", wl) or wl in _RUIDO_TITULO:
                continue
            tokens.append(w.strip())
        candidato = " ".join(tokens).strip()
        # Cara de nome próprio: 1 a 4 palavras, começa com maiúscula.
        if candidato and 1 <= len(candidato.split()) <= 4 and candidato[:1].isupper():
            return candidato[:60]
    return None


# ─── Extração do ID do documento ─────────────────────────────────────────────

def extrair_doc_id(url_ou_id: str) -> str:
    """
    Aceita tanto o link completo quanto só o ID do documento.
    https://docs.google.com/document/d/DOCID/edit  →  DOCID
    """
    # Padrão do link do Google Docs
    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url_ou_id)
    if match:
        return match.group(1)

    # Se não tem barra, assume que já é o ID direto
    if "/" not in url_ou_id and len(url_ou_id) > 10:
        return url_ou_id.strip()

    raise ValueError(f"Não foi possível extrair o ID do documento de: {url_ou_id}")


# ─── Leitura do documento ────────────────────────────────────────────────────

def ler_documento(doc_id: str, creds) -> str:
    """
    Lê o conteúdo completo do Google Doc e retorna como texto puro.
    Preserva a estrutura de títulos para que a separação de roteiros funcione.
    """
    from googleapiclient.discovery import build

    service = build("docs", "v1", credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()

    titulo_doc = doc.get("title", "Documento sem título")
    print(f"📄 Documento: {titulo_doc}")

    linhas = []
    body = doc.get("body", {})
    conteudo = body.get("content", [])

    for elemento in conteudo:
        paragrafo = elemento.get("paragraph")
        if not paragrafo:
            continue

        # Extrai estilo do parágrafo (Heading1, Heading2, Normal, etc.)
        estilo = paragrafo.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")

        # Extrai texto de todos os runs do parágrafo
        texto_partes = []
        for run in paragrafo.get("elements", []):
            texto_run = run.get("textRun", {}).get("content", "")
            texto_partes.append(texto_run)

        texto = "".join(texto_partes).rstrip("\n")

        if not texto.strip():
            linhas.append("")
            continue

        # Títulos viram marcadores explícitos para facilitar a separação
        if estilo in ("HEADING_1", "HEADING_2"):
            linhas.append(f"\n### {texto}")
        elif estilo == "HEADING_3":
            linhas.append(f"\n## {texto}")
        else:
            linhas.append(texto)

    return titulo_doc, "\n".join(linhas)


# ─── Separação de roteiros ───────────────────────────────────────────────────

def separar_roteiros_gdoc(texto: str) -> list[dict]:
    """
    Separa roteiros de um Google Doc com detecção inteligente de 3 formatos:

    1. Títulos formatados (Heading 1/2 no Docs) → marcados como ### no texto
    2. Padrão textual "Roteiro N:" ou "Roteiro N —" no início de uma linha
    3. Separadores explícitos (---, ***)

    Retorna lista de dicts: {numero, titulo, texto}
    """

    # ── Estratégia 1: Títulos formatados (Heading 1/2) ──────────────────────
    if "\n### " in texto:
        partes = re.split(r"\n### ", texto)
        partes = [p.strip() for p in partes if p.strip()]
        roteiros = []
        for i, parte in enumerate(partes, 1):
            linhas = parte.splitlines()
            titulo = linhas[0].strip() if linhas else f"Roteiro {i}"
            corpo  = "\n".join(linhas[1:]).strip()
            if corpo:
                roteiros.append({"numero": i, "titulo": titulo, "texto": corpo})
        if roteiros:
            return roteiros

    # ── Estratégia 2: Padrão "Roteiro N:" ou "Roteiro N —" ──────────────────
    # Detecta linhas como: "Roteiro 1: Título aqui" ou "Roteiro 2 — Título"
    padrao_roteiro = re.compile(
        r"(?m)^(Roteiro\s+\d+\s*[:–—-]+\s*.+)$"
    )
    matches = list(padrao_roteiro.finditer(texto))

    if matches:
        roteiros = []
        for i, match in enumerate(matches):
            titulo = match.group(1).strip()
            inicio = match.end()
            fim    = matches[i + 1].start() if i + 1 < len(matches) else len(texto)
            corpo  = texto[inicio:fim].strip()
            # Remove linhas de fontes/links do final do roteiro
            linhas_corpo = []
            em_fontes = False
            for linha in corpo.splitlines():
                if re.match(r"^(Fontes?|Fonte|Sources?)\s*:?\s*$", linha, re.IGNORECASE):
                    em_fontes = True
                if not em_fontes:
                    linhas_corpo.append(linha)
            corpo = "\n".join(linhas_corpo).strip()
            if corpo:
                roteiros.append({"numero": i + 1, "titulo": titulo, "texto": corpo})
        if roteiros:
            return roteiros

    # ── Estratégia 3: Separadores explícitos (--- ou ***) ───────────────────
    partes = re.split(r"(?m)^[-*]{3,}\s*$", texto)
    partes = [p.strip() for p in partes if p.strip()]
    if len(partes) > 1:
        roteiros = []
        for i, parte in enumerate(partes, 1):
            linhas = [l for l in parte.splitlines() if l.strip()]
            titulo = linhas[0][:80] if linhas else f"Roteiro {i}"
            corpo  = "\n".join(parte.splitlines()[1:]).strip()
            if corpo:
                roteiros.append({"numero": i, "titulo": titulo, "texto": corpo})
        if roteiros:
            return roteiros

    # ── Fallback: documento inteiro como roteiro único ───────────────────────
    linhas = [l for l in texto.splitlines() if l.strip()]
    titulo = linhas[0][:80] if linhas else "Roteiro"
    return [{"numero": 1, "titulo": titulo, "texto": texto}]


# ─── Função principal ────────────────────────────────────────────────────────

def carregar_roteiros_do_gdoc(url: str) -> list[dict]:
    """
    Função principal chamada pelo revisar.py.
    Recebe o link do Google Doc e retorna lista de roteiros separados.
    """
    doc_id = extrair_doc_id(url)
    creds  = autenticar()
    titulo_doc, texto = ler_documento(doc_id, creds)
    roteiros = separar_roteiros_gdoc(texto)

    # 1 cliente por documento — o nome geralmente está no título do doc.
    cliente = extrair_cliente_do_titulo(titulo_doc)
    for r in roteiros:
        r["cliente"] = cliente
        # O heading do roteiro É a headline (texto de tela). Remove o prefixo "Roteiro N:".
        r["headline"] = re.sub(
            r"^\s*roteiro\s*\d+\s*[:\-–—.]*\s*", "", r["titulo"], flags=re.IGNORECASE
        ).strip()

    print(f"✅ {len(roteiros)} roteiro(s) encontrado(s) no documento")
    if cliente:
        print(f"   👤 Cliente/criador (do título): {cliente}")
    else:
        print(f"   👤 Cliente não identificado no título — use --cliente se quiser definir")
    print()
    for r in roteiros:
        preview = r["texto"][:60].replace("\n", " ")
        print(f"   {r['numero']}. {r['titulo'][:50]}")
        print(f"      \"{preview}...\"")

    return roteiros


# ─── Execução direta (teste) ─────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python google_docs.py <link_ou_id_do_doc>")
        print("Ex:  python google_docs.py https://docs.google.com/document/d/ABC123/edit")
        sys.exit(1)

    url = sys.argv[1]
    print(f"\n🔗 Lendo documento: {url}\n")

    roteiros = carregar_roteiros_do_gdoc(url)

    print(f"\n{'='*50}")
    print(f"Total de roteiros encontrados: {len(roteiros)}")
    print(f"{'='*50}")
    for r in roteiros:
        print(f"\nRoteiro {r['numero']}: {r['titulo']}")
        print(f"Tamanho: {len(r['texto'])} caracteres")
        print(f"Preview: {r['texto'][:100]}...")
