from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uuid
import requests

import bcrypt, jwt, datetime, os
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from dotenv import load_dotenv

load_dotenv()


# ============================
# 🔁 VERSIONAMENTO DO BOT
# ============================
APP_LATEST_VERSION = (os.getenv("APP_LATEST_VERSION") or "1.0").strip()
APP_MIN_REQUIRED_VERSION = (os.getenv("APP_MIN_REQUIRED_VERSION") or "1.0").strip()



def _parse_version(v: str):
    """Converte '1.2' -> (1,2). Suporta '1', '1.2.3'."""
    v = (v or "").strip()
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts)

def _version_info(client_version: str):
    latest = os.getenv("APP_LATEST_VERSION", "1.0").strip()
    min_required = os.getenv("APP_MIN_REQUIRED_VERSION", "1.0").strip()

    cv = _parse_version(client_version)
    lv = _parse_version(latest)
    mv = _parse_version(min_required)

    return {
        "latest": latest,
        "min_required": min_required,
        "update_available": cv < lv,
        "update_required": cv < mv,
    }

def _ver_lt(a: str, b: str) -> bool:
    pa = _parse_version(a)
    pb = _parse_version(b)
    n = max(len(pa), len(pb))
    pa = pa + (0,) * (n - len(pa))
    pb = pb + (0,) * (n - len(pb))
    return pa < pb

def _version_status(client_version: str) -> dict:
    cv = (client_version or "").strip() or "0.0"
    latest = APP_LATEST_VERSION
    minreq = APP_MIN_REQUIRED_VERSION
    update_available = _ver_lt(cv, latest)
    update_required = _ver_lt(cv, minreq)
    return {
        "client_version": cv,
        "latest_version": latest,
        "min_required_version": minreq,
        "update_available": bool(update_available),
        "update_required": bool(update_required),
    }


SECRET_KEY = "chave_super_segura"
ADMIN_SECRET_KEY = "macdsmartpro_admin"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não configurada")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Painel Admin MACD Smart Pro")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
from sqlalchemy import text

def ensure_active_session_column():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS active_session VARCHAR;
            """))
            conn.commit()
            print("[DB] Coluna active_session verificada/criada.")
    except Exception as e:
        print("[DB] Erro ao garantir coluna active_session:", e)


def ensure_cadastro_columns():
    """Garante colunas/índices necessários para o cadastro público (CPF, Nome e Telefone)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS cpf VARCHAR;
            """))
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS full_name VARCHAR;
            """))
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS phone VARCHAR;
            """))  # 👈 NOVA COLUNA TELEFONE (ESSENCIAL)

            # índice único para CPF (não falha se já existir)
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_cpf ON users (cpf);"))
            except Exception:
                pass

            conn.commit()
            print("[DB] Colunas cpf/full_name/phone verificadas/criadas.")
    except Exception as e:
        print("[DB] Erro ao garantir colunas cpf/full_name/phone:", e)

def ensure_payment_columns():
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS last_payment_id VARCHAR;
            """))
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS last_payment_status VARCHAR;
            """))
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS last_payment_at TIMESTAMP;
            """))
            conn.commit()
            print("[DB] Colunas de pagamento verificadas/criadas.")
    except Exception as e:
        print("[DB] Erro ao garantir colunas de pagamento:", e)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, unique=True, index=True, nullable=False)

    # Cadastro público (CPF + Nome + Telefone)
    cpf = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)  # 👈 ADICIONE ESTA LINHA

    password = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    lucro = Column(Float, default=0.0)
    perfil = Column(String, default="Desconhecido")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0)
    trial_until = Column(DateTime, nullable=True)
    role = Column(String, default="user")
    active_session = Column(String, nullable=True)
    last_payment_id = Column(String, nullable=True)
    last_payment_status = Column(String, nullable=True)
    last_payment_at = Column(DateTime, nullable=True)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, index=True, nullable=False)
    symbol = Column(String, nullable=False)
    perfil = Column(String, nullable=True)
    valor = Column(Float, default=0.0)
    entry_price = Column(Float, default=0.0)
    exit_price = Column(Float, default=0.0)
    qty = Column(Float, default=0.0)
    retorno = Column(Float, default=0.0)
    reason = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


def create_token(user):
    payload = {"user": user, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=6)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================
# 🔐 ADMIN FIXO (apenas Vinici459)
# ============================
def require_admin(request: Request, db: Session = Depends(get_db_session)):
    token = request.cookies.get("token")
    data = decode_token(token) if token else None

    # 🔐 Se não estiver logado → vai para login admin secreto
    if not data:
        raise HTTPException(status_code=303, headers={"Location": "/admin-smartpro-459-panel"})

    username = data.get("user")

    # 🔐 Só o admin acessa o painel
    if username != "Vinici459":
        raise HTTPException(status_code=303, headers={"Location": "/admin-smartpro-459-panel"})

    return data


def require_login(request: Request):
    token = request.cookies.get("token")
    data = decode_token(token) if token else None

    # 🔐 Qualquer usuário não logado vai para /admin (não mais para /)
    if not data:
        raise HTTPException(status_code=303, headers={"Location": "/admin-smartpro-459-panel"})

    return data

def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def get_trial_days_left(trial_until):
    if not trial_until:
        return "-"
    try:
        if isinstance(trial_until, str):
            trial_end = datetime.datetime.fromisoformat(trial_until)
        else:
            trial_end = trial_until
        remaining = trial_end - datetime.datetime.utcnow()
        return max(0, remaining.days)
    except Exception:
        return "-"
# ==========================
# 🔄 PÁGINA DE RENOVAÇÃO
# ==========================

