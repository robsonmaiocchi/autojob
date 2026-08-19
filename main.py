import os
import json
import time
import re
import requests
import unicodedata
from urllib.parse import quote
from playwright.sync_api import sync_playwright

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HISTORICO_FILE = "vagas_enviadas.json"
CONFIG_FILE = "config.json"

def remover_acentos(texto):
    if not texto:
        return ""
    texto_norm = unicodedata.normalize('NFD', texto)
    return "".join(c for c in texto_norm if unicodedata.category(c) != 'Mn').lower().strip()

def carregar_configuracao():
    default_config = {
        "termos_busca": ["Analista de Suporte Tecnico", "Suporte SaaS"],
        "locais": ["Remoto", "Imbituba", "Tubarão"],
        "termos_excluir": ["Estágio", "Intern", "Sênior", "Senior", "Lead", "Coordenador", "Gerente"],
        "plataformas": {"gupy": True, "solides": True, "linkedin": True, "indeed": True}
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao ler {CONFIG_FILE}, usando padrão: {e}")
    return default_config

config = carregar_configuracao()
TERMOS_BUSCA = config.get("termos_busca", [])
FILTROS_LOCAL = [remover_acentos(l) for l in config.get("locais", [])]
TERMOS_EXCLUIR = [remover_acentos(t) for t in config.get("termos_excluir", [])]
PLATAFORMAS = config.get("plataformas", {})

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

def vaga_deve_ser_excluida(titulo):
    titulo_norm = remover_acentos(titulo)
    for termo in TERMOS_EXCLUIR:
        if termo in titulo_norm:
            return True
    return False

def local_corresponde(local):
    local_norm = remover_acentos(local)
    if "remoto" in local_norm:
        return True
    return any(loc in local_norm for loc in FILTROS_LOCAL)

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

# --- API GUPY ---
def buscar_gupy(termo, historico):
    novas_vagas = []
    url = f"https://portal.api.gupy.io/api/v1/jobs?name={quote(termo)}&limit=10&offset=0"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json().get("data", [])
            for item in data:
                vaga_id = f"gupy_{item.get('id')}"
                titulo = item.get("name", "")

                if vaga_id in historico or vaga_deve_ser_excluida(titulo):
                    continue

                is_remote = item.get("isRemote", False)
                city = item.get("city", "")
                state = item.get("state", "")
                local_str = "Remoto" if is_remote else f"{city} - {state}".strip(" -")

                if local_corresponde(local_str):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": titulo,
                        "empresa": item.get("companyName", "Não informada"),
                        "local": local_str,
                        "link": item.get("jobUrl"),
                        "plataforma": "Gupy"
                    })
    except Exception as e:
        print(f"Erro ao buscar na Gupy ({termo}): {e}")
    return novas_vagas

# --- API SOLIDES ---
def buscar_solides(termo, historico):
    novas_vagas = []
    url = f"https://vagas.solides.com.br/api/v1/jobs/search?title={quote(termo)}&take=10"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json().get("data", [])
            for item in data:
                vaga_id = f"solides_{item.get('id')}"
                titulo = item.get("title", "")

                if vaga_id in historico or vaga_deve_ser_excluida(titulo):
                    continue

                workplace_type = item.get("workplaceType", "")
                city = item.get("city", "")
                state = item.get("state", "")
                local_str = workplace_type if workplace_type else f"{city} - {state}".strip(" -")

                if local_corresponde(local_str):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": titulo,
                        "empresa": item.get("company", {}).get("name", "Não informada"),
                        "local": local_str,
                        "link": f"https://vagas.solides.com.br/vagas/{item.get('id')}",
                        "plataforma": "Solides"
                    })
    except Exception as e:
        print(f"Erro ao buscar na Solides ({termo}): {e}")
    return novas_vagas

