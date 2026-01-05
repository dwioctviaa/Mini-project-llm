from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base

# GANTI INI (sesuai Laragon default)
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/puskesmas_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# BUAT TABLE OTOMATIS
Base.metadata.create_all(bind=engine)