@app.api_route("/renovar", methods=["GET", "POST"], response_class=HTMLResponse)
def renovar_page(
    request: Request,
    cpf: str = Form(None),
    db: Session = Depends(get_db_session),
):
    def render_account_page(cpf_value: str = "", success_msg: str = None):
        cpf_clean = _only_digits(cpf_value or "")

        if not cpf_clean:
            return templates.TemplateResponse(
                "renew_payment.html",
                {
                    "request": request,
                    "account": None,
                    "error": None,
                    "success": success_msg,
                    "cpf": cpf_value or "",
                    "pix_qr": None,
                    "pix_code": None,
                    "payment_id": None,
                }
            )

        user = db.query(User).filter(User.cpf == cpf_clean).first()

        if not user:
            return templates.TemplateResponse(
                "renew_payment.html",
                {
                    "request": request,
                    "account": None,
                    "error": "Nenhuma conta encontrada para este CPF.",
                    "success": success_msg,
                    "cpf": cpf_value or "",
                    "pix_qr": None,
                    "pix_code": None,
                    "payment_id": None,
                }
            )

        now = datetime.datetime.utcnow()
        valid_until = user.trial_until.strftime("%d/%m/%Y %H:%M") if user.trial_until else "Não definido"

        if user.trial_until and now > user.trial_until:
            status_text = "Expirado"
            status_key = "expired"
        elif user.trial_until:
            dias = get_trial_days_left(user.trial_until)
            if isinstance(dias, int) and dias <= 7:
                status_text = f"Expirando ({dias} dias restantes)"
                status_key = "expiring"
            else:
                status_text = f"Ativo ({dias} dias restantes)"
                status_key = "active"
        else:
            status_text = "Sem validade definida"
            status_key = "unknown"

        def mask_cpf(v: str) -> str:
            v = _only_digits(v)
            if len(v) == 11:
                return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
            return v

        account = {
            "full_name": user.full_name or "Não informado",
            "username": user.user,
            "cpf_masked": mask_cpf(user.cpf or ""),
            "cpf_raw": user.cpf or "",
            "phone": user.phone or "Não informado",
            "valid_until": valid_until,
            "status_text": status_text,
            "status_key": status_key,
        }

        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": None,
                "success": success_msg,
                "cpf": cpf_value or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": None,
            }
        )

    if request.method == "GET":
        cpf_query = request.query_params.get("cpf", "") or ""
        paid = request.query_params.get("paid", "") or ""

        success_msg = None
        if paid == "1":
            success_msg = "Pagamento aprovado com sucesso. Seu acesso foi renovado por mais 30 dias."

        return render_account_page(cpf_query, success_msg)

    return render_account_page(cpf or "", None)

@app.post("/renovar/criar-pagamento", response_class=HTMLResponse)
def renovar_criar_pagamento(
    request: Request,
    cpf: str = Form(...),
    payment_method: str = Form(...),
    db: Session = Depends(get_db_session),
):
    access_token = (os.getenv("MP_ACCESS_TOKEN_PROD") or "").strip()

    cpf_clean = _only_digits(cpf)
    user = db.query(User).filter(User.cpf == cpf_clean).first()

    def build_account(u):
        now = datetime.datetime.utcnow()
        valid_until = u.trial_until.strftime("%d/%m/%Y %H:%M") if u.trial_until else "Não definido"

        if u.trial_until and now > u.trial_until:
            status_text = "Expirado"
            status_key = "expired"
        elif u.trial_until:
            dias = get_trial_days_left(u.trial_until)
            if isinstance(dias, int) and dias <= 7:
                status_text = f"Expirando ({dias} dias restantes)"
                status_key = "expiring"
            else:
                status_text = f"Ativo ({dias} dias restantes)"
                status_key = "active"
        else:
            status_text = "Sem validade definida"
            status_key = "unknown"

        def mask_cpf(v: str) -> str:
            v = _only_digits(v)
            if len(v) == 11:
                return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
            return v

        return {
            "full_name": u.full_name or "Não informado",
            "username": u.user,
            "cpf_masked": mask_cpf(u.cpf or ""),
            "cpf_raw": u.cpf or "",
            "phone": u.phone or "Não informado",
            "valid_until": valid_until,
            "status_text": status_text,
            "status_key": status_key,
        }

    if not user:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": None,
                "error": "Conta não encontrada.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
            }
        )

    account = build_account(user)

    if not access_token:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": "MP_ACCESS_TOKEN_PROD está vazio ou não foi carregado no Railway.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
            }
        )

    if payment_method != "pix":
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": "Cartão será implementado em seguida. Use Pix por enquanto.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
            }
        )

    payment_data = {
        "transaction_amount": 20.0,
        "description": f"Renovacao Bot Smart Pro - {user.user}",
        "payment_method_id": "pix",
        "payer": {
            "email": "pagamentos@botsmartpro.com"
        }
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid.uuid4()),
    }

    print("==== MERCADO PAGO DEBUG ====")
    print("Access token existe?", bool(access_token))
    print("Access token prefixo:", access_token[:12] if access_token else "")
    print("Access token tamanho:", len(access_token or ""))
    print("Payload enviado:", payment_data)

    try:
        response = requests.post(
            "https://api.mercadopago.com/v1/payments",
            json=payment_data,
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": f"Erro de conexão com o Mercado Pago: {e}",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
            }
        )

    print("Status MP:", response.status_code)
    print("Resposta MP:", response.text)

    if response.status_code != 201:
        try:
            mp_error = response.json()
        except Exception:
            mp_error = response.text

        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": f"Erro ao criar pagamento Pix: {mp_error}",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
            }
        )

    payment = response.json()

    # 👇 PEGAMOS O ID DO PAGAMENTO
    payment_id = str(payment.get("id") or "").strip()

    tx = payment.get("point_of_interaction", {}).get("transaction_data", {})
    qr_code = tx.get("qr_code", "")
    qr_base64 = tx.get("qr_code_base64", "")

    if not qr_code or not qr_base64:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": "O Mercado Pago respondeu, mas não retornou o QR Code do Pix.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": None,
            }
        )

    return templates.TemplateResponse(
        "renew_payment.html",
        {
            "request": request,
            "account": account,
            "error": None,
            "success": "Pix gerado com sucesso. Após pagar, clique em Confirmar Pagamento.",
            "pix_qr": qr_base64,
            "pix_code": qr_code,
            "payment_id": payment_id,  # 👈 AGORA ENVIAMOS O ID
            "cpf": cpf or "",
        }
    )

