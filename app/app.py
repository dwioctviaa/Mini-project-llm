# ===============================
# app.py - Final Version (Rapi & Aman)
# ===============================

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from pydantic import BaseModel

from dotenv import load_dotenv
import os
from openai import OpenAI

from app.models import User, Poli, JadwalDokter, Antrean
from app.database import SessionLocal

# ===============================
# ENV & OPENAI INIT
# ===============================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY belum diset di .env")

client = OpenAI(api_key=OPENAI_API_KEY)

# ===============================
# FASTAPI INIT
# ===============================
app = FastAPI(title="Sistem Puskesmas + LLM", version="1.0")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ===============================
# DATABASE DEPENDENCY
# ===============================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===============================
# SESSION (SIMPLE - DEMO)
# ===============================

sessions = {}  # {session_id: user_id}

def get_current_user(request: Request, db: Session):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in sessions:
        return db.query(User).filter(User.id == sessions[session_id]).first()
    return None

def require_admin(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(403, "Akses admin saja")
    return user


# ===============================
# OPENAI HELPER
# ===============================

def tanya_gpt(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Kamu adalah asisten Puskesmas yang ramah dan informatif."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
        max_tokens=300
    )
    return response.choices[0].message.content

def hitung_status_dokter(poli: Poli, jadwal: JadwalDokter | None):
    """
    Mengembalikan:
    - aktif (bool)
    - sumber_status (str): manual / jam operasional / tidak ada jadwal
    """

    now = datetime.now()
    today = date.today()

    # ===============================
    # 1️⃣ OVERRIDE MANUAL ADMIN
    # ===============================
    if getattr(poli, "dokter_override", False):
        return poli.dokter_aktif_manual, "manual (admin)"

    # ===============================
    # 2️⃣ TIDAK ADA JADWAL
    # ===============================
    if not jadwal:
        return False, "tidak ada jadwal"

    # ===============================
    # 3️⃣ HITUNG BERDASARKAN JAM
    # ===============================
    try:
        jam_mulai_time = datetime.strptime(jadwal.jam_mulai, "%H:%M").time()
        jam_selesai_time = datetime.strptime(jadwal.jam_selesai, "%H:%M").time()

        jam_mulai = datetime.combine(today, jam_mulai_time)
        jam_selesai = datetime.combine(today, jam_selesai_time)

        if jam_mulai <= now <= jam_selesai:
            return True, "jam operasional"
        else:
            return False, "di luar jam operasional"

    except Exception:
        return False, "format jam tidak valid"

# ===============================
# CHAT CONTEXT BUILDER
# ===============================

def build_chat_context(request: Request, db: Session) -> str:
    from datetime import datetime

    now = datetime.now()
    user = get_current_user(request, db)

    context = []

    # ===============================
    # WAKTU REAL-TIME
    # ===============================
    context.append(f"Waktu saat ini: {now.strftime('%H:%M')} WIB")

    # ===============================
    # STATUS PENANYA
    # ===============================
    if user:
        context.append(f"Status penanya: login sebagai {user.role}")
    else:
        context.append("Status penanya: guest (belum login)")

    # ===============================
    # DATA POLI
    # ===============================
    polis = db.query(Poli).all()

    for poli in polis:
        jadwal = db.query(JadwalDokter).filter(
            JadwalDokter.poli_id == poli.id
        ).first()

        # Nama dokter
        nama_dokter = jadwal.dokter if jadwal else "Tidak diketahui"

        # Status dokter (INTI LOGIKA)
        aktif, sumber_status = hitung_status_dokter(poli, jadwal)

        status_dokter = "aktif" if aktif else "tidak aktif"

        # Hitung antrean MENUNGGU saja
        antrean_menunggu = db.query(Antrean).filter(
            Antrean.poli_id == poli.id,
            Antrean.status == "menunggu"
        ).count()

        # Info jam (untuk konteks LLM)
        jam_info = "-"
        if jadwal:
            jam_info = f"{jadwal.jam_mulai} - {jadwal.jam_selesai}"

        context.append(
            f"Poli {poli.nama} | "
            f"Dokter: {nama_dokter} | "
            f"Jam: {jam_info} | "
            f"Status dokter: {status_dokter} | "
            f"Sumber status: {sumber_status} | "
            f"Antrean menunggu: {antrean_menunggu}"
        )

    return "\n".join(context)

# ===============================
# UI ROUTES
# ===============================

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")


@app.get("/ui", response_class=HTMLResponse)
def ui_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ---------- LOGIN ----------

@app.get("/ui/login", response_class=HTMLResponse)
def ui_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/ui/login")
def handle_login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or user.password != password:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Username atau password salah"})

    session_id = f"{user.id}-{datetime.utcnow().timestamp()}"
    sessions[session_id] = user.id

    response = RedirectResponse("/ui/poli", status_code=302)
    response.set_cookie("session_id", session_id, httponly=True)
    return response

# ---------- LOGOUT ----------

@app.get("/ui/logout")
def logout(request: Request):
    session_id = request.cookies.get("session_id")
    sessions.pop(session_id, None)
    response = RedirectResponse("/ui/login", status_code=302)
    response.delete_cookie("session_id")
    return response

# ---------- REGISTER ----------

@app.get("/ui/register", response_class=HTMLResponse)
def ui_register(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request
    })

