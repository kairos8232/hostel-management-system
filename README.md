# 🏠 eHostel — Hostel Management System

**eHostel** is a full-stack web application that streamlines hostel living for both residents and administrators. From booking a room and forming groups with housemates, to requesting room swaps and chatting in real time — eHostel brings the entire hostel experience into one clean, unified platform.

Built with **Python (Flask)** on the backend and a **MySQL** database, the system supports two distinct user experiences: a **Student Portal** for day-to-day living needs, and an **Admin Portal** for full operational control.

What sets it apart: a **smart roommate matching engine** (cosine similarity on survey responses), a **group booking flow** where students form and invite members before selecting rooms together, a **room swap/change approval workflow**, and **in-app chat** — all within a trimester-aware booking system.

---

## ✨ Features

### 🎓 Student Portal
- Complete a preference survey before booking (used for roommate matching)
- Book hostel rooms and beds — individually or as a group
- View and manage current bookings
- Request room changes or swaps with other students
- Create and manage groups — invite members, transfer leadership
- Chat one-on-one or in group threads
- Update profile info and profile picture

### 🛠️ Admin Portal
- Dashboard with live stats and summaries
- Manage hostels, rooms, beds, students, and trimesters
- Approve or reject room change and swap requests
- Post announcements targeted to specific trimesters or all students
- Full CRUD control over core entities

---

## 🧰 Tech Stack

| Layer      | Technology                                      |
|------------|-------------------------------------------------|
| Backend    | Python 3.10+, Flask                             |
| Database   | MySQL 8.x                                       |
| Frontend   | HTML, CSS (per-page), JavaScript                |
| Templating | Jinja2                                          |
| Auth       | Flask-Bcrypt (password hashing)                 |
| ML/Maths   | NumPy, SciPy (cosine similarity for matching)   |

---

## 🚀 Running Locally

**Prerequisites:** Python 3.10+, MySQL 8.x

```bash
# 1. Clone the repo
git clone https://github.com/kairos8232/eHostel.git
cd eHostel

# 2. Install dependencies
pip install -r requirements.txt

# 3. Import the database
mysql -u root -p < flaskapp.sql

# 4. Configure your DB credentials
#    Edit db.yaml — set mysql_host, mysql_user, mysql_password, mysql_db

# 5. Start the app
python main.py
```

App will be running at **http://127.0.0.1:5000**

### Demo Credentials

| Role    | Username | Password    |
|---------|----------|-------------|
| Admin   | `1234`   | `password1` |
| Student | `1`–`15` | `password1` |

> All 15 student accounts share the same default password for demo/testing purposes.

---

## 🔑 Core Modules

| Module              | Description                                                   |
|---------------------|---------------------------------------------------------------|
| **Authentication**  | Role-based login (student/admin), session management, bcrypt  |
| **Survey**          | Preference form completed before first booking                |
| **Booking**         | Individual and group room/bed selection flow                  |
| **Room Swap/Change**| Student-initiated requests with admin approval workflow       |
| **Group Management**| Create, join, invite, and manage housing groups               |
| **Chat**            | Real-time-style individual and group messaging                |
| **Announcements**   | Admin broadcasts scoped by trimester                          |
| **Admin Dashboard** | Stats, management tables, and approval queues                 |

---

## 🗂️ Project Structure

```
eHostel/
│
├── main.py               # All routes and application logic
├── requirements.txt      # Python dependencies
├── db.yaml               # Database connection config
├── flaskapp.sql          # MySQL schema + seed data
│
├── templates/            # Jinja2 HTML templates
│   ├── (student views)
│   └── (admin views)
│
└── static/
    ├── css/              # Per-page stylesheets
    ├── images/           # Default and hostel images
    └── uploads/          # User-uploaded profile pictures
```
