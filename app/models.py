from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func,Boolean 
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True)
    password = Column(String(255))
    role = Column(String(20))  # USER atau ADMIN

class Poli(Base):
    __tablename__ = "poli"
    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100))
    deskripsi = Column(String(255))
    dokter_aktif = Column(Boolean, default=True)  # status hasil akhir
    dokter_override = Column(Boolean, default=False)  # admin override ON/OFF
    dokter_aktif_manual = Column(Boolean, default=True)  # nilai manual admin

    
class JadwalDokter(Base):
    __tablename__ = "jadwal_dokter"
    id = Column(Integer, primary_key=True, index=True)
    poli_id = Column(Integer, ForeignKey("poli.id"))
    dokter = Column(String(100))
    hari = Column(String(20))
    jam_mulai = Column(String(10))
    jam_selesai = Column(String(10))

class Antrean(Base):
    __tablename__ = "antrean"
    id = Column(Integer, primary_key=True, index=True)
    poli_id = Column(Integer, ForeignKey("poli.id"))
    pasien_id = Column(Integer, ForeignKey("users.id"))
    waktu_daftar = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="menunggu")
    nomor_antrean = Column(Integer, default=1)
