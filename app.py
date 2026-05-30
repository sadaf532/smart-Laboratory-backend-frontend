"""
Smart Laboratory Equipment Queue Monitoring System
Backend: Flask + MySQL
"""

from flask import Flask, request, jsonify, session, render_template, redirect, url_for
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import mysql.connector
from mysql.connector import pooling
import math
import time
import datetime
import json
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app, supports_credentials=True)


DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',          
    'database': 'smart_lab',
    'pool_name': 'mypool',
    'pool_size': 5
}

pool = None

def get_db():
    """Connection pool থেকে connection নাও"""
    global pool
    if pool is None:
        pool = mysql.connector.pooling.MySQLConnectionPool(**DB_CONFIG)
    return pool.get_connection()


# ─────────────────────────────────────────────
# DATABASE INITIALIZATION
# ─────────────────────────────────────────────
def init_db():
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('admin', 'student', 'faculty') DEFAULT 'student',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50),
            state ENUM('idle', 'busy', 'unavailable') DEFAULT 'idle',
            service_rate FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queue_entries (
            id INT AUTO_INCREMENT PRIMARY KEY,
            equipment_id INT NOT NULL,
            user_id INT NOT NULL,
            status ENUM('waiting', 'in_service', 'completed', 'cancelled') DEFAULT 'waiting',
            position_in_queue INT DEFAULT 0,
            estimated_wait FLOAT DEFAULT 0.0,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            equipment_id INT NOT NULL,
            user_id INT NOT NULL,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP NULL,
            duration_minutes FLOAT DEFAULT 0.0,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS state_transitions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            equipment_id INT NOT NULL,
            from_state ENUM('idle', 'busy', 'unavailable'),
            to_state ENUM('idle', 'busy', 'unavailable'),
            transitioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            triggered_by VARCHAR(50),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()




VALID_TRANSITIONS = {
    'idle':        ['busy', 'unavailable'],
    'busy':        ['idle', 'unavailable'],
    'unavailable': ['idle']
}

def transition_equipment_state(equipment_id, new_state, triggered_by='system'):
    """FSM অনুযায়ী equipment এর state change করো"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT state FROM equipment WHERE id = %s", (equipment_id,))
    equip = cursor.fetchone()
    
    if not equip:
        cursor.close(); conn.close()
        return False, "Equipment not found"
    
    current_state = equip['state']
    
    if new_state not in VALID_TRANSITIONS.get(current_state, []):
        cursor.close(); conn.close()
        return False, f"Invalid transition: {current_state} → {new_state}"
    
    # State update
    cursor.execute("UPDATE equipment SET state = %s WHERE id = %s", (new_state, equipment_id))
    
   
    cursor.execute("""
        INSERT INTO state_transitions (equipment_id, from_state, to_state, triggered_by)
        VALUES (%s, %s, %s, %s)
    """, (equipment_id, current_state, new_state, triggered_by))
    
    conn.commit()
    cursor.close()
    conn.close()
    return True, f"Transition successful: {current_state} → {new_state}"



# QUEUING THEORY — M/M/1 and M/M/c Models


def mm1_metrics(arrival_rate, service_rate):
    """
    M/M/1 Queue Model
    λ = arrival_rate (requests per unit time)
    μ = service_rate (services per unit time)
    """
    lam = arrival_rate
    mu = service_rate
    
    if mu <= lam:
        return {
            'stable': False,
            'message': 'System unstable: arrival rate >= service rate'
        }
    
    rho = lam / mu                          # Server utilization
    L = rho / (1 - rho)                     # Average number in system
    Lq = (rho ** 2) / (1 - rho)            # Average number in queue
    W = 1 / (mu - lam)                     # Average time in system
    Wq = rho / (mu - lam)                  # Average waiting time in queue
    P0 = 1 - rho                           # Probability system is empty
    
    return {
        'stable': True,
        'model': 'M/M/1',
        'arrival_rate': lam,
        'service_rate': mu,
        'utilization': round(rho, 4),
        'avg_in_system': round(L, 4),
        'avg_in_queue': round(Lq, 4),
        'avg_time_in_system': round(W, 4),
        'avg_wait_time': round(Wq, 4),
        'prob_empty': round(P0, 4)
    }

def mmc_metrics(arrival_rate, service_rate, c):
    """
    M/M/c Queue Model (multiple servers)
    c = number of servers (equipment units of same type)
    """
    lam = arrival_rate
    mu = service_rate
    
    rho = lam / (c * mu)
    
    if rho >= 1:
        return {
            'stable': False,
            'message': 'System unstable: traffic intensity >= 1'
        }
    
    # P0 calculation
    sum_part = sum([(c * rho) ** n / math.factorial(n) for n in range(c)])
    last_part = ((c * rho) ** c) / (math.factorial(c) * (1 - rho))
    P0 = 1.0 / (sum_part + last_part)
    
    # Erlang C formula — probability of queueing
    Pc = ((c * rho) ** c / math.factorial(c)) * (1 / (1 - rho)) * P0
    
    Lq = Pc * rho / (1 - rho)              # Average queue length
    Wq = Lq / lam                           # Average wait in queue
    W = Wq + 1 / mu                        # Average time in system
    L = lam * W                            # Average number in system
    
    return {
        'stable': True,
        'model': 'M/M/c',
        'servers': c,
        'arrival_rate': lam,
        'service_rate': mu,
        'utilization': round(rho, 4),
        'avg_in_system': round(L, 4),
        'avg_in_queue': round(Lq, 4),
        'avg_time_in_system': round(W, 4),
        'avg_wait_time': round(Wq, 4),
        'prob_empty': round(P0, 4),
        'prob_queuing': round(Pc, 4)
    }


# ─────────────────────────────────────────────
# AUTH DECORATOR
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════

# ───── HOME PAGE ─────

@app.route('/')
def home():
    return render_template('index.html')

# ───── AUTH ROUTES ─────

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'student')
    
    if not username or not email or not password:
        return jsonify({'error': 'All fields required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        pw_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (username, email, pw_hash, role)
        )
        conn.commit()
        return jsonify({'message': 'Registration successful', 'user_id': cursor.lastrowid}), 201
    except mysql.connector.IntegrityError:
        return jsonify({'error': 'Username or email already exists'}), 409
    finally:
        cursor.close(); conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close(); conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({
            'message': 'Login successful',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'role': user['role']
            }
        })
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me', methods=['GET'])
@login_required
def get_current_user():
    return jsonify({
        'id': session['user_id'],
        'username': session['username'],
        'role': session['role']
    })

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    
    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not current_password or not new_password:
        return jsonify({'error': 'Both current and new password required'}), 400
    
    if len(new_password) < 4:
        return jsonify({'error': 'New password must be at least 4 characters'}), 400
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT password_hash FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    if not check_password_hash(user['password_hash'], current_password):
        cursor.close(); conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    new_hash = generate_password_hash(new_password)
    cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, session['user_id']))
    conn.commit()
    cursor.close(); conn.close()
    
    return jsonify({'message': 'Password changed successfully'})

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
   
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    new_password = data.get('new_password', '')
    
    if not username or not email or not new_password:
        return jsonify({'error': 'Username, email and new password required'}), 400
    
    if len(new_password) < 4:
        return jsonify({'error': 'New password must be at least 4 characters'}), 400
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE username = %s AND email = %s", (username, email))
    user = cursor.fetchone()
    
    if not user:
        cursor.close(); conn.close()
        return jsonify({'error': 'No account found with this username and email'}), 404
    
    new_hash = generate_password_hash(new_password)
    cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user['id']))
    conn.commit()
    cursor.close(); conn.close()
    
    return jsonify({'message': 'Password reset successful. You can now login with your new password.'})

@app.route('/api/admin/reset-user-password', methods=['POST'])
@admin_required
def admin_reset_password():
    
    data = request.get_json()
    user_id = data.get('user_id')
    new_password = data.get('new_password', '')
    
    if not user_id or not new_password:
        return jsonify({'error': 'User ID and new password required'}), 400
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.close(); conn.close()
        return jsonify({'error': 'User not found'}), 404
    
    new_hash = generate_password_hash(new_password)
    cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    conn.commit()
    cursor.close(); conn.close()
    
    return jsonify({'message': 'User password reset successful'})


# ───── EQUIPMENT CRUD ─────

@app.route('/api/equipment', methods=['GET'])
@login_required
def get_all_equipment():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT e.*, 
               (SELECT COUNT(*) FROM queue_entries q 
                WHERE q.equipment_id = e.id AND q.status = 'waiting') as queue_length
        FROM equipment e
        ORDER BY e.name
    """)
    equipment = cursor.fetchall()
    cursor.close(); conn.close()
    
   
    for eq in equipment:
        for key in ['created_at', 'updated_at']:
            if eq.get(key):
                eq[key] = eq[key].isoformat()
    
    return jsonify(equipment)

