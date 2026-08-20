import os
import json
import re
import hashlib
import urllib.parse
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# ==============================================================================
# CONFIGURAÇÕES E AMBIENTE
# ==============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CONFIG_FILE = "config.json"
HISTORY_FILE = "history.json"

ua = UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

def get_headers(referer="https://www.google.com/"):
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": referer,
        "Cache-Control": "no-cache"
    }

def fetch_url(url, method="GET", json_data=None, params=None, timeout=5, referer="https://www.google.com/"):
    headers = get_headers(referer=referer)
    try:
        if method.upper() == "POST":
            response = requests.post(url, json=json_data, headers=headers, params=params, timeout=timeout)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
        
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Falha ou timeout em {url}: {e}", flush=True)
        return None

# ==============================================================================
# ALGORITMO DE PONTUAÇÃO DE RELEVÂNCIA (MATCH SCORE)
# ==============================================================================
PALAVRAS_CHAVE_PESO = {
    "saas": 20, "sql": 20, "helpdesk": 20, "sla": 15, "itsm": 15,
    "atendimento": 15, "customer success": 15, "suporte tecnico": 25,
    "technical support": 25, "junior": 15, "jr": 15, "pleno": 15, "pl": 10, "analista": 10
}

def calcular_match_score(titulo, empresa, local):
    texto_completo = f"{titulo} {empresa} {local}".lower()
    score = sum(peso for termo, peso in PALAVRAS_CHAVE_PESO.items() if termo in texto_completo)
    score = min(score, 100)

    if score >= 70:
        badge = "🔥 Excelente (High Match)"
    elif score >= 40:
        badge = "🟡 Relevante (Medium Match)"
    else:
        badge = "⚪ Compatível (General Match)"

    return score, badge

# ==============================================================================
# UTILITÁRIOS E HISTÓRICO
# ==============================================================================
def load_config():
    default_config = {
        "termos_busca": ["Analista de Suporte Tecnico", "Suporte SaaS", "Suporte Tecnico", "Technical Support"],
        "locais": ["Remoto", "Imbituba", "Tubarão", "Joinville", "Curitiba"],
        "termos_excluir": ["Estágio", "Intern", "Sênior", "Senior", "Lead", "Coordenador", "Gerente", "Manager", "Especialista"],
        "plataformas": {
            "gupy": True,
            "solides": True,
            "linkedin": True,
            "remotar": True,
            "coodesh": True
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_config

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {"hashes": data, "detalhes": []}
                return data
        except Exception:
            pass
    return {"hashes": [], "detalhes": []}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Erro ao salvar histórico: {e}", flush=True)

def generate_hash(titulo, empresa, plataforma):
    text = f"{titulo.strip().lower()}_{empresa.strip().lower()}_{plataforma.strip().lower()}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def send_telegram(mensagem, link_vaga=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if link_vaga:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "🚀 Candidatar-se Agora", "url": link_vaga}]]
        }
    fetch_url(url, method="POST", json_data=payload, timeout=5)

def deve_excluir(titulo, termos_excluir):
    titulo_lower = titulo.lower()
    return any(termo.lower() in titulo_lower for termo in termos_excluir)

# ==============================================================================
# SCRAPERS
# ==============================================================================

def buscar_gupy(termos, locais, termos_excluir):
    vagas = []
    base_url = "https://portal.gupy.io/job-search/api/v1/jobs"
    for termo in termos:
        print(f"  └ Buscando termo Gupy: {termo}", flush=True)
        params = {"jobName": termo, "limit": 20, "offset": 0}
        res = fetch_url(base_url, params=params, referer="https://portal.gupy.io/")
        if not res:
            continue
        try:
            data = res.json()
            for item in data.get("data", []):
                titulo = item.get("name", "")
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = item.get("careerPageName", "Gupy")
                link = item.get("jobUrl", "")
                local = item.get("city", "") or ("Remoto" if item.get("isRemote") else "Brasil")
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "Gupy"
                })
        except Exception as e:
            print(f"⚠️ Erro no parsing Gupy: {e}", flush=True)
    return vagas

