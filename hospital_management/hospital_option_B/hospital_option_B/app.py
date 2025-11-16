from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash
import sqlite3, os, json
from functools import wraps
from datetime import datetime, timedelta

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
        try:
            cur.execute('INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)', (name, username, password, 'patient'))
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

@app.route('/admin/stats')
@login_required(role='admin')
def stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT specialization, COUNT(*) as cnt FROM users WHERE role="doctor" GROUP BY specialization')
    spec_data = cur.fetchall()
    conn.close()
    
    labels = [row['specialization'] or 'General' for row in spec_data]
    values = [row['cnt'] for row in spec_data]
    
    return render_template('admin/stats.html', labels=labels, values=values)

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

@app.route('/admin/doctor/<int:doctor_id>/appointments')
@login_required(role='admin')
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
@login_required(role='admin')
def api_patient_history(patient_id):
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
@login_required(role='admin')
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
@login_required(role='admin')
def admin_patients():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE role="patient"')
    pats = cur.fetchall()
    conn.close()
    return render_template('admin/patients.html', patients=pats)

# Admin - patient history view
@app.route('/admin/patient-history')
@login_required(role='admin')
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
@login_required()
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
        if appt.get('status') != 'Completed':
            # parse appointment date/time — supports 'DD/MM/YYYY' or 'YYYY-MM-DD'
            appt_date = appt.get('date') or ''
            appt_time = appt.get('time') or '00:00'
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
@login_required(role='doctor')
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
        cur.execute('INSERT INTO users (name, username, password, role) VALUES (?,?,?,?)', (name, username, password, 'patient'))
        conn.commit()
        new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    # create doctor-patient relation
    add_doctor_patient_relation(conn, session['user_id'], new_id)
    conn.close()
    return jsonify({'success': True, 'id': new_id, 'message': 'Patient created'})

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
@login_required(role='doctor')
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
@login_required(role='doctor')
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

            # Get booked slots for this date with patient info
            cur.execute(
                'SELECT id, time, patient_id FROM appointments WHERE doctor_id=? AND date=? AND status="Booked"',
                (doctor_id, date_str)
            )
            booked_rows = cur.fetchall()
            # map time -> dict with appointment id and patient id
            booked = {row['time']: {'appt_id': row['id'], 'patient_id': row['patient_id']} for row in booked_rows}

            # Define two 5-hour slots
            slots = [
                ('08:00', '12:00'),
                ('04:00', '09:00')
            ]

            day_slots = []
            for start, end in slots:
                if start in booked:
                    appt_info = booked[start]
                    pid = appt_info.get('patient_id')
                    appt_id = appt_info.get('appt_id')
                    pname = None
                    if pid:
                        cur2 = conn.cursor()
                        cur2.execute('SELECT name FROM users WHERE id=?', (pid,))
                        pr = cur2.fetchone()
                        pname = pr['name'] if pr else None
                    day_slots.append({'time': start, 'end_time': end, 'available': False, 'patient_id': pid, 'patient_name': pname, 'appt_id': appt_id})
                else:
                    day_slots.append({'time': start, 'end_time': end, 'available': True})

            availability.append({'date': date_str, 'slots': day_slots})
            days_added += 1
        current_date += timedelta(days=1)

    conn.close()
    return render_template('doctor/schedule.html', availability=availability, appointments=appts)

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

@app.route('/cancel/<int:appt_id>', methods=['POST'])
@login_required(role='patient')
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
    
    # Generate 7 days of availability (excluding Sundays), starting from tomorrow
    today = datetime.now()
    availability = []
    current_date = today + timedelta(days=1)
    days_added = 0
    
    while days_added < 7:
        # Skip Sundays (weekday() returns 6 for Sunday)
        if current_date.weekday() != 6:
            date_str = current_date.strftime('%d/%m/%Y')
            
            # Get booked slots for this date
            cur.execute(
                'SELECT time FROM appointments WHERE doctor_id=? AND date=? AND status="Booked"',
                (doctor_id, date_str)
            )
            booked_slots = set(row[0] for row in cur.fetchall())
            
            # Create availability slots: 08:00-12:00 and 04:00-09:00 (5-hour slots)
            slots = [
                ('08:00', '12:00'),
                ('04:00', '09:00')
            ]
            
            day_availability = {
                'date': date_str,
                'date_obj': current_date,
                'slots': []
            }
            
            for start, end in slots:
                is_available = start not in booked_slots
                day_availability['slots'].append({
                    'time': start,
                    'end_time': end,
                    'available': is_available
                })
            
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
        