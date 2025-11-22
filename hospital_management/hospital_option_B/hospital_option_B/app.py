from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash
import sqlite3, os, json, re
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required as flask_login_required

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'database', 'hms.db')

app = Flask(__name__)
app.secret_key = 'change-me-please'

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class DBUser(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.username = row['username'] if 'username' in row.keys() else None
        self.role = row['role'] if 'role' in row.keys() else None
        self._row = row

    def get_role(self):
        return getattr(self, 'role', None)


@login_manager.user_loader
def load_user_from_id(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE id=?', (int(user_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return DBUser(row)
    except Exception:
        return None

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def role_required(role):
    def decorator(f):
        @wraps(f)
        @flask_login_required
        def wrapped(*args, **kwargs):
            if getattr(current_user, 'role', None) != role:
                flash('Access denied.')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.before_request
def load_user():
    # expose a simple g.user for templates (keeps existing code compatible)
    if current_user and getattr(current_user, 'is_authenticated', False):
        g.user = {'id': int(current_user.get_id()), 'role': getattr(current_user, 'role', None), 'username': getattr(current_user, 'username', None)}
        # keep session values for backward compatibility
        session['user_id'] = int(current_user.get_id())
        session['username'] = getattr(current_user, 'username', None)
        session['role'] = getattr(current_user, 'role', None)
    else:
        g.user = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # basic server-side validation
        username = username.strip()
        if not username or not password:
            flash('Username and password required')
            return render_template('login.html')

        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username=?', (username,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            user_obj = DBUser(user)
            login_user(user_obj)
            # maintain session compatibility
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
    try:
        logout_user()
    except Exception:
        pass
    session.clear()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        # server-side validation
        name = (name or '').strip()
        username = (username or '').strip()
        if not name or not username or not password:
            flash('All fields required')
            return redirect(url_for('register'))
        if len(username) < 3 or len(password) < 4:
            flash('Username must be >=3 chars and password >=4 chars')
            return redirect(url_for('register'))
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)', (name, username, generate_password_hash(password), 'patient'))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Username already exists')
            conn.close()
            return redirect(url_for('register'))
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

# Admin
@app.route('/admin')
@role_required('admin')
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
@role_required('admin')
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

@app.route('/admin/stats')
@role_required('admin')
def stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT specialization, COUNT(*) as cnt FROM users WHERE role="doctor" GROUP BY specialization')
    spec_data = cur.fetchall()
    conn.close()
    
    labels = [row['specialization'] or 'General' for row in spec_data]
    values = [row['cnt'] for row in spec_data]
    
    return render_template('admin/stats.html', labels=labels, values=values)


@app.route('/admin/appointments')
@role_required('admin')
def admin_appointments():
    conn = get_db()
    cur = conn.cursor()
    # Fetch appointments with doctor and patient names, ordered by date desc
    cur.execute('''SELECT a.id, a.date, a.time, a.status, a.diagnosis, a.prescription,
                   d.id as doctor_id, d.name as doctor_name,
                   p.id as patient_id, p.name as patient_name
                   FROM appointments a
                   LEFT JOIN users d ON a.doctor_id = d.id
                   LEFT JOIN users p ON a.patient_id = p.id
                   ORDER BY a.date DESC, a.time DESC''')
    rows = cur.fetchall()
    conn.close()
    return render_template('admin/appointments.html', appointments=rows)

@app.route('/admin/add-doctor', methods=['GET','POST'])
@role_required('admin')
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
            # basic validation
            if not name or not username or not password:
                flash('Name, username and password required')
                conn.close()
                return redirect(url_for('admin_add_doctor'))
            cur.execute('INSERT INTO users (name, username, password, role, specialization, experience) VALUES (?,?,?,?,?,?)', (name, username, generate_password_hash(password), 'doctor', specialization, experience))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Username already exists')
            conn.close()
            return redirect(url_for('admin_add_doctor'))
        conn.close()
        return redirect(url_for('admin_doctors'))
    return render_template('admin/add_doctor.html')