def buscar_solides(termos, locais, termos_excluir):
    vagas = []
    base_url = "https://vagas.solides.com.br/api/v1/jobs/search"
    for termo in termos:
        print(f"  └ Buscando termo Sólides: {termo}", flush=True)
        params = {"title": termo, "take": 20, "page": 1}
        res = fetch_url(base_url, params=params, referer="https://vagas.solides.com.br/")
        if not res:
            continue
        try:
            data = res.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            for item in items:
                titulo = item.get("title") or item.get("name", "")
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = item.get("company", {}).get("name", "Sólides") if isinstance(item.get("company"), dict) else "Sólides"
                link = item.get("link") or item.get("url", "")
                if link and not link.startswith("http"):
                    link = f"https://vagas.solides.com.br{link}"
                local = item.get("city", {}).get("name", "Brasil") if isinstance(item.get("city"), dict) else "Brasil"
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "Sólides"
                })
        except Exception as e:
            print(f"⚠️ Erro no parsing Sólides: {e}", flush=True)
    return vagas

def buscar_linkedin(termos, locais, termos_excluir):
    vagas = []
    for termo in termos:
        print(f"  └ Buscando termo LinkedIn: {termo}", flush=True)
        termo_encoded = urllib.parse.quote(termo)
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={termo_encoded}&location=Brasil&start=0"
        res = fetch_url(url, referer="https://www.linkedin.com/")
        if not res:
            continue
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.find_all("li")
        for card in cards:
            title_tag = card.find("h3", class_=re.compile("base-search-card__title"))
            company_tag = card.find("h4", class_=re.compile("base-search-card__subtitle"))
            link_tag = card.find("a", class_=re.compile("base-card__full-link"))
            location_tag = card.find("span", class_=re.compile("job-search-card__location"))
            
            if title_tag and link_tag:
                titulo = title_tag.get_text(strip=True)
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = company_tag.get_text(strip=True) if company_tag else "LinkedIn"
                link = link_tag.get("href", "").split("?")[0]
                local = location_tag.get_text(strip=True) if location_tag else "Brasil"
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "LinkedIn"
                })
    return vagas

def buscar_remotar(termos, locais, termos_excluir):
    vagas = []
    print("  └ Buscando feed Remotar...", flush=True)
    url = "https://remotar.com.br/"
    res = fetch_url(url, referer="https://remotar.com.br/")
    if not res:
        return vagas
    soup = BeautifulSoup(res.text, "html.parser")
    cards = soup.find_all("a", href=re.compile(r"/vaga/"))
    for card in cards:
        titulo = card.get_text(strip=True)
        if any(t.lower() in titulo.lower() for t in termos) and not deve_excluir(titulo, termos_excluir):
            href = card.get("href", "")
            link = f"https://remotar.com.br{href}" if href.startswith("/") else href
            vagas.append({
                "titulo": titulo,
                "empresa": "Remotar",
                "local": "Remoto",
                "link": link,
                "plataforma": "Remotar"
            })
    return vagas

def buscar_coodesh(termos, locais, termos_excluir):
    vagas = []
    for termo in termos:
        print(f"  └ Buscando termo Coodesh: {termo}", flush=True)
        termo_encoded = urllib.parse.quote(termo)
        url = f"https://coodesh.com/vagas?search={termo_encoded}"
        res = fetch_url(url, referer="https://coodesh.com/")
        if not res:
            continue
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.find_all("a", href=re.compile(r"/vagas/"))
        for card in cards:
            titulo = card.get_text(strip=True)
            if titulo and not deve_excluir(titulo, termos_excluir):
                href = card.get("href", "")
                link = f"https://coodesh.com{href}" if href.startswith("/") else href
                vagas.append({
                    "titulo": titulo,
                    "empresa": "Coodesh",
                    "local": "Remoto",
                    "link": link,
                    "plataforma": "Coodesh"
                })
    return vagas

