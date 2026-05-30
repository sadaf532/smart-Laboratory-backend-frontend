# 🔬 Smart Laboratory Equipment Queue Monitoring System

## Backend — Flask + MySQL

---

## 📁 Project Structure

```
project/
├── app.py              ← Main Flask application (সব routes + logic)
├── requirements.txt    ← Python dependencies
├── setup_database.sql  ← MySQL database + table + sample data
└── README.md           ← এই file
```

---

## 🚀 কিভাবে Run করবে

### Step 1: MySQL Setup
```bash
# MySQL এ login করো
mysql -u root -p

# SQL file run করো
source setup_database.sql
```
অথবা phpMyAdmin এ গিয়ে `setup_database.sql` file import করো।

### Step 2: Python Dependencies Install
```bash
pip install -r requirements.txt
```

### Step 3: Database Password Set করো
`app.py` ফাইলে `DB_CONFIG` dictionary তে তোমার MySQL password দাও:
```python
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'তোমার_password',  # ← এখানে
    'database': 'smart_lab',
}
```

### Step 4: Server Start
```bash
python app.py
```
Server চালু হবে: `http://localhost:5000`

### Step 5: Admin User Create করো
Postman বা curl দিয়ে:
```bash
curl -X POST http://localhost:5000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@lab.edu","password":"admin123","role":"admin"}'
```

---

## 📡 API Endpoints

### 🔐 Authentication
| Method | Endpoint         | কাজ                    | Auth |
|--------|-----------------|------------------------|------|
| POST   | /api/register    | নতুন user registration  | ❌   |
| POST   | /api/login       | Login (session তৈরি)    | ❌   |
| POST   | /api/logout      | Logout                 | ✅   |
| GET    | /api/me          | Current user info       | ✅   |

### 🔧 Equipment (CRUD)
| Method | Endpoint              | কাজ                       | Auth  |
|--------|----------------------|---------------------------|-------|
| GET    | /api/equipment        | সব equipment দেখাও         | ✅    |
| POST   | /api/equipment        | নতুন equipment তৈরি        | Admin |
| PUT    | /api/equipment/:id    | Equipment update           | Admin |
| DELETE | /api/equipment/:id    | Equipment delete           | Admin |

### 🔄 FSM — State Transitions
| Method | Endpoint                         | কাজ                          |
|--------|----------------------------------|------------------------------|
| POST   | /api/equipment/:id/transition     | State change (idle→busy etc) |
| GET    | /api/equipment/:id/transitions    | Transition history           |
| GET    | /api/fsm-diagram                  | FSM diagram data             |

### 📋 Queue Management
| Method | Endpoint                      | কাজ                              |
|--------|------------------------------|----------------------------------|
| POST   | /api/equipment/:id/request    | Equipment এর জন্য request করো      |
| POST   | /api/equipment/:id/release    | Equipment ছেড়ে দাও               |
| GET    | /api/equipment/:id/queue      | Equipment এর current queue       |

### 📊 Analytics & Dashboard
| Method | Endpoint                      | কাজ                              |
|--------|------------------------------|----------------------------------|
| GET    | /api/dashboard                | Dashboard summary data           |
| GET    | /api/analytics/queue-metrics  | M/M/1 metrics per equipment      |
| POST   | /api/analytics/mmc            | M/M/c custom analysis            |
| GET    | /api/analytics/performance    | Equipment performance stats      |
| GET    | /api/history                  | Usage history (filterable)       |

---

## 🧠 Core Concepts Applied

### 1. Finite State Machine (FSM)
Equipment এর ৩টা state আছে:
```
         ┌──────────────────┐
         │                  │
    ┌────▼────┐        ┌────┴────┐
    │  idle   │◄──────►│  busy   │
    └────┬────┘        └────┬────┘
         │                  │
         └──────┐  ┌───────┘
              ┌─▼──▼──┐
              │unavail.│
              └────────┘
```
Valid transitions:
- `idle → busy` (user request)
- `busy → idle` (release)
- `idle → unavailable` (maintenance)
- `busy → unavailable` (emergency)
- `unavailable → idle` (repair done)

### 2. Queuing Theory
**M/M/1 Model** (single server):
- λ = arrival rate, μ = service rate
- ρ = λ/μ (utilization)
- Wq = ρ/(μ−λ) (average wait time)

**M/M/c Model** (multiple servers):
- Erlang C formula দিয়ে queue probability calculate করে
- Multiple equipment of same type থাকলে ব্যবহার হয়

### 3. Client-Server Architecture
- Flask REST API backend
- Session-based authentication
- MySQL relational database
- JSON response format

---

## 🧪 Postman দিয়ে Test করার Example

### Login:
```json
POST /api/login
{
    "username": "admin",
    "password": "admin123"
}
```

### Equipment তৈরি:
```json
POST /api/equipment
{
    "name": "New Oscilloscope",
    "category": "Measurement",
    "service_rate": 2.5
}
```

### Equipment Request (Queue এ ঢোকো):
```json
POST /api/equipment/1/request
```

### M/M/c Analysis:
```json
POST /api/analytics/mmc
{
    "arrival_rate": 5,
    "service_rate": 3,
    "servers": 2
}
```

---

## 📌 Notes
- `service_rate` মানে প্রতি ঘণ্টায় কতজন কে serve করতে পারে
- Queue automatically manage হয় — idle equipment পেলে direct assign, না পেলে queue তে ঢোকে
- State transition FSM rule follow করে — invalid transition reject হবে
- সব transition history database এ log থাকে
