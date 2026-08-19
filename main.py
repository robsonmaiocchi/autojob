import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def testar_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não definidos nas variáveis de ambiente.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "🚀 *Teste de Automação*: O Bot do GitHub Actions está online e se comunicando com sucesso!",
        "parse_mode": "Markdown"
    }

    response = requests.post(url, json=payload)
    
    print(f"Status Code do Telegram: {response.status_code}")
    print(f"Resposta do Telegram: {response.text}")

    # Lança um erro explicitamente se o Telegram rejeitar para a pipeline do GitHub ficar vermelha
    response.raise_for_status()

if __name__ == "__main__":
    print("Iniciando teste de envio do Telegram...")
    testar_telegram()