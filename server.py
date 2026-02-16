from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uuid

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

SECRET_KEY = "chave_super_segura"
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
    """Garante colunas/índices necessários para o cadastro público (CPF e Nome)."""
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
            # índice único para CPF (não falha se já existir)
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_cpf ON users (cpf);"))
            except Exception:
                pass
            conn.commit()
            print("[DB] Colunas cpf/full_name verificadas/criadas.")
    except Exception as e:
        print("[DB] Erro ao garantir colunas cpf/full_name:", e)



class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, unique=True, index=True, nullable=False)

    # Cadastro público (CPF + Nome)
    cpf = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)

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

    if not data:
        raise HTTPException(status_code=303, headers={"Location": "/"})

    username = data.get("user")

    # Só esse usuário tem acesso ao painel
    if username != "Vinici459":
        raise HTTPException(status_code=303, headers={"Location": "/"})

    return data


def require_login(request: Request):
    token = request.cookies.get("token")
    data = decode_token(token) if token else None
    if not data:
        raise HTTPException(status_code=303, headers={"Location": "/"})
    return data


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


@app.on_event("startup")
def startup():
    ensure_active_session_column()  # 👈 PRIMEIRA COISA, ANTES DE TUDO

    Base.metadata.create_all(bind=engine)

    # Colunas extras para cadastro público (seguro rodar sempre)
    ensure_cadastro_columns()

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




