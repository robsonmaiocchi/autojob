import os
import json
import re
import hashlib
import urllib.parse
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ==============================================================================
# CONFIGURAÇÕES E AMBIENTE
# ==============================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CONFIG_FILE = "config.json"
HISTORY_FILE = "history.json"

# Instância para geração de User-Agents aleatórios
ua = UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def get_headers():
    """Gera cabeçalhos HTTP dinâmicos para evitar bloqueios e simular navegação real."""
    return {
        "User-Agent": ua.random,
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, Exception)),
    reraise=False
)
def fetch_url(url, method="GET", json_data=None, params=None, timeout=12):
    """Realiza requisições HTTP com retry automático, backoff exponencial e User-Agent dinâmico."""
    headers = get_headers()
    if method.upper() == "POST":
        response = requests.post(url, json=json_data, headers=headers, params=params, timeout=timeout)
    else:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
    
    response.raise_for_status()
    return response

# ==============================================================================
# ALGORITMO DE PONTUAÇÃO DE RELEVÂNCIA (MATCH SCORE)
# ==============================================================================
PALAVRAS_CHAVE_PESO = {
    # Competências Técnicas e Termos Estratégicos (+20%)
    "saas": 20,
    "sql": 20,
    "helpdesk": 20,
    "sla": 15,
    "itsm": 15,
    "atendimento": 15,
    "customer success": 15,
    "suporte tecnico": 25,
    "technical support": 25,
    
    # Níveis de Experiência Alvo (+15%)
    "junior": 15,
    "jr": 15,
    "pleno": 15,
    "pl": 10,
    "analista": 10
}

def calcular_match_score(titulo, empresa, local):
    """Calcula uma pontuação de relevância de 0 a 100 baseada no título e contexto da vaga."""
    texto_completo = f"{titulo} {empresa} {local}".lower()
    score = 0

    for termo, peso in PALAVRAS_CHAVE_PESO.items():
        if termo in texto_completo:
            score += peso

    # Garantir limite de 0 a 100
    score = min(score, 100)

    # Definir selo/tag visual
    if score >= 70:
        badge = "🔥 Excelente (High Match)"
    elif score >= 40:
        badge = "🟡 Relevante (Medium Match)"
    else:
        badge = "⚪ Compatível (General Match)"

    return score, badge

# ==============================================================================
# LEITURA E GRAVAÇÃO DE ARQUIVOS
# ==============================================================================
def load_config():
    """Carrega as configurações do arquivo config.json."""
    default_config = {
        "termos_busca": ["Analista de Suporte Tecnico", "Suporte SaaS", "Suporte Tecnico", "Technical Support Analyst"],
        "locais": ["Remoto", "Imbituba", "Tubarão", "Joinville", "Curitiba"],
        "termos_excluir": ["Estágio", "Intern", "Sênior", "Senior", "Lead", "Coordenador", "Gerente", "Manager", "Especialista"],
        "plataformas": {
            "gupy": True,
            "solides": True,
            "linkedin": True,
            "indeed": True,
            "remotar": True,
            "coodesh": True
        }
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Erro ao ler {CONFIG_FILE}: {e}. Usando configuração padrão.")
    return default_config

def load_history():
    """Carrega o histórico de vagas processadas."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {"hashes": data, "detalhes": []}
                return data
        except Exception as e:
            print(f"⚠️ Erro ao ler {HISTORY_FILE}: {e}. Iniciando histórico novo.")
    return {"hashes": [], "detalhes": []}

def save_history(history):
    """Salva o histórico atualizado em history.json."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Erro ao salvar histórico: {e}")

