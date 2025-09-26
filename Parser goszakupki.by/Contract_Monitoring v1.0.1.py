import asyncio
import aiohttp
import tkinter as tk
from tkinter import ttk, messagebox
import logging
import json
import ssl, certifi, sys
import os
import webbrowser
import threading
from aiohttp import BasicAuth
from bs4 import BeautifulSoup
from aiohttp.client_exceptions import ClientConnectorCertificateError
from enum import Enum
from dataclasses import dataclass
import random
from typing import Optional, List, Dict
import async_timeout


# -------------------- Config --------------------

# Global lockout for reauthorization
_auth_lock_ref = {"lock": None}

def get_auth_lock():
    lock = _auth_lock_ref.get("lock")
    if lock is None:
        # create a lock in the current event loop
        _auth_lock_ref["lock"] = asyncio.Lock()
    return _auth_lock_ref["lock"]


DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
CONFIG_FILE = "config.json"
CACHE_FILE = "cache.json"

logging.basicConfig(
    filename="parser.log",
    level=logging.INFO,
    encoding="utf-8",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

READY_CACHE: set[str] = set()
NEED_STATEMENT_CACHE: set[str] = set()
WAITING_CACHE: set[str] = set()


# -------------------- Utilities --------------------
def get_browser_headers() -> dict:
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ru',
        'Connection': 'keep-alive',
    }


def get_certifi_path() -> str:
    # In exe files, they are unpacked into the temporary folder sys._MEIPASS.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")
        if os.path.exists(candidate):
            return candidate
    # Normal startup from Python/venv
    return certifi.where()

def build_ssl_context() -> ssl.SSLContext:
    cafile = get_certifi_path()
    logging.info(f"[SSL] Using CA file: {cafile}")
    ctx = ssl.create_default_context(cafile=cafile)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx

async def request_text(session: aiohttp.ClientSession, url: str,
                       *, proxy: Optional[str], proxy_auth: Optional[BasicAuth],
                       timeout: int = 30, allow_redirects: bool = True):
    async with session.get(
        url,
        headers=get_browser_headers(),
        proxy=proxy,
        proxy_auth=proxy_auth,
        allow_redirects=allow_redirects,
        timeout=timeout
    ) as resp:
        text = await resp.text()
        return text, resp.status, str(resp.url)


async def safe_get(
    session: aiohttp.ClientSession,
    url: str,
    retries: int = 3,
    timeout: int = 30,
    delay_base: float = 1.5,
    allow_redirects: bool = True,
    proxy: Optional[str] = None,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    proxy_auth: Optional[BasicAuth] = None,
) -> Optional[str]:
    """
    Secure GET with SSL/network error handling, 50x, timeouts, and proxies.
    - proxy: string in the format “http://host:port” or None.
    - proxy_auth: BasicAuth for the Proxy-Authorization header (recommended).
    """
    for attempt in range(1, retries + 1):
        try:
            async with async_timeout.timeout(timeout):
                async with session.get(
                    url,
                    allow_redirects=allow_redirects,
                    proxy=proxy,
                    proxy_auth=proxy_auth,
                    headers=headers,
                    params=params,
                ) as resp:
                    text = await resp.text()
                    final_url = str(resp.real_url)
                    status = resp.status

                    if status == 200:
                        return text

                    if status == 407:
                        logging.error(f"GET {url} через прокси ({proxy}) → HTTP 407 Proxy Auth Required. Без повторов.")
                        raise aiohttp.ClientHttpProxyError(request_info=resp.request_info, history=(), code=407,
                                                           message="Proxy Authentication Required",
                                                           headers=resp.headers)

                    if status in (502, 503, 504):
                        logging.warning(
                            f"GET {url} → HTTP {status} ({resp.reason}), final={final_url}. "
                            f"Попытка {attempt}/{retries}"
                        )
                    else:
                        logging.error(
                            f"GET {url} → HTTP {status} ({resp.reason}), final={final_url}. Без повторов."
                        )
                        return None

        except (aiohttp.ClientConnectorCertificateError, ssl.SSLCertVerificationError) as e:
            logging.error(f"SSL verification error on GET {url}: {e}. Без повторов.")
            return None

        except (aiohttp.ClientHttpProxyError, aiohttp.ClientProxyConnectionError) as e:
            logging.warning(
                f"Прокси-ошибка при GET {url} через {proxy}: {e}. Попытка {attempt}/{retries}"
            )

        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, aiohttp.ClientOSError) as e:
            logging.warning(
                f"Сетевой сбой при GET {url}: {e}. Попытка {attempt}/{retries}"
            )

        except asyncio.TimeoutError as e:
            logging.warning(
                f"Таймаут при GET {url} (timeout={timeout}s): {e}. "
                f"Попытка {attempt}/{retries}"
            )

        except Exception as e:
            logging.error(f"Ошибка при GET {url}: {type(e).__name__}: {e}")
            if attempt >= retries:
                return None

        if attempt < retries:
            sleep_s = min(10.0, delay_base * (2 ** (attempt - 1))) + random.uniform(0.0, 0.5)
            await asyncio.sleep(sleep_s)

    return None


# -------------------- Model --------------------
@dataclass
class Contract:
    contract_id: str
    title: str
    signable: bool
    sign_url: Optional[str] = None


# -------------------- Cash --------------------

def load_cache():
    global READY_CACHE, NEED_STATEMENT_CACHE, WAITING_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            data = json.load(open(CACHE_FILE, encoding="utf-8"))
            READY_CACHE = set(data.get("ready", []))
            NEED_STATEMENT_CACHE = set(data.get("need_statement", []))
            WAITING_CACHE = set(data.get("waiting", []))
            logging.info("Кэш загружен")
        except Exception as e:
            logging.error(f"Ошибка чтения кэша: {e}")

def save_cache():
    data = {
        "ready": list(READY_CACHE),
        "need_statement": list(NEED_STATEMENT_CACHE),
        "waiting": list(WAITING_CACHE),
    }
    try:
        json.dump(data, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        logging.info("Кэш сохранён")
    except Exception as e:
        logging.error(f"Ошибка сохранения кэша: {e}")


def _read_config() -> dict:
    """Reads the entire config.json file."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return {}
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Ошибка чтения {CONFIG_FILE}: {e}")
        return {}


def _write_config(cfg: dict):
    """Writes the entire config.json file."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка записи {CONFIG_FILE}: {e}")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_proxies() -> List[Dict[str, str]]:
    """
    Returns a list of proxies from config.json in the format:
    [
      {"scheme": "http", "host": "1.2.3.4", "port": "8080", "username": "u", "password": "p"},
      ...
    ]
    """
    cfg = load_config()
    return cfg.get("proxies", [])


def save_proxies(proxies: List[Dict[str, str]]) -> None:
    """
    Saves configuration of proxy in config.json
    :param proxies:
    :return: None
    """
    cfg = load_config()
    cfg["proxies"] = proxies
    save_config(cfg)


def load_proxy_usage_enabled() -> bool:
    """
    Checks the possibility of using a proxy from config.json
    :return: bool
    """
    cfg = load_config()
    return bool(cfg.get("use_proxies", False))


def save_proxy_usage_enabled(enabled: bool) -> None:
    """
    Saves data about the possibility of using a proxy in config.json
    :param enabled:
    :return: None
    """
    cfg = load_config()
    cfg["use_proxies"] = bool(enabled)
    save_config(cfg)


def is_valid_proxy_dict(p: Dict[str, str]) -> bool:
    """
    Checks for the presence of a dictionary with proxy data
    :param p: Dict[str, str]
    :return: bool
    """
    if not p:
        return False
    scheme = (p.get("scheme") or "").strip().lower()
    host = (p.get("host") or "").strip()
    port = (p.get("port") or "").strip()
    if scheme not in ("http", "https"):
        return False
    if not host or not port.isdigit():
        return False
    return True


def format_proxy_url(proxy: Dict[str, str]) -> str:
    """
    Generates a proxy URL WITHOUT a login/password.
    Example: http://194.156.97.230:1050
    :param proxy: Dict[str, str]
    :return: str
    """
    scheme = (proxy.get("scheme") or "http").strip().lower()
    host = (proxy.get("host") or "").strip()
    port = (proxy.get("port") or "").strip()

    if scheme not in ("http", "https") or not host or not port.isdigit():
        raise ValueError(f"Invalid proxy settings: scheme='{scheme}', host='{host}', port='{port}'")

    return f"{scheme}://{host}:{port}"