@app.route('/api/equipment', methods=['POST'])
@admin_required
def create_equipment():
    data = request.get_json()
    name = data.get('name', '').strip()
    category = data.get('category', '').strip()
    service_rate = data.get('service_rate', 1.0)
    
    if not name:
        return jsonify({'error': 'Equipment name required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO equipment (name, category, service_rate) VALUES (%s, %s, %s)",
        (name, category, service_rate)
    )
    conn.commit()
    eid = cursor.lastrowid
    cursor.close(); conn.close()
    
    return jsonify({'message': 'Equipment created', 'id': eid}), 201

@app.route('/api/equipment/<int:eid>', methods=['PUT'])
@admin_required
def update_equipment(eid):
    data = request.get_json()
    conn = get_db()
    cursor = conn.cursor()
    
    fields = []
    values = []
    for key in ['name', 'category', 'service_rate']:
        if key in data:
            fields.append(f"{key} = %s")
            values.append(data[key])
    
    if not fields:
        return jsonify({'error': 'No fields to update'}), 400
    
    values.append(eid)
    cursor.execute(f"UPDATE equipment SET {', '.join(fields)} WHERE id = %s", values)
    conn.commit()
    cursor.close(); conn.close()
    
    return jsonify({'message': 'Equipment updated'})

@app.route('/api/equipment/<int:eid>', methods=['DELETE'])
@admin_required
def delete_equipment(eid):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM equipment WHERE id = %s", (eid,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({'message': 'Equipment deleted'})


# ───── STATE TRANSITION (FSM) ─────

@app.route('/api/equipment/<int:eid>/transition', methods=['POST'])
@admin_required
def change_state(eid):
    data = request.get_json()
    new_state = data.get('new_state', '')
    triggered_by = session.get('username', 'system')
    
    success, msg = transition_equipment_state(eid, new_state, triggered_by)
    
    if success:
        return jsonify({'message': msg})
    return jsonify({'error': msg}), 400

@app.route('/api/equipment/<int:eid>/transitions', methods=['GET'])
@login_required
def get_transitions(eid):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM state_transitions 
        WHERE equipment_id = %s 
        ORDER BY transitioned_at DESC 
        LIMIT 50
    """, (eid,))
    transitions = cursor.fetchall()
    cursor.close(); conn.close()
    
    for t in transitions:
        if t.get('transitioned_at'):
            t['transitioned_at'] = t['transitioned_at'].isoformat()
    
    return jsonify(transitions)


# ───── QUEUE MANAGEMENT ─────

@app.route('/api/equipment/<int:eid>/request', methods=['POST'])
@login_required
def request_equipment(eid):
    
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Check equipment exists
    cursor.execute("SELECT * FROM equipment WHERE id = %s", (eid,))
    equip = cursor.fetchone()
    if not equip:
        cursor.close(); conn.close()
        return jsonify({'error': 'Equipment not found'}), 404
    
    if equip['state'] == 'unavailable':
        cursor.close(); conn.close()
        return jsonify({'error': 'Equipment is currently unavailable'}), 400
    
    # Already in queue?
    cursor.execute("""
        SELECT id FROM queue_entries 
        WHERE equipment_id = %s AND user_id = %s AND status = 'waiting'
    """, (eid, user_id))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({'error': 'You are already in queue for this equipment'}), 400
    
  
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM queue_entries 
        WHERE equipment_id = %s AND status = 'waiting'
    """, (eid,))
    queue_len = cursor.fetchone()['cnt']
   
    if equip['state'] == 'idle' and queue_len == 0:
        # Direct service
        transition_equipment_state(eid, 'busy', session.get('username', 'system'))
        
        cursor.execute("""
            INSERT INTO queue_entries (equipment_id, user_id, status, position_in_queue, estimated_wait, started_at)
            VALUES (%s, %s, 'in_service', 0, 0, NOW())
        """, (eid, user_id))
        
        
        cursor.execute("""
            INSERT INTO usage_history (equipment_id, user_id, start_time)
            VALUES (%s, %s, NOW())
        """, (eid, user_id))
        
        conn.commit()
        cursor.close(); conn.close()
        return jsonify({'message': 'Equipment assigned directly', 'status': 'in_service', 'wait_time': 0})
 
    position = queue_len + 1
    estimated_wait = position / equip['service_rate']  
    
    cursor.execute("""
        INSERT INTO queue_entries (equipment_id, user_id, status, position_in_queue, estimated_wait)
        VALUES (%s, %s, 'waiting', %s, %s)
    """, (eid, user_id, position, estimated_wait))
    
    conn.commit()
    cursor.close(); conn.close()
    
    return jsonify({
        'message': 'Added to queue',
        'status': 'waiting',
        'position': position,
        'estimated_wait_minutes': round(estimated_wait * 60, 1)
    })