@app.route('/admin/doctor/<int:doctor_id>/appointments')
@role_required('admin')
def admin_doctor_appointments(doctor_id):
    conn = get_db()
    cur = conn.cursor()
    # Get doctor info
    cur.execute('SELECT * FROM users WHERE id=? AND role="doctor"', (doctor_id,))
    doctor = cur.fetchone()
    if not doctor:
        flash('Doctor not found')
        return redirect(url_for('admin_doctors'))
    
    # Get all appointments for this doctor
    cur.execute('''SELECT a.id, a.date, a.time, a.status, 
                   p.id as patient_id, p.name as patient_name
                   FROM appointments a
                   LEFT JOIN users p ON a.patient_id = p.id
                   WHERE a.doctor_id=?
                   ORDER BY a.date DESC, a.time DESC''', (doctor_id,))
    appointments = cur.fetchall()
    conn.close()
    return render_template('admin/doctor_appointments.html', doctor=doctor, appointments=appointments)

@app.route('/api/patient-history/<int:patient_id>')
@flask_login_required
def api_patient_history(patient_id):
    # Allow admins to view any patient's history.
    # Allow doctors to view history only for patients they are related to (have appointments with).
    # Allow patients to view their own history.
    role = getattr(current_user, 'role', None)
    uid = int(current_user.get_id()) if current_user and getattr(current_user, 'is_authenticated', False) else None
    if role == 'admin':
        allowed = True
    elif role == 'doctor':
        # check doctor-patient relation or past appointments
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) as cnt FROM doctor_patient WHERE doctor_id=? AND patient_id=?', (uid, patient_id))
        r = cur.fetchone()
        has_rel = (r['cnt'] if r and 'cnt' in r.keys() else 0) > 0
        if not has_rel:
            cur.execute('SELECT COUNT(*) as cnt FROM appointments WHERE doctor_id=? AND patient_id=?', (uid, patient_id))
            r2 = cur.fetchone()
            has_rel = (r2['cnt'] if r2 and 'cnt' in r2.keys() else 0) > 0
        conn.close()
        allowed = bool(has_rel)
    elif role == 'patient':
        allowed = (uid == patient_id)
    else:
        allowed = False

    if not allowed:
        return jsonify({'success': False, 'message': 'Forbidden'}), 403

    conn = get_db()
    cur = conn.cursor()
    # Get patient history records
    cur.execute('''SELECT ph.id, ph.appointment_id, ph.visit_info, ph.prescription, ph.date,
                   d.name as doctor_name
                   FROM patient_history ph
                   LEFT JOIN users d ON ph.doctor_id = d.id
                   WHERE ph.patient_id=?
                   ORDER BY ph.date DESC''', (patient_id,))
    history = cur.fetchall()
    conn.close()
    return jsonify([dict(row) for row in history])

@app.route('/api/patient-appointments/<int:patient_id>')
@role_required('admin')
def api_patient_appointments(patient_id):
    conn = get_db()
    cur = conn.cursor()
    
    # Get patient appointments
    cur.execute('''SELECT a.id, a.date, a.time, a.status,
                   d.name as doctor_name
                   FROM appointments a
                   LEFT JOIN users d ON a.doctor_id = d.id
                   WHERE a.patient_id=?
                   ORDER BY a.date DESC, a.time DESC''', (patient_id,))
    appointments = cur.fetchall()
    
    conn.close()
    return jsonify([dict(row) for row in appointments])

@app.route('/admin/patients')
@role_required('admin')
def admin_patients():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE role="patient"')
    pats = cur.fetchall()
    conn.close()
    return render_template('admin/patients.html', patients=pats)

# Admin - patient history view
@app.route('/admin/patient-history')
@role_required('admin')
def admin_patient_history():
    patient_id = request.args.get('patient_id')
    conn = get_db()
    cur = conn.cursor()
    if patient_id:
        cur.execute('''SELECT ph.id, ph.appointment_id, ph.visit_info, ph.prescription, ph.date,
                       p.id as patient_id, p.name as patient_name,
                       d.id as doctor_id, d.name as doctor_name, d.specialization as doctor_dept
                       FROM patient_history ph
                       LEFT JOIN users p ON ph.patient_id = p.id
                       LEFT JOIN users d ON ph.doctor_id = d.id
                       WHERE ph.patient_id=?
                       ORDER BY ph.date DESC''', (patient_id,))
    else:
        cur.execute('''SELECT ph.id, ph.appointment_id, ph.visit_info, ph.prescription, ph.date,
                       p.id as patient_id, p.name as patient_name,
                       d.id as doctor_id, d.name as doctor_name, d.specialization as doctor_dept
                       FROM patient_history ph
                       LEFT JOIN users p ON ph.patient_id = p.id
                       LEFT JOIN users d ON ph.doctor_id = d.id
                       ORDER BY ph.date DESC''')
    rows = cur.fetchall()
    conn.close()
    return render_template('admin/patient_history.html', records=rows)