def build_proxy_auth(proxy: Dict[str, str]) -> Optional[BasicAuth]:
    """
    Creates a BasicAuth object for the Proxy-Authorization header.
    If the login/password is empty, returns None.
    """
    user = (proxy.get("username") or "").strip()
    pwd  = (proxy.get("password") or "").strip()
    if user or pwd:
        return BasicAuth(user, pwd, encoding="utf-8")
    return None


def choose_random_proxy(proxies: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Selects a random proxy from the list/dictionary
    :param proxies:
    :return:str
    """
    return random.choice(proxies) if proxies else None


def save_credentials(username: str, password: str):
    """Saves login/password in the credentials section
    :param username: str
    :param password:str
    :return: None
    """

    try:
        cfg = _read_config()
        cfg.setdefault("credentials", {})
        cfg["credentials"]["username"] = username
        cfg["credentials"]["password"] = password
        _write_config(cfg)
        logging.info("Учётные данные сохранены в config.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения учётных данных: {e}")


def load_credentials():
    """Returns a dict with username/password or None from the credentials section
       if username/password is stored there, else None.
    """
    try:
        cfg = _read_config()
        creds = cfg.get("credentials", {})
        if creds.get("username") and creds.get("password"):
            return creds
        return None
    except Exception as e:
        logging.error(f"Ошибка загрузки учётных данных: {e}")
        return None


def delete_credentials():
    """Removes the credentials section, keeps the rest"""
    try:
        cfg = _read_config()
        if "credentials" in cfg:
            cfg.pop("credentials", None)
            _write_config(cfg)
            logging.info("Сохранённые учётные данные удалены")
    except Exception as e:
        logging.error(f"Ошибка удаления учётных данных: {e}")


# -------------------- Session --------------------
async def create_aiohttp_session(verify_ssl: bool = True) -> aiohttp.ClientSession:
    """

    :param verify_ssl: bool
    :return: aiohttp.ClientSession
    """
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    if verify_ssl:
        ssl_context = build_ssl_context()
        connector = aiohttp.TCPConnector(ssl=ssl_context)
    else:
        logging.warning("[SSL] Using INSECURE connector (ssl=False)")
        connector = aiohttp.TCPConnector(ssl=False)

    # ВАЖНО: trust_env=False — игнорируем системные прокси из переменных окружения
    return aiohttp.ClientSession(
        timeout=DEFAULT_TIMEOUT,
        headers=get_browser_headers(),
        cookie_jar=cookie_jar,
        raise_for_status=False,
        connector=connector,
        trust_env=False,
    )


# -------------------- Authorization --------------------
class AuthManager:
    def __init__(self, use_proxies: bool = False):
        self.use_proxies = bool(use_proxies)
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self.current_proxy_auth: Optional[BasicAuth] = None
        self.current_proxy_url: Optional[str] = None
        self.is_authenticated = False


    def _get_session_lock(self) -> asyncio.Lock:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        return self._session_lock


    def _select_proxy(self):
        self.current_proxy_url = None
        self.current_proxy_auth = None

        if not (self.use_proxies and load_proxy_usage_enabled()):
            logging.info("[PROXY] Работа без прокси")
            return

        all_proxies = load_proxies()
        valid = [p for p in all_proxies if is_valid_proxy_dict(p)]
        if not valid:
            logging.warning("[PROXY] Нет валидных прокси в config.json. Работа без прокси.")
            return

        # БЕРЁМ ТОЛЬКО ПРОКСИ С ЛОГИНОМ/ПАРОЛЕМ, иначе гарантированно будет 407
        with_creds = [p for p in valid if (p.get("username") or p.get("password"))]
        if not with_creds:
            logging.warning("[PROXY] В списке нет прокси с логином/паролем. Работа без прокси.")
            return

        choice = choose_random_proxy(with_creds)
        try:
            self.current_proxy_url = format_proxy_url(choice)  # без логина/пароля в URL
            self.current_proxy_auth = build_proxy_auth(choice)  # BasicAuth
            logging.info(f"[PROXY] Using proxy: {self.current_proxy_url} (with auth)")
        except Exception as e:
            logging.error(f"[PROXY] Некорректный прокси: {choice} → {e}. Работа без прокси.")
            self.current_proxy_url = None
            self.current_proxy_auth = None

    async def _try_login_with_session(self, username: str, password: str) -> bool:
        """
        Attempts to log in to the current self.session using the selected proxy.
        Handles 407 responses from the proxy (proxy rotation), SSL errors, and unsuccessful responses.
        """
        login_url = "https://goszakupki.by/site/login"

        # 1) GET login form (via proxy + proxy_auth)
        try:
            html = await safe_get(
                self.session,
                login_url,
                proxy=self.current_proxy_url,
                proxy_auth=self.current_proxy_auth,
            )
        except aiohttp.ClientHttpProxyError as e:
            if e.code == 407:
                logging.warning("Proxy вернул 407 на GET формы — пробуем другой прокси")
                self._select_proxy()  # select a new proxy for the next attempt
                return False
            raise

        if not html:
            logging.error("Не удалось загрузить страницу логина (пустой ответ)")
            return False

        soup = BeautifulSoup(html, "html.parser")

        # 2) Collecting form data
        data = {"LoginForm[username]": username, "LoginForm[password]": password}
        for inp in soup.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            if name:
                data[name] = inp.get("value", "")

        # 3) POST of login
        try:
            headers = get_browser_headers() | {"Referer": login_url}
            async with self.session.post(
                    login_url,
                    data=data,
                    headers=headers,
                    allow_redirects=True,
                    proxy=self.current_proxy_url,
                    proxy_auth=self.current_proxy_auth,
            ) as resp:
                final_url = str(resp.url)
                text = await resp.text()

                if resp.status == 407:
                    logging.warning("Proxy вернул 407 на POST логина — пробуем другой прокси")
                    self._select_proxy()
                    return False

                # If after POST we are left at /site/login — authorization failed
                if "site/login" in final_url:
                    logging.warning("Авторизация не удалась: остались на странице логина")
                    return False

                # Simple markers of successful entry
                if any(w in text.lower() for w in ("выход", "logout", "личный кабинет")):
                    self.is_authenticated = True
                    logging.info("Авторизация успешна")
                    return True

                logging.warning("Авторизация не удалась: маркеры успеха не найдены")
                return False

        except aiohttp.ClientHttpProxyError as e:
            if e.code == 407:
                logging.warning("Proxy вернул 407 (исключение) на POST — пробуем другой прокси")
                self._select_proxy()
                return False
            raise
        except (ClientConnectorCertificateError, ssl.SSLCertVerificationError) as e:
            logging.error(f"SSL ошибка при POST логина: {e}")
            return False
        except Exception as e:
            logging.error(f"Ошибка авторизации: {e}")
            return False


    async def login(self, username: str, password: str, keep_proxy: bool = False) -> bool:
        """
        Attempts to log in. Up to 3 iterations:
        - On each iteration, create a new session with verify_ssl=True;
        - If unsuccessful, try verify_ssl=False with the same proxy;
        - If still unsuccessful, proceed to the next iteration.
        _try_login_with_session can change the proxy (to 407) via self._select_proxy().
        """
        attempts = 0
        while attempts < 3:
            # Proxy selection: if you don't have a current proxy or don't have one yet, select one.
            if (not keep_proxy) or (not self.current_proxy_url):
                self._select_proxy()

            # 1) Attempt with verified SSL
            async with self._get_session_lock():
                if self.session and not self.session.closed:
                    try:
                        await self.session.close()
                    except Exception:
                        pass
                self.session = await create_aiohttp_session(verify_ssl=True)

            ok = await self._try_login_with_session(username, password)
            if ok:
                self._ensure_keepalive()
                return True

            # 2) Fallback: insecure SSL (with the same proxy)
            async with self._get_session_lock():
                try:
                    if self.session and not self.session.closed:
                        await self.session.close()
                except Exception:
                    pass
                self.session = await create_aiohttp_session(verify_ssl=False)

            ok = await self._try_login_with_session(username, password)
            if ok:
                self._ensure_keepalive()
                return True

            # Close the session before the next iteration
            async with self._get_session_lock():
                try:
                    if self.session and not self.session.closed:
                        await self.session.close()
                except Exception:
                    pass
                self.session = None

            # The next iteration (the proxy may have already changed to 407 inside _try_login_with_session)
            attempts += 1

        # All attempts have been exhausted.
        self.is_authenticated = False
        return False

    async def close(self):
        async with self._get_session_lock():
            if self._keepalive_task and not self._keepalive_task.done():
                self._keepalive_task.cancel()
                try:
                    await self._keepalive_task
                except Exception:
                    pass
                self._keepalive_task = None

            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None
            self.is_authenticated = False


    async def _keep_session_alive(self, interval_sec: int = 150):
        ping_url = "https://goszakupki.by/site/index"
        while True:
            await asyncio.sleep(interval_sec)
            try:
                if not self.session or self.session.closed:
                    continue
                async with self.session.get(
                        ping_url,
                        headers=get_browser_headers(),
                        proxy=self.current_proxy_url,
                        proxy_auth=self.current_proxy_auth,
                        allow_redirects=False,
                        timeout=15,
                ) as resp:
                    _ = await resp.text()
            except Exception:
                # тихо
                pass

    def _ensure_keepalive(self):
        if not self._keepalive_task or self._keepalive_task.done():
            # create a task in the current loop
            self._keepalive_task = asyncio.create_task(self._keep_session_alive(150))


    async def get_my_contracts_page(self) -> Optional[str]:
        """Access to the filter page where contracts that need to be signed at the moment are stored"""
        if not self.is_authenticated:
            return None

        url = (
            "https://goszakupki.by/contracts/my-contracts"
            "?ContractSearch%5BcontractInnerNum%5D="
            "&ContractSearch%5BsubjectDescription%5D="
            "&ContractSearch%5Bauction_id%5D="
            "&ContractSearch%5Btype%5D="
            "&ContractSearch%5Bstatus%5D%5B%5D=signedByCustomer"
            "&ContractSearch%5Bstatus%5D%5B%5D=rejectedByWinner"
            "&ContractSearch%5Bcustomer_unp%5D="
            "&ContractSearch%5BunpProvider%5D="
            "&ContractSearch%5Bdate_customer_from%5D="
            "&ContractSearch%5Bdate_customer_to%5D="
            "&ContractSearch%5Bdate_provider_from%5D="
            "&ContractSearch%5Bdate_provider_to%5D="
        )

        html = await safe_get(
            self.session, url, retries=3,
            proxy=self.current_proxy_url,
            proxy_auth=self.current_proxy_auth,  # ВАЖНО
        )
        if html and "site/login" in html:
            self.is_authenticated = False
            return None
        return html


# -------------------- Parsing --------------------

class ContractSignStatus(str, Enum):
    READY = "ready_to_sign"
    AWAIT_DECISION = "awaiting_decision"
    NEEDS_STATEMENT = "needs_statement"
    UNKNOWN = "unknown"

def _has_visible_sign_button(soup: BeautifulSoup) -> bool:
    """
    Sign of readiness: REAL contract signing button.
    We allow:
      - an element with id=‘file-sign-0’ (main signature trigger),
      - or buttons/links in the #contractPanel / #contarctFiles block, whose text is exactly ‘Sign’ or contains ‘Sign contract’.
    Exclude:
      - any buttons of the type ‘Sign objections’, ‘Sign ...’ in modals/footers.
    """
    # 1) Exact id
    el = soup.select_one("#file-sign-0")
    if el:
        cls = " ".join(el.get("class", [])).lower()
        style = (el.get("style") or "").lower()
        if "disabled" not in cls and not el.has_attr("disabled"):
            if not any(s in style for s in ("display:none", "visibility:hidden", "pointer-events:none", "opacity:0")):
                return True

    # 2) Buttons/links in the document block
    containers = []
    cp = soup.select_one("#contractPanel")
    if cp:
        containers.append(cp)
    cf = soup.select_one("#contarctFiles")
    if cf:
        containers.append(cf)

    candidate_buttons = []
    for cont in containers:
        candidate_buttons.extend(cont.select("a.btn, button.btn, a.button, button.button"))

    def looks_like_sign_button(el) -> bool:
        text = (el.get_text(" ", strip=True) or "").lower()
        if not text:
            return False
        # Hard exceptions
        if "возражени" in text:
            return False
        # We accept strictly ‘sign’ or a phrase containing the word ‘agreement’.
        if text == "подписать":
            pass
        elif "подписать" in text and "договор" in text:
            pass
        else:
            return False

        cls = " ".join(el.get("class", [])).lower()
        if "disabled" in cls or el.has_attr("disabled"):
            return False
        style = (el.get("style") or "").lower()
        if any(s in style for s in ("display:none", "visibility:hidden", "pointer-events:none", "opacity:0")):
            return False
        return True

    for el in candidate_buttons:
        if looks_like_sign_button(el):
            return True

    return False


def _find_main_panels(soup: BeautifulSoup):
    """
    Returns a tuple (proposal_block, signing_block):
      - proposal_block: ‘Proposal to conclude a contract’ panel
      - signing_block: ‘To sign the contract, you must’ panel
    Search for the header <b> inside .panel-heading.
    """
    proposal_block = None
    signing_block = None
    for div in soup.select("div.panel"):
        b = div.select_one("div.panel-heading > b")
        if not b:
            continue
        t = b.get_text(strip=True)
        if "Предложение о заключении договора" in t:
            proposal_block = div
        elif "Для подписания договора необходимо" in t:
            signing_block = div
    return proposal_block, signing_block


def _is_waiting_decision_by_step(soup: BeautifulSoup) -> bool:
    proposal_block, signing_block = _find_main_panels(soup)
    root = proposal_block or signing_block
    if not root:
        return False
    for li in root.select("div.panel.panel-info div.panel-body ol li"):
        txt = li.get_text(" ", strip=True).lower()
        if "получить его решение" in txt or "получить решение заказчика" in txt:
            icon = li.select_one("i, span")
            classes = " ".join((icon.get("class") or [])) if icon else ""
            classes = classes.lower()
            if any(k in classes for k in ("glyphicon-remove", "fa-times", "text-danger")):
                return True
    return False

def classify_contract_sign_page(html: str) -> ContractSignStatus:
    """
    Strict determination of 4 statuses based on DOM markup.
    Priority:
      1) If the ‘Sign’ button is active → READY.
      2) If there are no panels and no buttons → UNKNOWN (it is better to double-check the page).
      3) If there are panels, apply the rules from the technical specifications.
    """
    if not html:
        return ContractSignStatus.UNKNOWN

    soup = BeautifulSoup(html, "html.parser")

    # 0) Strong READY signal
    if _has_visible_sign_button(soup):
        return ContractSignStatus.READY

    # 1) Find the panels
    proposal_block, signing_block = _find_main_panels(soup)

    # If both panels are missing and there is no button, the status is unclear.
    if not proposal_block and not signing_block:
        return ContractSignStatus.UNKNOWN

    # Auxiliary extractions from panels
    def extract_steps(panel: BeautifulSoup):
        """
        Returns:
          has_statement_step_ok: whether the ‘statement’ step has been completed (green check mark)
          has_payment_step: whether the ‘payment’ step exists at all
          payment_ok: if the payment step exists, whether it has been completed
          payment_fail: if the payment step exists, whether it has failed (red cross)
        """
        has_statement_step_ok = False
        has_payment_step = False
        payment_ok = False
        payment_fail = False

        if not panel:
            return has_statement_step_ok, has_payment_step, payment_ok, payment_fail

        # Inside the panel with steps, usually: .panel.panel-info .panel-body ol li
        li_items = panel.select("div.panel.panel-info div.panel-body ol li")
        for li in li_items:
            li_text = li.get_text(" ", strip=True).lower()
            icon = li.select_one("i, span")
            classes = " ".join((icon.get("class") or [])).lower() if icon else ""

            # Step 'statement'
            if "заявлен" in li_text or "заявить о соответствии" in li_text or "направить заказчику заявление" in li_text:
                if "glyphicon-ok" in classes or "text-success" in classes or "fa-check" in classes:
                    has_statement_step_ok = True
                elif "glyphicon-remove" in classes or "text-danger" in classes or "fa-times" in classes:
                    has_statement_step_ok = False  # явно не выполнен
                else:
                    # Нет явной зелёной галочки — трактуем как не выполнен
                    has_statement_step_ok = False

            # Step 'payment'
            if "оплатить услугу оператора" in li_text or "счет-фактура" in li_text or "счёт-фактура" in li_text:
                has_payment_step = True
                if "glyphicon-ok" in classes or "text-success" in classes or "fa-check" in classes:
                    payment_ok = True
                if "glyphicon-remove" in classes or "text-danger" in classes or "fa-times" in classes:
                    payment_fail = True

        return has_statement_step_ok, has_payment_step, payment_ok, payment_fail

    # “Application sent” indicator (panel 2 — footer with help block)
    def has_statement_sent(_proposal_block: BeautifulSoup) -> bool:
        if not _proposal_block:
            return False
        footer = _proposal_block.select_one("div.panel-footer")
        if not footer:
            return False
        spans = footer.find_all("span")
        return any("заявление о соответствии направлено" in s.get_text(strip=True).lower() for s in spans)

    statement_sent = has_statement_sent(proposal_block)

    # Let's examine the states of steps. Steps can be drawn in either of the two panels.
    st_ok_1, pay_step_1, pay_ok_1, pay_fail_1 = extract_steps(signing_block)
    st_ok_2, pay_step_2, pay_ok_2, pay_fail_2 = extract_steps(proposal_block)

    statement_ok = st_ok_1 or st_ok_2
    payment_step_present = pay_step_1 or pay_step_2
    payment_ok = pay_ok_1 or pay_ok_2
    payment_fail = pay_fail_1 or pay_fail_2

    # Category 4) Awaiting payment:
    # The application has been approved (green check mark), and the payment step is present and marked with a red cross.
    if statement_ok and payment_step_present and payment_fail and not _has_visible_sign_button(soup):
        # In the current UI, we do not have a separate category for payment, so
        # Leave AWAIT_DECISION as the closest (so as not to lose it),
        # but logically it is “Awaiting payment.” If desired, you can create a new Enum.
        return ContractSignStatus.AWAIT_DECISION

    # Category 3) Application requires review:
    # The ‘statement’ step has not yet been marked with a green check mark, but in panel 2 there is a help block ‘statement ... sent’.
    if not statement_ok and statement_sent:
        return ContractSignStatus.AWAIT_DECISION

    # Category 2) Requires an application:
    # The panels are there, the ‘statement’ step has not been completed, and the help block is missing.
    if (proposal_block or signing_block) and not statement_ok and not statement_sent:
        return ContractSignStatus.NEEDS_STATEMENT

    # Category 1) Ready for signature:
    # If you got here without an active button, we assume that all conditions are still green.
    if statement_ok and (not payment_step_present or payment_ok):
        return ContractSignStatus.READY

    # Otherwise, an incomprehensible state
    return ContractSignStatus.UNKNOWN


async def fetch_html_with_reauth(auth, app, url: str, *, retries: int = 2, timeout: int = 30) -> Optional[str]:
    """
    Gets HTML and reauthorizes ONLY if you hit the login page (/site/login),
    or got a 401/440, or the login form is visible in HTML. On 403 — we do NOT reauthorize.
    Protection against races — _auth_lock.
    """
    def needs_login(resp_status: int, final_url: str, text: str) -> bool:
        if resp_status in (401, 440):
            return True
        if "site/login" in (final_url or ""):
            return True
        tl = (text or "").lower()
        if "loginform[username]" in tl or "loginform[password]" in tl:
            return True
        return False

    for attempt in range(1, retries + 1):
        try:
            text, status, final_url = await request_text(
                auth.session, url,
                proxy=auth.current_proxy_url,
                proxy_auth=auth.current_proxy_auth,
                timeout=timeout,
                allow_redirects=True
            )

            if status == 403:
                logging.error(f"GET {url} → HTTP 403 (Forbidden), final={final_url}. Без реавторизации.")
                return None

            if needs_login(status, final_url, text):
                logging.info(f"[REAUTH] Требуется переавторизация для {url} (попытка {attempt}/{retries})")
                # Reset the flag, otherwise you may get stuck with a stale session.
                auth.is_authenticated = False
                async with get_auth_lock():
                    ok = await auth.login(app.username.get(), app.password.get(), keep_proxy=True)
                    if not ok:
                        logging.error("[REAUTH] Переавторизация не удалась")
                        return None
                continue

            return text

        except aiohttp.ClientHttpProxyError as e:
            if e.code == 407:
                logging.warning(f"[REAUTH] 407 от прокси на {url}. Ротация прокси и повтор.")
                async with get_auth_lock():
                    try:
                        async with auth._get_session_lock():
                            if auth.session and not auth.session.closed:
                                await auth.session.close()
                            auth.session = None
                    except Exception:
                        pass
                    ok = await auth.login(app.username.get(), app.password.get(), keep_proxy=False)
                    if not ok:
                        return None
                continue
            else:
                logging.error(f"[REAUTH] Прокси-ошибка {e} на {url}")
                return None

        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
            logging.warning(f"[REAUTH] Сетевая ошибка на {url}: {e}. Попытка {attempt}/{retries}")
            await asyncio.sleep(0.7 * attempt)
            continue

        except Exception as e:
            logging.error(f"[REAUTH] Неожиданная ошибка на {url}: {e}")
            return None

    return None


def parse_sign_conditions_html(html: str) -> dict:
    result = {"ready": False, "need_statement": False, "waiting_statement": False, "title": ""}
    try:
        if not html:
            return result
        if "Нет доступа к данному разделу сайта" in html:
            result["title"] = "Недоступно"
            return result

        soup = BeautifulSoup(html, "html.parser")

        contract_number = ""
        subject = ""
        for bold in soup.find_all("b"):
            title_text = bold.get_text(strip=True)
            if title_text == "Информация о договоре":
                table = bold.find_next("table")
                if not table:
                    break
                for row in table.find_all("tr"):
                    th = row.find("th"); td = row.find("td")
                    if not th or not td:
                        continue
                    header = th.get_text(" ", strip=True).lower()
                    value = td.get_text(" ", strip=True)
                    if "номер договора" in header:
                        contract_number = value
                    elif "наименование заказчика" in header:
                        subject = value
                break

        parts = []
        if contract_number: parts.append(contract_number)
        if subject: parts.append(subject)
        result["title"] = " — ".join(parts) if parts else "Без названия"

        proposal_block = None
        signing_block = None
        for div in soup.select("body > div > div > div"):
            b = div.select_one("div.panel-heading > b")
            if not b: continue
            t = b.get_text(strip=True)
            if "Предложение о заключении договора" in t:
                proposal_block = div
            elif "Для подписания договора необходимо" in t:
                signing_block = div

        file_sign_button = soup.select_one("#file-sign-0")

        if proposal_block:
            footer = proposal_block.select_one("div.panel-footer")
            spans = footer.find_all("span") if footer else []
            statement_sent = any("заявление о соответствии направлено" in s.get_text(strip=True).lower() for s in spans)

            li_items = proposal_block.select("div.panel.panel-info div.panel-body ol li")
            waiting = False
            for li in li_items:
                li_text = li.get_text(strip=True).lower()
                if "направить заказчику заявление о соответствии требованиям к участникам и получить его решение" in li_text:
                    icon = li.select_one("i")
                    if icon and "glyphicon-remove" in (icon.get("class") or []):
                        waiting = True
                        break

            if not statement_sent:
                result["need_statement"] = True
            elif waiting:
                result["waiting_statement"] = True
            else:
                all_ok = all("glyphicon-ok" in (li.select_one("i") or {}).get("class", []) for li in li_items)
                result["ready"] = bool(all_ok or file_sign_button)
        else:
            if not signing_block and file_sign_button:
                result["ready"] = True
            elif signing_block:
                li_items = signing_block.select("div.panel.panel-info div.panel-body ol li")
                all_ok = all("glyphicon-ok" in (li.select_one("i") or {}).get("class", []) for li in li_items)
                if all_ok or file_sign_button:
                    result["ready"] = True

    except Exception as e:
        logging.error(f"Ошибка парсинга условий: {e}")

    return result


async def parse_contracts_list(html: str) -> List[Contract]:
    soup = BeautifulSoup(html, "html.parser")
    contracts: List[Contract] = []
    for row in soup.select("table.table-hover tbody tr"):
        row_text = row.get_text(" ", strip=True)

        contract_id = None
        for word in row_text.split():
            if word.startswith("auc"):
                contract_id = word
                break

        btn = row.select_one("a.btn.btn-xs.btn-primary")

        if btn:
            url = f"https://goszakupki.by{btn['href']}"
            if not contract_id:
                contract_id = url.split("/")[-1]
            contracts.append(Contract(contract_id, "", True, url))
        else:
            if not contract_id:
                contract_id = "unknown"
            contracts.append(Contract(contract_id, "", False))
    return contracts

async def parse_sign_conditions(session, url: str, proxy: Optional[str] = None,
                                proxy_auth: Optional[BasicAuth] = None) -> dict:
    result = {"ready": False, "need_statement": False, "waiting_statement": False, "title": ""}
    try:
        html = await safe_get(session, url, retries=3, proxy=proxy, proxy_auth=proxy_auth)
        if not html:
            return result

        if "Нет доступа к данному разделу сайта" in html:
            result["title"] = "Недоступно"
            return result

        soup = BeautifulSoup(html, "html.parser")

        contract_number = ""  # Contract number
        subject = ""          # Customer name

        # Looking for the “Contract Information” section
        for bold in soup.find_all("b"):
            title_text = bold.get_text(strip=True)
            if title_text == "Информация о договоре":
                table = bold.find_next("table")
                if not table:
                    break
                for row in table.find_all("tr"):
                    th = row.find("th")
                    td = row.find("td")
                    if not th or not td:
                        continue
                    header = th.get_text(" ", strip=True).lower()
                    value = td.get_text(" ", strip=True)
                    if "номер договора" in header:
                        contract_number = value
                        continue
                    if "наименование заказчика" in header:
                        subject = value
                        continue
                break

        parts = []
        if contract_number:
            parts.append(contract_number)
        if subject:
            parts.append(subject)
        result["title"] = " — ".join(parts) if parts else "Без названия"

        # Search for blocks
        proposal_block = None
        signing_block = None
        for div in soup.select("body > div > div > div"):
            b = div.select_one("div.panel-heading > b")
            if not b:
                continue
            t = b.get_text(strip=True)
            if "Предложение о заключении договора" in t:
                proposal_block = div
            elif "Для подписания договора необходимо" in t:
                signing_block = div

        file_sign_button = soup.select_one("#file-sign-0")

        if proposal_block:
            # Has the application been submitted?
            footer = proposal_block.select_one("div.panel-footer")
            spans = footer.find_all("span") if footer else []
            statement_sent = any("заявление о соответствии направлено" in s.get_text(strip=True).lower() for s in spans)

            li_items = proposal_block.select("div.panel.panel-info div.panel-body ol li")
            waiting = False
            for li in li_items:
                li_text = li.get_text(strip=True).lower()
                if "направить заказчику заявление о соответствии требованиям к участникам и получить его решение" in li_text:
                    icon = li.select_one("i")
                    if icon and "glyphicon-remove" in (icon.get("class") or []):
                        waiting = True
                        break

            if not statement_sent:
                result["need_statement"] = True
            elif waiting:
                result["waiting_statement"] = True
            else:
                all_ok = all("glyphicon-ok" in (li.select_one("i") or {}).get("class", []) for li in li_items)
                result["ready"] = bool(all_ok or file_sign_button)
        else:
            if not signing_block and file_sign_button:
                result["ready"] = True
            elif signing_block:
                li_items = signing_block.select("div.panel.panel-info div.panel-body ol li")
                all_ok = all("glyphicon-ok" in (li.select_one("i") or {}).get("class", []) for li in li_items)
                if all_ok or file_sign_button:
                    result["ready"] = True

    except Exception as e:
        logging.error(f"Ошибка парсинга условий {url}: {e}")

    return result


# -------------------- Popup --------------------
def insert_hyperlink(text_widget, display_text: str, url: str, tag: str):
    text_widget.insert(tk.END, display_text, tag)
    text_widget.tag_config(tag, foreground="blue", underline=True)
    text_widget.tag_bind(tag, "<Button-1>", lambda e: webbrowser.open(url))
    text_widget.tag_bind(tag, "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind(tag, "<Leave>", lambda e: text_widget.config(cursor=""))


def _ensure_popup(app):
    need_create = True
    if getattr(app, "popup", None):
        try:
            if app.popup.winfo_exists():
                need_create = False
        except tk.TclError:
            need_create = True

    if need_create:
        app.popup = tk.Toplevel(app.root)
        app.popup.title("Новые договоры")
        app.popup.geometry("900x500")
        app.popup_text = tk.Text(app.popup, wrap="word", font=("Segoe UI", 11))
        app.popup_text.pack(expand=True, fill="both", padx=10, pady=10)

        def on_close_popup():
            if app.popup:
                try:
                    app.popup.destroy()
                except Exception:
                    pass
            app.popup = None
            app.popup_text = None

        app.popup.protocol("WM_DELETE_WINDOW", on_close_popup)

    return app.popup, app.popup_text


def open_proxy_editor_dialog(root):
    dlg = tk.Toplevel(root)
    dlg.title("Прокси")
    dlg.geometry("720x560")
    dlg.transient(root)
    dlg.grab_set()

    tk.Label(
        dlg,
        text=(
            "Укажите прокси по одному на строку в формате:\n"
            "scheme host port username password  (сначала ЛОГИН, потом ПАРОЛЬ)\n"
            "Примеры:\n"
            "http 1.2.3.4 8080 user pass\n"
            "https 11.22.33.44 3128 login SecretPass123\n"
            "\nПодсказка: можно вставить несколько строк сразу (Ctrl+V / Shift+Insert)."
        ),
        justify="left",
        anchor="w"
    ).pack(fill="x", padx=10, pady=6)

    # Button panel (convenient for checking insertion)
    toolbar = tk.Frame(dlg)
    toolbar.pack(fill="x", padx=10, pady=(0, 6))

    # Input field
    text_frame = tk.Frame(dlg)
    text_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    yscroll = tk.Scrollbar(text_frame, orient="vertical")
    yscroll.pack(side="right", fill="y")

    text = tk.Text(text_frame, height=18, wrap="none", undo=True, autoseparators=True, maxundo=-1)
    text.pack(side="left", fill="both", expand=True)
    text.config(yscrollcommand=yscroll.set)
    yscroll.config(command=text.yview)
    text.focus_set()

    # bindtags priority — our binds forward
    bt = list(text.bindtags())
    if bt and bt[0] != str(text):
        bt = [str(text)] + [t for t in bt if t != str(text)]
        text.bindtags(tuple(bt))

    # ============ Universal insert ============
    import sys
    import platform

    def paste_portable(ev=None):
        # 1) Regular Clipboard
        try:
            try:
                text.delete("sel.first", "sel.last")
            except Exception:
                pass
            clip = text.clipboard_get()
            if clip:
                text.insert("insert", clip)
                return "break"
        except Exception:
            pass

        # 2) X11 PRIMARY (Linux)
        try:
            primary = text.selection_get(selection="PRIMARY")
            if primary:
                text.insert("insert", primary)
                return "break"
        except Exception:
            pass

        # 3) Hidden Entry with <<Paste>> (bypasses class-binding bugs)
        try:
            hidden = tk.Entry(dlg)
            hidden.place_forget()
            hidden.focus_force()
            hidden.delete(0, "end")
            hidden.event_generate("<<Paste>>")
            dlg.update()
            data = hidden.get()
            hidden.destroy()
            if data:
                text.insert("insert", data)
                return "break"
        except Exception:
            pass

        # 4) Windows API (ctypes)
        try:
            if sys.platform.startswith("win"):
                import ctypes
                from ctypes import wintypes

                CF_UNICODETEXT = 13
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32

                if user32.OpenClipboard(None):
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        ptr = kernel32.GlobalLock(handle)
                        if ptr:
                            data = ctypes.wstring_at(ptr)
                            kernel32.GlobalUnlock(handle)
                            user32.CloseClipboard()
                            if data:
                                text.insert("insert", data)
                                return "break"
                    user32.CloseClipboard()
        except Exception:
            pass

        # 5) Last attempt — <<Paste>> (if available)
        try:
            text.event_generate("<<Paste>>")
            return "break"
        except Exception:
            pass

        return "break"

    def copy_portable(ev=None):
        try:
            sel = text.get("sel.first", "sel.last")
        except Exception:
            sel = ""
        try:
            text.clipboard_clear()
            if sel:
                text.clipboard_append(sel)
            return "break"
        except Exception:
            return None

    def cut_portable(ev=None):
        try:
            sel = text.get("sel.first", "sel.last")
        except Exception:
            sel = ""
        try:
            text.clipboard_clear()
            if sel:
                text.clipboard_append(sel)
                text.delete("sel.first", "sel.last")
            return "break"
        except Exception:
            return None

    def select_all(ev=None):
        text.tag_add("sel", "1.0", "end-1c")
        text.mark_set("insert", "1.0")
        return "break"

    def undo_direct(ev=None):
        try:
            text.edit_undo()
            return "break"
        except Exception:
            return None

    def redo_direct(ev=None):
        try:
            text.edit_redo()
            return "break"
        except Exception:
            return None

    # Local binds
    for seq in ("<Control-v>", "<Control-V>", "<Shift-Insert>", "<Command-v>", "<Meta-v>"):
        text.bind(seq, paste_portable)
    for seq in ("<Control-c>", "<Control-C>", "<Control-Insert>", "<Command-c>", "<Meta-c>"):
        text.bind(seq, copy_portable)
    for seq in ("<Control-x>", "<Control-X>", "<Shift-Delete>", "<Command-x>", "<Meta-x>"):
        text.bind(seq, cut_portable)
    for seq in ("<Control-a>", "<Control-A>", "<Command-a>", "<Meta-a>"):
        text.bind(seq, select_all)
    for seq in ("<Control-z>", "<Control-Z>", "<Command-z>", "<Meta-z>"):
        text.bind(seq, undo_direct)
    for seq in ("<Control-y>", "<Command-y>", "<Meta-y>", "<Control-Shift-Z>", "<Command-Shift-Z>"):
        text.bind(seq, redo_direct)

    # Global binds during dialogue (insurance)
    global_binds = []
    def bind_all_once(sequence, handler):
        dlg.bind_all(sequence, handler, add="+")
        global_binds.append(sequence)

    for seq in ("<Control-v>", "<Control-V>", "<Shift-Insert>", "<Command-v>", "<Meta-v>"):
        bind_all_once(seq, lambda e: (text.focus_set(), paste_portable(e)))
    for seq in ("<Control-c>", "<Control-C>", "<Control-Insert>", "<Command-c>", "<Meta-c>"):
        bind_all_once(seq, lambda e: (text.focus_set(), copy_portable(e)))
    for seq in ("<Control-x>", "<Control-X>", "<Shift-Delete>", "<Command-x>", "<Meta-x>"):
        bind_all_once(seq, lambda e: (text.focus_set(), cut_portable(e)))
    for seq in ("<Control-a>", "<Control-A>", "<Command-a>", "<Meta-a>"):
        bind_all_once(seq, lambda e: (text.focus_set(), select_all(e)))
    for seq in ("<Control-z>", "<Control-Z>", "<Command-z>", "<Meta-z>"):
        bind_all_once(seq, lambda e: (text.focus_set(), undo_direct(e)))
    for seq in ("<Control-y>", "<Command-y>", "<Meta-y>", "<Control-Shift-Z>", "<Command-Shift-Z>"):
        bind_all_once(seq, lambda e: (text.focus_set(), redo_direct(e)))

    def on_close():
        try:
            for seq in global_binds:
                dlg.unbind_all(seq)
        except Exception:
            pass
        dlg.destroy()

    dlg.protocol("WM_DELETE_WINDOW", on_close)

    # Context menu
    menu = tk.Menu(text, tearoff=0)
    menu.add_command(label="Вставить", command=lambda: (text.focus_set(), paste_portable()))
    menu.add_command(label="Копировать", command=lambda: (text.focus_set(), copy_portable()))
    menu.add_command(label="Вырезать", command=lambda: (text.focus_set(), cut_portable()))
    menu.add_separator()
    menu.add_command(label="Отменить", command=lambda: (text.focus_set(), undo_direct()))
    menu.add_command(label="Повторить", command=lambda: (text.focus_set(), redo_direct()))
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=lambda: (text.focus_set(), select_all()))

    def show_context_menu(event):
        try:
            text.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    text.bind("<Button-3>", show_context_menu)
    text.bind("<Button-2>", show_context_menu)

    # Panel buttons
    tk.Button(toolbar, text="Вставить", command=lambda: (text.focus_set(), paste_portable())).pack(side="left")
    tk.Button(toolbar, text="Копировать", command=lambda: (text.focus_set(), copy_portable())).pack(side="left", padx=6)
    tk.Button(toolbar, text="Вырезать", command=lambda: (text.focus_set(), cut_portable())).pack(side="left")
    tk.Button(toolbar, text="Выделить всё", command=lambda: (text.focus_set(), select_all())).pack(side="left", padx=6)
    tk.Button(toolbar, text="Отменить", command=lambda: (text.focus_set(), undo_direct())).pack(side="left")
    tk.Button(toolbar, text="Повторить", command=lambda: (text.focus_set(), redo_direct())).pack(side="left", padx=6)

    # Bring up the dialogue and bring back the focus
    dlg.after(50, lambda: (dlg.lift(), dlg.focus_force(), text.focus_set()))

    # Filling in config.json
    existing = load_proxies()
    lines = []
    for p in existing:
        scheme = p.get("scheme", "http")
        host = p.get("host", "")
        port = p.get("port", "")
        user = p.get("username", "")
        pwd  = p.get("password", "")
        parts = [scheme, host, port]
        if user or pwd:
            parts += [user, pwd]
        lines.append(" ".join(parts))
    if lines:
        text.insert("1.0", "\n".join(lines))

    # Bottom buttons
    btn_frame = tk.Frame(dlg)
    btn_frame.pack(fill="x", padx=10, pady=8)

    def save():
        raw_text = text.get("1.0", "end").strip()
        if not raw_text:
            save_proxies([])
            on_close()
            return

        raw = raw_text.splitlines()
        proxies, errors = [], []
        for idx, ln in enumerate(raw, start=1):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split()
            if len(parts) < 3:
                errors.append(f"Строка {idx}: минимум 3 поля (scheme host port)")
                continue
            scheme, host = parts[0], parts[1]
            port = parts[2] if len(parts) >= 3 else ""
            user = parts[3] if len(parts) >= 4 else ""
            pwd  = parts[4] if len(parts) >= 5 else ""
            if (not port.isdigit()) and len(parts) >= 4 and parts[3].isdigit():
                port, user = parts[3], parts[2]
                pwd = parts[4] if len(parts) >= 5 else ""
            if not port.isdigit():
                errors.append(f"Строка {idx}: порт должен быть числом (получено '{port}')")
                continue
            if user and pwd and len(user) >= 8 and len(pwd) <= 6:
                user, pwd = pwd, user
            p = {"scheme": (scheme or "http").strip().lower(),
                 "host": host.strip(),
                 "port": port.strip(),
                 "username": user.strip(),
                 "password": pwd.strip()}
            if not is_valid_proxy_dict(p):
                errors.append(f"Строка {idx}: некорректные поля (scheme=http/https, host непустой, port — число)")
                continue
            proxies.append(p)

        if errors:
            messagebox.showerror("Ошибки в прокси", "\n".join(errors))
            return

        try:
            save_proxies(proxies)
            reloaded = load_proxies()
            if len(reloaded) != len(proxies):
                messagebox.showwarning("Внимание", "Не все прокси удалось сохранить. Проверьте формат строк.")
            else:
                messagebox.showinfo("Готово", f"Сохранено прокси: {len(reloaded)}")
            on_close()
        except Exception as e:
            logging.error(f"Ошибка сохранения прокси: {e}")
            messagebox.showerror("Ошибка", f"Не удалось сохранить прокси: {e}")

    tk.Button(btn_frame, text="Сохранить", command=save).pack(side="right")
    tk.Button(btn_frame, text="Отмена", command=on_close).pack(side="right", padx=6)
    tk.Button(btn_frame, text="Очистить", command=lambda: text.delete("1.0", "end")).pack(side="left")


def show_contracts_popup(
    app,
    ready: List[Contract],
    need_statement: List[Contract],
    waiting: List[Contract] = None,
    new_ready_ids: set[str] | None = None,
    new_need_ids: set[str] | None = None,
    new_waiting_ids: set[str] | None = None,
):
    waiting = waiting or []
    new_ready_ids = new_ready_ids or set()
    new_need_ids = new_need_ids or set()
    new_waiting_ids = new_waiting_ids or set()

    popup, text = _ensure_popup(app)

    # Guaranteed to bring to the top of all windows (even if minimized/behind)
    try:
        popup.deiconify()
        # The “withdraw → deiconify” trick helps to get above some windows.
        popup.withdraw()
        popup.after(50, popup.deiconify)
        popup.lift()
        popup.focus_force()
        # Hold topmost a little longer, then remove
        popup.attributes("-topmost", True)
        popup.after(800, lambda: popup.attributes("-topmost", False))
    except Exception:
        pass

    text.config(state="normal")
    text.delete("1.0", tk.END)

    # Section 1 — READY
    text.insert(tk.END, "✅ Готовы к подписанию:\n\n", "header_ready")
    if ready:
        for i, c in enumerate(ready):
            tag_base = f"ready_link_{i}_{id(c)}"
            is_new = c.contract_id in new_ready_ids
            link_tag = tag_base if not is_new else f"{tag_base}_new"
            insert_hyperlink(text, f"{c.contract_id} — {c.title}\n", c.sign_url or "", link_tag)
            text.insert(tk.END, "──────────────────────────────\n", "separator")
            if is_new:
                text.tag_add("new_ready", "end-2l linestart", "end-2l lineend")
    else:
        text.insert(tk.END, "Нет таких договоров\n")

    # Section 2 — NEED
    text.insert(tk.END, "\n❗ Требуют заявления:\n\n", "header_need")
    if need_statement:
        for i, c in enumerate(need_statement):
            tag_base = f"need_link_{i}_{id(c)}"
            is_new = c.contract_id in new_need_ids
            link_tag = tag_base if not is_new else f"{tag_base}_new"
            insert_hyperlink(text, f"{c.contract_id} — {c.title}\n", c.sign_url or "", link_tag)
            text.insert(tk.END, "──────────────────────────────\n", "separator")
            if is_new:
                text.tag_add("new_need", "end-2l linestart", "end-2l lineend")
    else:
        text.insert(tk.END, "Нет таких договоров\n")

    # Section 3 — WAITING
    text.insert(tk.END, "\n⏳ Ожидают рассмотрения заявления:\n\n", "header_waiting")
    if waiting:
        for i, c in enumerate(waiting):
            tag_base = f"waiting_link_{i}_{id(c)}"
            is_new = c.contract_id in new_waiting_ids
            link_tag = tag_base if not is_new else f"{tag_base}_new"
            insert_hyperlink(text, f"{c.contract_id} — {c.title}\n", c.sign_url or "", link_tag)
            text.insert(tk.END, "──────────────────────────────\n", "separator")
            if is_new:
                text.tag_add("new_waiting", "end-2l linestart", "end-2l lineend")
    else:
        text.insert(tk.END, "Нет таких договоров\n")

    # Design
    text.tag_config("header_ready", font=("Segoe UI", 12, "bold"), foreground="green")
    text.tag_config("header_need", font=("Segoe UI", 12, "bold"), foreground="red")
    text.tag_config("header_waiting", font=("Segoe UI", 12, "bold"), foreground="orange")
    text.tag_config("separator", foreground="#888888")

    # Highlighting the “new”
    # Soft fill and semi-bold.
    text.tag_config("new_ready", background="#e6ffec", foreground="#0b7d26", font=("Segoe UI", 10, "bold"))
    text.tag_config("new_need", background="#ffecec", foreground="#b00020", font=("Segoe UI", 10, "bold"))
    text.tag_config("new_waiting", background="#fff6e0", foreground="#a85b00", font=("Segoe UI", 10, "bold"))

    text.config(state="disabled")


def play_alert(new_ready_cnt: int, new_need_cnt: int, new_waiting_cnt: int) -> None:
    """Plays a sound signal when there are new contracts in any status in the popup."""
    try:
        import winsound
        # The more “new” ones there are, the longer (and slightly lower) the signal.
        total = new_ready_cnt + new_need_cnt + new_waiting_cnt
        if total <= 0:
            return
        # A little “melody” – different tones for different categories
        pattern = []
        if new_ready_cnt:
            pattern += [(1200, 160)] * min(new_ready_cnt, 3)
        if new_need_cnt:
            pattern += [(900, 160)] * min(new_need_cnt, 3)
        if new_waiting_cnt:
            pattern += [(700, 160)] * min(new_waiting_cnt, 3)
        # If there is a lot, we will add the final tone.
        if total >= 3:
            pattern += [(1500, 220)]
        for freq, dur in pattern:
            winsound.Beep(freq, dur)
    except Exception:
        # Fallback
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


# -------------------- Monitoring --------------------
async def _sleep_interruptible(app, seconds: int):
    for _ in range(seconds):
        if not app.monitoring:
            return
        await asyncio.sleep(1)

async def monitor_contracts(auth, interval: int, app):
    global READY_CACHE, NEED_STATEMENT_CACHE, WAITING_CACHE
    logging.info(">>> monitor_contracts ЗАПУЩЕН")

    try:
        while app.monitoring:
            try:
                logging.info("Начало обхода")
                app.set_status("Проверка договоров...", "blue")

                html = await auth.get_my_contracts_page()
                if not html:
                    logging.error("Не удалось загрузить 'Мои договоры'")
                    app.set_status("Переавторизация...", "orange")
                    try:
                        if auth.session and not auth.session.closed:
                            await auth.session.close()
                    except Exception:
                        pass
                    ok = await auth.login(app.username.get(), app.password.get(), keep_proxy=True)
                    if not ok:
                        app.set_status("Ошибка переавторизации", "red")
                        await _sleep_interruptible(app, interval * 60)
                        if not app.monitoring:
                            return
                        continue
                    # After successful reauthorization, we try again.
                    html = await auth.get_my_contracts_page()
                    if not html:
                        app.set_status("Ошибка загрузки договоров", "red")
                        await _sleep_interruptible(app, interval * 60)
                        if not app.monitoring:
                            return
                        continue

                contracts = await parse_contracts_list(html)

                all_ready, all_need, all_waiting = [], [], []
                current_ready_ids, current_need_ids, current_waiting_ids = set(), set(), set()

                for c in contracts:
                    if c.signable and c.sign_url:
                        html2 = await fetch_html_with_reauth(auth, app, c.sign_url)
                        if not html2:
                            continue

                        # We take the header from the existing function (it gets the number/customer).
                        conds = parse_sign_conditions_html(html2)
                        c.title = conds.get("title", "Без названия")

                        status = classify_contract_sign_page(html2)
                        logging.info(f"[CLASSIFY] {c.contract_id}: {status}")

                        if status == ContractSignStatus.READY:
                            all_ready.append(c);
                            current_ready_ids.add(c.contract_id)
                        elif status == ContractSignStatus.NEEDS_STATEMENT:
                            all_need.append(c);
                            current_need_ids.add(c.contract_id)
                        elif status == ContractSignStatus.AWAIT_DECISION:
                            all_waiting.append(c);
                            current_waiting_ids.add(c.contract_id)

                        await asyncio.sleep(1)

                # Calculate new IDs by category
                new_ready_ids = current_ready_ids - READY_CACHE
                new_need_ids = current_need_ids - NEED_STATEMENT_CACHE
                new_waiting_ids = current_waiting_ids - WAITING_CACHE

                # Updating caches
                READY_CACHE = current_ready_ids
                NEED_STATEMENT_CACHE = current_need_ids
                WAITING_CACHE = current_waiting_ids

                # Sound, if new ones have appeared in any category
                if new_ready_ids or new_need_ids or new_waiting_ids:
                    app.root.after(0, lambda: play_alert(len(new_ready_ids), len(new_need_ids), len(new_waiting_ids)))

                # Popap if elements are present
                if all_ready or all_need or all_waiting:
                    app.root.after(
                        0,
                        lambda r=all_ready, n=all_need, w=all_waiting, nr=new_ready_ids, nn=new_need_ids, nw=new_waiting_ids:
                            show_contracts_popup(app, r, n, w, nr, nn, nw)
                    )

                save_cache()
                logging.info(f"Обход завершён. Найдено договоров: {len(contracts)}")

                # timeout timer
                for i in range(interval * 60, 0, -1):
                    if not app.monitoring:
                        logging.info("Мониторинг остановлен во время ожидания")
                        return
                    mins, secs = divmod(i, 60)
                    app.ui(lambda m=mins, s=secs: app.next_check_label.config(
                        text=f"След. проверка через: {m:02d}:{s:02d}"
                    ))
                    await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"Ошибка мониторинга: {e}")
                app.set_status(f"Ошибка: {e}", "red")
                await _sleep_interruptible(app, interval * 60)
                if not app.monitoring:
                    return

    finally:
        await auth.close()
        logging.info("Сессия auth закрыта корректно.")


async def one_shot_check(auth, app):
    global READY_CACHE, NEED_STATEMENT_CACHE, WAITING_CACHE
    try:
        need_login = (
            not getattr(auth, "is_authenticated", False)
            or not getattr(auth, "session", None)
            or getattr(auth.session, "closed", True)
        )

        if need_login:
            username = password = None
            if hasattr(app, "remember_var") and app.remember_var.get():
                creds = load_credentials()
                if creds:
                    username = creds.get("username")
                    password = creds.get("password")
                    if username and password:
                        logging.info("Используем сохранённые учётные данные")
            if not username or not password:
                username = app.username.get()
                password = app.password.get()
                logging.info("Используем учётные данные из полей GUI")
            if not username or not password:
                app.set_status("Не указаны логин или пароль", "red")
                logging.error("Отсутствуют учётные данные для входа")
                return
            if not await auth.login(username, password):
                app.set_status("Авторизация не удалась", "red")
                logging.error("Не удалось залогиниться для одноразовой проверки")
                return

        html = await auth.get_my_contracts_page()
        if not html:
            app.set_status("Ошибка загрузки договоров", "red")
            return

        contracts = await parse_contracts_list(html)
        logging.info(f"Одноразовая проверка: найдено {len(contracts)} строк в таблице")

        all_ready, all_need, all_waiting = [], [], []
        current_ready_ids, current_need_ids, current_waiting_ids = set(), set(), set()

        for c in contracts:
            if c.signable and c.sign_url:
                html2 = await fetch_html_with_reauth(auth, app, c.sign_url)
                if not html2:
                    continue

                # We take the header from the existing function (it gets the number/customer).
                conds = parse_sign_conditions_html(html2)
                c.title = conds.get("title", "Без названия")

                status = classify_contract_sign_page(html2)
                logging.info(f"[CLASSIFY] {c.contract_id}: {status}")

                if status == ContractSignStatus.READY:
                    all_ready.append(c);
                    current_ready_ids.add(c.contract_id)
                elif status == ContractSignStatus.NEEDS_STATEMENT:
                    all_need.append(c);
                    current_need_ids.add(c.contract_id)
                elif status == ContractSignStatus.AWAIT_DECISION:
                    all_waiting.append(c);
                    current_waiting_ids.add(c.contract_id)

                await asyncio.sleep(1)

        new_ready_ids = current_ready_ids - READY_CACHE
        new_need_ids = current_need_ids - NEED_STATEMENT_CACHE
        new_waiting_ids = current_waiting_ids - WAITING_CACHE

        # Updating caches
        READY_CACHE = current_ready_ids
        NEED_STATEMENT_CACHE = current_need_ids
        WAITING_CACHE = current_waiting_ids

        # Sound, if new ones have appeared
        if new_ready_ids or new_need_ids or new_waiting_ids:
            app.root.after(0, lambda: play_alert(len(new_ready_ids), len(new_need_ids), len(new_waiting_ids)))

        if all_ready or all_need or all_waiting:
            app.root.after(
                0,
                lambda r=all_ready, n=all_need, w=all_waiting, nr=new_ready_ids, nn=new_need_ids, nw=new_waiting_ids:
                    show_contracts_popup(app, r, n, w, nr, nn, nw)
            )

        app.set_status(f"Проверка завершена. Найдено {len(contracts)} договоров.", "green")

    except Exception as e:
        logging.error(f"Ошибка в однократной проверке: {e}")
        app.set_status(f"Ошибка проверки: {e}", "red")


# -------------------- GUI --------------------
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Парсер договоров goszakupki.by")
        self.auth_manager = AuthManager(use_proxies=load_proxy_usage_enabled())
        self.remember_var = tk.BooleanVar(value=False)
        # Proxy usage switch
        self.use_proxy_var = tk.BooleanVar(value=load_proxy_usage_enabled())
        proxy_frame = tk.Frame(self.root)
        proxy_frame.pack(anchor="w", padx=10, pady=(4, 0))

        proxy_check = tk.Checkbutton(proxy_frame, text="Использовать прокси", variable=self.use_proxy_var,
                                     command=lambda: save_proxy_usage_enabled(self.use_proxy_var.get()))
        proxy_check.pack(side="left")

        proxy_btn = tk.Button(proxy_frame, text="Настроить прокси…", command=self.open_proxy_editor)
        proxy_btn.pack(side="left", padx=8)

        self.popup = None
        self.popup_text = None

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        self.monitoring = False

        self.create_widgets()
        self.load_config()
        load_cache()

    def create_widgets(self):
        frm_auth = ttk.LabelFrame(self.root, text="Авторизация", padding=10)
        frm_auth.pack(fill="x", padx=10, pady=5)

        ttk.Label(frm_auth, text="Логин:").grid(row=0, column=0, sticky="w", pady=2)
        self.username = ttk.Entry(frm_auth, width=30)
        self.username.grid(row=0, column=1, pady=2)

        ttk.Label(frm_auth, text="Пароль:").grid(row=1, column=0, sticky="w", pady=2)
        self.password = ttk.Entry(frm_auth, width=30, show="*")
        self.password.grid(row=1, column=1, pady=2)

        self.chk = ttk.Checkbutton(frm_auth, text="Запомнить меня", variable=self.remember_var)
        self.chk.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)

        self.btn_login = ttk.Button(frm_auth, text="Войти", command=self.handle_login)
        self.btn_login.grid(row=3, column=0, columnspan=2, pady=5)

        frm_ctrl = ttk.LabelFrame(self.root, text="Управление", padding=10)
        frm_ctrl.pack(fill="x", padx=10, pady=5)

        # interval field
        ttk.Label(frm_ctrl, text="Интервал (мин):").pack(side="left", padx=(0, 5))
        self.interval_entry = ttk.Entry(frm_ctrl, width=5)
        self.interval_entry.insert(0, "5")  # значение по умолчанию
        self.interval_entry.pack(side="left", padx=(0, 15))

        self.btn_start = ttk.Button(frm_ctrl, text="Запустить мониторинг", command=self.start_monitoring, state="disabled")
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(frm_ctrl, text="Остановить мониторинг", command=self.stop_monitoring, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.btn_check = ttk.Button(frm_ctrl, text="Проверить сейчас", command=self.check_once, state="disabled")
        self.btn_check.pack(side="left", padx=5)

        frm_status = ttk.Frame(self.root, padding=10)
        frm_status.pack(fill="x", padx=10, pady=(0, 5))

        self.status = ttk.Label(frm_status, text="Статус: Не авторизован", foreground="red")
        self.status.pack(anchor="w")

        self.next_check_label = ttk.Label(frm_status, text="След. проверка: --:--")
        self.next_check_label.pack(anchor="w")

        frm_log = ttk.LabelFrame(self.root, text="Лог", padding=5)
        frm_log.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(frm_log, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def load_config(self):
        """Loads the configuration and automatically fills in the fields if there is saved data."""
        try:
            cfg = _read_config()

            # Interval
            if "interval" in cfg:
                self.interval_entry.delete(0, "end")
                self.interval_entry.insert(0, str(cfg["interval"]))

            # Credentials
            creds = cfg.get("credentials", {})
            if creds.get("username") and creds.get("password"):
                self.username.delete(0, "end")
                self.password.delete(0, "end")
                self.username.insert(0, creds["username"])
                self.password.insert(0, creds["password"])
                self.remember_var.set(True)
                logging.info("Загружены сохранённые учётные данные в поля GUI")
        except Exception as e:
            logging.error(f"Ошибка чтения config: {e}")


    def ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass


    def set_status(self, text, color="black"):
        def _do():
            self.status.config(text=text, foreground=color)
            self.log(f"[STATUS] {text}", direct=True)

        self.ui(_do)

    def log(self, msg, direct=False):
        def _do():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.yview("end")
            self.log_text.config(state="disabled")

        if direct:
            # is already called from the UI thread
            _do()
        else:
            self.ui(_do)


    def save_config(self):
        """Сохраняет конфиг с учётом галочки Remember Me"""
        try:
            cfg = _read_config()

            # Save the interval
            cfg["interval"] = self.interval_entry.get()

            # Working with credentials
            if self.remember_var.get():
                cfg.setdefault("credentials", {})
                cfg["credentials"]["username"] = self.username.get()
                cfg["credentials"]["password"] = self.password.get()
            else:
                # If the check mark is removed, delete the credentials.
                cfg.pop("credentials", None)

            _write_config(cfg)

        except Exception as e:
            logging.error(f"Ошибка сохранения config: {e}")


    def handle_login(self):
        # Synchronize settings before logging in
        self.auth_manager.use_proxies = bool(self.use_proxy_var.get())
        asyncio.run_coroutine_threadsafe(self.try_login(), self.loop)

    async def try_login(self):
        ok = await self.auth_manager.login(self.username.get(), self.password.get())
        if ok:
            self.set_status("Авторизация успешна", "green")
            self.save_config()
            self.ui(lambda: (
                self.btn_start.config(state="normal"),
                self.btn_check.config(state="normal")
            ))
        else:
            self.set_status("Ошибка авторизации", "red")
            self.ui(lambda: messagebox.showerror("Ошибка", "Неверный логин или пароль"))



    def open_proxy_editor(self):
        open_proxy_editor_dialog(self.root)


    def start_monitoring(self):
        if self.monitoring:
            return
        try:
            interval = int(self.interval_entry.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Интервал должен быть числом")
            return

        self.monitoring = True
        logging.info(f"Запуск мониторинга с интервалом {interval} мин")
        self.auth_manager.use_proxies = bool(self.use_proxy_var.get())
        asyncio.run_coroutine_threadsafe(monitor_contracts(self.auth_manager, interval, self), self.loop)
        self.set_status("Мониторинг запущен", "green")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")


    def stop_monitoring(self):
        # Just stop the cycle, do NOT close the session here.
        self.monitoring = False
        self.set_status("Мониторинг остановлен", "orange")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.next_check_label.config(text="След. проверка: --:--")


    def check_once(self):
        asyncio.run_coroutine_threadsafe(one_shot_check(self.auth_manager, self), self.loop)


    def on_close(self):
        self.monitoring = False
        fut = asyncio.run_coroutine_threadsafe(self.auth_manager.close(), self.loop)
        try:
            fut.result(timeout=2.0)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()


# -------------------- MAIN --------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()