@app.post("/ui/register")
def ui_register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username sudah digunakan"}
        )

    user = User(username=username, password=password, role="user")
    db.add(user)
    db.commit()

    session_id = f"{user.id}-{datetime.utcnow().timestamp()}"
    sessions[session_id] = user.id

    response = RedirectResponse("/ui/poli", status_code=302)
    response.set_cookie("session_id", session_id, httponly=True)
    return response


# ---------- POLI ----------

@app.get("/ui/poli", response_class=HTMLResponse)
def ui_poli(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    poli = db.query(Poli).all()
    return templates.TemplateResponse("poli.html", {"request": request, "poli": poli, "user": user})

@app.get("/ui/poli/{poli_id}", response_class=HTMLResponse)
def ui_poli_detail(
    request: Request,
    poli_id: int,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)

    poli = db.query(Poli).filter(Poli.id == poli_id).first()
    if not poli:
        raise HTTPException(404, "Poli tidak ditemukan")

    # 🔹 AMBIL SEMUA JADWAL (JANGAN DIUBAH)
    jadwal = db.query(JadwalDokter).filter(
        JadwalDokter.poli_id == poli_id
    ).all()

    # 🔹 PILIH JADWAL HARI INI UNTUK STATUS
    from datetime import datetime
    today = datetime.now().strftime("%A").lower()
    jadwal_hari_ini = None
    for j in jadwal:
        if j.hari.lower() == today:
            jadwal_hari_ini = j
            break

    dokter_aktif, sumber_status = hitung_status_dokter(
        poli,
        jadwal_hari_ini
    )

    antrean_user = None
    if user and user.role.lower() == "user":
        antrean_user = db.query(Antrean).filter(
            Antrean.poli_id == poli_id,
            Antrean.pasien_id == user.id,
            Antrean.status == "menunggu"
        ).first()

    antrean_list = None
    if user and user.role.lower() == "admin":
        antrean_list = (
            db.query(Antrean, User.username)
            .join(User, User.id == Antrean.pasien_id)
            .filter(Antrean.poli_id == poli_id)
            .order_by(Antrean.nomor_antrean)
            .all()
        )

    return templates.TemplateResponse(
        "poli_detail.html",
        {
            "request": request,
            "poli": poli,
            "jadwal": jadwal,  
            "user": user,
            "dokter_aktif": dokter_aktif,
            "sumber_status": sumber_status,
            "antrean_user": antrean_user,
            "antrean_list": antrean_list
        }
    )

@app.get("/admin/poli/{poli_id}", response_class=HTMLResponse)
def admin_poli_detail(
    request: Request,
    poli_id: int,
    db: Session = Depends(get_db)
):
    admin = require_admin(request, db)

    poli = db.query(Poli).filter(Poli.id == poli_id).first()
    if not poli:
        raise HTTPException(404, "Poli tidak ditemukan")

    antrean = (
        db.query(Antrean, User)
        .join(User, User.id == Antrean.pasien_id)
        .filter(Antrean.poli_id == poli_id)
        .order_by(Antrean.nomor_antrean)
        .all()
    )

    return templates.TemplateResponse(
        "poli_detail.html",
        {
            "request": request,
            "poli": poli,
            "antrean": antrean,
            "admin": admin
        }
    )

@app.post("/admin/antrean/{antrean_id}/selesai")
def selesai_antrean(antrean_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)

    antrean = db.query(Antrean).filter(Antrean.id == antrean_id).first()
    if not antrean:
        raise HTTPException(404, "Antrean tidak ditemukan")

    antrean.status = "selesai"
    db.commit()

    return {"message": "Antrean diselesaikan"}

from fastapi import Query

@app.post("/admin/poli/{poli_id}/override-dokter")
def override_dokter(
    poli_id: int,
    aktif: bool = Query(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    require_admin(request, db)

    poli = db.query(Poli).filter(Poli.id == poli_id).first()
    if not poli:
        raise HTTPException(404, "Poli tidak ditemukan")

    poli.dokter_override = True
    poli.dokter_aktif_manual = aktif
    db.commit()
    db.refresh(poli)

    return {
        "message": f"Status dokter dipaksa {'aktif' if aktif else 'tidak aktif'}"
    }

@app.post("/admin/poli/{poli_id}/auto-dokter")
def auto_dokter(
    poli_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    require_admin(request, db)

    poli = db.query(Poli).filter(Poli.id == poli_id).first()
    if not poli:
        raise HTTPException(404, "Poli tidak ditemukan")

    poli.dokter_override = False
    db.commit()
    db.refresh(poli)

    return {"message": "Status dokter kembali mengikuti jam operasional"}


# ===============================
# ANTREAN API
# ===============================

class AntreanRequest(BaseModel):
    poli_id: int
    user_id: int

@app.post("/user/antrean")
def daftar_antrean(request: Request, req: AntreanRequest, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "Silakan login")

    existing = db.query(Antrean).filter(
        Antrean.poli_id == req.poli_id,
        Antrean.pasien_id == user.id,
        Antrean.status == "menunggu"
    ).first()

    if existing:
        return {"message": "Anda sudah terdaftar", "nomor_antrean": existing.nomor_antrean}

    last = db.query(Antrean).filter(
        Antrean.poli_id == req.poli_id
    ).order_by(Antrean.nomor_antrean.desc()).first()

    nomor = 1 if not last else last.nomor_antrean + 1

    antrean = Antrean(
        poli_id=req.poli_id,
        pasien_id=user.id,
        nomor_antrean=nomor
    )
    db.add(antrean)
    db.commit()

    return {"message": "Berhasil daftar antrean", "nomor_antrean": existing.nomor_antrean}


@app.post("/ui/antrean/daftar")
def daftar_antrean_form(
    poli_id: int = Form(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/ui/login", status_code=302)

    existing = db.query(Antrean).filter(
        Antrean.poli_id == poli_id,
        Antrean.pasien_id == user.id,
        Antrean.status == "menunggu"
    ).first()

    if not existing:
        last = db.query(Antrean).filter(
            Antrean.poli_id == poli_id
        ).order_by(Antrean.nomor_antrean.desc()).first()

        nomor = 1 if not last else last.nomor_antrean + 1

        antrean = Antrean(
            poli_id=poli_id,
            pasien_id=user.id,
            nomor_antrean=nomor
        )
        db.add(antrean)
        db.commit()

    return RedirectResponse(f"/ui/poli/{poli_id}", status_code=302)

# ===============================
# CHAT ASISTEN (RAG)
# ===============================

@app.get("/ui/chat", response_class=HTMLResponse)
def ui_chat(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse("chat.html", {"request": request, "user": user})

@app.post("/chat")
async def chat(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    pertanyaan = data.get("pertanyaan", "").strip()

    if not pertanyaan:
        return JSONResponse({"jawaban": "Pertanyaan tidak boleh kosong."})

    # ===============================
    # BUILD CONTEXT DARI DATABASE
    # ===============================
    context = build_chat_context(request, db)

    # ===============================
    # PROMPT KE LLM
    # ===============================
    prompt = f"""
Kamu adalah asisten AI resmi Puskesmas.

ATURAN PENTING:
- Gunakan HANYA data yang ada di bawah ini
- Jangan mengarang jam, status, atau antrean
- Jika data tidak tersedia, katakan dengan jujur
- Boleh memberi saran dan keputusan berbasis kondisi

DATA RESMI:
{context}

PERTANYAAN:
{pertanyaan}

Jawablah secara jelas, sopan, dan membantu.
"""

    jawaban = tanya_gpt(prompt)

    return JSONResponse({"jawaban": jawaban})

