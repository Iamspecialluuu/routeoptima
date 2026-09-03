import os, math, time, sqlite3, hashlib, secrets, json
from datetime import datetime, timedelta
from functools import wraps
from itertools import permutations
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'dispatch_tsp.db')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', 'YOUR_GOOGLE_MAPS_API_KEY')
DEPOT_NAME = 'Choba, Port Harcourt Nigeria'
DEPOT_COORDS = (4.8156, 7.0498)
AVG_SPEED_KMH = 25

def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    c = g.pop('db', None)
    if c:
        c.close()

def hash_password(p, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', p.encode(), salt.encode(), 120000).hex()
    return f'{salt}${h}'

def verify_password(p, stored):
    try:
        salt, d = stored.split('$', 1)
        h = hashlib.pbkdf2_hmac('sha256', p.encode(), salt.encode(), 120000).hex()
        return secrets.compare_digest(h, d)
    except ValueError:
        return False

def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS admins(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS riders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        vehicle TEXT,
        status TEXT NOT NULL DEFAULT 'Available',
        latitude REAL,
        longitude REAL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS deliveries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        address TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        rider_id INTEGER,
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY(rider_id) REFERENCES riders(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS route_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rider_id INTEGER,
        algorithm TEXT NOT NULL,
        stop_count INTEGER NOT NULL,
        total_distance REAL NOT NULL,
        execution_ms REAL NOT NULL,
        route_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(rider_id) REFERENCES riders(id) ON DELETE SET NULL
    );
    ''')
    try:
        c.execute('ALTER TABLE riders ADD COLUMN vehicle TEXT')
    except sqlite3.OperationalError:
        pass

    now = datetime.now().isoformat(timespec='seconds')
    if c.execute('SELECT COUNT(*) FROM admins').fetchone()[0] == 0:
        c.execute('INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)',
                  ('admin', hash_password('admin123'), now))

    if c.execute('SELECT COUNT(*) FROM riders').fetchone()[0] == 0:
        rows = [
            ('Chinedu Okafor', '08030000001', 'Honda CB125', 'Available', 4.8156, 7.0498),
            ('Emeka Nwosu', '08030000002', 'Bajaj Boxer BM150', 'On Delivery', 4.825, 7.033),
            ('Daniel George', '08030000003', 'TVS Apache 180', 'Available', 4.84, 7.015),
            ('Samuel Johnson', '08030000004', 'Bajaj Discover 125', 'Available', 4.79, 7.04)
        ]
        c.executemany('INSERT INTO riders(name,phone,vehicle,status,latitude,longitude,created_at) VALUES(?,?,?,?,?,?,?)',
                      [(a, b, v, d, e, f, now) for a, b, v, d, e, f in rows])

    if c.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0] == 0:
        rows = [
            ('Customer 001', 'GRA Phase 2', 4.8156, 7.0498),
            ('Customer 002', 'Rumuola', 4.839, 7.018),
            ('Customer 003', 'D-Line', 4.806, 7.02),
            ('Customer 004', 'Trans Amadi', 4.8, 7.07),
            ('Customer 005', 'Old GRA', 4.797, 7.035),
            ('Customer 006', 'Woji', 4.792, 7.09),
            ('Customer 007', 'Rumuokoro', 4.873, 7.011),
            ('Customer 008', 'Rumuodara', 4.855, 7.055)
        ]
        c.executemany('INSERT INTO deliveries(customer_name,address,latitude,longitude,status,created_at) VALUES(?,?,?,?,?,?)',
                      [(a, b, d, e, 'Pending', now) for a, b, d, e in rows])
    c.commit()

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        return f(*a, **kw) if 'admin_id' in session else redirect(url_for('login'))
    return w

def haversine(a, b):
    R = 6371.0
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(h))

def matrix(points):
    return [[0 if i == j else haversine(points[i], points[j]) for j in range(len(points))] for i in range(len(points))]

def route_distance(order, m):
    return sum(m[order[i]][order[i + 1]] for i in range(len(order) - 1))

def two_opt(route, m):
    best = route
    best_dist = route_distance(best, m)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(route) - 2):
            for j in range(i + 1, len(route) - 1):
                if j - i == 1:
                    continue
                new_route = route[:i] + route[i:j][::-1] + route[j:]
                new_dist = route_distance(new_route, m)
                if new_dist < best_dist:
                    best = new_route
                    best_dist = new_dist
                    improved = True
                    route = new_route
                    break
            if improved:
                break
    return best, best_dist

def exact_tsp(points):
    n = len(points)
    if n <= 1:
        return list(range(n)), 0.0
    if n > 11:  # 1 Depot + 10 delivery stops max for exact permutations
        raise ValueError('Exact TSP is limited to 10 delivery stops.')
    m = matrix(points)
    best = None
    bd = float('inf')
    for p in permutations(range(1, n)):
        o = [0] + list(p) + [0]
        d = route_distance(o, m)
        if d < bd:
            bd = d
            best = o
    return best, bd

def nearest_neighbor_tsp(points):
    n = len(points)
    if n <= 1:
        return list(range(n)), 0.0
    m = matrix(points)
    left = set(range(1, n))
    o = [0]
    while left:
        cur = o[-1]
        nxt = min(left, key=lambda j: m[cur][j])
        o.append(nxt)
        left.remove(nxt)
    o.append(0)
    # Refine NN route with 2-Opt algorithm
    return two_opt(o, m)

def optimize_points(points, algo='auto'):
    if len(points) < 2:
        return list(range(len(points))), 0.0, 'Not applicable'
    if algo == 'exact' and len(points) <= 11:
        o, d = exact_tsp(points)
        return o, d, 'Exact TSP'
    if algo == 'nearest':
        o, d = nearest_neighbor_tsp(points)
        return o, d, 'Nearest Neighbour'
    if len(points) <= 11:
        o, d = exact_tsp(points)
        return o, d, 'Exact TSP'
    o, d = nearest_neighbor_tsp(points)
    return o, d, 'Nearest Neighbour'

PAGE_META = {
    'dashboard': ('Dashboard', 'Overview of your delivery system'),
    'riders': ('Riders', 'Manage dispatch riders and their status'),
    'deliveries': ('Deliveries', 'Track and assign customer deliveries'),
    'routes': ('Routes', 'Optimize and manage delivery routes'),
    'reports': ('Reports', 'System reports and analytics'),
    'users': ('Users', 'Manage admin users and permissions'),
    'settings': ('Settings', 'System configuration and preferences'),
    'optimize': ('Optimize Route', 'Select stops and compute the shortest route'),
    'history': ('Route History', 'Past route optimizations and results'),
}

@app.context_processor
def globals_():
    title, sub = PAGE_META.get(request.endpoint, (None, None))
    return {
        'google_maps_api_key': GOOGLE_MAPS_API_KEY,
        'page_title': title,
        'page_sub': sub
    }

@app.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('dashboard'))
    c = db()
    stats = {
        'deliveries': c.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0],
        'riders': c.execute("SELECT COUNT(*) FROM riders WHERE status='Available'").fetchone()[0],
        'total_distance': round(c.execute('SELECT COALESCE(SUM(total_distance),0) FROM route_history').fetchone()[0], 1)
    }
    return render_template('landing.html', stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        a = db().execute('SELECT * FROM admins WHERE username=?', (request.form.get('username', '').strip(),)).fetchone()
        if a and verify_password(request.form.get('password', ''), a['password_hash']):
            session['admin_id'] = a['id']
            session['username'] = a['username']
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    c = db()
    stats = {
        'riders': c.execute('SELECT COUNT(*) FROM riders').fetchone()[0],
        'active_riders': c.execute("SELECT COUNT(*) FROM riders WHERE status='Available'").fetchone()[0],
        'deliveries': c.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0],
        'pending': c.execute("SELECT COUNT(*) FROM deliveries WHERE status='Pending'").fetchone()[0],
        'routes': c.execute('SELECT COUNT(*) FROM route_history').fetchone()[0],
        'total_distance': round(c.execute('SELECT COALESCE(SUM(total_distance),0) FROM route_history').fetchone()[0], 1)
    }
    top_riders = c.execute(
        'SELECT r.name, COUNT(d.id) c FROM riders r LEFT JOIN deliveries d ON d.rider_id=r.id GROUP BY r.id ORDER BY c DESC, r.name LIMIT 5'
    ).fetchall()
    days = []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        cnt = c.execute("SELECT COUNT(*) FROM deliveries WHERE substr(created_at,1,10)=?", (day,)).fetchone()[0]
        days.append({'label': datetime.strptime(day, '%Y-%m-%d').strftime('%a'), 'count': cnt})
    
    def fmt_num(n):
        try:
            return '{:,}'.format(int(n))
        except (ValueError, TypeError):
            return n

    max_day = max([d['count'] for d in days] + [1])
    for d in days:
        d['pct'] = max(6, round(d['count'] / max_day * 100))
    stats['riders_fmt'] = fmt_num(stats['riders'])
    stats['deliveries_fmt'] = fmt_num(stats['deliveries'])
    stats['routes_fmt'] = fmt_num(stats['routes'])
    stats['total_distance_fmt'] = fmt_num(stats['total_distance'])
    return render_template('dashboard.html', stats=stats, top_riders=top_riders, days=days, max_day=max_day, fmt_num=fmt_num)

@app.route('/riders', methods=['GET', 'POST'])
@login_required
def riders():
    c = db()
    if request.method == 'POST':
        c.execute(
            'INSERT INTO riders(name,phone,vehicle,status,latitude,longitude,created_at) VALUES(?,?,?,?,?,?,?)',
            (request.form['name'], request.form['phone'], request.form.get('vehicle', ''), request.form['status'],
             float(request.form['latitude']), float(request.form['longitude']),
             datetime.now().isoformat(timespec='seconds'))
        )
        c.commit()
        flash('Rider added successfully.', 'success')
        return redirect(url_for('riders'))
    rows = c.execute(
        'SELECT r.*, COUNT(d.id) deliveries_count FROM riders r LEFT JOIN deliveries d ON d.rider_id=r.id '
        'GROUP BY r.id ORDER BY r.id DESC'
    ).fetchall()
    return render_template('riders.html', riders=rows)

@app.route('/riders/add')
@login_required
def add_rider_page():
    return render_template('add_rider.html')

@app.route('/riders/delete/<int:rider_id>', methods=['POST'])
@login_required
def delete_rider(rider_id):
    db().execute('DELETE FROM riders WHERE id=?', (rider_id,))
    db().commit()
    flash('Rider deleted.', 'success')
    return redirect(url_for('riders'))

@app.route('/riders/<int:rider_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_rider(rider_id):
    c = db()
    rider = c.execute('SELECT * FROM riders WHERE id = ?', (rider_id,)).fetchone()
    if not rider:
        flash('Rider not found', 'danger')
        return redirect(url_for('riders'))

    if request.method == 'POST':
        c.execute('''UPDATE riders 
                      SET name=?, phone=?, vehicle=?, status=?, latitude=?, longitude=? 
                      WHERE id=?''',
                  (request.form['name'],
                   request.form['phone'],
                   request.form.get('vehicle', ''),
                   request.form['status'],
                   float(request.form['latitude']),
                   float(request.form['longitude']),
                   rider_id))
        c.commit()
        flash('Rider updated successfully', 'success')
        return redirect(url_for('riders'))

    return render_template('edit_rider.html', rider=rider)

@app.route('/riders/<int:rider_id>')
@login_required
def view_rider(rider_id):
    c = db()
    rider = c.execute('SELECT * FROM riders WHERE id = ?', (rider_id,)).fetchone()
    if not rider:
        flash('Rider not found', 'danger')
        return redirect(url_for('riders'))
    return render_template('view_rider.html', rider=rider)

@app.route('/deliveries', methods=['GET', 'POST'])
@login_required
def deliveries():
    c = db()
    if request.method == 'POST':
        c.execute(
            'INSERT INTO deliveries(customer_name,address,latitude,longitude,rider_id,status,created_at) VALUES(?,?,?,?,?,?,?)',
            (request.form['customer_name'], request.form['address'],
             float(request.form['latitude']), float(request.form['longitude']),
             int(request.form['rider_id']) if request.form.get('rider_id') else None,
             request.form['status'], datetime.now().isoformat(timespec='seconds'))
        )
        c.commit()
        flash('Delivery added successfully.', 'success')
        return redirect(url_for('deliveries'))
    rows = c.execute(
        'SELECT d.*, r.name rider_name FROM deliveries d LEFT JOIN riders r ON r.id=d.rider_id ORDER BY d.id DESC'
    ).fetchall()
    return render_template('deliveries.html', deliveries=rows, riders=c.execute('SELECT * FROM riders ORDER BY name').fetchall())

@app.route('/deliveries/status/<int:delivery_id>', methods=['POST'])
@login_required
def delivery_status(delivery_id):
    db().execute('UPDATE deliveries SET status=? WHERE id=?', (request.form['status'], delivery_id))
    db().commit()
    return redirect(url_for('deliveries'))

@app.route('/optimize')
@login_required
def optimize():
    return render_template('optimize.html', deliveries=db().execute("SELECT * FROM deliveries WHERE status!='Delivered' ORDER BY id").fetchall(), depot_name=DEPOT_NAME)

@app.route('/api/optimize', methods=['POST'])
@login_required
def api_optimize():
    p = request.get_json(force=True)
    ids = [int(x) for x in p.get('delivery_ids', [])]
    algo = p.get('algorithm', 'auto')
    
    if len(ids) < 1:
        return jsonify(error='Select at least one delivery location.'), 400

    ph = ','.join('?' * len(ids))
    rows = db().execute(f'SELECT * FROM deliveries WHERE id IN ({ph})', ids).fetchall()
    by = {r['id']: r for r in rows}
    rows = [by[i] for i in ids if i in by]
    
    # Critical Fix: Prepend the Depot as Index 0
    points = [DEPOT_COORDS] + [(r['latitude'], r['longitude']) for r in rows]
    
    before = list(range(len(points))) + [0]
    bd = route_distance(before, matrix(points))
    t = time.perf_counter()
    try:
        o, d, used = optimize_points(points, algo)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    ms = (time.perf_counter() - t) * 1000

    route_inner = []
    for idx, i in enumerate(o):
        if i == 0 and idx == 0:
            route_inner.append({
                'id': 'depot',
                'customer_name': DEPOT_NAME,
                'address': 'Pickup / Start',
                'latitude': DEPOT_COORDS[0],
                'longitude': DEPOT_COORDS[1],
                'is_depot_start': True
            })
        elif i == 0 and idx == len(o) - 1:
            route_inner.append({
                'id': 'depot_end',
                'customer_name': DEPOT_NAME,
                'address': 'Return to Start',
                'latitude': DEPOT_COORDS[0],
                'longitude': DEPOT_COORDS[1],
                'is_depot_end': True
            })
        else:
            # Map index offset back to delivery rows (-1 due to Depot at index 0)
            delivery_row = rows[i - 1]
            route_inner.append({
                'id': delivery_row['id'],
                'customer_name': delivery_row['customer_name'],
                'address': delivery_row['address'],
                'latitude': delivery_row['latitude'],
                'longitude': delivery_row['longitude']
            })

    saved = max(0.0, bd - d)
    imp = (saved / bd * 100) if bd else 0
    algo_label = used
    if 'Exact' in algo_label:
        algo_label = 'Exact TSP (Brute-Force)'
    elif 'Nearest' in algo_label:
        algo_label = 'TSP (NN + 2-Opt)'

    db().execute(
        'INSERT INTO route_history(algorithm,stop_count,total_distance,execution_ms,route_json,created_at) VALUES(?,?,?,?,?,?)',
        (used, len(points) - 1, d, ms, json.dumps(route_inner), datetime.now().isoformat(timespec='seconds'))
    )
    db().commit()
    
    est_minutes = round(d / AVG_SPEED_KMH * 60)
    date_label = datetime.now().strftime('%b %d, %Y')
    
    return jsonify(
        route=route_inner,
        algorithm=algo_label,
        total_distance=round(d, 2),
        before_distance=round(bd, 3),
        distance_saved=round(saved, 3),
        improvement=round(imp, 2),
        execution_ms=round(ms, 3),
        estimated_minutes=est_minutes,
        total_stops=len(points) - 1,
        date=date_label,
        depot_name=DEPOT_NAME,
        depot_latitude=DEPOT_COORDS[0],
        depot_longitude=DEPOT_COORDS[1]
    )

@app.route('/history')
@login_required
def history():
    return render_template('history.html', history=db().execute('SELECT * FROM route_history ORDER BY id DESC').fetchall())

@app.route('/routes')
@login_required
def routes():
    return redirect(url_for('optimize'))

@app.route('/reports')
@login_required
def reports():
    flash('Reports module coming soon.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/users')
@login_required
def users():
    flash('Users module coming soon.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/settings')
@login_required
def settings():
    flash('Settings module coming soon.', 'info')
    return redirect(url_for('dashboard'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)