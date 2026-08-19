import os
import json
import requests
import unicodedata
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Configurações do Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def normalizar_texto(texto):
    """Remove acentos, caracteres especiais e converte para minúsculas."""
    if not texto:
        return ""
    texto_nfkd = unicodedata.normalize("NFKD", texto)
    return "".join([c for c in texto_nfkd if not unicodedata.combining(c)]).lower().strip()

def gerar_hash_deduplicacao(titulo, local):
    """Gera uma chave única simplificada para detectar vagas idênticas em plataformas diferentes."""
    t_norm = re.sub(r'[^a-z0-9]', '', normalizar_texto(titulo))
    l_norm = re.sub(r'[^a-z0-9]', '', normalizar_texto(local))
    return f"{t_norm}_{l_norm}"

def carregar_configuracao():
    config_default = {
        "termos_busca": ["suporte", "analista de suporte", "support", "helpdesk", "technical support", "suporte tecnico"],
        "termos_exclusao": ["estagio", "estágio", "intern", "senior", "sênior", "director", "diretor", "manager", "gerente", "lead", "coordenador"],
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
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Erro ao ler config.json: {e}")
    return config_default

def carregar_historico():
    if os.path.exists("history.json"):
        with open("history.json", "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    hashes = {v.get("hash", v.get("id")) for v in data if "id" in v or "hash" in v}
                    return hashes, data
                elif isinstance(data, dict):
                    hashes = set(data.get("hashes", data.get("ids", [])))
                    return hashes, data.get("detalhes", [])
            except Exception:
                pass
    return set(), []

def salvar_historico(hashes, detalhes):
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump({"hashes": list(hashes), "detalhes": detalhes[:200]}, f, ensure_ascii=False, indent=2)

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
        res = requests.post(url, data=payload, timeout=8)
        if res.status_code != 200:
            print(f"⚠️ Erro ao enviar Telegram: {res.text}")
    except Exception as e:
        print(f"⚠️ Exceção ao enviar mensagem Telegram: {e}")

def detectar_senioridade(texto):
    """Mapeia o nível de senioridade no título ou na descrição."""
    texto_norm = normalizar_texto(texto)
    
    if any(k in texto_norm for k in ["senior", "sênior", "lead", "principal", "head", "gerente", "coordenador"]):
        return "Sênior / Liderança 🛑"
    elif any(k in texto_norm for k in ["pleno", "pl", "mid", "level 2", "n2", "nivel 2"]):
        return "Pleno (N2) 🟢"
    elif any(k in texto_norm for k in ["junior", "júnior", "jr", "level 1", "n1", "nivel 1", "entry"]):
        return "Júnior (N1) 🟢"
    elif any(k in texto_norm for k in ["estagio", "estágio", "intern", "trainee"]):
        return "Estágio / Trainee 🟡"
    
    return "Júnior / Pleno (Geral) 🟢"

def calcular_score_fit(titulo, local, descricao, config):
    titulo_norm = normalizar_texto(titulo)
    desc_norm = normalizar_texto(descricao)
    local_norm = normalizar_texto(local)
    texto_completo = f"{titulo_norm} {desc_norm} {local_norm}"

    # 1. Verificar termos de exclusão
    for ex in config.get("termos_exclusao", []):
        if normalizar_texto(ex) in titulo_norm:
            return 0, f"Contém termo de exclusão '{ex}'"

    # 2. Verificar termos de busca no título
    termos_busca = [normalizar_texto(t) for t in config.get("termos_busca", [])]
    passou_termo = any(t in titulo_norm for t in termos_busca)
    if not passou_termo:
        return 0, "Título não bate com os termos de busca"

    # 3. Verificar localização / modalidade
    locais_permitidos = [normalizar_texto(l) for l in config.get("locais_permitidos", [])]
    passou_local = any(loc in texto_completo for loc in locais_permitidos)
    if not passou_local:
        return 0, f"Localização fora do perfil ({local})"

    # Pontuação dinâmica de Match (Base: 50%)
    score = 50

    # Modalidade
    if "remoto" in texto_completo or "home office" in texto_completo:
        score += 15

    # Contexto de Negócio & SaaS
    if "saas" in texto_completo or "software as a service" in texto_completo:
        score += 10

    # Ferramentas ITSM / Helpdesk
    if any(k in texto_completo for k in ["zendesk", "jira", "servicenow", "freshdesk"]):
        score += 10

    # Banco de Dados & Infra
    if any(k in texto_completo for k in ["sql", "postgresql", "mysql", "linux", "aws", "api", "rest"]):
        score += 10

    # Linguagens / Desenvolvimento
    if any(k in texto_completo for k in ["python", "kotlin", "salesforce"]):
        score += 5

    return min(score, 100), "Aprovada"

def analisar_modalidade(texto):
    texto_norm = normalizar_texto(texto)
    if "remoto" in texto_norm or "remote" in texto_norm or "home office" in texto_norm:
        return "Remoto 🏠"
    elif "hibrido" in texto_norm or "hybrid" in texto_norm:
        return "Híbrido 🔄"
    elif "presencial" in texto_norm or "on-site" in texto_norm:
        return "Presencial 🏢"
    return "Remoto / Não especificada 📍"

def extrair_stack_tecnologia(texto):
    tecnologias = ["python", "sql", "kotlin", "salesforce", "aws", "linux", "zendesk", "jira", "servicenow", "docker", "git", "saas", "api"]
    encontradas = []
    texto_norm = normalizar_texto(texto)
    for tech in tecnologias:
        if tech in texto_norm:
            encontradas.append(tech.upper() if len(tech) <= 4 else tech.capitalize())
    return ", ".join(encontradas) if encontradas else "Geral / Suporte Técnico"

# --- SCRAPERS / APIS ---

def buscar_gupy(termos, config):
    vagas = []
    print("🔎 Consultando Gupy (via Playwright)...", flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 820}
            )
            page = context.new_page()

            for termo in termos:
                try:
                    url = f"https://portal.gupy.io/job-search?jobName={requests.utils.quote(termo)}"
                    page.goto(url, wait_until="networkidle", timeout=25000)

                    cards = page.locator('a[href*="/job/"]').all()
                    for card in cards:
                        try:
                            link = card.get_attribute("href")
                            if not link:
                                continue
                            if not link.startswith("http"):
                                link = f"https://portal.gupy.io{link}"

                            titulo = card.inner_text().split("\n")[0] if card.inner_text() else termo
                            id_vaga = f"gupy_{link.split('/')[-1].split('?')[0]}"

                            vagas.append({
                                "id": id_vaga,
                                "titulo": titulo.strip(),
                                "plataforma": "Gupy",
                                "local": "Brasil / Remoto",
                                "link": link,
                                "descricao": f"{titulo} Gupy Remoto"
                            })
                        except Exception:
                            continue
                except Exception as e:
                    print(f"⚠️ Erro Gupy no termo '{termo}': {e}", flush=True)

            browser.close()
    except Exception as e_pw:
        print(f"⚠️ Falha geral no Playwright (Gupy): {e_pw}", flush=True)

    return vagas

def buscar_solides(termos, config):
    vagas = []
    print("🔎 Consultando Sólides...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for termo in termos:
        try:
            url = f"https://api.solides.jobs/v2/vacancies/search?title={requests.utils.quote(termo)}&take=20"
            res = requests.get(url, headers=headers, timeout=8)
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
            print(f"⚠️ Erro Sólides ({termo}): {e}", flush=True)
    return vagas

def buscar_linkedin(termos, config):
    vagas = []
    print("🔎 Scrapeando LinkedIn...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for termo in termos:
        try:
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={requests.utils.quote(termo)}&location=Brasil&geoId=106057199&start=0"
            res = requests.get(url, headers=headers, timeout=8)
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
            print(f"⚠️ Erro LinkedIn ({termo}): {e}", flush=True)
    return vagas

def buscar_remotar(termos, config):
    vagas = []
    print("🔎 Consultando Remotar...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for termo in termos:
        try:
            url = f"https://remotar.com.br/search?q={requests.utils.quote(termo)}"
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                cards = soup.find_all("a", href=re.compile(r'/job/'))
                for card in cards[:10]:
                    link = card["href"]
                    if not link.startswith("http"):
                        link = f"https://remotar.com.br{link}"
                    titulo = card.text.strip()
                    if titulo:
                        vaga_id = f"remotar_{link.split('/')[-1]}"
                        vagas.append({
                            "id": vaga_id,
                            "titulo": titulo,
                            "plataforma": "Remotar",
                            "local": "Remoto",
                            "link": link,
                            "descricao": f"{titulo} Remoto SaaS"
                        })
        except Exception as e:
            print(f"⚠️ Erro Remotar ({termo}): {e}", flush=True)
    return vagas

def buscar_coodesh(termos, config):
    vagas = []
    print("🔎 Consultando Coodesh...", flush=True)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for termo in termos:
        try:
            url = f"https://coodesh.com/api/v1/jobs/public?search={requests.utils.quote(termo)}&limit=15"
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200 and res.text.strip().startswith("{"):
                data = res.json()
                for item in data.get("jobs", []):
                    vaga_id = f"coodesh_{item.get('id')}"
                    titulo = item.get("title", "")
                    link = f"https://coodesh.com/vagas/{item.get('slug', '')}"
                    vagas.append({
                        "id": vaga_id,
                        "titulo": titulo,
                        "plataforma": "Coodesh",
                        "local": "Remoto / Brasil",
                        "link": link,
                        "descricao": f"{titulo} Tech Support"
                    })
        except Exception as e:
            print(f"⚠️ Erro Coodesh ({termo}): {e}", flush=True)
    return vagas

def main():
    config = carregar_configuracao()
    historico_hashes, historico_detalhado = carregar_historico()
    
    termos = config.get("termos_busca", ["suporte"])
    
    todas_vagas = []
    todas_vagas.extend(buscar_gupy(termos, config))
    todas_vagas.extend(buscar_solides(termos, config))
    todas_vagas.extend(buscar_linkedin(termos, config))
    todas_vagas.extend(buscar_remotar(termos, config))
    todas_vagas.extend(buscar_coodesh(termos, config))

    print(f"\n📊 Total de vagas capturadas de todas as fontes: {len(todas_vagas)}", flush=True)

    novas_vagas = 0

    for vaga in todas_vagas:
        hash_vaga = gerar_hash_deduplicacao(vaga["titulo"], vaga["local"])
        
        if hash_vaga in historico_hashes or vaga["id"] in historico_hashes:
            continue

        score, razao = calcular_score_fit(vaga["titulo"], vaga["local"], vaga["descricao"], config)
        
        if score > 0:
            modalidade = analisar_modalidade(vaga["local"] + " " + vaga["descricao"])
            senioridade = detectar_senioridade(vaga["titulo"] + " " + vaga["descricao"])
            stack = extrair_stack_tecnologia(vaga["descricao"])
            
            msg = (
                f"🎯 *NOVA VAGA ENCONTRADA* (Fit: {score}%)\n\n"
                f"📌 *Cargo:* {vaga['titulo']}\n"
                f"👤 *Senioridade:* {senioridade}\n"
                f"🏢 *Plataforma:* {vaga['plataforma']}\n"
                f"📍 *Modalidade:* {modalidade}\n"
                f"🛠️ *Stack / Ferramentas:* {stack}"
            )
            
            enviar_telegram(msg, link_vaga=vaga["link"])
            
            historico_hashes.add(hash_vaga)
            historico_hashes.add(vaga["id"])
            historico_detalhado.insert(0, {
                "id": vaga["id"],
                "hash": hash_vaga,
                "titulo": vaga["titulo"],
                "senioridade": senioridade,
                "plataforma": vaga["plataforma"],
                "local": vaga["local"],
                "score": score,
                "link": vaga["link"]
            })
            novas_vagas += 1
        else:
            print(f"❌ Rejeitada [{vaga['plataforma']}]: {vaga['titulo']} -> {razao}", flush=True)
            historico_hashes.add(hash_vaga)

    salvar_historico(historico_hashes, historico_detalhado)
    print(f"✅ Processamento finalizado! {novas_vagas} novas vagas enviadas ao Telegram.", flush=True)

if __name__ == "__main__":
    main()