@app.route('/api/equipment/<int:eid>/release', methods=['POST'])
@login_required
def release_equipment(eid):
    
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        UPDATE queue_entries SET status = 'completed', completed_at = NOW()
        WHERE equipment_id = %s AND user_id = %s AND status = 'in_service'
    """, (eid, user_id))
   
    cursor.execute("""
        UPDATE usage_history SET end_time = NOW(),
        duration_minutes = TIMESTAMPDIFF(SECOND, start_time, NOW()) / 60.0
        WHERE equipment_id = %s AND user_id = %s AND end_time IS NULL
    """, (eid, user_id))
    
   
    cursor.execute("""
        SELECT * FROM queue_entries 
        WHERE equipment_id = %s AND status = 'waiting'
        ORDER BY requested_at ASC LIMIT 1
    """, (eid,))
    next_entry = cursor.fetchone()
    
    if next_entry:
     
        cursor.execute("""
            UPDATE queue_entries SET status = 'in_service', started_at = NOW()
            WHERE id = %s
        """, (next_entry['id'],))
        
        cursor.execute("""
            INSERT INTO usage_history (equipment_id, user_id, start_time)
            VALUES (%s, %s, NOW())
        """, (eid, next_entry['user_id']))
        
        
        cursor.execute("""
            UPDATE queue_entries SET position_in_queue = position_in_queue - 1
            WHERE equipment_id = %s AND status = 'waiting'
        """, (eid,))
    else:
       
        transition_equipment_state(eid, 'idle', 'system')
    
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({'message': 'Equipment released'})

@app.route('/api/equipment/<int:eid>/queue', methods=['GET'])
@login_required
def get_queue(eid):
   
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT q.*, u.username 
        FROM queue_entries q
        JOIN users u ON q.user_id = u.id
        WHERE q.equipment_id = %s AND q.status IN ('waiting', 'in_service')
        ORDER BY q.position_in_queue
    """, (eid,))
    queue = cursor.fetchall()
    cursor.close(); conn.close()
    
    for entry in queue:
        for key in ['requested_at', 'started_at', 'completed_at']:
            if entry.get(key):
                entry[key] = entry[key].isoformat()
    
    return jsonify(queue)


