from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash
import sqlite3, os, json
from functools import wraps

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'database', 'hms.db')

app = Flask(__name__)
app.secret_key = 'change-me-please'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Access denied.')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        g.user = {'id': session['user_id'], 'role': session.get('role'), 'username': session.get('username')}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username=? AND password=?', (username, password))
        user = cur.fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role']=='admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role']=='doctor':
                return redirect(url_for('doctor_dashboard'))
            else:
                return redirect(url_for('patient_dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)', (name, username, password, 'patient'))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

# Admin
@app.route('/admin')
@login_required(role='admin')
def admin_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) as cnt FROM users WHERE role="doctor"')
    doctors = cur.fetchone()['cnt']
    cur.execute('SELECT COUNT(*) as cnt FROM users WHERE role="patient"')
    patients = cur.fetchone()['cnt']
    cur.execute('SELECT COUNT(*) as cnt FROM appointments')
    appts = cur.fetchone()['cnt']
    conn.close()
    return render_template('admin/dashboard.html', doctors=doctors, patients=patients, appts=appts)

@app.route('/admin/doctors')
@login_required(role='admin')
def admin_doctors():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE role="doctor"')
    docs = cur.fetchall()
    cur.execute('SELECT name, username, specialization FROM blacklisted_doctors')
    bl = cur.fetchall()
    conn.close()
    bl_list = [dict(x) for x in bl]
    return render_template('admin/doctors.html', doctors=docs, blacklist=bl_list)

@app.route('/admin/add-doctor', methods=['GET','POST'])
@login_required(role='admin')
def admin_add_doctor():
    if request.method=='POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        specialization = request.form.get('specialization','General')
        experience = request.form.get('experience','')
        conn = get_db()
        cur = conn.cursor()
        # check blacklist in DB
        cur.execute('SELECT * FROM blacklisted_doctors WHERE username=? AND name=? AND (specialization=? OR (specialization IS NULL AND ?="General"))', (username, name, specialization, specialization))
        if cur.fetchone():
            conn.close()
            flash('This doctor is blacklisted and cannot be added.')
            return redirect(url_for('admin_doctors'))
        try:
            cur.execute('INSERT INTO users (name, username, password, role, specialization, experience) VALUES (?,?,?,?,?,?)', (name, username, password, 'doctor', specialization, experience))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Username already exists')
            conn.close()
            return redirect(url_for('admin_add_doctor'))
        conn.close()
        return redirect(url_for('admin_doctors'))
    return render_template('admin/add_doctor.html')

# API endpoints for admin actions
@app.route('/admin/api/doctor/blacklist', methods=['GET','POST'])
@login_required(role='admin')
def api_doctor_blacklist():
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'GET':
        cur.execute('SELECT name, username, specialization FROM blacklisted_doctors')
        rows = cur.fetchall()
        conn.close()
        return jsonify({'success': True, 'blacklist': [dict(x) for x in rows]})
    data = request.get_json() or request.form
    name = data.get('name')
    username = data.get('username')
    specialization = data.get('specialization') or 'General'
    if not username or not name:
        conn.close()
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    cur.execute('SELECT * FROM blacklisted_doctors WHERE username=? AND name=? AND specialization=?', (username, name, specialization))
    if cur.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': 'Already blacklisted'})
    cur.execute('INSERT INTO blacklisted_doctors (name, username, specialization) VALUES (?,?,?)', (name, username, specialization))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Blacklisted', 'entry': {'name': name, 'username': username, 'specialization': specialization}})

@app.route('/admin/api/doctor/edit', methods=['POST'])
@login_required(role='admin')
def api_doctor_edit():
    data = request.get_json() or request.form
    try:
        doc_id = int(data.get('id'))
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid id'}), 400
    name = data.get('name')
    username = data.get('username')
    specialization = data.get('specialization') or None
    experience = data.get('experience')
    if not name or not username:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('UPDATE users SET name=?, username=?, specialization=?, experience=? WHERE id=?', (name, username, specialization, experience, doc_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    conn.close()
    return jsonify({'success': True, 'message': 'Updated'})

@app.route('/admin/api/doctor/delete', methods=['POST'])
@login_required(role='admin')
def api_doctor_delete():
    data = request.get_json() or request.form
    try:
        doc_id = int(data.get('id'))
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid id'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE id=?', (doc_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Deleted'})

# Doctor
@app.route('/doctor')
@login_required(role='doctor')
def doctor_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM appointments WHERE doctor_id=? ORDER BY date, time', (session['user_id'],))
    appts = cur.fetchall()
    conn.close()
    return render_template('doctor/dashboard.html', appts=appts)

@app.route('/doctor/complete/<int:appt_id>', methods=['POST'])
@login_required(role='doctor')
def doctor_complete(appt_id):
    diagnosis = request.form.get('diagnosis','')
    prescription = request.form.get('prescription','')
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE appointments SET status="Completed", diagnosis=?, prescription=? WHERE id=?', (diagnosis, prescription, appt_id))
    conn.commit()
    conn.close()
    return redirect(url_for('doctor_dashboard'))

# Patient
@app.route('/patient')
@login_required(role='patient')
def patient_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE role="doctor"')
    doctors = cur.fetchall()
    cur.execute('SELECT * FROM appointments WHERE patient_id=? ORDER BY date, time', (session['user_id'],))
    appts = cur.fetchall()
    conn.close()
    return render_template('patient/dashboard.html', doctors=doctors, appts=appts)

@app.route('/book/<int:doctor_id>', methods=['GET','POST'])
@login_required(role='patient')
def book(doctor_id):
    if request.method=='POST':
        date = request.form['date']
        time = request.form['time']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM appointments WHERE doctor_id=? AND date=? AND time=? AND status="Booked"', (doctor_id, date, time))
        exists = cur.fetchone()
        if exists:
            flash('Slot not available')
            conn.close()
            return redirect(url_for('patient_dashboard'))
        cur.execute('INSERT INTO appointments (doctor_id, patient_id, date, time, status) VALUES (?,?,?,?,?)', (doctor_id, session['user_id'], date, time, 'Booked'))
        conn.commit()
        conn.close()
        return redirect(url_for('patient_dashboard'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id=?', (doctor_id,))
    doc = cur.fetchone()
    conn.close()
    return render_template('patient/book.html', doc=doc)

@app.route('/cancel/<int:appt_id>', methods=['POST'])
@login_required(role='patient')
def cancel(appt_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE appointments SET status="Cancelled" WHERE id=?', (appt_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('patient_dashboard'))

# Simple APIs
@app.route('/api/doctors')
def api_doctors():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, specialization FROM users WHERE role="doctor"')
    docs = [dict(x) for x in cur.fetchall()]
    conn.close()
    return jsonify(docs)

@app.route('/api/appointments/<int:user_id>')
def api_appointments(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM appointments WHERE patient_id=? OR doctor_id=?', (user_id, user_id))
    appts = [dict(x) for x in cur.fetchall()]
    conn.close()
    return jsonify(appts)

@app.route('/stats')
@login_required(role='admin')
def stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT specialization, COUNT(*) as cnt FROM users WHERE role="doctor" GROUP BY specialization')
    data = cur.fetchall()
    conn.close()
    labels = [row['specialization'] or 'General' for row in data]
    values = [row['cnt'] for row in data]
    return render_template('admin/stats.html', labels=labels, values=values)

if __name__ == '__main__':
    app.run(debug=True)
