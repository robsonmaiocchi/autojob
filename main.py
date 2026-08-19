import os
import json
import requests
import unicodedata
from bs4 import BeautifulSoup

# Configurações do Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def normalizar_texto(texto):
    """Remove acentos, caracteres especiais e converte para minúsculas."""
    if not texto:
        return ""
    texto_nfkd = unicodedata.normalize("NFKD", texto)
    return "".join([c for c in texto_nfkd if not unicodedata.combining(c)]).lower().strip()

def carregar_configuracao():
    config_default = {
        "termos_busca": ["suporte", "analista de suporte", "support", "helpdesk"],
        "termos_exclusao": ["estagio", "estágio", "intern"],
        "locais_permitidos": [
            "remoto", "brasil", "br", 
            "santa catarina", "sc", "imbituba", "tubarao", "tubarão", 
            "curitiba", "florianopolis", "florianópolis", 
            "sao jose", "são josé", "palhoca", "palhoça"
        ]
    }
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"⚠️ Erro ao ler config.json: {e}")
    return config_default

def carregar_historico():
    if os.path.exists("history.json"):
        with open("history.json", "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    return {v.get("id") for v in data if "id" in v}, data
                elif isinstance(data, dict):
                    return set(data.get("ids", [])), data.get("detalhes", [])
            except Exception:
                pass
    return set(), []

def salvar_historico(ids, detalhes):
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump({"ids": list(ids), "detalhes": detalhes[:100]}, f, ensure_ascii=False, indent=2)

def enviar_telegram(mensagem, link_vaga=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Token ou Chat ID do Telegram não configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }

    if link_vaga:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[
                {"text": "🌐 Abrir Vaga", "url": link_vaga}
            ]]
        })

    try:
        res = requests.post(url, data=payload, timeout=5)
        if res.status_code != 200:
            print(f"⚠️ Erro ao enviar Telegram: {res.text}")
    except Exception as e:
        print(f"⚠️ Exceção ao enviar mensagem Telegram: {e}")

def validar_fit_vaga(titulo, local, descricao, config):
    titulo_norm = normalizar_texto(titulo)
    desc_norm = normalizar_texto(descricao)
    local_norm = normalizar_texto(local)

    # 1. Verificar termos de exclusão
    for ex in config.get("termos_exclusao", []):
        if normalizar_texto(ex) in titulo_norm:
            return False, f"Contém termo de exclusão '{ex}'"

    # 2. Verificar termos de busca
    termos_busca = [normalizar_texto(t) for t in config.get("termos_busca", [])]
    passou_termo = any(t in titulo_norm for t in termos_busca)
    if not passou_termo:
        return False, "Título não bate com os termos de busca"

    # 3. Verificar localização / modalidade
    locais_permitidos = [
        normalizar_texto(l) for l in config.get("locais_permitidos", [
            "remoto", "brasil", "br", "santa catarina", "sc", 
            "imbituba", "tubarao", "curitiba", "florianopolis", "sao jose", "palhoca"
        ])
    ]
    
    # Adicionar flexibilidade extra para SC e Brasil no texto do local/descrição
    texto_checar = f"{local_norm} {desc_norm}"
    passou_local = any(loc in texto_checar for loc in locais_permitidos)
    
    if not passou_local:
        return False, f"Localização fora do perfil ({local})"

    return True, "Aprovada"

def analisar_modalidade(texto):
    texto_norm = normalizar_texto(texto)
    if "remoto" in texto_norm or "remote" in texto_norm or "home office" in texto_norm:
        return "Remoto 🏠"
    elif "hibrido" in texto_norm or "hybrid" in texto_norm:
        return "Híbrido 🔄"
    elif "presencial" in texto_norm or "on-site" in texto_norm:
        return "Presencial 🏢"
    return "Não especificada 📍"

def extrair_stack_tecnologia(texto):
    tecnologias = ["python", "sql", "kotlin", "salesforce", "aws", "linux", "zendesk", "jira", "docker", "git"]
    encontradas = []
    texto_norm = normalizar_texto(texto)
    for tech in tecnologias:
        if tech in texto_norm:
            encontradas.append(tech.capitalize())
    return ", ".join(encontradas) if encontradas else "Geral / Suporte Técnico"