# ───── QUEUING THEORY ANALYTICS ─────

@app.route('/api/analytics/queue-metrics', methods=['GET'])
@login_required
def queue_metrics():
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM equipment")
    all_equip = cursor.fetchall()
    
    results = []
    for eq in all_equip:
       
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM queue_entries
            WHERE equipment_id = %s AND requested_at >= NOW() - INTERVAL 1 HOUR
        """, (eq['id'],))
        arrivals = cursor.fetchone()['cnt']
        
        arrival_rate = arrivals / 1.0  
        service_rate = eq['service_rate']
        
        if arrival_rate > 0:
            metrics = mm1_metrics(arrival_rate, service_rate)
        else:
            metrics = {'stable': True, 'utilization': 0, 'avg_wait_time': 0, 'message': 'No traffic'}
        
        metrics['equipment_id'] = eq['id']
        metrics['equipment_name'] = eq['name']
        results.append(metrics)
    
    cursor.close(); conn.close()
    return jsonify(results)

@app.route('/api/analytics/mmc', methods=['POST'])
@login_required
def mmc_analysis():
    """M/M/c model analysis — custom parameters"""
    data = request.get_json()
    arrival_rate = data.get('arrival_rate', 1)
    service_rate = data.get('service_rate', 2)
    servers = data.get('servers', 1)
    
    if servers == 1:
        result = mm1_metrics(arrival_rate, service_rate)
    else:
        result = mmc_metrics(arrival_rate, service_rate, servers)
    
    return jsonify(result)


# ───── DASHBOARD / REAL-TIME STATUS ─────

@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
   
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    # Equipment status counts
    cursor.execute("""
        SELECT state, COUNT(*) as count FROM equipment GROUP BY state
    """)
    state_counts = {row['state']: row['count'] for row in cursor.fetchall()}
    
    # Total equipment
    cursor.execute("SELECT COUNT(*) as total FROM equipment")
    total_equip = cursor.fetchone()['total']
    
    # Total waiting in queue
    cursor.execute("SELECT COUNT(*) as total FROM queue_entries WHERE status = 'waiting'")
    total_waiting = cursor.fetchone()['total']
    
    # Total in service
    cursor.execute("SELECT COUNT(*) as total FROM queue_entries WHERE status = 'in_service'")
    total_in_service = cursor.fetchone()['total']
    
    # Today's completed
    cursor.execute("""
        SELECT COUNT(*) as total FROM queue_entries 
        WHERE status = 'completed' AND DATE(completed_at) = CURDATE()
    """)
    today_completed = cursor.fetchone()['total']
    
    # Average utilization (from usage history)
    cursor.execute("""
        SELECT AVG(duration_minutes) as avg_duration FROM usage_history
        WHERE end_time IS NOT NULL AND DATE(start_time) = CURDATE()
    """)
    avg_duration = cursor.fetchone()['avg_duration'] or 0
    
    cursor.close(); conn.close()
    
    return jsonify({
        'total_equipment': total_equip,
        'state_counts': state_counts,
        'total_waiting': total_waiting,
        'total_in_service': total_in_service,
        'today_completed': today_completed,
        'avg_duration_minutes': round(avg_duration, 2)
    })


# ───── USAGE HISTORY ─────

@app.route('/api/history', methods=['GET'])
@login_required
def usage_history():
    """Usage history — optional filters"""
    equipment_id = request.args.get('equipment_id')
    days = request.args.get('days', 7, type=int)
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT uh.*, u.username, e.name as equipment_name
        FROM usage_history uh
        JOIN users u ON uh.user_id = u.id
        JOIN equipment e ON uh.equipment_id = e.id
        WHERE uh.start_time >= NOW() - INTERVAL %s DAY
    """
    params = [days]
    
    if equipment_id:
        query += " AND uh.equipment_id = %s"
        params.append(equipment_id)
    
    query += " ORDER BY uh.start_time DESC LIMIT 100"
    
    cursor.execute(query, params)
    history = cursor.fetchall()
    cursor.close(); conn.close()
    
    for h in history:
        for key in ['start_time', 'end_time']:
            if h.get(key):
                h[key] = h[key].isoformat()
    
    return jsonify(history)