@app.post("/renovar/confirmar-pagamento", response_class=HTMLResponse)
def renovar_confirmar_pagamento(
    request: Request,
    cpf: str = Form(...),
    payment_id: str = Form(...),
    db: Session = Depends(get_db_session),
):
    access_token = (os.getenv("MP_ACCESS_TOKEN_PROD") or "").strip()

    cpf_clean = _only_digits(cpf)
    user = db.query(User).filter(User.cpf == cpf_clean).first()

    def build_account(u):
        now = datetime.datetime.utcnow()
        valid_until = u.trial_until.strftime("%d/%m/%Y %H:%M") if u.trial_until else "Não definido"

        if u.trial_until and now > u.trial_until:
            status_text = "Expirado"
            status_key = "expired"
        elif u.trial_until:
            dias = get_trial_days_left(u.trial_until)
            if isinstance(dias, int) and dias <= 7:
                status_text = f"Expirando ({dias} dias restantes)"
                status_key = "expiring"
            else:
                status_text = f"Ativo ({dias} dias restantes)"
                status_key = "active"
        else:
            status_text = "Sem validade definida"
            status_key = "unknown"

        def mask_cpf(v: str) -> str:
            v = _only_digits(v)
            if len(v) == 11:
                return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
            return v

        return {
            "full_name": u.full_name or "Não informado",
            "username": u.user,
            "cpf_masked": mask_cpf(u.cpf or ""),
            "cpf_raw": u.cpf or "",
            "phone": u.phone or "Não informado",
            "valid_until": valid_until,
            "status_text": status_text,
            "status_key": status_key,
        }

    if not access_token:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": build_account(user) if user else None,
                "error": "Token do Mercado Pago não configurado.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": payment_id or "",
            }
        )

    if not user:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": None,
                "error": "Usuário não encontrado.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": payment_id or "",
            }
        )

    account = build_account(user)

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": f"Erro ao consultar pagamento: {e}",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": payment_id or "",
            }
        )

    if response.status_code != 200:
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": "Não foi possível consultar o pagamento no Mercado Pago.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": payment_id or "",
            }
        )

    payment = response.json()
    status = (payment.get("status") or "").strip().lower()

    if status != "approved":
        return templates.TemplateResponse(
            "renew_payment.html",
            {
                "request": request,
                "account": account,
                "error": f"Pagamento ainda não foi aprovado. Status atual: {status or 'desconhecido'}.",
                "success": None,
                "cpf": cpf or "",
                "pix_qr": None,
                "pix_code": None,
                "payment_id": payment_id or "",
            }
        )

    now = datetime.datetime.utcnow()

    # evita adicionar 30 dias duas vezes para o mesmo payment_id
    if getattr(user, "last_payment_id", None) != str(payment_id):
        if user.trial_until and user.trial_until > now:
            user.trial_until = user.trial_until + datetime.timedelta(days=30)
        else:
            user.trial_until = now + datetime.timedelta(days=30)

        user.last_payment_id = str(payment_id)
        user.last_payment_status = "approved"
        user.last_payment_at = now

        db.add(user)
        db.commit()
        db.refresh(user)

    account = build_account(user)

    return templates.TemplateResponse(
        "renew_payment.html",
        {
            "request": request,
            "account": account,
            "error": None,
            "success": "Pagamento confirmado com sucesso. Seu acesso foi renovado por mais 30 dias.",
            "cpf": cpf or "",
            "pix_qr": None,
            "pix_code": None,
            "payment_id": None,
        }
    )


@app.get("/renovar/status-pagamento")
def renovar_status_pagamento(
    cpf: str,
    payment_id: str,
    db: Session = Depends(get_db_session),
):
    access_token = (os.getenv("MP_ACCESS_TOKEN_PROD") or "").strip()

    if not access_token:
        return {"ok": False, "reason": "missing_access_token"}

    cpf_clean = _only_digits(cpf)
    user = db.query(User).filter(User.cpf == cpf_clean).first()

    if not user:
        return {"ok": False, "reason": "user_not_found"}

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    try:
        response = requests.get(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        return {"ok": False, "reason": "request_error", "detail": str(e)}

    if response.status_code != 200:
        return {"ok": False, "reason": "mp_lookup_failed", "status_code": response.status_code}

    payment = response.json()
    status = (payment.get("status") or "").strip().lower()

    if status == "approved":
        now = datetime.datetime.utcnow()

        # evita adicionar 30 dias várias vezes
        if getattr(user, "last_payment_id", None) != str(payment_id):
            if user.trial_until and user.trial_until > now:
                user.trial_until = user.trial_until + datetime.timedelta(days=30)
            else:
                user.trial_until = now + datetime.timedelta(days=30)

            user.last_payment_id = str(payment_id)
            user.last_payment_status = "approved"
            user.last_payment_at = now

            db.add(user)
            db.commit()

        return {
            "ok": True,
            "approved": True,
            "status": status,
            "trial_until": user.trial_until.isoformat() if user.trial_until else None,
        }

    return {
        "ok": True,
        "approved": False,
        "status": status,
    }

@app.on_event("startup")
def startup():
    ensure_active_session_column()  # 👈 PRIMEIRA COISA

    Base.metadata.create_all(bind=engine)

    # Colunas extras para cadastro público
    ensure_cadastro_columns()

    # 🔥 NOVAS COLUNAS DE PAGAMENTO
    ensure_payment_columns()

    db: Session = SessionLocal()
    try:
        admin = db.query(User).filter(User.user == "Vinici459").first()
        if not admin:
            pw_hash = bcrypt.hashpw("Polegar159826eu!".encode(), bcrypt.gensalt()).decode()
            trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=9999)
            admin_user = User(
                user="Vinici459",
                password=pw_hash,
                role="admin",
                trial_until=trial_until,
                enabled=True,
            )
            db.add(admin_user)
            db.commit()
    finally:
        db.close()


