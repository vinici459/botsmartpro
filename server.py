from fastapi import FastAPI, Request, Form, Depends, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3, bcrypt, jwt, datetime, os

# === Configurações Gerais ===
SECRET_KEY = "chave_super_segura"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Painel Admin MACD Smart Pro")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# === Banco de Dados ===
def get_db():
    db_path = os.getenv("DB_PATH", "/tmp/users.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con



# === Token ===
def create_token(user):
    payload = {"user": user, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=6)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


# --- Verificação de administrador e login ---
def require_admin(request: Request):
    token = request.cookies.get("token")
    data = decode_token(token) if token else None
    if not data:
        raise HTTPException(status_code=303, detail="Redirecionar para login", headers={"Location": "/"})
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
        remaining = datetime.datetime.fromisoformat(trial_until) - datetime.datetime.utcnow()
        return max(0, remaining.days)
    except Exception:
        return "-"


# === Inicialização do Banco ===
@app.on_event("startup")
def startup():
    os.environ["DB_PATH"] = "/tmp/users.db"
    con = get_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT UNIQUE,
            password TEXT,
            enabled INTEGER DEFAULT 1,
            lucro REAL DEFAULT 0.0,
            perfil TEXT DEFAULT 'Desconhecido',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            login_count INTEGER DEFAULT 0,
            trial_until TEXT,
            role TEXT DEFAULT 'user'
        )
    """)
    # Cria admin padrão
    admin = con.execute("SELECT * FROM users WHERE user='admin'").fetchone()
    if not admin:
        pw_hash = bcrypt.hashpw("1234".encode(), bcrypt.gensalt()).decode()
        con.execute("""
            INSERT INTO users (user, password, role, trial_until)
            VALUES (?, ?, ?, ?)
        """, ("admin", pw_hash, "admin", (datetime.datetime.utcnow() + datetime.timedelta(days=9999)).isoformat()))
        con.commit()
    con.close()


# === Rotas principais ===
@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "msg": ""})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    con = get_db()
    user = con.execute("SELECT * FROM users WHERE user=?", (username,)).fetchone()

    if not user:
        con.close()
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Usuário não encontrado."})
    if not bcrypt.checkpw(password.encode(), user["password"].encode()):
        con.close()
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Senha incorreta."})
    if not user["enabled"]:
        con.close()
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Usuário desativado."})

    # Verifica trial
    if user["role"] != "admin" and user["trial_until"]:
        trial_end = datetime.datetime.fromisoformat(user["trial_until"])
        if datetime.datetime.utcnow() > trial_end:
            con.close()
            return templates.TemplateResponse("login.html", {"request": request, "msg": "Período de teste expirado."})

    # Atualiza login info
    now = datetime.datetime.utcnow().isoformat()
    con.execute("UPDATE users SET last_login=?, login_count=login_count+1 WHERE user=?", (now, username))
    con.commit()
    con.close()

    token = create_token(username)
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie("token", token, httponly=True, max_age=21600)
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, admin=Depends(require_login)):
    con = get_db()
    users = con.execute("SELECT * FROM users").fetchall()
    con.close()
    users_data = []
    for u in users:
        users_data.append({
            "id": u["id"],
            "user": u["user"],
            "enabled": "Ativo" if u["enabled"] else "Desativado",
            "lucro": f"{u['lucro']:.2f}%",
            "perfil": u["perfil"],
            "trial": get_trial_days_left(u["trial_until"]),
            "created": u["created_at"].split("T")[0],
            "logins": u["login_count"]
        })
    return templates.TemplateResponse("dashboard.html", {"request": request, "users": users_data, "admin": admin["user"]})


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/")
    resp.delete_cookie("token")
    return resp


# === Ações do painel ===
@app.post("/add_user")
def add_user(username: str = Form(...), password: str = Form(...), trial_days: int = Form(7), admin=Depends(require_login)):
    con = get_db()
    try:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        trial_until = (datetime.datetime.utcnow() + datetime.timedelta(days=trial_days)).isoformat()
        con.execute("INSERT INTO users (user, password, trial_until) VALUES (?, ?, ?)", (username, pw_hash, trial_until))
        con.commit()
    except sqlite3.IntegrityError:
        pass
    con.close()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/delete_user/{user_id}")
def delete_user(user_id: int, admin=Depends(require_login)):
    con = get_db()
    con.execute("DELETE FROM users WHERE id=?", (user_id,))
    con.commit()
    con.close()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/toggle_user/{user_id}/{state}")
def toggle_user(user_id: int, state: int, admin=Depends(require_login)):
    con = get_db()
    con.execute("UPDATE users SET enabled=? WHERE id=?", (state, user_id))
    con.commit()
    con.close()
    return RedirectResponse(url="/dashboard", status_code=303)


# === Editar Trial de Usuário ===
@app.get("/edit_trial/{user_id}", response_class=HTMLResponse)
def edit_trial_page(request: Request, user_id: int, admin=Depends(require_login)):
    con = get_db()
    user = con.execute("SELECT user, trial_until FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()

    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)

    return HTMLResponse(content=f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <title>Editar Trial — {user['user']}</title>
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
          <p>Usuário: <b>{user['user']}</b></p>
          <form action="/update_trial/{user_id}" method="post">
            <label>Dias de teste:</label><br>
            <input type="number" name="trial_days" min="1" value="7" required><br>
            <button type="submit">Salvar</button>
          </form>
          <p><a href="/dashboard" style="color:#60a5fa;">Voltar</a></p>
        </div>
      </body>
    </html>
    """)


@app.post("/update_trial/{user_id}")
def update_trial(user_id: int, trial_days: int = Form(...), admin=Depends(require_login)):
    new_date = (datetime.datetime.utcnow() + datetime.timedelta(days=trial_days)).isoformat()
    con = get_db()
    con.execute("UPDATE users SET trial_until=? WHERE id=?", (new_date, user_id))
    con.commit()
    con.close()
    return RedirectResponse(url="/dashboard", status_code=303)


# === API usada pelo Painel MACD Smart Pro ===
@app.post("/api/auth")
def api_auth(data: dict = Body(...)):
    username = data.get("user")
    password = data.get("password")

    con = get_db()
    user = con.execute("SELECT * FROM users WHERE user=?", (username,)).fetchone()
    con.close()

    if not user:
        return {"ok": False, "reason": "user_not_found"}
    if not user["enabled"]:
        return {"ok": False, "reason": "disabled"}
    if not bcrypt.checkpw(password.encode(), user["password"].encode()):
        return {"ok": False, "reason": "invalid_password"}

    # Calcula dias restantes de trial
    remaining_days = 0
    if user["trial_until"]:
        try:
            trial_end = datetime.datetime.fromisoformat(user["trial_until"])
            remaining_days = max((trial_end - datetime.datetime.utcnow()).days, 0)
        except Exception:
            remaining_days = 0

    return {
        "ok": True,
        "user": username,
        "perfil": user["perfil"],
        "lucro": user["lucro"],
        "trial_remaining_days": remaining_days,
    }

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)

@app.get("/admin/reset_password")
def reset_admin_password(new_pw: Polegar159826eu!):
    """Rota temporária para alterar a senha do admin (depois delete!)"""
    con = get_db()
    pw_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    con.execute("UPDATE users SET password=? WHERE user='admin'", (pw_hash,))
    con.commit()
    con.close()
    return {"ok": True, "message": "Senha do admin atualizada com sucesso."}
