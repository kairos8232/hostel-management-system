# 🏠 Mini Hostel Management System (eHostel)

A **web-based hostel management system** for university students and admins, built with **Flask** and **MySQL**.  
Students can book rooms, form groups, request swaps, and chat — while admins manage hostels, announcements, and approvals.

---

## ✨ Features

### 🎓 Student Portal
- Book hostel rooms and beds (individual or group)
- View and manage existing bookings
- Request room changes or swaps
- Create and manage groups (invitations, leadership, etc.)
- Chat (individual and group)
- Update profile and complete pre-booking survey

### 🛠️ Admin Portal
- Manage students, rooms, beds, hostels, and trimesters
- Approve/reject room change and swap requests
- Post announcements
- Dashboard with statistics and summaries

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-------------|
| Backend | Python 3.10+ (Flask) |
| Database | MySQL 8.x |
| Frontend | HTML, CSS (custom per-page), JavaScript (minimal) |
| Templates | Jinja2 |
| Security | bcrypt (password hashing) |

---

## ⚙️ Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/eHostel.git
   cd eHostel
   ```
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
3. **Set up the MySQL database**
   - Ensure MySQL is running.
   - Import the schema and sample data:
   ```bash
   mysql -u root -p < flaskapp.sql
   ```
   - Edit db.yaml to match your MySQL credentials.
4. Run the Flask app
   ```bash
   python main.py
   ```
   The app runs at http://127.0.0.1:5000 by default.
5. Default Admin Login
   ```yaml
   username: admin
   password: securepassword
   ```
   (Password is hashed in DB — see flaskapp.sql for hash.)

---

## 🧱 File Structure
```bash
eHostel/
│
├── main.py               # Main Flask application
├── requirements.txt      # Python dependencies
├── db.yaml               # Database connection config
├── flaskapp.sql          # MySQL schema and seed data
│
├── templates/            # Jinja2 HTML templates
│
└── static/
    ├── css/              # Per-page CSS
    ├── images/           # Profile and hostel images
    └── uploads/          # User-uploaded files
```

---

## 🔑 Key Modules
- Authentication: Student/admin login & session management
- Booking: Room/bed selection (group or individual), confirmation
- Room Change/Swap: Requests and admin approvals
- Group Management: Create/join/leave groups, invite members
- Admin Management: Students, rooms, hostels, trimesters, requests
- Chat: Individual and group chat features
- Survey: Student satisfaction or preference survey before booking
