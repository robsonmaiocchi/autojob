import os
import json
import requests
import re
from bs4 import BeautifulSoup
from unicodedata import normalize

# --- CONFIGURAÇÕES E AMBIENTE ---
CONFIG_FILE = "config.json"
HISTORY_FILE = "history.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def normalizar_texto(texto):
    if not texto:
        return ""
    return normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII').lower().strip()

def carregar_json(caminho, padrao):
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao ler {caminho}: {e}", flush=True)
    return padrao

def salvar_json(caminho, dados):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def enviar_telegram(mensagem):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado (tokens ausentes).", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar mensagem no Telegram: {e}", flush=True)

# --- ANALISADOR DE FIT E REQUISITOS ---
def analisar_modalidade(texto_completo):
    texto = normalizar_texto(texto_completo)
    if "remoto" in texto or "remote" in texto or "home office" in texto:
        return "🏠 REMOTO"
    elif "hibrido" in texto or "hybrid" in texto:
        return "🏢 HÍBRIDO"
    elif "presencial" in texto or "on-site" in texto:
        return "📍 PRESENCIAL"
    return "❓ NÃO ESPECIFICADO"

def extrair_stack_tecnologia(texto_completo):
    tecnologias = [
        "Python", "SQL", "Kotlin", "Salesforce", "AWS", "Docker",
        "PostgreSQL", "MySQL", "REST API", "Linux", "Git", "Zendesk", "Jira"
    ]
    encontradas = []
    texto_norm = normalizar_texto(texto_completo)
    for tech in tecnologias:
        if normalizar_texto(tech) in texto_norm:
            encontradas.append(tech)
    return ", ".join(encontradas) if encontradas else "Não identificada no resumo"

def validar_fit_vaga(titulo, local, descricao, config):
    titulo_norm = normalizar_texto(titulo)
    local_norm = normalizar_texto(local)
    desc_norm = normalizar_texto(descricao)

    # 1. Filtro de Exclusão
    for ex in config.get("termos_excluir", []):
        ex_norm = normalizar_texto(ex)
        if ex_norm and (ex_norm in titulo_norm or ex_norm in desc_norm):
            return False, "Possui termo de exclusão"

    # 2. Filtro de Termos de Busca
    termo_match = any(normalizar_texto(t) in titulo_norm for t in config.get("termos_busca", []))
    if not termo_match:
        return False, "Título não bate com os termos de busca"

    # 3. Filtro de Local
    locais_config = [normalizar_texto(l) for l in config.get("locais", [])]
    local_match = any(l in local_norm or l in desc_norm for l in locais_config)
    if not local_match and "remoto" not in local_norm and "remoto" not in desc_norm:
        return False, "Localização fora do perfil"

    return True, "OK"

# --- SCRAPERS / APIS COM RESILIÊNCIA ---

def buscar_gupy(termos, config):
    vagas = []
    print("🔎 Consultando Gupy...", flush=True)
    try:
        for termo in termos:
            url = f"https://portal.gupy.io/api/v1/jobs?name={requests.utils.quote(termo)}&limit=20"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("data", []):
                    id_vaga = f"gupy_{item.get('id')}"
                    titulo = item.get("name", "")
                    local = "Remoto" if item.get("isRemoteWork") else f"{item.get('city', '')} - {item.get('state', '')}"
                    link = item.get("jobUrl", "")
                    vagas.append({
                        "id": id_vaga,
                        "titulo": titulo,
                        "plataforma": "Gupy",
                        "local": local,
                        "link": link,
                        "descricao": f"{titulo} {local}"
                    })
    except Exception as e:
        print(f"⚠️ Erro ao consultar Gupy: {e}", flush=True)
    return vagas

def buscar_solides(termos, config):
    vagas = []
    print("🔎 Consultando Sólides...", flush=True)
    try:
        for termo in termos:
            url = f"https://vagas.solides.com.br/api/v1/jobs/search?query={requests.utils.quote(termo)}&take=20"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("data", []):
                    id_vaga = f"solides_{item.get('id')}"
                    titulo = item.get("title", "")
                    local = item.get("city", {}).get("name", "Não informado")
                    link = item.get("link", "")
                    vagas.append({
                        "id": id_vaga,
                        "titulo": titulo,
                        "plataforma": "Sólides",
                        "local": local,
                        "link": link,
                        "descricao": f"{titulo} {local}"
                    })
    except Exception as e:
        print(f"⚠️ Erro ao consultar Sólides: {e}", flush=True)
    return vagas

def buscar_linkedin(termos, config):
    vagas = []
    print("🔎 Scrapeando LinkedIn...", flush=True)
    try:
        for termo in termos:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={requests.utils.quote(termo)}&start=0"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                cards = soup.find_all("li")
                for card in cards:
                    title_elem = card.find("h3", class_="base-search-card__title")
                    link_elem = card.find("a", class_="base-card__full-link")
                    loc_elem = card.find("span", class_="job-search-card__location")
                    
                    if title_elem and link_elem:
                        link = link_elem.get("href", "").split("?")[0]
                        vaga_id = f"linkedin_{link.split('-')[-1]}"
                        titulo = title_elem.text.strip()
                        local = loc_elem.text.strip() if loc_elem else "Não informado"
                        vagas.append({
                            "id": vaga_id,
                            "titulo": titulo,
                            "plataforma": "LinkedIn",
                            "local": local,
                            "link": link,
                            "descricao": f"{titulo} {local}"
                        })
    except Exception as e:
        print(f"⚠️ Erro ao consultar LinkedIn: {e}", flush=True)
    return vagas

# --- FLUXO PRINCIPAL ---
def main():
    config = carregar_json(CONFIG_FILE, {})
    historico = carregar_json(HISTORY_FILE, [])
    
    plataformas_ativas = config.get("plataformas", {})
    termos = config.get("termos_busca", [])
    
    todas_vagas = []
    
    if plataformas_ativas.get("gupy", True):
        todas_vagas.extend(buscar_gupy(termos, config))
    if plataformas_ativas.get("solides", True):
        todas_vagas.extend(buscar_solides(termos, config))
    if plataformas_ativas.get("linkedin", True):
        todas_vagas.extend(buscar_linkedin(termos, config))

    novas_vagas = 0
    print(f"Total de vagas capturadas nas APIs: {len(todas_vagas)}", flush=True)

    for vaga in todas_vagas:
        if vaga["id"] in historico:
            continue

        passou_filtro, razao = validar_fit_vaga(vaga["titulo"], vaga["local"], vaga["descricao"], config)
        
        if passou_filtro:
            modalidade = analisar_modalidade(vaga["local"] + " " + vaga["descricao"])
            stack = extrair_stack_tecnologia(vaga["descricao"])
            
            # Formatação refinada da notificação Telegram
            msg = (
                f"🎯 *NOVA VAGA ENCONTRADA*\n\n"
                f"📌 *Cargo:* {vaga['titulo']}\n"
                f"🏢 *Plataforma:* {vaga['plataforma']}\n"
                f"📍 *Modalidade:* {modalidade}\n"
                f"🛠️ *Stack/Tecnologias:* {stack}\n"
                f"🔗 *Link:* [Candidatar-se na Vaga]({vaga['link']})"
            )
            
            enviar_telegram(msg)
            historico.append(vaga["id"])
            novas_vagas += 1
        else:
            # Registra no histórico para não reprocessar vagas que não deram fit
            historico.append(vaga["id"])

    salvar_json(HISTORY_FILE, historico)
    print(f"✅ Processamento finalizado! {novas_vagas} novas vagas enviadas ao Telegram.", flush=True)

if __name__ == "__main__":
    main()