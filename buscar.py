import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------
# CONFIGURAÇÃO (pode editar)
# ---------------------------------------------------------------

# Canais públicos de promoções do Telegram (nome do canal, sem @).
# Para adicionar outro: abra o canal, veja o link t.me/NOME e coloque NOME aqui.
CANAIS = [
    "achadosdotb",
]

# Só avisa sobre produtos que contenham alguma destas palavras.
PRODUTOS_GAMER = [
    "rtx", "gtx", "geforce", "radeon", "rx 6", "rx 7", "rx 9", "ryzen",
    "intel core", "placa de video", "processador", "ssd", "nvme",
    "memoria ram", "ddr4", "ddr5", "placa mae", "gabinete",
    "fonte 650", "fonte 750", "fonte 850", "water cooler",
    "monitor gamer", "monitor 144", "monitor 165", "monitor 240",
    "headset", "mouse gamer", "teclado mecanico", "teclado gamer",
    "playstation", "ps5", "ps4", "xbox", "nintendo", "switch",
    "steam deck", "controle", "dualsense", "notebook gamer",
    "cadeira gamer", "gamer",
]

# Palavras que sugerem erro de preço.
SINAIS_DE_BUG = [
    "bug", "bugou", "bugado", "erro de preco", "preco errado",
    "corre", "corra", "pode cancelar", "precificacao",
]

# Desconto mínimo (em %) para avisar mesmo sem a palavra "bug".
DESCONTO_MINIMO = 60

# Máximo de alertas por execução (evita enxurrada).
MAX_ALERTAS = 10

ARQUIVO_ESTADO = Path("estado.json")


# ---------------------------------------------------------------
# FUNÇÕES
# ---------------------------------------------------------------

def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def baixar(canal):
    url = f"https://t.me/s/{canal}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def ler_mensagens(pagina):
    """Devolve lista de (id, texto, [links]) das mensagens da página."""
    saida = []
    for bloco in re.split(r'(?=<div class="tgme_widget_message_wrap)', pagina):
        post = re.search(r'data-post="[^"/]+/(\d+)"', bloco)
        corpo = re.search(
            r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', bloco, re.S
        )
        if not post or not corpo:
            continue
        bruto = corpo.group(1)
        links = re.findall(r'href="(https?://[^"]+)"', bruto)
        texto = re.sub(r"<br\s*/?>", "\n", bruto)
        texto = html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()
        saida.append((int(post.group(1)), texto, links))
    return saida


def numero_br(txt):
    try:
        return float(txt.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def analisar(texto):
    """Devolve o motivo do alerta, ou None se não for interessante."""
    t = normalizar(texto)

    if not any(p in t for p in PRODUTOS_GAMER):
        return None

    for s in SINAIS_DE_BUG:
        if re.search(rf"\b{re.escape(s)}\w*", t):
            return f"palavra '{s}' no anúncio"

    for m in re.finditer(r"(\d{2,3})\s?%\s?(?:off|de desconto|desc)", t):
        if int(m.group(1)) >= DESCONTO_MINIMO:
            return f"{m.group(1)}% de desconto"

    m = re.search(r"de\s+r\$\s*([\d\.,]+)\s+por\s+r\$\s*([\d\.,]+)", t)
    if m:
        antigo, novo = numero_br(m.group(1)), numero_br(m.group(2))
        if antigo and novo and novo <= antigo * (1 - DESCONTO_MINIMO / 100):
            return f"de R$ {antigo:.0f} por R$ {novo:.0f}"

    return None


def enviar(token, chat_id, texto):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    dados = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": texto, "disable_web_page_preview": "true"}
    ).encode()
    with urllib.request.urlopen(url, data=dados, timeout=30) as r:
        return r.read()


def carregar_estado():
    if ARQUIVO_ESTADO.exists():
        return json.loads(ARQUIVO_ESTADO.read_text())
    return {}


def main():
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Faltam os Secrets TELEGRAM_TOKEN e/ou TELEGRAM_CHAT_ID.")
        raise SystemExit(1)

    estado = carregar_estado()
    primeira_vez = not estado.get("iniciado")
    alertas = 0

    for canal in CANAIS:
        try:
            msgs = ler_mensagens(baixar(canal))
        except Exception as e:
            print(f"Erro ao ler o canal {canal}: {type(e).__name__}")
            continue

        if not msgs:
            print(f"Nenhuma mensagem lida em {canal} (a página pode ter mudado).")
            continue

        ultimo = estado.get(canal, 0)
        if canal not in estado:
            # primeira leitura: só marca o ponto de partida, sem alertar
            estado[canal] = max(i for i, _, _ in msgs)
            continue

        for idm, texto, links in sorted(msgs):
            if idm <= ultimo:
                continue
            estado[canal] = max(estado[canal], idm)
            motivo = analisar(texto)
            if motivo and alertas < MAX_ALERTAS:
                msg = f"🚨 POSSÍVEL BUG ({motivo})\n\n{texto[:500]}\n"
                if links:
                    msg += f"\n🛒 {links[0]}"
                msg += f"\n💬 https://t.me/{canal}/{idm}"
                enviar(token, chat_id, msg)
                alertas += 1

    if primeira_vez:
        enviar(token, chat_id, "✅ Caçador de preços ativo! Vou avisar quando "
               "aparecer um possível bug de preço gamer.")
        estado["iniciado"] = True

    ARQUIVO_ESTADO.write_text(json.dumps(estado))
    print(f"Concluído. Alertas enviados: {alertas}")


if __name__ == "__main__":
    main()