def validar_telefone(phone: str) -> bool:
    phone = _only_digits(phone)

    # Deve ter 10 ou 11 dígitos
    if len(phone) not in (10, 11):
        return False

    # Não pode ser repetição tipo 99999999999
    if phone == phone[0] * len(phone):
        return False

    # Se for celular (11 dígitos), o 3º número deve ser 9
    if len(phone) == 11 and phone[2] != "9":
        return False

    return True

def validar_cpf(cpf: str) -> bool:
    """Validação padrão de CPF (dígitos verificadores)."""
    cpf = _only_digits(cpf)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False

    # 1º dígito
    s1 = sum(int(d) * w for d, w in zip(cpf[:9], range(10, 1, -1)))
    r1 = (s1 * 10) % 11
    d1 = "0" if r1 == 10 else str(r1)

    # 2º dígito
    s2 = sum(int(d) * w for d, w in zip(cpf[:9] + d1, range(11, 1, -1)))
    r2 = (s2 * 10) % 11
    d2 = "0" if r2 == 10 else str(r2)

    return cpf[-2:] == d1 + d2


def _trial_info(user: "User") -> dict:
    until = getattr(user, "trial_until", None)
    if not until:
        return {
            "trial_until": None,
            "trial_remaining_seconds": None,
            "trial_remaining_days": None,
            "trial_expiring": False,
        }

    try:
        now = datetime.datetime.utcnow()
        remaining = max(0.0, float((until - now).total_seconds()))
        days = int(remaining // 86400)
        expiring = remaining <= (3 * 86400)
        return {
            "trial_until": until.isoformat(),
            "trial_remaining_seconds": int(remaining),
            "trial_remaining_days": days,
            "trial_expiring": bool(expiring),
        }
    except Exception:
        return {
            "trial_until": None,
            "trial_remaining_seconds": None,
            "trial_remaining_days": None,
            "trial_expiring": False,
        }


# ==========================
# CADASTRO PÚBLICO (COM LINK)
# ==========================
PUBLIC_SIGNUP_KEY = os.getenv("PUBLIC_SIGNUP_KEY", "").strip()  # defina no Railway


def _signup_key_ok(key: str | None) -> bool:
    if not PUBLIC_SIGNUP_KEY:
        return False
    return (key or "").strip() == PUBLIC_SIGNUP_KEY


@app.get("/cadastro", response_class=HTMLResponse)
def signup_form(key: str | None = None):
    if not _signup_key_ok(key):
        return HTMLResponse("<h3>404</h3>", status_code=404)

    html = """<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cadastro — Bot Smart Pro</title>
  <style>
    body { background:#0b1220; color:#e5e7eb; font-family: Arial, sans-serif; }
    .card { max-width:520px; margin:40px auto; padding:22px; background:#111827; border:1px solid #1f2937; border-radius:14px; }
    h2 { margin:0 0 12px 0; }
    label { display:block; margin-top:12px; color:#cbd5e1; font-size:14px; }
    input { width:100%; padding:12px; margin-top:6px; border-radius:10px; border:1px solid #334155; background:#0f172a; color:#e5e7eb; }
    button { width:100%; padding:12px; margin-top:16px; border:none; border-radius:10px; background:#22c55e; color:#052e16; font-weight:700; cursor:pointer; }
    .muted { margin-top:10px; color:#94a3b8; font-size:12px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Cadastro — Bot Smart Pro</h2>
    <p class="muted">Cadastro com período de teste automático de 15 dias.</p>

    <form action="/cadastro?key=__KEY__" method="post">
  
        <label>Nome completo *</label>
        <input name="full_name" required maxlength="120" placeholder="Seu nome completo">

        <label>CPF *</label>
        <input name="cpf" required maxlength="14" placeholder="000.000.000-00">

        <label>Telefone / WhatsApp *</label>
        <input name="phone" required maxlength="20" placeholder="(11) 99999-9999">

        <label>Usuário *</label>
        <input name="user" required maxlength="50" placeholder="ex: Username">

        <label>Senha *</label>
        <input name="password" required minlength="4" type="password" placeholder="••••••">

        <label>Confirmar Senha *</label>
        <input name="confirm_password" required minlength="4" type="password" placeholder="••••••">

        <button type="submit">Criar conta</button>

        <div style="margin-top:14px;text-align:center;">
            <a href="/renovar" style="color:#60a5fa;text-decoration:none;font-size:13px;">
                Já tem conta? Clique aqui para renovar acesso
            </a>
        </div>

        </form>

  </div>
</body>
</html>"""
    return HTMLResponse(html.replace("__KEY__", key or ""))


@app.post("/cadastro", response_class=HTMLResponse)
def signup_submit(
    key: str | None = None,
    full_name: str = Form(...),
    cpf: str = Form(...),
    phone: str = Form(...),  # 👈 NOVO CAMPO TELEFONE
    user: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),  # 🔐 confirmação de senha
    db: Session = Depends(get_db_session),
):
    if not _signup_key_ok(key):
        return HTMLResponse("<h3>404</h3>", status_code=404)

    username = (user or "").strip()
    name = (full_name or "").strip()
    phone_clean = _only_digits(phone)
    cpf_clean = _only_digits(cpf)

    def render_form(erro_msg=""):
        # 🔁 mesma tela de cadastro, sem página branca
        html = f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>Cadastro — Bot Smart Pro</title>
  <style>
    body {{ background:#0b1220; color:#e5e7eb; font-family: Arial; }}
    .card {{ max-width:520px; margin:40px auto; padding:22px; background:#111827; border-radius:14px; }}
    label {{ display:block; margin-top:12px; }}
    input {{ width:100%; padding:12px; margin-top:6px; border-radius:10px; border:1px solid #334155; background:#0f172a; color:#e5e7eb; }}
    button {{ width:100%; padding:12px; margin-top:16px; border:none; border-radius:10px; background:#22c55e; font-weight:bold; }}
    .erro {{ background:#7f1d1d; color:#fecaca; padding:12px; border-radius:10px; margin-bottom:12px; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Cadastro — Bot Smart Pro</h2>
    {"<div class='erro'>" + erro_msg + "</div>" if erro_msg else ""}
    <form action="/cadastro?key={key}" method="post">
      <label>Nome completo *</label>
      <input name="full_name" value="{name}" required>

      <label>CPF *</label>
      <input name="cpf" value="{cpf}" required>

      <label>Telefone / WhatsApp *</label>
      <input name="phone" value="{phone_clean}" required>

      <label>Usuário *</label>
      <input name="user" value="{username}" required>

      <label>Senha *</label>
      <input name="password" type="password" required>

      <label>Confirmar Senha *</label>
      <input name="confirm_password" type="password" required>

      <button type="submit">Criar conta</button>
    </form>
  </div>
</body>
</html>"""
        return HTMLResponse(html)

    # 🔐 valida campos obrigatórios
    if not name or not username or not password or not phone_clean:
        return render_form("Preencha todos os campos obrigatórios, incluindo o telefone.")

    # 📞 valida telefone
    if not validar_telefone(phone_clean):
        return render_form("Telefone inválido. Digite um número válido com DDD.")

    # 🔐 valida confirmação de senha
    if password != confirm_password:
        return render_form("As senhas não conferem. Volte e digite novamente.")

    # 🔐 valida CPF
    if not validar_cpf(cpf_clean):
        return render_form("CPF inválido (dígitos verificadores não conferem).")

    # 🔐 bloqueia CPF duplicado
    if db.query(User).filter(User.cpf == cpf_clean).first():
        return render_form("CPF já cadastrado. Se sua conta estiver desativada, fale com o suporte.")

    # 🔐 bloqueia usuário duplicado
    if db.query(User).filter(User.user == username).first():
        return render_form("Usuário já existe. Escolha outro.")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=15)

    # 👇 AGORA SALVA O TELEFONE NO BANCO
    new_user = User(
        user=username,
        password=hashed,
        enabled=True,
        role="user",
        perfil="Desconhecido",
        lucro=0.0,
        trial_until=trial_until,
        cpf=cpf_clean,
        full_name=name,
        phone=phone_clean,  # 👈 ESSENCIAL (controle de cliente real)
    )

    db.add(new_user)
    db.commit()

    return HTMLResponse(
        f"""<html><body style='background:#0b1220;color:#e5e7eb;font-family:Arial'>
        <div style='max-width:520px;margin:40px auto;padding:22px;background:#111827;border-radius:14px;'>
        <h2>Conta criada ✅</h2>
        <p>Usuário: <b>{username}</b></p>
        <p>Telefone: <b>{phone_clean}</b></p>
        <p>Período de teste até: <b>{trial_until.strftime('%d/%m/%Y %H:%M')} (UTC)</b></p>
        <p>Agora você já pode fazer login no bot.</p>
        </div></body></html>"""
    )

@app.post("/api/register")
def api_register(data: dict = Body(...), db: Session = Depends(get_db_session)):
    """Cadastro via API (mesma regra do /cadastro)."""
    key = (data.get("key") or "").strip()
    if not _signup_key_ok(key):
        return {"ok": False, "reason": "invalid_key"}

    username = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    client_version = (data.get("version") or data.get("app_version") or "").strip()
    vinfo = _version_status(client_version)

    if vinfo.get("update_required"):
        return {"ok": False, "reason": "update_required", **vinfo}

    name = (data.get("full_name") or "").strip()
    cpf_clean = _only_digits(data.get("cpf") or "")

    if not username or not password or not name or not cpf_clean:
        return {"ok": False, "reason": "missing_fields"}

    if not validar_cpf(cpf_clean):
        return {"ok": False, "reason": "invalid_cpf"}

    if db.query(User).filter(User.cpf == cpf_clean).first():
        return {"ok": False, "reason": "cpf_exists"}

    if db.query(User).filter(User.user == username).first():
        return {"ok": False, "reason": "user_exists"}

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=15)

    new_user = User(
        user=username,
        password=hashed,
        enabled=True,
        role="user",
        perfil="Desconhecido",
        lucro=0.0,
        trial_until=trial_until,
        cpf=cpf_clean,
        full_name=name,
    )
    db.add(new_user)
    db.commit()

    return {"ok": True, "user": username, **_trial_info(new_user)}



@app.get("/")
def root():
    # Redireciona visitantes para a página de cadastro público
    return RedirectResponse(url=f"/cadastro?key={PUBLIC_SIGNUP_KEY}")

@app.get("/admin-smartpro-459-panel", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "msg": ""})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.user == username).first()
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Usuário não encontrado."})

    # 👇 Só o admin pode acessar o painel
    if username != "Vinici459":
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Acesso permitido apenas ao administrador."})

    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Senha incorreta."})
    if not user.enabled:
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Usuário desativado."})
    if user.role != "admin" and user.trial_until:
        if datetime.datetime.utcnow() > user.trial_until:
            return templates.TemplateResponse("login.html", {"request": request, "msg": "Período de teste expirado."})
    now = datetime.datetime.utcnow()
    user.last_login = now
    user.login_count = (user.login_count or 0) + 1
    db.add(user)
    db.commit()
    token = create_token(username)
    resp = RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)
    resp.set_cookie("token", token, httponly=True, max_age=21600)
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    key: str | None = None,  # 👈 NOVO
    admin=Depends(require_admin),
    db: Session = Depends(get_db_session),
):
    # 🔒 BLOQUEIO POR CHAVE SECRETA
    if key != ADMIN_SECRET_KEY:
        return HTMLResponse("<h3>404</h3>", status_code=404)

    users = db.query(User).all()
    users_data = []

    for u in users:
        created_str = ""
        if u.created_at:
            created_str = u.created_at.date().isoformat()

        users_data.append(
            {
                "id": u.id,
                "user": u.user,
                "full_name": u.full_name or "",
                "cpf": u.cpf or "",
                "phone": getattr(u, "phone", "") or "",
                "enabled": "Ativo" if u.enabled else "Desativado",
                "lucro": f"{(u.lucro or 0.0):.2f}%",
                "perfil": u.perfil or "Desconhecido",
                "trial": get_trial_days_left(u.trial_until),
                "created": created_str,
                "logins": u.login_count or 0,
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "users": users_data,
            "admin": admin["user"]
        }
    )


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/admin-smartpro-459-panel")
    resp.delete_cookie("token")
    return resp


@app.post("/add_user")
def add_user(
    username: str = Form(...),
    password: str = Form(...),
    trial_days: int = Form(7),
    admin=Depends(require_admin),
    db: Session = Depends(get_db_session),
):
    existing = db.query(User).filter(User.user == username).first()
    if existing:
        return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=trial_days)
    new_user = User(
        user=username,
        password=pw_hash,
        trial_until=trial_until,
        enabled=True,
        lucro=0.0,
        perfil="Desconhecido",
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)


@app.post("/delete_user/{user_id}")
def delete_user(user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)


@app.post("/toggle_user/{user_id}/{state}")
def toggle_user(user_id: int, state: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.enabled = bool(state)
        db.add(user)
        db.commit()
    return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)


@app.get("/edit_trial/{user_id}", response_class=HTMLResponse)
def edit_trial_page(request: Request, user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)
    return HTMLResponse(
        content=f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Editar Trial — {user.user}</title>
        <style>
          body {{
            background-color: #0e1013;
            color: #e5e7eb;
            font-family: 'Segoe UI', Arial;
            text-align: center;
            padding-top: 100px;
          }}
          .card {{
            background-color: #171a1d;
            padding: 30px 50px;
            display: inline-block;
            border-radius: 16px;
            box-shadow: 0 0 15px #00000070;
          }}
          input {{
            background-color: #1f2225;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px;
            width: 120px;
            text-align: center;
            margin-bottom: 15px;
          }}
          button {{
            background-color: #2563eb;
            border: none;
            color: white;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
          }}
          button:hover {{ background-color: #1d4ed8; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2>Editar período de trial</h2>
          <p>Usuário: <b>{user.user}</b></p>
          <form action="/update_trial/{user_id}" method="post">
            <label>Dias de teste:</label><br>
            <input type="number" name="trial_days" min="1" value="7" required><br>
            <button type="submit">Salvar</button>
          </form>
          <p><a href="/dashboard?key=macdsmartpro_admin" style="color:#60a5fa;">Voltar</a></p>
        </div>
      </body>
    </html>
    """
    )


@app.post("/update_trial/{user_id}")
def update_trial(user_id: int, trial_days: int = Form(...), admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=trial_days)
        db.add(user)
        db.commit()
    return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)




@app.post("/api/auth")
def api_auth(data: dict = Body(...), db: Session = Depends(get_db_session)):

    # =========================
    # 📦 VERSIONAMENTO
    # =========================
    client_version = (data.get("version") or "0.0").strip()
    vinfo = _version_info(client_version)

    # =========================
    # 🔐 LOGIN NORMAL
    # =========================
    username = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return {"ok": False, "reason": "missing_fields"}

    # 🚨 Se for atualização obrigatória → bloqueia antes de tudo
    if vinfo.get("update_required"):
        return {
            "ok": False,
            "reason": "update_required",
            **vinfo
        }

    user = db.query(User).filter(User.user == username).first()

    if not user:
        return {"ok": False, "reason": "user_not_found"}

    if not user.enabled:
        return {"ok": False, "reason": "disabled"}

    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        return {"ok": False, "reason": "invalid_password"}

    # =========================
    # 🧪 TRIAL / LICENÇA
    # =========================
    if user.trial_until:
        try:
            if datetime.datetime.utcnow() > user.trial_until:
                return {"ok": False, "reason": "trial_expired"}
        except Exception:
            pass

    # =========================
    # 🔐 NOVA SESSÃO
    # =========================
    session_id = str(uuid.uuid4())
    user.active_session = session_id
    user.last_login = datetime.datetime.utcnow()
    user.login_count = (user.login_count or 0) + 1

    db.add(user)
    db.commit()

    # =========================
    # ✅ SUCESSO
    # =========================
    return {
        "ok": True,
        "user": username,
        "session_id": session_id,
        "perfil": user.perfil,
        "lucro": user.lucro,
        **_trial_info(user),
        **vinfo  # 👈 AQUI ENTRA O VERSIONAMENTO
    }

@app.post("/api/update_results")
def api_update_results(data: dict = Body(...), db: Session = Depends(get_db_session)):

    username = data.get("user")
    lucro = data.get("lucro")
    perfil = data.get("perfil")

    # ✅ PEGAR VERSÃO DO CLIENTE
    client_version = (data.get("version") or data.get("app_version") or "").strip()
    vinfo = _version_status(client_version)

    if not username:
        return {"ok": False, "reason": "missing_user"}

    # 🚨 Atualização obrigatória bloqueia
    if vinfo.get("update_required"):
        return {"ok": False, "reason": "update_required", **vinfo}

    try:
        lucro = float(lucro)
    except Exception:
        lucro = 0.0

    perfil = str(perfil or "Desconhecido").strip()

    user = db.query(User).filter(User.user == username).first()

    if not user:
        return {"ok": False, "reason": "user_not_found"}

    user.lucro = lucro
    user.perfil = perfil

    db.add(user)
    db.commit()

    return {"ok": True, **vinfo}


@app.post("/api/account_status")
def api_account_status(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = (data.get("user") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    client_version = (data.get("version") or data.get("app_version") or "").strip()
    vinfo = _version_status(client_version)

    if not username:
        return {
            "ok": False,
            "valid": False,
            "reason": "missing_user",
            "trial_remaining_seconds": 0,
            "trial_remaining_days": 0,
            "trial_expiring": False,
        }

    user = db.query(User).filter(User.user == username).first()

    if not user:
        return {
            "ok": False,
            "valid": False,
            "reason": "user_not_found",
            "trial_remaining_seconds": 0,
            "trial_remaining_days": 0,
            "trial_expiring": False,
        }

    # Conta desativada pelo admin
    if not user.enabled:
        trial_data = _trial_info(user)
        return {
            "ok": False,
            "valid": False,
            "reason": "disabled",
            **trial_data,
        }

    # 🔐 Validação de sessão única (anti multi-dispositivo)
    if session_id:
        if not user.active_session or user.active_session != session_id:
            trial_data = _trial_info(user)
            return {
                "ok": False,
                "valid": False,
                "reason": "session_invalid",
                **trial_data,
            }

    # 🚫 Atualização obrigatória?
    if vinfo.get("update_required"):
        trial_data = _trial_info(user)
        return {
            "ok": False,
            "valid": False,
            "reason": "update_required",
            **trial_data,
            **vinfo,
        }

    # 📅 Verificação do período de teste/licença
    trial_data = _trial_info(user)

    if user.trial_until:
        try:
            now = datetime.datetime.utcnow()

            # Expirou completamente
            if now > user.trial_until:
                return {
                    "ok": False,
                    "valid": False,
                    "reason": "trial_expired",
                    **trial_data,
                }

        except Exception as e:
            print("[ACCOUNT_STATUS] erro ao verificar trial:", e)

    # ✅ Licença válida (fluxo normal do bot)
    return {
        "ok": True,
        "valid": True,
        "reason": "active",
        **trial_data,
        **vinfo,
    }

@app.post("/api/validate_session")
def api_validate_session(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = data.get("user")
    session_id = data.get("session_id")
    client_version = (data.get("version") or data.get("app_version") or "").strip()
    vinfo = _version_status(client_version)
    
    if not username:
        return {"ok": False, "reason": "missing_fields"}

    user = db.query(User).filter(User.user == username).first()

    if not user:
        return {"ok": False, "reason": "user_not_found"}
   
    if not user.enabled:
        return {"ok": False, "reason": "disabled"}
    
    if user.trial_until:
        try:
            if datetime.datetime.utcnow() > user.trial_until:
                return {"ok": False, "reason": "trial_expired"}
        except Exception:
            pass
   
    if session_id:
        if not user.active_session or user.active_session != session_id:
            return {"ok": False, "reason": "session_invalid"}
    
    return {"ok": True}


@app.post("/api/trade_report")
def api_trade_report(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = data.get("user")
    symbol = data.get("symbol")
    perfil = data.get("perfil")
    valor = data.get("valor")
    entry_price = data.get("entry_price")
    exit_price = data.get("exit_price")
    qty = data.get("qty")
    retorno = data.get("retorno")
    reason = data.get("reason")
    entry_time = data.get("entry_time")
    exit_time = data.get("exit_time")
    if not username or not symbol:
        return {"ok": False, "reason": "missing_fields"}
    try:
        valor = float(valor) if valor is not None else 0.0
    except Exception:
        valor = 0.0
    try:
        entry_price = float(entry_price) if entry_price is not None else 0.0
    except Exception:
        entry_price = 0.0
    try:
        exit_price = float(exit_price) if exit_price is not None else 0.0
    except Exception:
        exit_price = 0.0
    try:
        qty = float(qty) if qty is not None else 0.0
    except Exception:
        qty = 0.0
    try:
        retorno = float(retorno) if retorno is not None else 0.0
    except Exception:
        retorno = 0.0
    started_at = None
    ended_at = None
    try:
        if entry_time is not None:
            started_at = datetime.datetime.utcfromtimestamp(float(entry_time))
    except Exception:
        started_at = None
    try:
        if exit_time is not None:
            ended_at = datetime.datetime.utcfromtimestamp(float(exit_time))
    except Exception:
        ended_at = None
    trade = Trade(
        user=username,
        symbol=symbol,
        perfil=perfil,
        valor=valor,
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty,
        retorno=retorno,
        reason=reason,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(trade)
    db.commit()
    return {"ok": True}


@app.get("/api/users_summary")
def api_users_summary(admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    users = db.query(User).all()
    data = []
    for u in users:
        created_str = u.created_at.isoformat() if u.created_at else ""
        trial = get_trial_days_left(u.trial_until)
        data.append(
            {
                "id": u.id,
                "user": u.user,
                "enabled": bool(u.enabled),
                "lucro": u.lucro or 0.0,
                "lucro_fmt": f"{(u.lucro or 0.0):.2f}%",
                "perfil": u.perfil or "Desconhecido",
                "trial": trial,
                "created": created_str,
                "logins": u.login_count or 0,
            }
        )
    return {"users": data}


@app.get("/user_info/{username}", response_class=HTMLResponse)
def user_info_page(
    request: Request,
    username: str,
    key: str | None = None,  # 🔐 chave secreta do admin
    admin=Depends(require_admin),
    db: Session = Depends(get_db_session)
):
    # 🔒 Proteção por chave (igual ao dashboard)
    if key != ADMIN_SECRET_KEY:
        return HTMLResponse("<h3>404</h3>", status_code=404)

    # 🔥 LINHA CRÍTICA QUE FALTAVA (obrigatória)
    user = db.query(User).filter(User.user == username).first()

    # Se usuário não existir, volta ao painel seguro
    if not user:
        return RedirectResponse(url=f"/dashboard?key={ADMIN_SECRET_KEY}", status_code=303)

    created_at = user.created_at.isoformat() if user.created_at else ""
    last_login = user.last_login.isoformat() if user.last_login else "Nunca"
    trial_days = get_trial_days_left(user.trial_until)

    return HTMLResponse(
        content=f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Informações do Cliente — {username}</title>
        <style>
          body {{
            background-color: #0e1013;
            color: #e5e7eb;
            font-family: 'Segoe UI', Arial;
            margin: 0;
            padding: 30px;
          }}
          .card {{
            max-width: 700px;
            margin: auto;
            background: #171a1d;
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 0 15px #00000060;
          }}
          h2 {{
            text-align: center;
            margin-bottom: 25px;
          }}
          .row {{
            margin-bottom: 12px;
            font-size: 16px;
          }}
          .label {{
            color: #9ca3af;
            font-weight: bold;
          }}
          .value {{
            color: #e5e7eb;
          }}
          .btn {{
            display: inline-block;
            margin-top: 25px;
            padding: 10px 18px;
            background: #2563eb;
            color: white;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
          }}
          .btn:hover {{
            background: #1d4ed8;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2>Ficha do Cliente</h2>

          <div class="row">
            <span class="label">Usuário:</span>
            <span class="value">{user.user}</span>
          </div>

          <div class="row">
            <span class="label">Nome completo:</span>
            <span class="value">{user.full_name or "Não informado"}</span>
          </div>

          <div class="row">
            <span class="label">CPF:</span>
            <span class="value">{user.cpf or "Não informado"}</span>
          </div>

          <div class="row">
            <span class="label">Telefone / WhatsApp:</span>
            <span class="value">{getattr(user, "phone", "Não informado")}</span>
          </div>

          <div class="row">
            <span class="label">Status:</span>
            <span class="value">{"Ativo" if user.enabled else "Desativado"}</span>
          </div>

          <div class="row">
            <span class="label">Perfil do Bot:</span>
            <span class="value">{user.perfil or "Desconhecido"}</span>
          </div>

          <div class="row">
            <span class="label">Lucro registrado:</span>
            <span class="value">{(user.lucro or 0.0):.2f}%</span>
          </div>

          <div class="row">
            <span class="label">Dias de Trial restantes:</span>
            <span class="value">{trial_days}</span>
          </div>

          <div class="row">
            <span class="label">Data de criação:</span>
            <span class="value">{created_at}</span>
          </div>

          <div class="row">
            <span class="label">Último login:</span>
            <span class="value">{last_login}</span>
          </div>

          <div class="row">
            <span class="label">Total de logins:</span>
            <span class="value">{user.login_count or 0}</span>
          </div>

          <a class="btn" href="/dashboard?key={ADMIN_SECRET_KEY}">⬅ Voltar ao Painel</a>
          &nbsp;
          <a class="btn" href="/user_trades/{username}?key={ADMIN_SECRET_KEY}">📊 Ver Trades</a>
        </div>
      </body>
    </html>
    """
    )
@app.get("/user_trades/{username}", response_class=HTMLResponse)
def user_trades_page(
    request: Request,
    username: str,
    key: str | None = None,  # 🔐 proteção por chave
    admin=Depends(require_admin),
    db: Session = Depends(get_db_session)
):
    # 🔒 Proteção igual ao dashboard
    if key != ADMIN_SECRET_KEY:
        return HTMLResponse("<h3>404</h3>", status_code=404)

    trades = (
        db.query(Trade)
        .filter(Trade.user == username)
        .order_by(Trade.id.desc())
        .all()
    )

    total_trades = len(trades)
    total_retorno = sum([(t.retorno or 0.0) for t in trades])
    total_em_usdt = sum([(t.valor or 0.0) * ((t.retorno or 0.0) / 100.0) for t in trades])

    rows_html = ""
    for t in trades:
        started_at = t.started_at.isoformat() if t.started_at else ""
        ended_at = t.ended_at.isoformat() if t.ended_at else ""
        created_at = t.created_at.isoformat() if t.created_at else ""

        rows_html += f"""
        <tr>
          <td>{t.symbol}</td>
          <td>{t.perfil or ''}</td>
          <td>{(t.valor or 0.0):.2f}</td>
          <td>{(t.entry_price or 0.0):.4f}</td>
          <td>{(t.exit_price or 0.0):.4f}</td>
          <td>{(t.qty or 0.0):.6f}</td>
          <td>{(t.retorno or 0.0):.2f}%</td>
          <td>{t.reason or ''}</td>
          <td>{started_at}</td>
          <td>{ended_at}</td>
          <td>{created_at}</td>
        </tr>
        """

    return HTMLResponse(
        content=f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Trades — {username}</title>
        <style>
          body {{
            background-color: #0e1013;
            color: #e5e7eb;
            font-family: 'Segoe UI', Arial;
            margin: 0;
            padding: 20px;
          }}
          h2 {{ text-align: center; }}
          table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
          }}
          th, td {{
            border: 1px solid #111827;
            padding: 8px;
            font-size: 13px;
            text-align: center;
          }}
          th {{ background-color: #1f2933; }}
          tr:nth-child(even) {{ background-color: #15171b; }}
          .btn {{
            display: inline-block;
            margin-bottom: 15px;
            padding: 10px 18px;
            background: #2563eb;
            color: white;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
          }}
        </style>
      </head>
      <body>
        <h2>Histórico de Trades — {username}</h2>
        <div style="text-align:center;">
          <a class="btn" href="/dashboard?key={ADMIN_SECRET_KEY}">⬅ Voltar ao Painel</a>
        </div>

        <div style="text-align:center; margin-top:10px;">
          <b>Total de Trades:</b> {total_trades} |
          <b>Lucro acumulado:</b> {total_retorno:.2f}% |
          <b>Lucro em USDT:</b> {total_em_usdt:.2f}
        </div>

        <table>
          <tr>
            <th>Moeda</th>
            <th>Perfil</th>
            <th>Valor</th>
            <th>Entrada</th>
            <th>Saída</th>
            <th>Qtd</th>
            <th>Retorno</th>
            <th>Motivo</th>
            <th>Início</th>
            <th>Fim</th>
            <th>Registrado</th>
          </tr>
          {rows_html}
        </table>
      </body>
    </html>
    """
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
    