# API: add or edit history (doctors + admin)
@app.route('/api/patient-history', methods=['POST'])
@flask_login_required
def api_patient_history_add_edit():
    # Only doctors and admins may create or edit history records
    role = session.get('role')
    if role not in ('doctor', 'admin'):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403
    data = request.get_json() or request.form
    rec_id = data.get('id')
    appointment_id = data.get('appointment_id')
    patient_id = data.get('patient_id')
    doctor_id = data.get('doctor_id')
    visit_info = data.get('visit_info')
    prescription = data.get('prescription')
    date = data.get('date')
    conn = get_db()
    cur = conn.cursor()
    # If creating a new history entry, ensure appointment exists and its time has passed (unless already marked Completed)
    if not rec_id and appointment_id:
        cur.execute('SELECT * FROM appointments WHERE id=?', (appointment_id,))
        appt = cur.fetchone()
        if not appt:
            conn.close()
            return jsonify({'success': False, 'message': 'Appointment not found'}), 400
        # if doctor role, ensure appointment belongs to this doctor
        if role == 'doctor' and appt['doctor_id'] != session.get('user_id'):
            conn.close()
            return jsonify({'success': False, 'message': 'Forbidden'}), 403
        # allow if appointment already Completed
        status = appt['status'] if 'status' in appt.keys() else None
        if status != 'Completed':
            # parse appointment date/time — supports 'DD/MM/YYYY' or 'YYYY-MM-DD'
            appt_date = appt['date'] if 'date' in appt.keys() else ''
            appt_time = appt['time'] if 'time' in appt.keys() else '00:00'
            try:
                if '/' in appt_date:
                    dparts = appt_date.split('/')
                    appt_dt = datetime(int(dparts[2]), int(dparts[1]), int(dparts[0]), int(appt_time.split(':')[0]), int(appt_time.split(':')[1]))
                else:
                    # assume ISO format
                    dtstr = appt_date
                    if 'T' in dtstr:
                        appt_dt = datetime.fromisoformat(dtstr)
                    else:
                        # combine date and time
                        appt_dt = datetime.strptime(dtstr + ' ' + appt_time, '%Y-%m-%d %H:%M')
            except Exception:
                # if parsing fails, deny to be safe
                conn.close()
                return jsonify({'success': False, 'message': 'Invalid appointment datetime'}), 400
            if datetime.now() < appt_dt:
                conn.close()
                return jsonify({'success': False, 'message': 'Cannot add history before appointment time'}), 400

    if rec_id:
        # update
        cur.execute('UPDATE patient_history SET visit_info=?, prescription=?, date=? WHERE id=?', (visit_info, prescription, date, rec_id))
        res_id = rec_id
    else:
        cur.execute('INSERT INTO patient_history (appointment_id, patient_id, doctor_id, visit_info, prescription, date) VALUES (?,?,?,?,?,?)', (appointment_id, patient_id, doctor_id, visit_info, prescription, date))
        res_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': res_id})

def add_doctor_patient_relation(conn, doctor_id, patient_id):
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO doctor_patient (doctor_id, patient_id) VALUES (?,?)', (doctor_id, patient_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass

# Allow doctors to create new patients (AJAX)
@app.route('/doctor/add-patient', methods=['POST'])
@role_required('doctor')
def doctor_add_patient():
    data = request.get_json() or request.form
    name = data.get('name')
    username = data.get('username')
    password = data.get('password')
    if not name or not username or not password:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)', (name, username, generate_password_hash(password), 'patient'))
        conn.commit()
        new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    # create doctor-patient relation
    add_doctor_patient_relation(conn, session['user_id'], new_id)
    conn.close()
    return jsonify({'success': True, 'id': new_id, 'message': 'Patient created'})


