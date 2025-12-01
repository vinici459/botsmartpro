from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    lucro = Column(Float, default=0.0)
    perfil = Column(String, default="Desconhecido")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    login_count = Column(Integer, default=0)
    trial_until = Column(DateTime, nullable=True)
    role = Column(String, default="user")


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


# =====================================================
# 🚨 ADMIN FIXO — SOMENTE "Vinici459"
# =====================================================
def require_admin(request: Request, db: Session = Depends(get_db_session)):
    token = request.cookies.get("token")
    data = decode_token(token) if token else None

    if not data:
        raise HTTPException(status_code=303, headers={"Location": "/"})

    username = data.get("user")

    # 🔥 APENAS ESTE USUÁRIO PODE ACESSAR
    if username != "Vinici459":
        raise HTTPException(status_code=303, headers={"Location": "/"})

    return data
# =====================================================


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
    Base.metadata.create_all(bind=engine)
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


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "msg": ""})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.user == username).first()

    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Usuário não encontrado."})

    # 🔥 O ÚNICO USUÁRIO COM PERMISSÃO
    if username != "Vinici459":
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Acesso permitido apenas ao administrador."})

    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Senha incorreta."})

    now = datetime.datetime.utcnow()
    user.last_login = now
    user.login_count = (user.login_count or 0) + 1
    db.add(user)
    db.commit()

    token = create_token(username)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie("token", token, httponly=True, max_age=21600)
    return resp


# =====================================================
# 🔥 ALTERAÇÃO PRINCIPAL: require_admin no dashboard
# =====================================================
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    users = db.query(User).all()
    users_data = []
    for u in users:
        created_str = u.created_at.date().isoformat() if u.created_at else ""
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


# =====================================================
# 🔥 TODAS AS ROTAS ADMIN DEVEM USAR require_admin
# =====================================================

@app.post("/add_user")
def add_user(username: str = Form(...), password: str = Form(...),
             trial_days: int = Form(7), admin=Depends(require_admin),
             db: Session = Depends(get_db_session)):
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
    return templates.TemplateResponse("edit_trial.html", {"request": request, "user": user})


@app.post("/update_trial/{user_id}")
def update_trial(user_id: int, trial_days: int = Form(...), admin=Depends(require_admin), db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.trial_until = datetime.datetime.utcnow() + datetime.timedelta(days=trial_days)
        db.add(user)
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


# =====================================================
# API ORIGINAL MANTIDA — NÃO ALTERAMOS
# =====================================================
@app.post("/api/auth")
def api_auth(data: dict = Body(...), db: Session = Depends(get_db_session)):
    username = data.get("user")
    password = data.get("password")
    user = db.query(User).filter(User.user == username).first()
    if not user:
        return {"ok": False, "reason": "user_not_found"}
    if not user.enabled:
        return {"ok": False, "reason": "disabled"}
    if not bcrypt.checkpw(password.encode(), user.password.encode()):
        return {"ok": False, "reason": "invalid_password"}
    remaining_days = 0
    if user.trial_until:
        remaining_days = max((user.trial_until - datetime.datetime.utcnow()).days, 0)
    return {
        "ok": True,
        "user": username,
        "perfil": user.perfil,
        "lucro": user.lucro,
        "trial_remaining_days": remaining_days,
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
        valor = float(valor) if valor else 0.0
    except:
        valor = 0.0
    try:
        entry_price = float(entry_price) if entry_price else 0.0
    except:
        entry_price = 0.0
    try:
        exit_price = float(exit_price) if exit_price else 0.0
    except:
        exit_price = 0.0
    try:
        qty = float(qty) if qty else 0.0
    except:
        qty = 0.0
    try:
        retorno = float(retorno) if retorno else 0.0
    except:
        retorno = 0.0
    started_at = None
    ended_at = None
    try:
        if entry_time:
            started_at = datetime.datetime.utcfromtimestamp(float(entry_time))
    except:
        pass
    try:
        if exit_time:
            ended_at = datetime.datetime.utcfromtimestamp(float(exit_time))
    except:
        pass

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
      </head>
      <body>
        <h2>Histórico de trades — {username}</h2>
        <table border="1">{rows_html}</table>
      </body>
    </html>
    """
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
