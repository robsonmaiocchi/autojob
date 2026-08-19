import os
import requests
from playwright.sync_api import sync_playwright

# Configurações do Telegram enviadas pelo GitHub Secrets / Ambiente
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Filtros da busca
KEYWORDS = ["suporte técnico", "support analyst", "python", "atendimento"]


def send_telegram_message(message: str):
    """Envia mensagens formatadas para o Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[AVISO] Credenciais do Telegram não configuradas no ambiente.")
        print(f"Mensagem que seria enviada:\n{message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print(" Notificação enviada para o Telegram com sucesso!")
    else:
        print(f" Falha ao enviar para o Telegram: {response.status_code} - {response.text}")


def run_job_scraper():
    print(" Iniciando a busca automatizada de vagas...")

    with sync_playwright() as p:
        # Lança o navegador Chromium em modo headless
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Exemplo de navegação (Substitua pela URL do portal/board desejado)
        url = "https://exemplo-de-portal-de-vagas.com"
        print(f"Navegando até: {url}")
        
        # page.goto(url)
        # page.wait_for_selector('.job-card')

        # Simulando uma lista de vagas encontradas para validação da estrutura
        jobs_found = [
            {"title": "Analista de Suporte Técnico Junior", "company": "TechCorp", "link": "https://exemplo.com/vaga1"},
            {"title": "Desenvolvedor Python Pleno", "company": "DataData", "link": "https://exemplo.com/vaga2"},
            {"title": "Atendente de SAC", "company": "CallCenterCo", "link": "https://exemplo.com/vaga3"},
        ]

        # Filtragem por palavras-chave
        matched_jobs = []
        for job in jobs_found:
            title_lower = job["title"].lower()
            if any(keyword in title_lower for keyword in KEYWORDS):
                matched_jobs.append(job)

        browser.close()

    # Formatação e envio do relatório no Telegram
    if matched_jobs:
        msg = f" *Vagas Encontradas ({len(matched_jobs)})*\n\n"
        for job in matched_jobs:
            msg += f"• *{job['title']}* - {job['company']}\n🔗 [Acessar Vaga]({job['link']})\n\n"
        
        send_telegram_message(msg)
    else:
        print("Nenhuma vaga correspondente aos filtros foi encontrada hoje.")


if __name__ == "__main__":
    run_job_scraper()