# Doctor availability management removed — availability derived from booking status
@app.route('/doctor/availability', methods=['GET','POST','DELETE'])
@role_required('doctor')
def doctor_availability():
    # This endpoint is intentionally disabled. Availability is no longer managed by doctors.
    return jsonify({'success': False, 'message': 'Doctor-managed availability removed. System derives availability from booked slots.'}), 410

@app.route('/admin/api/doctor/blacklist', methods=['GET','POST'])
@role_required('admin')
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
@role_required('admin')
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
@role_required('admin')
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
@role_required('doctor')
def doctor_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT a.id, a.date, a.time, a.status, p.id as patient_id, p.name as patient_name,
                   ph.id as history_id
                   FROM appointments a
                   LEFT JOIN users p ON a.patient_id = p.id
                   LEFT JOIN patient_history ph ON ph.appointment_id = a.id
                   WHERE a.doctor_id=?
                   ORDER BY a.date, a.time''', (session['user_id'],))
    appts = cur.fetchall()
    # fetch recent patients for sidebar (most recent 20)
    cur.execute('SELECT id, name, username FROM users WHERE role="patient" ORDER BY id DESC LIMIT 20')
    pats = cur.fetchall()
    conn.close()
    return render_template('doctor/dashboard.html', appts=appts, patients=pats)


@app.route('/api/history/<int:appointment_id>')
@role_required('doctor')
def api_history_by_appointment(appointment_id):
    # Ensure appointment belongs to logged-in doctor
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT doctor_id FROM appointments WHERE id=?', (appointment_id,))
    ap = cur.fetchone()
    if not ap or ap['doctor_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    cur.execute('SELECT * FROM patient_history WHERE appointment_id=?', (appointment_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({}), 404
    return jsonify(dict(row))


@app.route('/doctor/schedule')
@role_required('doctor')
def doctor_schedule():
    doctor_id = session['user_id']
    conn = get_db()
    cur = conn.cursor()

    # fetch all appointments for this doctor (to show upcoming/past)
    cur.execute('''SELECT a.id, a.date, a.time, a.status, p.id as patient_id, p.name as patient_name
                   FROM appointments a
                   LEFT JOIN users p ON a.patient_id = p.id
                   WHERE a.doctor_id=?
                   ORDER BY a.date DESC, a.time DESC''', (doctor_id,))
    appts = cur.fetchall()

    # Generate 7 days of availability (excluding Sundays), starting from today
    today = datetime.now()
    availability = []
    current_date = today
    days_added = 0
    while days_added < 7:
        # Skip Sundays (weekday() returns 6 for Sunday)
        if current_date.weekday() != 6:
            date_str = current_date.strftime('%d/%m/%Y')

            # Use fixed default slots; availability is simply whether a slot is already booked or not
            default_slots = [('08:00','12:00'), ('04:00','09:00')]
            avail_times = [s[0] for s in default_slots]

            # Get booked slots for this date with patient info
            cur.execute('SELECT id, time, patient_id FROM appointments WHERE doctor_id=? AND date=? AND status="Booked"', (doctor_id, date_str))
            booked_rows = cur.fetchall()
            booked = {row['time']: {'appt_id': row['id'], 'patient_id': row['patient_id']} for row in booked_rows}

            day_slots = []
            for t in avail_times:
                if t in booked:
                    appt_info = booked[t]
                    pid = appt_info.get('patient_id')
                    appt_id = appt_info.get('appt_id')
                    pname = None
                    if pid:
                        cur2 = conn.cursor()
                        cur2.execute('SELECT name FROM users WHERE id=?', (pid,))
                        pr = cur2.fetchone()
                        pname = pr['name'] if pr else None
                    # determine end_time from defaults
                    end_time = next((de for ds, de in default_slots if ds == t), '')
                    day_slots.append({'time': t, 'end_time': end_time, 'available': False, 'patient_id': pid, 'patient_name': pname, 'appt_id': appt_id})
                else:
                    end_time = next((de for ds, de in default_slots if ds == t), '')
                    day_slots.append({'time': t, 'end_time': end_time, 'available': True})

            if day_slots:
                availability.append({'date': date_str, 'slots': day_slots})
            days_added += 1
        current_date += timedelta(days=1)

    conn.close()
    return render_template('doctor/schedule.html', availability=availability, appointments=appts)

@app.route('/doctor/complete/<int:appt_id>', methods=['POST'])
@role_required('doctor')
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
@role_required('patient')
def patient_dashboard():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE role="doctor"')
    doctors = cur.fetchall()
    cur.execute('SELECT a.*, d.name as doctor_name FROM appointments a LEFT JOIN users d ON a.doctor_id=d.id WHERE a.patient_id=? ORDER BY a.date, a.time', (session['user_id'],))
    appts = cur.fetchall()
    conn.close()
    return render_template('patient/dashboard.html', doctors=doctors, appts=appts)


@app.route('/patient/profile', methods=['GET','POST'])
@role_required('patient')
def patient_profile():
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or None
        if not name or not username:
            flash('Name and username required')
            return redirect(url_for('patient_profile'))
        # ensure username uniqueness
        cur.execute('SELECT id FROM users WHERE username=? AND id<>?', (username, session['user_id']))
        if cur.fetchone():
            flash('Username already taken')
            return redirect(url_for('patient_profile'))
        if password:
            cur.execute('UPDATE users SET name=?, username=?, password=? WHERE id=?', (name, username, generate_password_hash(password), session['user_id']))
        else:
            cur.execute('UPDATE users SET name=?, username=? WHERE id=?', (name, username, session['user_id']))
        conn.commit()
        # update session username
        session['username'] = username
        flash('Profile updated')
        conn.close()
        return redirect(url_for('patient_dashboard'))

    cur.execute('SELECT * FROM users WHERE id=?', (session['user_id'],))
    user = cur.fetchone()
    conn.close()
    return render_template('patient/profile.html', user=user)


@app.route('/reschedule/<int:appt_id>', methods=['GET','POST'])
@role_required('patient')
def reschedule(appt_id):
    conn = get_db()
    cur = conn.cursor()
    # ensure appointment belongs to patient
    cur.execute('SELECT * FROM appointments WHERE id=? AND patient_id=?', (appt_id, session['user_id']))
    appt = cur.fetchone()
    if not appt:
        flash('Appointment not found')
        conn.close()
        return redirect(url_for('patient_dashboard'))
    doctor_id = appt['doctor_id']
    if request.method == 'POST':
        new_date = request.form.get('date')
        new_time = request.form.get('time')
        if not new_date or not new_time:
            flash('Date and time required')
            return redirect(url_for('reschedule', appt_id=appt_id))
        # No availability table check: a slot is available if it's not already booked
        # check conflict (already booked by other appointment)
        cur.execute('SELECT * FROM appointments WHERE doctor_id=? AND date=? AND time=? AND status="Booked" AND id<>?', (doctor_id, new_date, new_time, appt_id))
        if cur.fetchone():
            flash('Selected slot is not available')
            conn.close()
            return redirect(url_for('reschedule', appt_id=appt_id))
        cur.execute('UPDATE appointments SET date=?, time=? WHERE id=?', (new_date, new_time, appt_id))
        conn.commit()
        conn.close()
        flash('Appointment rescheduled')
        return redirect(url_for('patient_dashboard'))

    # prepare availability similar to booking page
    cur.execute('SELECT * FROM users WHERE id=?', (doctor_id,))
    doctor = cur.fetchone()
    # Build availability from availability table for next 7 days
    today = datetime.now()
    availability = []
    current_date = today + timedelta(days=1)
    days_added = 0
    while days_added < 7:
        if current_date.weekday() != 6:
            date_str = current_date.strftime('%d/%m/%Y')
            # get availability entries for this doctor/date
            cur.execute('SELECT time_slot FROM availability WHERE doctor_id=? AND date=?', (doctor_id, date_str))
            avail_times = [row[0] for row in cur.fetchall()]
            default_slots = [('08:00','12:00'),('04:00','09:00')]
            if not avail_times:
                avail_times = [s[0] for s in default_slots]
            # get booked slots
            cur.execute('SELECT time FROM appointments WHERE doctor_id=? AND date=? AND status="Booked"', (doctor_id, date_str))
            booked_slots = set(row[0] for row in cur.fetchall())
            day_slots = []
            for t in avail_times:
                is_available = t not in booked_slots
                # match end_time from default slots
                end_time = ''
                for ds, de in default_slots:
                    if ds == t:
                        end_time = de
                        break
                day_slots.append({'time': t, 'end_time': end_time, 'available': is_available})
            if day_slots:
                availability.append({'date': date_str, 'date_obj': current_date, 'slots': day_slots})
            days_added += 1
        current_date += timedelta(days=1)
    conn.close()
    return render_template('patient/reschedule.html', doc=doctor, availability=availability, appt=appt)

@app.route('/cancel/<int:appt_id>', methods=['POST'])
@role_required('patient')
def cancel(appt_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM appointments WHERE id=? AND patient_id=?', (appt_id, session['user_id']))
    appt = cur.fetchone()
    if not appt:
        flash('Appointment not found')
        conn.close()
        return redirect(url_for('patient_dashboard'))
    cur.execute('UPDATE appointments SET status="Cancelled" WHERE id=?', (appt_id,))
    conn.commit()
    conn.close()
    flash('Appointment cancelled successfully')
    return redirect(url_for('patient_dashboard'))

@app.route('/book/<int:doctor_id>', methods=['GET','POST'])
@role_required('patient')
def book(doctor_id):
    if request.method=='POST':
        date = request.form['date']
        time = request.form['time']
        conn = get_db()
        cur = conn.cursor()
        # No availability table check: a slot is available if it's not already booked
        cur.execute('SELECT * FROM appointments WHERE doctor_id=? AND date=? AND time=? AND status="Booked"', (doctor_id, date, time))
        exists = cur.fetchone()
        if exists:
            flash('Slot not available')
            conn.close()
            return redirect(url_for('book', doctor_id=doctor_id))
        cur.execute('INSERT INTO appointments (doctor_id, patient_id, date, time, status) VALUES (?,?,?,?,?)', (doctor_id, session['user_id'], date, time, 'Booked'))
        conn.commit()
        # create doctor-patient relation from booking if not exists
        add_doctor_patient_relation(conn, doctor_id, session['user_id'])
        flash('Appointment booked successfully!')
        conn.close()
        return redirect(url_for('patient_dashboard'))
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE id=?', (doctor_id,))
    doctor = cur.fetchone()
    
    # Build availability for next 7 days from availability table
    today = datetime.now()
    availability = []
    current_date = today + timedelta(days=1)
    days_added = 0

    while days_added < 7:
        # Skip Sundays (weekday() returns 6 for Sunday)
        if current_date.weekday() != 6:
            date_str = current_date.strftime('%d/%m/%Y')

            # Use default slots for every date; availability is whether the slot is already booked
            default_slots = [('08:00','12:00'), ('04:00','09:00')]
            avail_times = [s[0] for s in default_slots]

            # Get booked slots for this date
            cur.execute('SELECT time FROM appointments WHERE doctor_id=? AND date=? AND status="Booked"', (doctor_id, date_str))
            booked_slots = set(row[0] for row in cur.fetchall())

            day_availability = {
                'date': date_str,
                'date_obj': current_date,
                'slots': []
            }

            for t in avail_times:
                is_available = t not in booked_slots
                # find matching default end_time if available
                end_time = ''
                for ds, de in default_slots:
                    if ds == t:
                        end_time = de
                        break
                day_availability['slots'].append({ 'time': t, 'end_time': end_time, 'available': is_available })

            availability.append(day_availability)
            days_added += 1
        current_date += timedelta(days=1)
    
    conn.close()
    return render_template('patient/book.html', doc=doctor, availability=availability, doctor_id=doctor_id)

def add_doctor_patient_relation(conn, doctor_id, patient_id):
    cur = conn.cursor()
    cur.execute('SELECT * FROM doctor_patient WHERE doctor_id=? AND patient_id=?', (doctor_id, patient_id))
    if not cur.fetchone():
        cur.execute('INSERT INTO doctor_patient (doctor_id, patient_id) VALUES (?,?)', (doctor_id, patient_id))
        conn.commit()

if __name__ == '__main__':
    app.run(debug=True)
        