def generate_hash(titulo, empresa, plataforma):
    """Gera um hash único para identificar duplicatas de vagas."""
    text = f"{titulo.strip().lower()}_{empresa.strip().lower()}_{plataforma.strip().lower()}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def send_telegram(mensagem, link_vaga):
    """Envia notificação para o Telegram com botões inline interativos."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Teclado com botão Inline para aplicação direta
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🚀 Candidatar-se Agora", "url": link_vaga}
            ]
        ]
    }

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup
    }

    try:
        res = fetch_url(url, method="POST", json_data=payload)
        if not res or not res.ok:
            print(f"❌ Erro ao enviar para o Telegram: {res.status_code if res else 'sem resposta'}")
    except Exception as e:
        print(f"❌ Exceção ao enviar Telegram: {e}")

def deve_excluir(titulo, termos_excluir):
    """Verifica se o título contém palavras banidas."""
    titulo_lower = titulo.lower()
    for termo in termos_excluir:
        if termo.lower() in titulo_lower:
            return True
    return False

# ==============================================================================
# SCRAPERS / CONSUMIDORES DE API PARA AS 6 PLATAFORMAS
# ==============================================================================

def buscar_gupy(termos, locais, termos_excluir):
    vagas = []
    base_url = "https://portal.api.gupy.io/api/v1/jobs"
    for termo in termos:
        params = {"jobName": termo, "limit": 20, "offset": 0}
        res = fetch_url(base_url, params=params)
        if not res or res.status_code != 200:
            continue
        try:
            data = res.json()
            for item in data.get("data", []):
                titulo = item.get("name", "")
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = item.get("careerPageName", "Gupy")
                link = item.get("jobUrl", "")
                local = item.get("city", "") or ("Remoto" if item.get("isRemote") else "Não informado")
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "Gupy"
                })
        except Exception as e:
            print(f"⚠️ Erro ao processar dados da Gupy para o termo '{termo}': {e}")
    return vagas

def buscar_solides(termos, locais, termos_excluir):
    vagas = []
    base_url = "https://vacancy-service.vagas.solides.com.br/api/v1/vacancies/search"
    for termo in termos:
        payload = {"title": termo, "take": 20, "page": 1}
        res = fetch_url(base_url, method="POST", json_data=payload)
        if not res or res.status_code != 200:
            continue
        try:
            data = res.json()
            items = data.get("data", []) if isinstance(data, dict) else data
            for item in items:
                titulo = item.get("title") or item.get("name", "")
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = item.get("company", {}).get("name") if isinstance(item.get("company"), dict) else "Sólides"
                link = item.get("link") or item.get("url", "")
                if link and not link.startswith("http"):
                    link = f"https://vagas.solides.com.br{link}"
                local = item.get("city", {}).get("name", "Não informado") if isinstance(item.get("city"), dict) else "Brasil"
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "Sólides"
                })
        except Exception as e:
            print(f"⚠️ Erro ao processar dados da Sólides para o termo '{termo}': {e}")
    return vagas

def buscar_linkedin(termos, locais, termos_excluir):
    vagas = []
    for termo in termos:
        termo_encoded = urllib.parse.quote(termo)
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={termo_encoded}&location=Brasil&start=0"
        res = fetch_url(url)
        if not res or res.status_code != 200:
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

def buscar_indeed(termos, locais, termos_excluir):
    vagas = []
    for termo in termos:
        termo_encoded = urllib.parse.quote(termo)
        url = f"https://br.indeed.com/jobs?q={termo_encoded}&l=Brasil"
        res = fetch_url(url)
        if not res or res.status_code != 200:
            continue
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.find_all("div", class_=re.compile("job_seen_beacon|result"))
        for card in cards:
            title_tag = card.find("h2", class_=re.compile("jobTitle"))
            company_tag = card.find("span", class_=re.compile("companyName|company_location"))
            link_tag = card.find("a", href=True)
            location_tag = card.find("div", class_=re.compile("companyLocation"))
            
            if title_tag and link_tag:
                titulo = title_tag.get_text(strip=True)
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = company_tag.get_text(strip=True) if company_tag else "Indeed"
                href = link_tag.get("href", "")
                link = f"https://br.indeed.com{href}" if href.startswith("/") else href
                local = location_tag.get_text(strip=True) if location_tag else "Brasil"
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local,
                    "link": link,
                    "plataforma": "Indeed"
                })
    return vagas

def buscar_remotar(termos, locais, termos_excluir):
    vagas = []
    for termo in termos:
        termo_encoded = urllib.parse.quote(termo)
        url = f"https://remotar.com.br/busca?q={termo_encoded}"
        res = fetch_url(url)
        if not res or res.status_code != 200:
            continue
        soup = BeautifulSoup(res.text, "html.parser")
        cards = soup.find_all("div", class_=re.compile("job-card|card"))
        for card in cards:
            title_tag = card.find(["h2", "h3", "a"], class_=re.compile("title|job-title"))
            company_tag = card.find(["span", "div"], class_=re.compile("company|employer"))
            link_tag = card.find("a", href=True)
            
            if title_tag and link_tag:
                titulo = title_tag.get_text(strip=True)
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = company_tag.get_text(strip=True) if company_tag else "Remotar"
                href = link_tag.get("href", "")
                link = f"https://remotar.com.br{href}" if href.startswith("/") else href
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": "Remoto",
                    "link": link,
                    "plataforma": "Remotar"
                })
    return vagas

def buscar_coodesh(termos, locais, termos_excluir):
    vagas = []
    url = "https://api.coodesh.com/v1/public/jobs"
    for termo in termos:
        params = {"search": termo, "limit": 20}
        res = fetch_url(url, params=params)
        if not res or res.status_code != 200:
            continue
        try:
            data = res.json()
            items = data.get("hits", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for item in items:
                titulo = item.get("title", "")
                if deve_excluir(titulo, termos_excluir):
                    continue
                empresa = item.get("company", {}).get("name", "Coodesh") if isinstance(item.get("company"), dict) else "Coodesh"
                slug = item.get("slug", "")
                link = f"https://coodesh.com/vagas/{slug}" if slug else "https://coodesh.com/vagas"
                local = item.get("homeOffice", False)
                local_str = "Remoto" if local else "Presencial/Híbrido"
                vagas.append({
                    "titulo": titulo,
                    "empresa": empresa,
                    "local": local_str,
                    "link": link,
                    "plataforma": "Coodesh"
                })
        except Exception as e:
            print(f"⚠️ Erro ao processar dados da Coodesh para o termo '{termo}': {e}")
    return vagas

# ==============================================================================
# REGISTRO E EXECUÇÃO PRINCIPAL
# ==============================================================================
def main():
    print("🚀 Iniciando varredura de vagas com AutoJob...")
    config = load_config()
    history = load_history()
    
    termos = config.get("termos_busca", [])
    locais = config.get("locais", [])
    termos_excluir = config.get("termos_excluir", [])
    plataformas_ativas = config.get("plataformas", {})

    vagas_encontradas = []

    # Executa cada plataforma se estiver ativa nas configurações
    if plataformas_ativas.get("gupy", True):
        print("🔎 Buscando na Gupy...")
        vagas_encontradas.extend(buscar_gupy(termos, locais, termos_excluir))

    if plataformas_ativas.get("solides", True):
        print("🔎 Buscando na Sólides...")
        vagas_encontradas.extend(buscar_solides(termos, locais, termos_excluir))

    if plataformas_ativas.get("linkedin", True):
        print("🔎 Buscando no LinkedIn...")
        vagas_encontradas.extend(buscar_linkedin(termos, locais, termos_excluir))

    if plataformas_ativas.get("indeed", True):
        print("🔎 Buscando no Indeed...")
        vagas_encontradas.extend(buscar_indeed(termos, locais, termos_excluir))

    if plataformas_ativas.get("remotar", True):
        print("🔎 Buscando na Remotar...")
        vagas_encontradas.extend(buscar_remotar(termos, locais, termos_excluir))

    if plataformas_ativas.get("coodesh", True):
        print("🔎 Buscando na Coodesh...")
        vagas_encontradas.extend(buscar_coodesh(termos, locais, termos_excluir))

    print(f"📊 Total de vagas capturadas antes da desduplicação: {len(vagas_encontradas)}")

    novas_vagas_count = 0
    hashes_existentes = set(history.get("hashes", []))
    detalhes_recentes = history.get("detalhes", [])

    for vaga in vagas_encontradas:
        h = generate_hash(vaga["titulo"], vaga["empresa"], vaga["plataforma"])
        if h not in hashes_existentes:
            hashes_existentes.add(h)
            novas_vagas_count += 1

            # Calcula a relevância da vaga
            score, badge = calcular_match_score(vaga["titulo"], vaga["empresa"], vaga["local"])

            # Monta notificação do Telegram com Match Score
            msg = (
                f"🎯 <b>Nova Vaga Encontrada!</b>\n\n"
                f"📌 <b>Título:</b> {vaga['titulo']}\n"
                f"🏢 <b>Empresa:</b> {vaga['empresa']}\n"
                f"📍 <b>Local:</b> {vaga['local']}\n"
                f"🌐 <b>Plataforma:</b> {vaga['plataforma']}\n"
                f"📊 <b>Match Score:</b> {score}% ({badge})"
            )
            
            send_telegram(msg, vaga["link"])
            import time
            time.sleep(1) # Intervalo suave entre mensagens para evitar Rate Limit do Telegram

            # Adiciona aos detalhes do histórico
            detalhes_recentes.insert(0, {
                "titulo": vaga["titulo"],
                "empresa": vaga["empresa"],
                "plataforma": vaga["plataforma"],
                "link": vaga["link"],
                "score": score,
                "data": datetime.now().strftime("%Y-%m-%d %H:%M")
            })

    # Mantém apenas os 50 detalhes mais recentes no history.json
    history["hashes"] = list(hashes_existentes)
    history["detalhes"] = detalhes_recentes[:50]
    
    save_history(history)

    print(f"✅ Processamento concluído. {novas_vagas_count} novas vagas notificadas com pontuação de relevância.")

if __name__ == "__main__":
    main()