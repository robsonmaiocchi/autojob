import os
import json
import requests
from urllib.parse import quote

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HISTORICO_FILE = "vagas_enviadas.json"

# Configurações de Busca
TERMOS_BUSCA = ["Analista de Suporte Tecnico", "Suporte SaaS", "Suporte Tecnico"]
FILTROS_LOCAL = ["Remoto", "Imbituba", "Tubarao"]

def carregar_historico():
    if os.path.exists(HISTORICO_FILE):
        try:
            with open(HISTORICO_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def salvar_historico(historico):
    with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
        json.dump(list(historico), f, indent=2, ensure_ascii=False)

def enviar_telegram(vaga):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Credenciais do Telegram ausentes.")
        return False

    mensagem = (
        f"🎯 *Nova Vaga Encontrada!*\n\n"
        f"📌 *Cargo:* {vaga['titulo']}\n"
        f"🏢 *Empresa:* {vaga['empresa']}\n"
        f"📍 *Local/Modalidade:* {vaga['local']}\n"
        f"🌐 *Plataforma:* {vaga['plataforma']}\n\n"
        f"🔗 [Acessar Vaga]({vaga['link']})"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    res = requests.post(url, json=payload)
    return res.status_code == 200

def buscar_gupy(termo, historico):
    novas_vagas = []
    # API publica direta da Gupy para busca de vagas
    url = f"https://portal.api.gupy.io/api/v1/jobs?name={quote(termo)}&limit=10&offset=0"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json().get("data", [])
            for item in data:
                vaga_id = f"gupy_{item.get('id')}"
                if vaga_id in historico:
                    continue

                is_remote = item.get("isRemote", False)
                city = item.get("city", "")
                state = item.get("state", "")
                local_str = "Remoto" if is_remote else f"{city} - {state}".strip(" -")

                # Valida localizacao desejada
                if is_remote or any(loc.lower() in local_str.lower() for loc in FILTROS_LOCAL):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": item.get("name"),
                        "empresa": item.get("companyName", "Não informada"),
                        "local": local_str,
                        "link": item.get("jobUrl"),
                        "plataforma": "Gupy"
                    })
    except Exception as e:
        print(f"Erro ao buscar na Gupy ({termo}): {e}")

    return novas_vagas

def buscar_solides(termo, historico):
    novas_vagas = []
    # API publica da Solides / Vacancies
    url = f"https://vagas.solides.com.br/api/v1/jobs/search?title={quote(termo)}&take=10"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json().get("data", [])
            for item in data:
                vaga_id = f"solides_{item.get('id')}"
                if vaga_id in historico:
                    continue

                workplace_type = item.get("workplaceType", "")
                city = item.get("city", "")
                state = item.get("state", "")
                local_str = workplace_type if workplace_type else f"{city} - {state}".strip(" -")

                if "remote" in workplace_type.lower() or any(loc.lower() in local_str.lower() for loc in FILTROS_LOCAL):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": item.get("title"),
                        "empresa": item.get("company", {}).get("name", "Não informada"),
                        "local": local_str,
                        "link": f"https://vagas.solides.com.br/vagas/{item.get('id')}",
                        "plataforma": "Solides"
                    })
    except Exception as e:
        print(f"Erro ao buscar na Solides ({termo}): {e}")

    return novas_vagas

def main():
    historico = carregar_historico()
    vagas_para_enviar = []

    print("🔎 Iniciando varredura de vagas...")

    for termo in TERMOS_BUSCA:
        print(f"Buscando por: {termo}")
        vagas_para_enviar.extend(buscar_gupy(termo, historico))
        vagas_para_enviar.extend(buscar_solides(termo, historico))

    enviadas_com_sucesso = 0
    for vaga in vagas_para_enviar:
        if enviar_telegram(vaga):
            historico.add(vaga["id"])
            enviadas_com_sucesso += 1

    salvar_historico(historico)
    print(f"🚀 Processo concluído! {enviadas_com_sucesso} novas vagas enviadas.")

if __name__ == "__main__":
    main()