# --- PLAYWRIGHT: LINKEDIN ---
def buscar_linkedin(page, termo, historico):
    novas_vagas = []
    url = f"https://www.linkedin.com/jobs/search?keywords={quote(termo)}&location=Brasil&f_TPR=r86400"
    print(f"  [LinkedIn] Buscando: {termo}")
    
    try:
        page.goto(url, timeout=30000)
        page.wait_for_selector(".jobs-search__results-list", timeout=10000)
        cards = page.query_selector_all(".jobs-search__results-list > li")

        for card in cards[:10]:
            try:
                link_elem = card.query_selector("a.base-card__full-link")
                if not link_elem:
                    continue
                
                link = link_elem.get_attribute("href").split("?")[0]
                vaga_id = f"linkedin_{link.split('-')[-1]}"

                titulo_elem = card.query_selector(".base-search-card__title")
                titulo = titulo_elem.inner_text().strip() if titulo_elem else "Título não informado"

                if vaga_id in historico or vaga_deve_ser_excluida(titulo):
                    continue

                empresa_elem = card.query_selector(".base-search-card__subtitle")
                local_elem = card.query_selector(".job-search-card__location")

                empresa = empresa_elem.inner_text().strip() if empresa_elem else "Empresa não informada"
                local = local_elem.inner_text().strip() if local_elem else "Brasil"

                if local_corresponde(local):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": titulo,
                        "empresa": empresa,
                        "local": local,
                        "link": link,
                        "plataforma": "LinkedIn"
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"  [LinkedIn] Aviso/Erro ({termo}): {e}")

    return novas_vagas

# --- PLAYWRIGHT: INDEED ---
def buscar_indeed(page, termo, historico):
    novas_vagas = []
    url = f"https://br.indeed.com/jobs?q={quote(termo)}&l=Brasil&fromage=1"
    print(f"  [Indeed] Buscando: {termo}")

    try:
        page.goto(url, timeout=30000)
        time.sleep(2)
        cards = page.query_selector_all(".job_seen_beacon")

        for card in cards[:10]:
            try:
                title_elem = card.query_selector("a.jserp-job-link") or card.query_selector("h2.jobTitle a")
                if not title_elem:
                    continue

                job_key = title_elem.get_attribute("data-jk")
                if not job_key:
                    continue

                vaga_id = f"indeed_{job_key}"
                titulo = title_elem.inner_text().strip()

                if vaga_id in historico or vaga_deve_ser_excluida(titulo):
                    continue

                company_elem = card.query_selector("[data-testid='company-name']")
                location_elem = card.query_selector("[data-testid='text-location']")

                empresa = company_elem.inner_text().strip() if company_elem else "Não informada"
                local = location_elem.inner_text().strip() if location_elem else "Brasil"
                link = f"https://br.indeed.com/viewjob?jk={job_key}"

                if local_corresponde(local):
                    novas_vagas.append({
                        "id": vaga_id,
                        "titulo": titulo,
                        "empresa": empresa,
                        "local": local,
                        "link": link,
                        "plataforma": "Indeed"
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"  [Indeed] Aviso/Erro ({termo}): {e}")

    return novas_vagas

def main():
    historico = carregar_historico()
    vagas_para_enviar = []

    print("🔎 Iniciando varredura com inteligência de filtro UTF-8...")

    # 1. APIs
    for termo in TERMOS_BUSCA:
        if PLATAFORMAS.get("gupy", True):
            vagas_para_enviar.extend(buscar_gupy(termo, historico))
        if PLATAFORMAS.get("solides", True):
            vagas_para_enviar.extend(buscar_solides(termo, historico))

    # 2. Playwright
    usar_linkedin = PLATAFORMAS.get("linkedin", True)
    usar_indeed = PLATAFORMAS.get("indeed", True)

    if usar_linkedin or usar_indeed:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            for termo in TERMOS_BUSCA:
                if usar_linkedin:
                    vagas_para_enviar.extend(buscar_linkedin(page, termo, historico))
                if usar_indeed:
                    vagas_para_enviar.extend(buscar_indeed(page, termo, historico))

            browser.close()

    enviadas_com_sucesso = 0
    for vaga in vagas_para_enviar:
        if enviar_telegram(vaga):
            historico.add(vaga["id"])
            enviadas_com_sucesso += 1

    salvar_historico(historico)
    print(f"🚀 Processo concluído! {enviadas_com_sucesso} novas vagas enviadas.")

if __name__ == "__main__":
    main()