def _only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


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
      <input name="full_name" required maxlength="120" placeholder="Seu nome">
      <label>CPF *</label>
      <input name="cpf" required maxlength="14" placeholder="000.000.000-00">
      <label>Usuário *</label>
      <input name="user" required maxlength="50" placeholder="ex: vinici459">
      <label>Senha *</label>
      <input name="password" required minlength="4" type="password" placeholder="••••••">
      <button type="submit">Criar conta</button>
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
    user: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db_session),
):
    if not _signup_key_ok(key):
        return HTMLResponse("<h3>404</h3>", status_code=404)

    username = (user or "").strip()
    name = (full_name or "").strip()
    cpf_clean = _only_digits(cpf)

    if not name or not username or not password:
        return HTMLResponse("<p>Campos obrigatórios.</p>", status_code=400)

    if not validar_cpf(cpf_clean):
        return HTMLResponse("<p>CPF inválido (dígitos verificadores não conferem).</p>", status_code=400)

    # Bloqueia duplicado de CPF (mesmo se desativado)
    if db.query(User).filter(User.cpf == cpf_clean).first():
        return HTMLResponse("<p>CPF já cadastrado. Se sua conta estiver desativada, fale com o suporte.</p>", status_code=409)

    # Bloqueia duplicado de username
    if db.query(User).filter(User.user == username).first():
        return HTMLResponse("<p>Usuário já existe. Escolha outro.</p>", status_code=409)

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

    return HTMLResponse(
        f"""<html><body style='background:#0b1220;color:#e5e7eb;font-family:Arial'>
        <div style='max-width:520px;margin:40px auto;padding:22px;background:#111827;border:1px solid #1f2937;border-radius:14px;'>
        <h2>Conta criada ✅</h2>
        <p>Usuário: <b>{username}</b></p>
        <p>Período de teste até: <b>{trial_until.strftime('%d/%m/%Y %H:%M')} (UTC)</b></p>
        <p style='color:#94a3b8;font-size:12px;'>Agora você já pode fazer login no bot.</p>
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

@app.get("/", response_class=HTMLResponse)
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
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie("token", token, httponly=True, max_age=21600)
    return resp


# 👇 AQUI trocamos require_login → require_admin
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
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
                "enabled": "Ativo" if u.enabled else "Desativado",
                "lucro": f"{(u.lucro or 0.0):.2f}%",
                "perfil": u.perfil or "Desconhecido",
                "trial": get_trial_days_left(u.trial_until),
                "created": created_str,
                "logins": u.login_count or 0,
            }
        )
    return templates.TemplateResponse("dashboard.html", {"request": request, "users": users_data, "admin": admin["user"]})


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/")
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
        return RedirectResponse(url="/dashboard", status_code=303)
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
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/delete_user/{user_id}")
def delete_user(user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/toggle_user/{user_id}/{state}")
def toggle_user(user_id: int, state: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.enabled = bool(state)
        db.add(user)
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/edit_trial/{user_id}", response_class=HTMLResponse)
def edit_trial_page(request: Request, user_id: int, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
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
          <p><a href="/dashboard" style="color:#60a5fa;">Voltar</a></p>
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
    return RedirectResponse(url="/dashboard", status_code=303)




@app.post("/api/auth")
def api_auth(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return {"ok": False, "reason": "missing_fields"}

    user = db.query(User).filter(User.user == username).first()

    if not user:
        return {"ok": False, "reason": "user_not_found"}

    if not user.enabled:
        return {"ok": False, "reason": "disabled"}

    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        return {"ok": False, "reason": "invalid_password"}

    # valida trial/licença
    if user.trial_until:
        try:
            if datetime.datetime.utcnow() > user.trial_until:
                return {"ok": False, "reason": "trial_expired"}
        except Exception:
            pass

    # 🔐 gera nova sessão (derruba qualquer login anterior)
    session_id = str(uuid.uuid4())
    user.active_session = session_id

    user.last_login = datetime.datetime.utcnow()
    user.login_count = (user.login_count or 0) + 1

    db.add(user)
    db.commit()

    return {
        "ok": True,
        "user": username,
        "session_id": session_id,   # 👈 BOT VAI USAR ISSO NO HEARTBEAT
        "perfil": user.perfil,
        "lucro": user.lucro,
        **_trial_info(user),
    }



@app.post("/api/update_results")
def api_update_results(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = data.get("user")
    lucro = data.get("lucro")
    perfil = data.get("perfil")
    if not username:
        return {"ok": False, "reason": "missing_user"}
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
    return {"ok": True}


@app.post("/api/account_status")
def api_account_status(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = (data.get("user") or "").strip()
    session_id = (data.get("session_id") or "").strip()

    if not username:
        return {"ok": False, "reason": "missing_user"}

    user = db.query(User).filter(User.user == username).first()
    if not user:
        return {"ok": False, "reason": "user_not_found"}
    if not user.enabled:
        return {"ok": False, "reason": "disabled"}

    if session_id:
        if not user.active_session or user.active_session != session_id:
            return {"ok": False, "reason": "session_invalid"}

    # trial check
    if user.trial_until:
        try:
            if datetime.datetime.utcnow() > user.trial_until:
                return {"ok": False, "reason": "trial_expired", **_trial_info(user)}
        except Exception:
            pass

    return {"ok": True, **_trial_info(user)}

@app.post("/api/validate_session")
def api_validate_session(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = data.get("user")
    session_id = data.get("session_id")
    
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


@app.get("/user_trades/{username}", response_class=HTMLResponse)
def user_trades_page(request: Request, username: str, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    trades = (
        db.query(Trade)
        .filter(Trade.user == username)
        .order_by(Trade.id.desc())
        .all()
    )

    total_trades = len(trades)
    total_retorno = sum([(t.retorno or 0.0) for t in trades])
    total_em_usdt = sum([(t.valor or 0.0) * ((t.retorno or 0.0) / 100.0) for t in trades])

    summary_html = f"""
    <div style='margin-bottom:20px; text-align:center; font-size:16px;'>
        <b>Total de Trades:</b> {total_trades} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Lucro acumulado:</b> {total_retorno:.2f}% &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Lucro em USDT:</b> {total_em_usdt:.2f}
    </div>
    """

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
          h2 {{
            text-align: center;
            margin-bottom: 8px;
          }}
          table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
          }}
          th, td {{
            border: 1px solid #111827;
            padding: 8px;
            font-size: 13px;
            text-align: center;
          }}
          th {{
            background-color: #1f2933;
          }}
          tr:nth-child(even) {{
            background-color: #15171b;
          }}
          a {{
            color: #60a5fa;
          }}
        </style>
      </head>
      <body>
        <h2>Histórico de trades — {username}</h2>
        <p style="text-align:center;"><a href="/dashboard">Voltar ao painel</a></p>
        {summary_html}
        <table>
          <tr>
            <th>Moeda</th>
            <th>Perfil</th>
            <th>Valor (USDT)</th>
            <th>Entrada</th>
            <th>Saída</th>
            <th>Quantidade</th>
            <th>Retorno</th>
            <th>Motivo</th>
            <th>Início</th>
            <th>Fim</th>
            <th>Registrado em</th>
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