@app.route('/api/analytics/performance', methods=['GET'])
@login_required
def performance_metrics():
    """Equipment wise performance statistics"""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            e.id,
            e.name,
            e.state,
            COUNT(uh.id) as total_uses,
            ROUND(AVG(uh.duration_minutes), 2) as avg_duration,
            ROUND(MAX(uh.duration_minutes), 2) as max_duration,
            ROUND(MIN(uh.duration_minutes), 2) as min_duration,
            ROUND(SUM(uh.duration_minutes), 2) as total_minutes
        FROM equipment e
        LEFT JOIN usage_history uh ON e.id = uh.equipment_id AND uh.end_time IS NOT NULL
        GROUP BY e.id, e.name, e.state
        ORDER BY total_uses DESC
    """)
    performance = cursor.fetchall()
    cursor.close(); conn.close()
    
    return jsonify(performance)




@app.route('/api/fsm-diagram', methods=['GET'])
def fsm_diagram():
   
    return jsonify({
        'states': ['idle', 'busy', 'unavailable'],
        'transitions': [
            {'from': 'idle', 'to': 'busy', 'label': 'User request / Start service'},
            {'from': 'busy', 'to': 'idle', 'label': 'Release / Service complete'},
            {'from': 'idle', 'to': 'unavailable', 'label': 'Maintenance'},
            {'from': 'busy', 'to': 'unavailable', 'label': 'Emergency'},
            {'from': 'unavailable', 'to': 'idle', 'label': 'Repair complete'},
        ],
        'initial': 'idle'
    })



# MAIN


if __name__ == '__main__':
    init_db()
    print("Database initialized")
    print("Server running at http://localhost:5000")
    app.run(debug=True, port=5000)