# ==============================================================================
# EXECUÇÃO PRINCIPAL
# ==============================================================================
def main():
    print("🚀 Iniciando varredura de vagas com AutoJob...", flush=True)
    config = load_config()
    history = load_history()
    
    termos = config.get("termos_busca", [])
    locais = config.get("locais", [])
    termos_excluir = config.get("termos_excluir", [])
    plataformas_ativas = config.get("plataformas", {})

    vagas_encontradas = []

    if plataformas_ativas.get("gupy", True):
        print("🔎 Buscando na Gupy...", flush=True)
        vagas_encontradas.extend(buscar_gupy(termos, locais, termos_excluir))

    if plataformas_ativas.get("solides", True):
        print("🔎 Buscando na Sólides...", flush=True)
        vagas_encontradas.extend(buscar_solides(termos, locais, termos_excluir))

    if plataformas_ativas.get("linkedin", True):
        print("🔎 Buscando no LinkedIn...", flush=True)
        vagas_encontradas.extend(buscar_linkedin(termos, locais, termos_excluir))

    if plataformas_ativas.get("remotar", True):
        print("🔎 Buscando na Remotar...", flush=True)
        vagas_encontradas.extend(buscar_remotar(termos, locais, termos_excluir))

    if plataformas_ativas.get("coodesh", True):
        print("🔎 Buscando na Coodesh...", flush=True)
        vagas_encontradas.extend(buscar_coodesh(termos, locais, termos_excluir))

    print(f"📊 Total de vagas capturadas antes da desduplicação: {len(vagas_encontradas)}", flush=True)

    novas_vagas_count = 0
    high_match_count = 0
    medium_match_count = 0
    general_match_count = 0
    plat_counts = {}

    hashes_existentes = set(history.get("hashes", []))
    detalhes_recentes = history.get("detalhes", [])

    for vaga in vagas_encontradas:
        h = generate_hash(vaga["titulo"], vaga["empresa"], vaga["plataforma"])
        if h not in hashes_existentes:
            hashes_existentes.add(h)
            novas_vagas_count += 1

            plat = vaga["plataforma"]
            plat_counts[plat] = plat_counts.get(plat, 0) + 1

            score, badge = calcular_match_score(vaga["titulo"], vaga["empresa"], vaga["local"])

            if score >= 70:
                high_match_count += 1
            elif score >= 40:
                medium_match_count += 1
            else:
                general_match_count += 1

            msg = (
                f"🎯 <b>Nova Vaga Encontrada!</b>\n\n"
                f"📌 <b>Título:</b> {vaga['titulo']}\n"
                f"🏢 <b>Empresa:</b> {vaga['empresa']}\n"
                f"📍 <b>Local:</b> {vaga['local']}\n"
                f"🌐 <b>Plataforma:</b> {vaga['plataforma']}\n"
                f"📊 <b>Match Score:</b> {score}% ({badge})"
            )
            
            send_telegram(msg, vaga["link"])
            time.sleep(0.5)

            detalhes_recentes.insert(0, {
                "titulo": vaga["titulo"],
                "empresa": vaga["empresa"],
                "plataforma": vaga["plataforma"],
                "link": vaga["link"],
                "score": score,
                "data": datetime.now().strftime("%Y-%m-%d %H:%M")
            })

    history["hashes"] = list(hashes_existentes)
    history["detalhes"] = detalhes_recentes[:50]
    
    save_history(history)

    if novas_vagas_count > 0:
        resumo_plat = "\n".join([f"• {k}: {v}" for k, v in plat_counts.items()])
        msg_resumo = (
            f"📊 <b>RESUMO DA VARREDURA DE VAGAS</b>\n"
            f"----------------------------------\n"
            f"🔹 <b>Novas Vagas Encontradas:</b> {novas_vagas_count}\n"
            f"🔥 <b>Alta Relevância:</b> {high_match_count}\n"
            f"🟡 <b>Média Relevância:</b> {medium_match_count}\n"
            f"⚪ <b>Outras:</b> {general_match_count}\n\n"
            f"🌐 <b>Por Plataforma:</b>\n{resumo_plat}\n"
            f"----------------------------------\n"
            f"⚡ <i>AutoJob executado com sucesso!</i>"
        )
        send_telegram(msg_resumo)

    print(f"✅ Processamento concluído. {novas_vagas_count} novas vagas notificadas.", flush=True)

if __name__ == "__main__":
    main()