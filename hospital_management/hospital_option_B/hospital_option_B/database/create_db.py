import sqlite3, os
BASE = os.path.dirname(__file__)
DB = os.path.join(BASE, 'hms.db')

def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        specialization TEXT
    )''')
    # ensure experience column exists
    try:
        cur.execute('ALTER TABLE users ADD COLUMN experience TEXT')
    except Exception:
        pass

    cur.execute('''CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER,
        patient_id INTEGER,
        date TEXT,
        time TEXT,
        status TEXT DEFAULT 'Booked',
        diagnosis TEXT,
        prescription TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER,
        date TEXT,
        time_slot TEXT
    )''')
    # blacklist table
    cur.execute('''CREATE TABLE IF NOT EXISTS blacklisted_doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        username TEXT,
        specialization TEXT
    )''')
    # patient history
    cur.execute('''CREATE TABLE IF NOT EXISTS patient_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER,
        patient_id INTEGER,
        doctor_id INTEGER,
        visit_info TEXT,
        prescription TEXT,
        date TEXT
    )''')
    # doctor-patient relationship (many-to-many)
    cur.execute('''CREATE TABLE IF NOT EXISTS doctor_patient (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER NOT NULL,
        patient_id INTEGER NOT NULL,
        UNIQUE(doctor_id, patient_id)
    )''')
    # create admin
    cur.execute("SELECT * FROM users WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)", ('Administrator','admin','adminpass','admin'))
    # sample doctor
    cur.execute("SELECT * FROM users WHERE username='dr1'")
    if not cur.fetchone():
        cur.execute("INSERT INTO users (name, username, password, role, specialization, experience) VALUES (?,?,?,?,?,?)", ('Dr. Alice','dr1','dr1pass','doctor','Cardiology','5'))
    conn.commit()
    conn.close()
    print('DB initialized at', DB)

if __name__=='__main__':
    init_db()
