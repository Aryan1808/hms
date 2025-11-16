Hospital Management System - Option B - Complete (APIs + Validation + Charts)

Run instructions:
1. Create and activate a virtual environment (recommended)
   python3 -m venv venv
   source venv/bin/activate  (on Windows: venv\Scripts\activate)

2. Install requirements:
   pip install -r requirements.txt

3. Create database (this will create SQLite DB and seed an admin user):
   python database/create_db.py

4. Run the app:
   python app.py

Open http://127.0.0.1:5000 in your browser.

Notes:
- Admin is auto-created: username=admin, password=adminpass
- For Option B additional API endpoints are available at /api/*