def buscar_gupy(termos, config):
    vagas = []
    print("🔎 Consultando Gupy...", flush=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    for termo in termos:
        try:
            url = f"https://portal.gupy.io/api/v1/jobs?jobName={requests.utils.quote(termo)}&limit=20"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200 and res.text.strip().startswith("{"):
                data = res.json()
                for item in data.get("data", []):
                    id_vaga = f"gupy_{item.get('id')}"
                    titulo = item.get("name", "")
                    is_remote = item.get("isRemoteWork", False)
                    city = item.get("city", "")
                    state = item.get("state", "")
                    local = "Remoto" if is_remote else f"{city} - {state}".strip(" -")
                    link = item.get("jobUrl", "")
                    vagas.append({
                        "id": id_vaga,
                        "titulo": titulo,
                        "plataforma": "Gupy",
                        "local": local if local else "Brasil",
                        "link": link,
                        "descricao": f"{titulo} {local}"
                    })
            else:
                print(f"⚠️ Gupy bloqueou ou respondeu sem JSON público para '{termo}' (Status {res.status_code})", flush=True)
        except Exception as e:
            print(f"⚠️ Erro ao consultar Gupy ({termo}): {e}", flush=True)
    return vagas

def buscar_solides(termos, config):
    vagas = []
    print("🔎 Consultando Sólides...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    for termo in termos:
        try:
            url = f"https://api.solides.jobs/v2/vacancies/search?title={requests.utils.quote(termo)}&take=20"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200 and res.text.strip().startswith("{"):
                data = res.json()
                for item in data.get("data", []):
                    id_vaga = f"solides_{item.get('id')}"
                    titulo = item.get("title", "")
                    city = item.get("city", {}).get("name", "") if isinstance(item.get("city"), dict) else ""
                    state = item.get("state", {}).get("acronym", "") if isinstance(item.get("state"), dict) else ""
                    local = "Remoto" if item.get("isRemote") else f"{city} - {state}".strip(" -")
                    link = item.get("linkVacancy", "")
                    vagas.append({
                        "id": id_vaga,
                        "titulo": titulo,
                        "plataforma": "Sólides",
                        "local": local if local else "Brasil",
                        "link": link,
                        "descricao": f"{titulo} {local}"
                    })
        except Exception as e:
            print(f"⚠️ Erro ao consultar Sólides ({termo}): {e}", flush=True)
    return vagas

def buscar_linkedin(termos, config):
    vagas = []
    print("🔎 Scrapeando LinkedIn...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    for termo in termos:
        try:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={requests.utils.quote(termo)}&location=Brasil&geoId=106057199&start=0"
            res = requests.get(url, headers=headers, timeout=5)
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
                        local = loc_elem.text.strip() if loc_elem else "Brasil"
                        vagas.append({
                            "id": vaga_id,
                            "titulo": titulo,
                            "plataforma": "LinkedIn",
                            "local": local,
                            "link": link,
                            "descricao": f"{titulo} {local}"
                        })
        except Exception as e:
            print(f"⚠️ Erro ao consultar LinkedIn ({termo}): {e}", flush=True)
    return vagas

def buscar_indeed(termos, config):
    vagas = []
    print("🔎 Scrapeando Indeed...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    for termo in termos:
        try:
            url = f"https://br.indeed.com/jobs?q={requests.utils.quote(termo)}&l=Brasil"
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                cards = soup.find_all("div", class_="job_seen_beacon")
                for card in cards:
                    title_elem = card.find("h2", class_="jobTitle")
                    loc_elem = card.find("div", class_="company_location")
                    link_elem = card.find("a", href=True)
                    
                    if title_elem and link_elem:
                        job_id = link_elem.get("data-jk", link_elem["href"][-10:])
                        vaga_id = f"indeed_{job_id}"
                        titulo = title_elem.text.strip()
                        local = loc_elem.text.strip() if loc_elem else "Brasil"
                        link = f"https://br.indeed.com/viewjob?jk={job_id}" if "jk=" not in link_elem["href"] else f"https://br.indeed.com{link_elem['href']}"
                        vagas.append({
                            "id": vaga_id,
                            "titulo": titulo,
                            "plataforma": "Indeed",
                            "local": local,
                            "link": link,
                            "descricao": f"{titulo} {local}"
                        })
        except Exception as e:
            print(f"⚠️ Erro ao consultar Indeed ({termo}): {e}", flush=True)
    return vagas

def main():
    config = carregar_configuracao()
    historico_ids, historico_detalhado = carregar_historico()
    
    termos = config.get("termos_busca", ["Suporte"])
    
    todas_vagas = []
    todas_vagas.extend(buscar_gupy(termos, config))
    todas_vagas.extend(buscar_solides(termos, config))
    todas_vagas.extend(buscar_linkedin(termos, config))
    todas_vagas.extend(buscar_indeed(termos, config))

    print(f"Total de vagas capturadas nas APIs/Scrapers: {len(todas_vagas)}", flush=True)

    novas_vagas = 0

    for vaga in todas_vagas:
        if vaga["id"] in historico_ids:
            continue

        passou_filtro, razao = validar_fit_vaga(vaga["titulo"], vaga["local"], vaga["descricao"], config)
        
        if passou_filtro:
            modalidade = analisar_modalidade(vaga["local"] + " " + vaga["descricao"])
            stack = extrair_stack_tecnologia(vaga["descricao"])
            
            msg = (
                f"🎯 *NOVA VAGA ENCONTRADA*\n\n"
                f"📌 *Cargo:* {vaga['titulo']}\n"
                f"🏢 *Plataforma:* {vaga['plataforma']}\n"
                f"📍 *Modalidade:* {modalidade}\n"
                f"🛠️ *Stack/Tecnologias:* {stack}"
            )
            
            enviar_telegram(msg, link_vaga=vaga["link"])
            
            historico_ids.add(vaga["id"])
            historico_detalhado.insert(0, {
                "id": vaga["id"],
                "titulo": vaga["titulo"],
                "plataforma": vaga["plataforma"],
                "local": vaga["local"],
                "link": vaga["link"]
            })
            novas_vagas += 1
        else:
            print(f"❌ Rejeitada [{vaga['plataforma']}]: {vaga['titulo']} ({vaga['local']}) -> Motivo: {razao}", flush=True)
            historico_ids.add(vaga["id"])

    salvar_historico(historico_ids, historico_detalhado)
    print(f"✅ Processamento finalizado! {novas_vagas} novas vagas enviadas ao Telegram.", flush=True)

if __name__ == "__main__":
    main()