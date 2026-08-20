import os
import json
import requests
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HISTORY_FILE = "history.json"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"hashes": [], "detalhes": []}

def send_message(text, link=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Token ou Chat ID do Telegram não configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if link:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "🚀 Ver Vaga", "url": link}]]
        }
    requests.post(url, json=payload, timeout=5)

def cmd_status():
    history = load_history()
    total_hashes = len(history.get("hashes", []))
    detalhes = history.get("detalhes", [])
    
    ultima_atualizacao = detalhes[0]["data"] if detalhes else "Nenhuma varredura registrada"
    
    msg = (
        f"🤖 <b>STATUS DO AUTOJOB</b>\n"
        f"----------------------------------\n"
        f"📦 <b>Total de vagas no histórico:</b> {total_hashes}\n"
        f"🕒 <b>Última execução:</b> {ultima_atualizacao}\n"
        f"🟢 <b>Status do Bot:</b> Ativo e Operacional\n"
        f"----------------------------------"
    )
    send_message(msg)

def cmd_vagas():
    history = load_history()
    detalhes = history.get("detalhes", [])
    
    relevantes = [v for v in detalhes if v.get("score", 0) >= 40][:5]
    
    if not relevantes:
        send_message("ℹ️ Nenhuma vaga de alta/média relevância encontrada recentemente no histórico.")
        return

    send_message(f"🔥 <b>ÚLTIMAS {len(relevantes)} VAGAS DE DESTAQUE:</b>")
    
    for v in relevantes:
        msg = (
            f"📌 <b>{v['titulo']}</b>\n"
            f"🏢 Empresa: {v['empresa']}\n"
            f"🌐 Plataforma: {v['plataforma']}\n"
            f"📊 Match Score: {v.get('score', 0)}%\n"
            f"📅 Capturado em: {v.get('data', 'N/A')}"
        )
        send_message(msg, v.get("link"))

def cmd_ajuda():
    msg = (
        f"💡 <b>COMANDOS DISPONÍVEIS</b>\n\n"
        f"• <b>/status</b> - Exibe a saúde do bot e total de vagas\n"
        f"• <b>/vagas</b> - Lista as 5 vagas mais relevantes recentes\n"
        f"• <b>/ajuda</b> - Exibe esta mensagem de suporte"
    )
    send_message(msg)

if __name__ == "__main__":
    import sys
    comando = sys.argv[1] if len(sys.argv) > 1 else "/status"
    
    if comando in ["/status", "status"]:
        cmd_status()
    elif comando in ["/vagas", "vagas"]:
        cmd_vagas()
    else:
        cmd_ajuda()