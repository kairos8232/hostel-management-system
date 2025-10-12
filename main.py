from flask import Flask, render_template, request, redirect, url_for, session, flash, get_flashed_messages
from flask_mysqldb import MySQL
from functools import wraps
import MySQLdb.cursors
import yaml
from flask_bcrypt import Bcrypt
import os
from scipy.spatial.distance import cosine
import numpy as np
from datetime import datetime

main = Flask(__name__)

db = yaml.safe_load(open('db.yaml'))
main.config['MYSQL_HOST'] = db['mysql_host']
main.config['MYSQL_USER'] = db['mysql_user']
main.config['MYSQL_PASSWORD'] = db['mysql_password']
main.config['MYSQL_DB'] = db['mysql_db']
main.config['UPLOAD_FOLDER'] = db['mysql_profile_pic']
main.secret_key = 'terrychin'
bcrypt = Bcrypt(main)
mysql = MySQL(main)

# Check Admin Role
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin', False): 
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('index'))
        if not session.get('loggedin', False):
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Check Student Role
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_admin', False):
            flash('Access denied. This area is for students only.', 'error')
            return redirect(url_for('index'))
        if not session.get('loggedin', False):
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Check survey done
def survey_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('id')
        if user_id:
            cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
            user = cur.fetchone()
            cur.close()
            if user and user['survey_completed'] == 0:
                return redirect(url_for('survey'))
        return f(*args, **kwargs)
    return decorated_function

# Get image url, to ensure every route catch the profile picture correctly
@main.context_processor
def inject_profile_pic():
    if 'id' in session:
        return {'profile_pic_url': get_profile_pic_url(session['id'])}
    return {}

def get_profile_pic_url(user_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT profile_pic FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    return user['profile_pic'] if user and user['profile_pic'] else url_for('static', filename='images/default_profile_pic.jpg')

def get_group_profile_pic_url(group_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT profile_pic FROM `groups` WHERE group_id = %s", (group_id,))
    group = cur.fetchone()
    cur.close()
    return group['profile_pic'] if group and group['profile_pic'] else url_for('static', filename='images/default_group_pic.jpg')

# Comparision between User and User
def calculate_similarity(ratings1, ratings2):
    v1 = np.array(ratings1)    # Convert ratings to numpy arrays
    v2 = np.array(ratings2)
    
    similarity = (1 - cosine(v1, v2))*100     # Calculate cosine similarity
    return similarity

@main.route('/')
def index():
    return render_template('index.html')

@main.route("/about")
def about():
    return render_template('about.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        userDetails = request.form
        id = userDetails['id']
        password = userDetails['password']

        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute('SELECT * FROM roles WHERE SoA_id=%s', (id,))
        role_entry = cur.fetchone()
        
        if role_entry:
            if role_entry['role'] == 'admin':
                cur.execute('SELECT * FROM admin WHERE id=%s', (id,))
                user = cur.fetchone()
                
                if user and bcrypt.check_password_hash(user['password'], password):
                    session['loggedin'] = True
                    session['id'] = user['id']
                    session['is_admin'] = True
                    cur.close()
                    return redirect(url_for('admin_dashboard'))
            
            elif role_entry['role'] == 'user':
                cur.execute('SELECT * FROM users WHERE id=%s', (id,))
                user = cur.fetchone()
                
                if user and bcrypt.check_password_hash(user['password'], password):
                    session['loggedin'] = True
                    session['id'] = user['id']
                    session['is_admin'] = False
                    cur.close()
                    return redirect(url_for('home'))
  
        cur.close()
        flash('Incorrect ID or password. Please try again!', 'error')
        return redirect(url_for('login'))
    
    return render_template('login.html')


#########################################STUDENT#############################################

#Student Home
@main.route("/student")
@student_required
@survey_required
def home():
    user_id = session.get('id')
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        SELECT invitations.invitation_id, `groups`.name AS group_name, users.name AS leader_name
        FROM invitations
        JOIN `groups` ON invitations.group_id = `groups`.group_id
        JOIN users ON invitations.inviter_id = users.id
        WHERE invitee_id = %s AND status = 'pending'
    """, (user_id,))
    invitation = cur.fetchone()
    
    # Fetch announcements
    cur.execute("SELECT * FROM announcement ORDER BY id DESC")
    announcements = cur.fetchall()
    cur.close()
    
    current_index = session.get('announcement_index', 0)
    total_announcements = len(announcements)
    
    if request.args.get('next'):
        current_index = (current_index + 1) % total_announcements
    elif request.args.get('back'):
        current_index = (current_index - 1) % total_announcements
    
    session['announcement_index'] = current_index
    
    current_announcement = announcements[current_index] if announcements else None
    
    return render_template('home.html', 
                           announcement=current_announcement, 
                           has_next=total_announcements > 1,
                           has_back=total_announcements > 1,
                           invitation=invitation,
    )

@main.route('/chat/')
@student_required
@survey_required
def chat_home():
    user_id = session.get('id')
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch all individual conversations for the current user
    cur.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN cm.sender_id = %s THEN cm.receiver_id 
                ELSE cm.sender_id 
            END AS partner_id,
            u.name AS partner_name,
            u.profile_pic AS partner_profile_pic
        FROM chat_messages cm
        JOIN users u ON u.id = CASE 
            WHEN cm.sender_id = %s THEN cm.receiver_id 
            ELSE cm.sender_id 
        END
        WHERE %s IN (cm.sender_id, cm.receiver_id) AND cm.group_id IS NULL
    """, (user_id, user_id, user_id))
    individual_conversations = cur.fetchall()

    # Fetch all group conversations for the current user
    cur.execute("""
        SELECT g.group_id, g.name AS group_name, g.profile_pic AS group_profile_pic
        FROM `groups` g 
        JOIN group_members gm ON g.group_id = gm.group_id 
        WHERE gm.user_id = %s
    """, (user_id,))
    group_conversations = cur.fetchall()

    cur.close()

    return render_template('chat.html', 
                           individual_conversations=individual_conversations,
                           group_conversations=group_conversations,
                           messages=[],
                           chat_partner=None,
                           user_group=None,
                           user_profile_pic=get_profile_pic_url(user_id))

@main.route('/chat/individual/<int:partner_id>')
@student_required
def individual_chat(partner_id):
    user_id = session.get('id')
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch messages for the selected individual conversation
    cur.execute("""
        SELECT cm.*, u.name as sender_name, u.profile_pic as sender_profile_pic
        FROM chat_messages cm 
        JOIN users u ON cm.sender_id = u.id 
        WHERE ((cm.sender_id = %s AND cm.receiver_id = %s) 
        OR (cm.sender_id = %s AND cm.receiver_id = %s))
        AND cm.group_id IS NULL
        ORDER BY cm.timestamp
    """, (user_id, partner_id, partner_id, user_id))
    messages = cur.fetchall()

    cur.execute("SELECT id, name, profile_pic FROM users WHERE id = %s", (partner_id,))
    chat_partner = cur.fetchone()

    # Fetch all individual conversations (for sidebar)
    cur.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN cm.sender_id = %s THEN cm.receiver_id 
                ELSE cm.sender_id 
            END AS partner_id,
            u.name AS partner_name,
            u.profile_pic AS partner_profile_pic
        FROM chat_messages cm
        JOIN users u ON u.id = CASE 
            WHEN cm.sender_id = %s THEN cm.receiver_id 
            ELSE cm.sender_id 
        END
        WHERE %s IN (cm.sender_id, cm.receiver_id) AND cm.group_id IS NULL
    """, (user_id, user_id, user_id))
    individual_conversations = cur.fetchall()

    # Fetch all group conversations (for sidebar)
    cur.execute("""
        SELECT g.group_id, g.name AS group_name, g.profile_pic AS group_profile_pic
        FROM `groups` g 
        JOIN group_members gm ON g.group_id = gm.group_id 
        WHERE gm.user_id = %s
    """, (user_id,))
    group_conversations = cur.fetchall()

    cur.close()

    return render_template('chat.html', 
                           individual_conversations=individual_conversations,
                           group_conversations=group_conversations,
                           messages=messages,
                           chat_partner=chat_partner,
                           user_group=None,
                           user_profile_pic=get_profile_pic_url(user_id))

@main.route('/chat/group/<int:group_id>')
@student_required
def group_chat(group_id):
    user_id = session.get('id')
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch messages for the selected group conversation
    cur.execute("""
        SELECT cm.*, u.name as sender_name, u.profile_pic as sender_profile_pic
        FROM chat_messages cm 
        JOIN users u ON cm.sender_id = u.id 
        WHERE cm.group_id = %s 
        ORDER BY cm.timestamp
    """, (group_id,))
    messages = cur.fetchall()

    # Fetch group info
    cur.execute("SELECT * FROM `groups` WHERE group_id = %s", (group_id,))
    user_group = cur.fetchone()

    # Fetch all individual conversations (for sidebar)
    cur.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN cm.sender_id = %s THEN cm.receiver_id 
                ELSE cm.sender_id 
            END AS partner_id,
            u.name AS partner_name,
            u.profile_pic AS partner_profile_pic
        FROM chat_messages cm
        JOIN users u ON u.id = CASE 
            WHEN cm.sender_id = %s THEN cm.receiver_id 
            ELSE cm.sender_id 
        END
        WHERE %s IN (cm.sender_id, cm.receiver_id) AND cm.group_id IS NULL
    """, (user_id, user_id, user_id))
    individual_conversations = cur.fetchall()

    # Fetch all group conversations (for sidebar)
    cur.execute("""
        SELECT g.group_id, g.name AS group_name, g.profile_pic AS group_profile_pic
        FROM `groups` g 
        JOIN group_members gm ON g.group_id = gm.group_id 
        WHERE gm.user_id = %s
    """, (user_id,))
    group_conversations = cur.fetchall()

    cur.close()

    return render_template('chat.html', 
                           individual_conversations=individual_conversations,
                           group_conversations=group_conversations,
                           messages=messages,
                           chat_partner=None,
                           user_group=user_group,
                           user_profile_pic=get_profile_pic_url(user_id))

@main.route('/search_user', methods=['POST'])
@student_required
def search_user():
    user_id = session.get('id')
    search_id = request.form['search_id']
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch all individual conversations for the current user
    cur.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN cm.sender_id = %s THEN cm.receiver_id 
                ELSE cm.sender_id 
            END AS partner_id,
            u.name AS partner_name,
            u.profile_pic AS partner_profile_pic
        FROM chat_messages cm
        JOIN users u ON u.id = CASE 
            WHEN cm.sender_id = %s THEN cm.receiver_id 
            ELSE cm.sender_id 
        END
        WHERE %s IN (cm.sender_id, cm.receiver_id) AND cm.group_id IS NULL
    """, (user_id, user_id, user_id))
    individual_conversations = cur.fetchall()

    # Fetch all group conversations for the current user
    cur.execute("""
        SELECT g.group_id, g.name AS group_name, g.profile_pic AS group_profile_pic
        FROM `groups` g 
        JOIN group_members gm ON g.group_id = gm.group_id 
        WHERE gm.user_id = %s
    """, (user_id,))
    group_conversations = cur.fetchall()

    # Fetch the chat partner based on user ID
    cur.execute("SELECT id, name FROM users WHERE id = %s", (search_id,))
    chat_partner = cur.fetchone()

    messages = []  # Initialize messages

    if chat_partner:
        # Fetch chat history if chat partner is found
        cur.execute("""
            SELECT cm.*, u.name as sender_name 
            FROM chat_messages cm 
            JOIN users u ON cm.sender_id = u.id 
            WHERE (cm.sender_id = %s AND cm.receiver_id = %s) 
            OR (cm.sender_id = %s AND cm.receiver_id = %s) 
            ORDER BY cm.timestamp
        """, (user_id, chat_partner['id'], chat_partner['id'], user_id))
        messages = cur.fetchall()

    cur.close()

    return render_template('chat.html', chat_partner=chat_partner, messages=messages, individual_conversations=individual_conversations, group_conversations=group_conversations)

@main.route('/send_message', methods=['POST'])
@student_required
def send_message():
    sender_id = session.get('id')
    receiver_id = request.form['receiver_id']
    message = request.form['message']

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        INSERT INTO chat_messages (sender_id, receiver_id, message)
        VALUES (%s, %s, %s)
    """, (sender_id, receiver_id, message))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('individual_chat', partner_id=receiver_id))

@main.route('/send_group_message', methods=['POST'])
@student_required
def send_group_message():

    sender_id = session.get('id')
    group_id = request.form['group_id']
    message = request.form['message']

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        INSERT INTO chat_messages (sender_id, group_id, message)
        VALUES (%s, %s, %s)
    """, (sender_id, group_id, message))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('group_chat', group_id=group_id))

# Student Profile
@main.route('/student/profile', methods=['GET', 'POST'])
@student_required
def profile():
    user_id = session.get('id')
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()  # Close the cursor after fetching user data

    # Determine profile picture URL (reuse context processor logic)
    profile_pic_url = user[6] if user[6] else url_for('static', filename='images/default_profile_pic.jpg')
    return render_template('profile.html',
        name=user[1],
        student_id=user[0],
        gender=user[2],
        email=user[3],
        faculty=user[5],
        profile_pic_url=profile_pic_url,
        messages=get_flashed_messages(with_categories=True)
    )

# Edit Profile
@main.route('/student/edit_profile', methods=['GET', 'POST'])
@student_required
def edit_profile():
    user_id = session.get('id')
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    if request.method == 'POST':
        email = request.form['email']
        profile_pic = request.files.get('profile_pic')

        if profile_pic:
            # Save the uploaded profile picture
            profile_pic_path = os.path.join(main.config['UPLOAD_FOLDER'], profile_pic.filename)
            profile_pic.save(profile_pic_path)
            profile_pic_url = url_for('static', filename=f"uploads/{profile_pic.filename}")
        else:
            profile_pic_url = None

        # Update the user's profile data
        cur.execute("""
            UPDATE users SET email=%s, profile_pic=%s
            WHERE id=%s
            """, (email, profile_pic_url, user_id))
        mysql.connection.commit()

        flash('Profile updated successfully!', 'success')
        cur.close()

        return redirect(url_for('profile'))

    cur.execute("SELECT name, id, gender, faculty, email, profile_pic FROM users WHERE id=%s", [user_id])
    user_data = cur.fetchone()
    cur.close()

    user_profile = {
        'name': user_data['name'],
        'student_id': user_data['id'],
        'gender': user_data['gender'],
        'faculty': user_data['faculty'],
        'email': user_data['email'],
        'image_url': user_data['profile_pic']
    }
    return render_template('edit_profile.html', **user_profile)

# Change Password Route
@main.route('/student/change_password', methods=['GET', 'POST'])
@student_required
def change_password():
    user_id = session.get('id')
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT password FROM users WHERE id=%s", [user_id])
        user_data = cur.fetchone()
        cur.close()

        if user_data and bcrypt.check_password_hash(user_data[0], current_password):
            if new_password == confirm_password:
                hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                cur = mysql.connection.cursor()
                cur.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_password, user_id))
                mysql.connection.commit()
                cur.close()
                flash('Your password has been updated successfully!', 'success')
                return redirect(url_for('profile'))
            else:
                flash('Passwords do not match.', 'error')
                return redirect(url_for('change_password'))
        else:
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('change_password'))

    return render_template('change_password.html')

# Student Room Setting
@main.route('/student/room_setting')
@student_required
def room_setting():
    user_id = session.get('id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch the default trimester
    cur.execute("""
        SELECT id, term, name
        FROM trimester
        WHERE is_default = 1
        LIMIT 1
    """)
    default_trimester = cur.fetchone()

    if not default_trimester:
        # If no default trimester is found, redirect to an appropriate page
        flash('No default trimester is set.', 'error')
        return redirect(url_for('select_trimester'))

    default_trimester_id = default_trimester['id']

    # Fetch the user's booking for the default trimester
    cur.execute("""
        SELECT b.*, h.name AS hostel_name, r.category AS room_type, bd.bed_letter, t.term AS trimester_term
        FROM booking b
        JOIN hostel h ON b.hostel_id = h.id
        JOIN rooms r ON b.room_no = r.number
        JOIN beds bd ON b.bed_number = bd.id
        JOIN trimester t ON b.trimester_id = t.id
        WHERE b.user_id = %s AND b.trimester_id = %s
        ORDER BY b.booking_no DESC
        LIMIT 1
    """, (user_id, default_trimester_id))
    booking = cur.fetchone()

    # If no booking exists for the default trimester, redirect to select a trimester
    if not booking:
        flash('You do not have a booking in the current trimester.', 'info')
        return redirect(url_for('select_trimester'))

    # Fetch pending room swap requests for this user in the default trimester
    cur.execute("""
        SELECT rsr.*, u.name AS requester_name, b.room_no AS requester_room, b.bed_number AS requester_bed, bd.bed_letter AS requester_bed_letter
        FROM room_swap_requests rsr
        JOIN users u ON rsr.user_id = u.id
        JOIN booking b ON rsr.user_id = b.user_id AND b.trimester_id = %s
        JOIN beds bd ON b.bed_number = bd.id
        WHERE rsr.other_user_id = %s AND rsr.status = 'pending'
    """, (default_trimester_id, user_id))
    pending_swaps = cur.fetchall()

    cur.close()

    # Render the template with booking information and default trimester
    return render_template(
        'room_setting.html',
        booking=booking,
        pending_swaps=pending_swaps,
        default_trimester=default_trimester
    )

# Select Trimester Route
@main.route('/student/select_trimester', methods=['GET', 'POST'])
@student_required
@survey_required
def select_trimester():
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM trimester WHERE is_default = 1")
    trimester = cur.fetchone()
    cur.close()

    if request.method == 'POST' and trimester:
        session['trimester_id'] = trimester['id']
        return redirect(url_for('choose_mode'))

    return render_template('select_trimester.html', trimester=trimester)

# Mode selection route (Individual or Group)
@main.route('/student/choose_mode', methods=['GET', 'POST'])
@student_required
def choose_mode():    
    if 'trimester_id' not in session:
        return redirect(url_for('select_trimester'))
    
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT group_id FROM group_members WHERE user_id = %s AND trimester_id = %s", (user_id, trimester_id))
    user_group = cur.fetchone()
    
    if user_group:
        session['group_id'] = user_group['group_id']
        return redirect(url_for('manage_group', group_id=user_group['group_id']))

    if request.method == 'POST':
        mode = request.form['mode']
        if mode == 'individual':
            session['group_id'] = None
            return redirect(url_for('select_hostel', mode='individual'))
        elif mode == 'group':
            cur.execute("SELECT group_id FROM group_members WHERE user_id = %s AND trimester_id = %s", (user_id, trimester_id))
            user_group = cur.fetchone()
            if user_group:
                session['group_id'] = user_group['group_id']
            return redirect(url_for('group_page'))

    cur.close()
    return render_template('choose_mode.html')

# Group page route (Create or Join Group)
@main.route('/student/group', methods=['GET', 'POST'])
@student_required
def group_page():
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM `groups` WHERE leader_id = %s AND trimester_id = %s", (user_id, trimester_id))
    group = cur.fetchone()
    cur.close()

    if group:
        return redirect(url_for('manage_group', group_id=group['group_id']))
    
    if request.method == 'POST':
        group_action = request.form['group_action']
        
        if group_action == 'create':
            group_name = request.form['group_name']
            profile_pic = request.files.get('profile_pic')

            cur = mysql.connection.cursor()

            if profile_pic:
                profile_pic_path = os.path.join(main.config['UPLOAD_FOLDER'], profile_pic.filename)
                profile_pic.save(profile_pic_path)
                profile_pic_url = url_for('static', filename=f"uploads/{profile_pic.filename}")
            else:
                profile_pic_url = None

            cur.execute(
                "INSERT INTO `groups`(leader_id, trimester_id, name, profile_pic) VALUES(%s, %s, %s, %s)", 
                (user_id, trimester_id, group_name, profile_pic_url)
            )
            mysql.connection.commit()
            group_id = cur.lastrowid

            cur.execute("INSERT INTO group_members(group_id, user_id, trimester_id) VALUES(%s, %s, %s)", (group_id, user_id, trimester_id))
            mysql.connection.commit()
            cur.close()

            session['group_id'] = group_id
            return redirect(url_for('manage_group', group_id=group_id))

    return render_template('group_page.html')

# Edit Group
@main.route('/student/edit_group/<int:group_id>', methods=['GET', 'POST'])
@student_required
def edit_group(group_id):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id') 

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        SELECT * FROM `groups` 
        WHERE group_id = %s AND leader_id = %s AND trimester_id = %s
    """, (group_id, user_id, trimester_id))
    
    group = cur.fetchone()
    if not group:
        return redirect(url_for('group_page'))

    if request.method == 'POST':
        group_name = request.form['group_name']
        profile_pic = request.files.get('profile_pic')

        if profile_pic:
            profile_pic_path = os.path.join(main.config['UPLOAD_FOLDER'], profile_pic.filename)
            profile_pic.save(profile_pic_path)
            profile_pic_url = url_for('static', filename=f"uploads/{profile_pic.filename}")
        else:
            profile_pic_url = group['profile_pic']

        cur.execute("""
            UPDATE `groups`
            SET name = %s, profile_pic = %s
            WHERE group_id = %s AND leader_id = %s AND trimester_id = %s
        """, (group_name, profile_pic_url, group_id, user_id, trimester_id))

        mysql.connection.commit()
        cur.close()

        return redirect(url_for('manage_group', group_id=group_id))

    cur.close()
    return render_template('group_edit.html', group=group)

# Manage Group route with student filtering and suggested roommate
@main.route('/student/manage_group/<int:group_id>', methods=['GET', 'POST'])
@student_required
def manage_group(group_id):
    user_id = session.get('id')
    trimester_id = request.args.get('trimester_id') or session.get('trimester_id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Check if user is the group leader or a member of the group
    cur.execute("""
        SELECT * FROM `groups` 
        WHERE group_id = %s AND leader_id = %s AND trimester_id = %s
    """, (group_id, user_id, trimester_id))
    group = cur.fetchone()

    cur.execute("""
        SELECT users.id, users.email FROM users 
        JOIN group_members ON users.id = group_members.user_id 
        WHERE group_members.group_id = %s AND group_members.user_id = %s AND group_members.trimester_id = %s
    """, (group_id, user_id, trimester_id))
    is_group_member = cur.fetchone()

    if not group and not is_group_member:
        return redirect(url_for('group_page'))

    cur.execute("SELECT * FROM `groups` WHERE group_id = %s AND trimester_id = %s", (group_id, trimester_id))
    group = cur.fetchone()

    is_leader = group['leader_id'] == user_id

    cur.execute("SELECT gender FROM users WHERE id = %s", (group['leader_id'],))
    leader_gender = cur.fetchone()['gender']

    cur.execute("""
        SELECT users.id, users.email, users.name, users.faculty, users.gender,
               CASE WHEN users.id = groups.leader_id THEN 1 ELSE 0 END as is_leader
        FROM users 
        JOIN group_members ON users.id = group_members.user_id 
        JOIN `groups` ON group_members.group_id = groups.group_id
        WHERE group_members.group_id = %s AND group_members.trimester_id = %s
    """, (group_id, trimester_id))
    members = cur.fetchall()

    students = None
    if request.method == 'POST':
        if 'suggest_roommates' in request.form:
            # Get the current user's ratings
            cur.execute("SELECT rating FROM user_ratings WHERE user_id = %s ORDER BY question_id", (user_id,))
            user_ratings = [rating['rating'] for rating in cur.fetchall()]

            # Get all other users of the same gender who are not in the group, not in any other group in the same trimester, and haven't made a booking
            cur.execute("""
                SELECT u.id, u.name, u.faculty, u.gender
                FROM users u
                LEFT JOIN group_members gm ON u.id = gm.user_id AND gm.trimester_id = %s
                LEFT JOIN booking b ON u.id = b.user_id AND b.trimester_id = %s
                WHERE u.gender = %s
                AND u.id != %s
                AND (gm.group_id IS NULL OR gm.trimester_id != %s)  -- Ensure not part of any group in the same trimester
                AND b.user_id IS NULL
            """, (trimester_id, trimester_id, leader_gender, user_id, trimester_id))
            potential_roommates = cur.fetchall()

            students = []
            for roommate in potential_roommates:
                cur.execute("SELECT rating FROM user_ratings WHERE user_id = %s ORDER BY question_id", (roommate['id'],))
                roommate_ratings = [rating['rating'] for rating in cur.fetchall()]
                
                if len(user_ratings) == len(roommate_ratings):
                    similarity = calculate_similarity(user_ratings, roommate_ratings)
                    roommate['similarity'] = round(similarity, 2)
                    students.append(roommate)

            # Sort by similarity (highest first) and take top 1
            students = sorted(students, key=lambda x: x['similarity'], reverse=True)[:1]

        elif 'filter_student_id' in request.form:
            filter_student_id = request.form.get('filter_student_id')
            if filter_student_id:
                cur.execute("""
                    SELECT u.id, u.name, u.faculty, u.gender
                    FROM users u
                    LEFT JOIN group_members gm ON u.id = gm.user_id AND gm.trimester_id = %s
                    LEFT JOIN booking b ON u.id = b.user_id AND b.trimester_id = %s
                    WHERE u.id = %s
                    AND u.gender = %s
                    AND u.id != %s
                    AND (gm.group_id IS NULL OR gm.trimester_id != %s)  -- Ensure not part of any group in the same trimester
                    AND b.user_id IS NULL
                """, (trimester_id, trimester_id, filter_student_id, leader_gender, user_id, trimester_id))
                students = cur.fetchall()

                if students:
                    # Calculate similarity for the found student
                    cur.execute("SELECT rating FROM user_ratings WHERE user_id = %s ORDER BY question_id", (user_id,))
                    user_ratings = [rating['rating'] for rating in cur.fetchall()]

                    cur.execute("SELECT rating FROM user_ratings WHERE user_id = %s ORDER BY question_id", (students[0]['id'],))
                    student_ratings = [rating['rating'] for rating in cur.fetchall()]

                    if len(user_ratings) == len(student_ratings):
                        similarity = calculate_similarity(user_ratings, student_ratings)
                        students[0]['similarity'] = round(similarity, 2)
                    else:
                        students[0]['similarity'] = 0
            else:
                students = []

    cur.close()

    return render_template('manage_group.html', members=members, group_id=group_id, group_name=group['name'], students=students, is_leader=is_leader, current_user_id=user_id, leader_gender=leader_gender)

# Leave Group
@main.route('/student/leave_group/<int:group_id>', methods=['POST'])
@student_required
def leave_group(group_id):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id') 

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        SELECT leader_id FROM `groups` 
        WHERE group_id = %s AND trimester_id = %s
    """, (group_id, trimester_id))

    group = cur.fetchone()
    if not group:
        return redirect(url_for('group_page'))

    cur.execute("""
        DELETE FROM group_members 
        WHERE group_id = %s AND user_id = %s AND trimester_id = %s
    """, (group_id, user_id, trimester_id))
    mysql.connection.commit()
    
    cur.execute("""
        SELECT COUNT(*) as count FROM group_members 
        WHERE group_id = %s AND trimester_id = %s
    """, (group_id, trimester_id))
    
    member_count = cur.fetchone()['count']
    
    if member_count == 0:
        cur.execute("""
            DELETE FROM `groups` 
            WHERE group_id = %s AND trimester_id = %s
        """, (group_id, trimester_id))
        mysql.connection.commit()

    cur.close()
    return redirect(url_for('choose_mode'))

@main.route('/student/invite_user/<int:group_id>/<int:invitee_id>', methods=['POST'])
@student_required
def invite_user(group_id, invitee_id):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    cur = mysql.connection.cursor()

    # Check if the invitee already has a pending or accepted invitation in the same trimester
    cur.execute("""
        SELECT status 
        FROM invitations 
        WHERE invitee_id = %s AND trimester_id = %s AND (status = 'pending' OR status = 'accepted')
    """, (invitee_id, trimester_id))
    
    existing_invitation = cur.fetchone()

    if existing_invitation:
        flash('This user is already part of a group or has a pending invitation in this trimester.', 'info')
        return redirect(url_for('manage_group', group_id=group_id))

    # If no pending or accepted invitation, send a new invitation
    cur.execute("""
        INSERT INTO invitations (group_id, inviter_id, invitee_id, status, trimester_id)
        VALUES (%s, %s, %s, 'pending', %s)
    """, (group_id, user_id, invitee_id, trimester_id))
    
    mysql.connection.commit()
    cur.close()

    flash('Invitation sent successfully!', 'success')
    return redirect(url_for('manage_group', group_id=group_id))

# Accept the invitation
@main.route('/student/accept_invite/<int:invitation_id>', methods=['POST'])
@student_required
def accept_invite(invitation_id):
    user_id = session.get('id')  # User B (invitee)
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Update invitation status to 'accepted'
    cur.execute("""
        UPDATE invitations
        SET status = 'accepted'
        WHERE invitation_id = %s AND invitee_id = %s
    """, (invitation_id, user_id))

    # Fetch group_id and trimester_id from the invitation
    cur.execute("SELECT group_id, trimester_id FROM invitations WHERE invitation_id = %s", (invitation_id,))
    invitation = cur.fetchone()

    # Add user to the group members for the correct trimester
    cur.execute("""
        INSERT INTO group_members (group_id, user_id, trimester_id)
        VALUES (%s, %s, %s)
    """, (invitation['group_id'], user_id, invitation['trimester_id']))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('manage_group', group_id=invitation['group_id'], trimester_id=invitation['trimester_id']))

# Decline the invitation
@main.route('/student/decline_invite/<int:invitation_id>', methods=['POST'])
@student_required
def decline_invite(invitation_id):
    user_id = session.get('id')  # User B (invitee)

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch group_id and trimester_id from the invitation
    cur.execute("SELECT group_id, trimester_id FROM invitations WHERE invitation_id = %s", (invitation_id,))
    invitation = cur.fetchone()

    # Update invitation status to 'declined' for the correct trimester
    cur.execute("""
        UPDATE invitations
        SET status = 'declined'
        WHERE invitation_id = %s AND invitee_id = %s AND trimester_id = %s
    """, (invitation_id, user_id, invitation['trimester_id']))

    mysql.connection.commit()
    cur.close()

    return redirect(url_for('home'))

# Select Hostel Route
@main.route('/student/select_hostel/<mode>', methods=['GET', 'POST'])
@student_required
def select_hostel(mode):
    user_id = session.get('id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Get user's gender
    cur.execute("SELECT gender FROM users WHERE id = %s", (user_id,))
    user_gender = cur.fetchone()['gender']

    # Get hostels matching the user's gender
    cur.execute("SELECT * FROM hostel WHERE gender = %s", (user_gender,))
    hostels = cur.fetchall()

    if request.method == 'POST':
        selected_hostel_id = request.form.get('hostel')
        if selected_hostel_id:
            hostel_id = int(selected_hostel_id)
            session['hostel_id'] = hostel_id
            return redirect(url_for('select_room_type', mode=mode, hostel_id=hostel_id))

    cur.close()
    return render_template('select_hostel.html', mode=mode, hostels=hostels)

# Select Room Type Route
@main.route('/student/select_room_type/<mode>/<int:hostel_id>', methods=['GET', 'POST'])
@student_required
def select_room_type(mode, hostel_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    trimester_id = session.get('trimester_id')

    if mode == 'individual':
        cur.execute("""
            SELECT r.*, COUNT(b.id) as total_beds, 
            SUM(CASE WHEN b.id NOT IN (
                SELECT bed_number FROM booking 
                WHERE trimester_id = %s AND hostel_id = %s
            ) THEN 1 ELSE 0 END) as available_beds
            FROM rooms r
            LEFT JOIN beds b ON r.number = b.room_number
            WHERE r.hostel_id = %s
            GROUP BY r.number
            HAVING available_beds > 0
        """, (trimester_id, hostel_id, hostel_id))
    elif mode == 'group':
        group_id = session.get('group_id')
        cur.execute("SELECT COUNT(*) as count FROM group_members WHERE group_id = %s", (group_id,))
        group_size = cur.fetchone()['count']
        cur.execute("""
            SELECT r.*, COUNT(b.id) as total_beds, 
            SUM(CASE WHEN b.id NOT IN (
                SELECT bed_number FROM booking 
                WHERE trimester_id = %s AND hostel_id = %s
            ) THEN 1 ELSE 0 END) as available_beds
            FROM rooms r
            LEFT JOIN beds b ON r.number = b.room_number
            WHERE r.hostel_id = %s
            GROUP BY r.number
            HAVING available_beds >= %s
        """, (trimester_id, hostel_id, hostel_id, group_size))
    
    available_rooms = cur.fetchall()

    if request.method == 'POST':
        selected_room = request.form.get('room_number')
        if selected_room:
            return redirect(url_for('select_bed', mode=mode, hostel_id=hostel_id, room_type=available_rooms[0]['category'], selected_room=selected_room))

    cur.close()
    return render_template('select_room_type.html', mode=mode, hostel_id=hostel_id, available_rooms=available_rooms, group_id=session.get('group_id'))

# Select Bed Route
@main.route('/student/select_bed/<mode>/<int:hostel_id>/<room_type>', methods=['GET', 'POST'])
@student_required
def select_bed(mode, hostel_id, room_type):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    selected_room = request.args.get('selected_room')
    if not selected_room:
        return redirect(url_for('select_room_type', mode=mode, hostel_id=hostel_id))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    cur.execute("SELECT * FROM rooms WHERE number = %s", (selected_room,))
    room_info = cur.fetchone()

    cur.execute("""
        SELECT * FROM beds 
        WHERE room_number = %s 
        AND id NOT IN (
            SELECT bed_number FROM booking 
            WHERE trimester_id = %s AND room_no = %s
        )
    """, (selected_room, trimester_id, selected_room))
    available_beds = cur.fetchall()

    group_id = session.get('group_id')
    
    if mode == 'group' and group_id:
        cur.execute("""
            SELECT users.id, users.name, users.email 
            FROM users 
            JOIN group_members ON users.id = group_members.user_id 
            WHERE group_members.group_id = %s
        """, (group_id,))
        group_members = cur.fetchall()
    elif mode == 'individual':
        cur.execute("SELECT id, name, email FROM users WHERE id = %s", (user_id,))
        current_user = cur.fetchone()
        group_members = [current_user] if current_user else []
    else:
        group_members = []

    assigned_users = []

    if request.method == 'POST':
        bed_assignments = {}
        for bed in available_beds:
            assigned_user_id = request.form.get(f'user_for_bed_{bed["id"]}')
            if assigned_user_id:
                bed_assignments[bed['id']] = int(assigned_user_id)
                assigned_users.append(str(assigned_user_id))

        if bed_assignments:
            bed_ids = ','.join(map(str, bed_assignments.keys()))
            user_ids = ','.join(map(str, bed_assignments.values()))
            return redirect(url_for('booking_summary', mode=mode, hostel_id=hostel_id, 
                                    room_type=room_type, room_number=selected_room, 
                                    bed_ids=bed_ids, user_ids=user_ids))
        
    cur.close()
        
    return render_template('select_bed.html', mode=mode, hostel_id=hostel_id, room_type=room_type, 
                            selected_room=selected_room, beds=available_beds, 
                            group_members=group_members, room_info=room_info, assigned_users=assigned_users)

# Booking Confirmation
@main.route('/student/booking_summary/<mode>/<int:hostel_id>/<room_type>/<int:room_number>/<bed_ids>/<user_ids>', methods=['GET', 'POST'])
@student_required
def booking_summary(mode, hostel_id, room_type, room_number, bed_ids, user_ids):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM rooms WHERE number = %s", (room_number,))
    room_info = cur.fetchone()
    
    cur.execute("SELECT * FROM hostel WHERE id = %s", (hostel_id,))
    hostel_info = cur.fetchone()

    bed_id_list = bed_ids.split(',')
    user_id_list = user_ids.split(',')
    bed_assignments = []
    group_id = session.get('group_id') if mode == 'group' else None

    for bed_id, assigned_user_id in zip(bed_id_list, user_id_list):
        cur.execute("SELECT * FROM beds WHERE id = %s", (bed_id,))
        bed_info = cur.fetchone()
        
        cur.execute("SELECT * FROM users WHERE id = %s", (assigned_user_id,))
        user_info = cur.fetchone()
        
        bed_assignments.append({
            'bed': bed_info,
            'user': user_info if user_info else {'id': user_id, 'name': 'You'}
        })

    booking_details = {
        'hostel_name': hostel_info['name'],
        'room_number': room_number,
        'room_type': room_type,
        'price': room_info['price'],
        'bed_assignments': bed_assignments
    }

    if request.method == 'POST':
        for assignment in bed_assignments:
            cur.execute(
                "INSERT INTO booking(user_id, trimester_id, group_individual, group_id, hostel_id, room_no, bed_number, cost) "
                "VALUES(%s, %s, %s, %s, %s, %s, %s, %s)",
                (assignment['user']['id'], trimester_id, 1 if mode == 'group' else 0, group_id, hostel_id, room_number, assignment['bed']['id'], room_info['price'])
            )

        # Note: room occupancy is derived from bookings elsewhere; no need to maintain rooms.status here.

        mysql.connection.commit()
        cur.close()

        return render_template('booking_success.html')

    cur.close()

    return render_template('booking_summary.html', booking_details=booking_details, mode=mode, hostel_id=hostel_id, room_type=room_type, room_number=room_number, bed_ids=bed_ids)

# Transfer Leadership
@main.route('/student/transfer_leadership/<int:group_id>/<int:new_leader_id>', methods=['POST'])
@student_required
def transfer_leadership(group_id, new_leader_id):
    trimester_id = session.get('trimester_id')
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT leader_id FROM `groups` WHERE group_id = %s AND trimester_id = %s", (group_id, trimester_id))

    cur.execute("UPDATE `groups` SET leader_id = %s WHERE group_id = %s AND trimester_id = %s", (new_leader_id, group_id, trimester_id))
    mysql.connection.commit()
    cur.close()

    session['group_id'] = group_id

    return redirect(url_for('manage_group', group_id=group_id))

# Remove Member
@main.route('/student/remove_member/<int:group_id>/<int:member_id>', methods=['POST'])
@student_required
def remove_member(group_id, member_id):
    trimester_id = session.get('trimester_id')
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("DELETE FROM group_members WHERE group_id = %s AND user_id = %s AND trimester_id = %s", (group_id, member_id, trimester_id))
    mysql.connection.commit()
    cur.close()

    session['group_id'] = group_id

    return redirect(url_for('manage_group', group_id=group_id))

# Disband Group
@main.route('/student/disband_group/<int:group_id>', methods=['POST'])
@student_required
def disband_group(group_id):
    user_id = session.get('id')
    trimester_id = session.get('trimester_id')

    session.pop('group_id', None)
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT * FROM `groups` WHERE group_id = %s AND leader_id = %s AND trimester_id = %s", (group_id, user_id, trimester_id))

    cur.execute("DELETE FROM invitations WHERE group_id = %s AND trimester_id = %s", (group_id, trimester_id))
    cur.execute("DELETE FROM group_members WHERE group_id = %s AND trimester_id = %s", (group_id, trimester_id))
    cur.execute("DELETE FROM `groups` WHERE group_id = %s AND trimester_id = %s", (group_id, trimester_id))
    
    mysql.connection.commit()
    cur.close()

    return redirect(url_for('choose_mode'))

# Survey Start Route
@main.route('/student/survey', methods=['GET', 'POST'])
@student_required
def survey():
    user_id = session['id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Check if the user has already completed the survey
    cursor.execute("SELECT survey_completed FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if user['survey_completed'] == 1:
        return render_template('survey_completed.html')

    if request.method == 'POST':
        # Get the first section
        cursor.execute("SELECT id FROM ques_sections ORDER BY id ASC LIMIT 1")
        first_section = cursor.fetchone()
        if first_section:
            return redirect(url_for('survey_questions', section_id=first_section['id']))
    
    return render_template('survey_start.html')

# Answer Survey Route
@main.route('/student/rate/<int:section_id>', methods=['GET', 'POST'])
@student_required
def survey_questions(section_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get all questions for the current section
    cursor.execute("SELECT * FROM questions WHERE section_id = %s", (section_id,))
    questions = cursor.fetchall()

    # Get section name
    cursor.execute("SELECT name FROM ques_sections WHERE id = %s", (section_id,))
    section = cursor.fetchone()
    section_name = section['name'] if section else "Unknown Section"

    # Check if this is the last section
    cursor.execute("SELECT id FROM ques_sections WHERE id > %s ORDER BY id ASC LIMIT 1", (section_id,))
    next_section = cursor.fetchone()
    is_last_section = next_section is None

    if request.method == 'POST':
        # Store ratings for all questions in the section
        for question in questions:
            rating = request.form.get(f'rating_{question["id"]}')
            if rating:
                cursor.execute("""
                    INSERT INTO user_ratings (user_id, question_id, rating) 
                    VALUES (%s, %s, %s) 
                    ON DUPLICATE KEY UPDATE rating = %s
                """, (session['id'], question['id'], rating, rating))
        mysql.connection.commit()

        if is_last_section:
            return redirect(url_for('save_survey'))
        else:
            return redirect(url_for('survey_questions', section_id=next_section['id']))

    return render_template('survey_questions.html', 
                           questions=questions, 
                           section_name=section_name,
                           section_id=section_id,
                           is_last_section=is_last_section)

# Done Survey Route
@main.route('/student/survey_done')
@student_required
def save_survey():
    user_id = session['id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Mark the survey as completed for this user
    cursor.execute("UPDATE users SET survey_completed = 1 WHERE id = %s", (user_id,))
    mysql.connection.commit()
    
    return render_template('survey_success.html')

# Get User Ratings
def get_user_ratings(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT rating FROM user_ratings WHERE user_id = %s ORDER BY question_id", (user_id,))
    ratings = cur.fetchall()
    cur.close()
    return [rating[0] for rating in ratings]

# Student Request Room Change
@main.route('/student/request_room_change', methods=['POST'])
@student_required
def request_room_change():
    user_id = session.get('id')
    trimester_id = request.form.get('trimester_id')
    reason = request.form.get('reason')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("""
        INSERT INTO room_change_requests (user_id, reason, status, trimester_id)
        VALUES (%s, %s, 'pending', %s)
    """, (user_id, reason, trimester_id))
    mysql.connection.commit()
    cur.close()
    
    flash('Your room change request has been submitted.', 'success')
    return redirect(url_for('room_setting'))

# Student Request Room Swap
@main.route('/student/request_room_swap', methods=['POST'])
@student_required
def request_room_swap():
    user_id = session.get('id')
    trimester_id = request.form.get('trimester_id')
    other_student_id = request.form.get('other_student_id')
    other_student_email = request.form.get('other_student_email')
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Check if the other student exists and has the same hostel and is in the same trimester
    # Include bed_letter for display (bed_number is the internal bed id)
    cur.execute("""
        SELECT u.id, u.email, b.hostel_id, b.room_no, b.bed_number, bb.bed_letter, b.trimester_id, t.term AS trimester_term
        FROM users u
        JOIN booking b ON u.id = b.user_id
        JOIN beds bb ON b.bed_number = bb.id
        JOIN trimester t ON b.trimester_id = t.id
        WHERE u.id = %s AND u.email = %s AND b.trimester_id = %s
    """, (other_student_id, other_student_email, trimester_id))
    other_student = cur.fetchone()
    
    if not other_student:
        flash('No student found with the given ID, email, or they are not in the same trimester.', 'error')
        return redirect(url_for('room_setting'))
    
    # Get current user's booking in the same trimester
    cur.execute("""
        SELECT hostel_id, room_no, bed_number, t.term AS trimester_term
        FROM booking b
        JOIN trimester t ON b.trimester_id = t.id
        WHERE user_id = %s AND b.trimester_id = %s
        ORDER BY b.booking_no DESC
        LIMIT 1
    """, (user_id, trimester_id))
    current_booking = cur.fetchone()
    
    if not current_booking:
        flash('Your booking is not found for the current trimester.', 'error')
        return redirect(url_for('room_setting'))
    
    if current_booking['hostel_id'] != other_student['hostel_id']:
        flash('Room swap is only allowed within the same hostel.', 'error')
        return redirect(url_for('room_setting'))
    
    trimester_term = current_booking['trimester_term']
    
    cur.close()

    return render_template('confirm_room_swap.html', other_student=other_student, trimester_term=trimester_term, trimester_id=trimester_id)

# Student Confirm Room Swap
@main.route('/student/confirm_room_swap', methods=['POST'])
@student_required
def confirm_room_swap():
    user_id = session.get('id')
    trimester_id = request.form.get('trimester_id')
    other_student_id = request.form.get('other_student_id')
    reason = request.form.get('reason')

    cur = mysql.connection.cursor()
    
    cur.execute("""
        INSERT INTO room_swap_requests (user_id, other_user_id, reason, status, trimester_id)
        VALUES (%s, %s, %s, 'pending', %s)
    """, (user_id, other_student_id, reason, trimester_id))
    
    mysql.connection.commit()
    cur.close()
    
    flash('Your room swap request has been submitted.', 'success')
    return redirect(url_for('room_setting'))

# Student Respond to Swap
@main.route('/student/respond_to_swap', methods=['POST'])
@student_required
def respond_to_swap():
    user_id = session.get('id')
    trimester_id = request.form.get('trimester_id')  # Fetch trimester_id from the form
    swap_request_id = request.form.get('swap_request_id')
    response = request.form.get('response')
    
    cur = mysql.connection.cursor()
    if response == 'approve':
        cur.execute("""
            UPDATE room_swap_requests
            SET status = 'approved_by_student'
            WHERE swap_id = %s AND other_user_id = %s AND trimester_id = %s
        """, (swap_request_id, user_id, trimester_id))
        flash('You have approved the room swap request. It will now be reviewed by the admin.', 'success')
    else:
        cur.execute("""
            UPDATE room_swap_requests
            SET status = 'rejected'
            WHERE swap_id = %s AND other_user_id = %s AND trimester_id = %s
        """, (swap_request_id, user_id, trimester_id))
        flash('You have rejected the room swap request.', 'info')
    
    mysql.connection.commit()
    cur.close()
    
    return redirect(url_for('room_setting'))

#########################################ADMIN#############################################

@main.route('/admin')
@admin_required
def admin_dashboard():
    admin_id = session.get('id')

    current_hour = datetime.now().hour
    if current_hour < 12:
        greeting = "Good Morning"
    elif 12 <= current_hour < 18:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    cur = mysql.connection.cursor()
    cur.execute("SELECT name FROM admin WHERE id = %s", (admin_id,))
    admin_name = cur.fetchone()[0]

    # Query to count registered students
    cur.execute("SELECT COUNT(*) FROM users")
    students = cur.fetchone()[0]

    # Query to count total rooms
    cur.execute("SELECT COUNT(*) FROM rooms")
    total_rooms = cur.fetchone()[0]

    # Query to count booked rooms
    cur.execute("""
        SELECT COUNT(DISTINCT room_no) 
        FROM booking
    """)
    booked_rooms = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM hostel")
    total_hostels = cur.fetchone()[0]

    cur.close()

    return render_template('admin_dashboard.html', students=students, total_rooms=total_rooms, booked_rooms=booked_rooms, total_hostels=total_hostels, greeting=greeting, admin_name=admin_name)

# Post Annoucement Route
@main.route('/admin/post_annoucement', methods=['GET', 'POST'])
@admin_required
def post():
    if request.method == 'POST':
        userDetails = request.form
        title = userDetails['title']
        context = userDetails['context']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO announcement(title, context) VALUES(%s  , %s)", (title, context))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('post'))
  
    return render_template('post_announcement.html')

# Admin Edit Trimester
@main.route('/admin/add_trimester', methods=['GET', 'POST'])
@admin_required
def add_trimester():
    if request.method == 'POST':
        name = request.form['trimester_name']
        term = request.form['trimester_term']
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO trimester(name, term) 
            VALUES(%s  , %s)
        """, (name, term))
        mysql.connection.commit()
        cur.close()
        flash('Trimester added successfully!', 'success')
        return redirect(url_for('add_trimester'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.close()
    return render_template('trimester_add.html')

# Admin Manage Trimesters
@main.route('/admin/manage_trimesters', methods=['GET', 'POST'])
@admin_required
def manage_trimesters():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # POST request to handle actions (set or remove default trimester)
    if request.method == 'POST':
        action = request.form.get('action')
        trimester_id = request.form.get('trimester_id')

        if action == 'set_default':
            # Check if there is already a default trimester
            cur.execute("SELECT COUNT(*) as count FROM trimester WHERE is_default = TRUE")
            default_count = cur.fetchone()['count']

            if default_count > 0:
                flash('Please remove the existing default trimester before setting a new one.', 'error')
            else:
                # Set new default
                cur.execute("UPDATE trimester SET is_default = TRUE WHERE id = %s", (trimester_id,))
                flash('Default trimester set successfully!', 'success')

            mysql.connection.commit()
            
            # Redirect to avoid the POST-Redirect-GET issue
            return redirect(url_for('manage_trimesters'))

        elif action == 'remove_default':
            cur.execute("UPDATE trimester SET is_default = FALSE WHERE is_default = TRUE")
            flash('Default trimester removed successfully!', 'success')
            mysql.connection.commit()
            return redirect(url_for('manage_trimesters'))

    # Fetch all trimesters
    cur.execute("SELECT * FROM trimester ORDER BY id")
    trimesters = cur.fetchall()

    # Get the current default trimester
    cur.execute("SELECT * FROM trimester WHERE is_default = TRUE LIMIT 1")
    default_trimester = cur.fetchone()

    cur.close()
    return render_template('trimester_manage.html', trimesters=trimesters, default_trimester=default_trimester)

# Admin Edit Trimester
@main.route('/admin/edit_trimester/<int:trimester_id>', methods=['GET', 'POST'])
@admin_required
def edit_trimester(trimester_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        term = request.form['trimester_term']
        name = request.form['trimester_name']
        cur.execute("""
            UPDATE trimester 
            SET term = %s, name = %s
            WHERE id = %s
        """, (term, name, trimester_id))
        mysql.connection.commit()
        flash('Trimester updated successfully!', 'success')
        return redirect(url_for('edit_trimester', trimester_id=trimester_id))

    cur.execute("SELECT * FROM trimester WHERE id = %s", (trimester_id,))
    trimester = cur.fetchone()
    cur.close()
    return render_template('trimester_edit.html', trimester=trimester)

# Admin Add Student
@main.route('/admin/add_student', methods=['GET', 'POST'])
@admin_required
def add_student():
    if request.method == 'POST':
        id = request.form['student_id']
        name = request.form['student_name']
        gender = request.form['gender']
        faculty = request.form['faculty']
        email = request.form['email']
        password = request.form['password']
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        cur = mysql.connection.cursor()

        cur.execute("SELECT * FROM roles WHERE SoA_id=%s", (id,))
        existing_role = cur.fetchone()

        if existing_role:
            flash('ID already exists in system.', 'error')
            cur.close()
            return redirect(url_for('add_student'))

        cur.execute("""
            INSERT INTO users (id, name, gender, faculty, email, password) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (id, name, gender, faculty, email, hashed_password))

        cur.execute("INSERT INTO roles(SoA_id, role) VALUES(%s, %s)", (id, 'user'))

        mysql.connection.commit()
        cur.close()
        flash('Student added successfully!', 'success')
        return redirect(url_for('add_student'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM users")
    students = cur.fetchall()
    cur.close()
    return render_template('student_add.html', students=students)

# Admin Manage Students
@main.route('/admin/manage_students', methods=['GET', 'POST'])
@admin_required
def manage_students():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT DISTINCT gender FROM users ORDER BY gender")
    genders = cur.fetchall()

    selected_gender = request.args.get('gender')
    filter_student_id = request.form.get('filter_student_id')

    if filter_student_id:
        cur.execute('''
            SELECT * FROM users
            WHERE id = %s
        ''', (filter_student_id,))
        students = cur.fetchall()
    elif selected_gender and selected_gender != 'all':
        cur.execute('''
            SELECT * FROM users
            WHERE gender = %s
            ORDER BY id
        ''', (selected_gender,))
        students = cur.fetchall()
    else:
        cur.execute('''
            SELECT * FROM users
            ORDER BY id
        ''')
        students = cur.fetchall()

    cur.close()

    return render_template('student_manage.html', students=students, genders=genders, selected_gender=selected_gender)

# Admin Edit Student
@main.route('/admin/edit_student/<int:student_id>', methods=['GET', 'POST'])
@admin_required
def edit_student(student_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        name = request.form['student_name']
        gender = request.form['gender']
        faculty = request.form['faculty']
        email = request.form['email']
        password = request.form['password']
        survey_completed = request.form.get('survey_completed')  # Capture survey_completed status
        
        # Update only the provided fields
        if password:
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            cur.execute("""
                UPDATE users 
                SET name = %s, gender = %s, faculty = %s, email = %s, password = %s, survey_completed = %s 
                WHERE id = %s
            """, (name, gender, faculty, email, hashed_password, survey_completed, student_id))
        else:
            cur.execute("""
                UPDATE users 
                SET name = %s, gender = %s, faculty = %s, email = %s, survey_completed = %s
                WHERE id = %s
            """, (name, gender, faculty, email, survey_completed, student_id))

        if survey_completed == '0': 
            cur.execute("DELETE FROM user_ratings WHERE user_id = %s", (student_id,))
        
        mysql.connection.commit()
        flash('Student updated successfully!', 'success')
        return redirect(url_for('manage_students'))
    
    cur.execute("SELECT * FROM users WHERE id = %s", (student_id,))
    student = cur.fetchone()
    cur.close()
    return render_template('student_edit.html', student=student)


# Admin Delete Student
@main.route('/admin/delete_student/<int:student_id>', methods=['POST'])
@admin_required
def delete_student(student_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM roles WHERE SoA_id = %s AND role = 'user'", (student_id,))
    cur.execute("DELETE FROM users WHERE id = %s", (student_id,))
    
    mysql.connection.commit()
    cur.close()
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('manage_students'))

# Add room route
@main.route('/admin/add_room', methods=['GET', 'POST'])
@admin_required
def add_room():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("SELECT id, name, gender FROM hostel")
    hostels = cur.fetchall()

    if request.method == 'POST':
        number = request.form['number']
        hostel_id = request.form['hostel_id']
        category = request.form['category']
        price = request.form['price']

        if category == 'Single':
            capacity = 1
            beds = ['A']
        elif category == 'Double':
            capacity = 2
            beds = ['A', 'B']
        elif category == 'Triple':
            capacity = 3
            beds = ['A', 'B', 'C']
            
        cur.execute("SELECT * FROM rooms WHERE number = %s AND hostel_id = %s", (number, hostel_id))
        existing_room = cur.fetchone()

        if existing_room:
            flash(f"Room number {number} already exists in this hostel.", 'error')
            return redirect(url_for('add_room'))

        try:
            cur.execute(''' 
                INSERT INTO rooms (number, hostel_id, category, capacity, price) 
                VALUES (%s, %s, %s, %s, %s) 
            ''', (number, hostel_id, category, capacity, price))

            for bed in beds:
                cur.execute(''' 
                    INSERT INTO beds (room_number, bed_letter, status) 
                    VALUES (%s, %s, %s) 
                ''', (number, bed, 'Available'))

            mysql.connection.commit()
            flash('Room and beds added successfully!', 'success')
        except mysql.connection.Error as err:
            mysql.connection.rollback()
            flash('An error occurred. Please try again.', 'error')
        finally:
            cur.close()

        return redirect(url_for('add_room'))

    return render_template('room_add.html', hostels=hostels)

    # Render template and pass hostels to the form
@main.route('/admin/edit_room/<int:room_number>', methods=['GET', 'POST'])
@admin_required
def edit_room(room_number):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch room details along with its hostel gender based on the room number
    cur.execute('''
        SELECT r.*, h.gender AS hostel_gender 
        FROM rooms r 
        JOIN hostel h ON r.hostel_id = h.id 
        WHERE r.number = %s
    ''', (room_number,))
    room = cur.fetchone()

    # Fetch only hostels with the same gender as the room's hostel
    cur.execute("SELECT id, name, gender FROM hostel WHERE gender = %s", (room['hostel_gender'],))
    hostels = cur.fetchall()

    if request.method == 'POST':
        hostel_id = request.form['hostel_id']
        category = request.form['category']
        price = request.form['price']

        # Determine the capacity based on the category
        capacity = {'Single': 1, 'Double': 2, 'Triple': 3}[category]

        try:
            # Update room details in the database
            cur.execute('''
                UPDATE rooms 
                SET hostel_id = %s, category = %s, capacity = %s, price = %s
                WHERE number = %s
            ''', (hostel_id, category, capacity, price, room_number))

            # Adjust the number of beds if the category has changed
            cur.execute("SELECT COUNT(*) as bed_count FROM beds WHERE room_number = %s", (room_number,))
            current_beds = cur.fetchone()['bed_count']

            if current_beds < capacity:
                for i in range(current_beds, capacity):
                    bed_letter = chr(65 + i)  # A, B, C
                    cur.execute('''
                        INSERT INTO beds (room_number, bed_letter, status)
                        VALUES (%s, %s, 'Available')
                    ''', (room_number, bed_letter))
            elif current_beds > capacity:
                cur.execute("DELETE FROM beds WHERE room_number = %s ORDER BY bed_letter DESC LIMIT %s", 
                            (room_number, current_beds - capacity))

            mysql.connection.commit()
            flash('Room and beds updated successfully!', 'success')
            return redirect(url_for('manage_rooms'))
        except MySQLdb.Error as err:
            mysql.connection.rollback()
            flash('An error occurred. Please try again.', 'error')

    cur.close()
    return render_template('room_edit.html', room=room, hostels=hostels)

# Admin Manage Rooms
@main.route('/admin/manage_rooms', methods=['GET', 'POST'])
@admin_required
def manage_rooms():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch all hostels for the filter dropdown
    cur.execute("SELECT id, name FROM hostel")
    hostels = cur.fetchall()

    # Determine default trimester (for occupancy calculation)
    cur.execute("SELECT id FROM trimester WHERE is_default = 1 LIMIT 1")
    default_trimester = cur.fetchone()
    default_trimester_id = default_trimester['id'] if default_trimester else None

    # Fetch rooms based on the selected hostel filter
    selected_hostel_id = request.args.get('hostel_id')

    if selected_hostel_id and selected_hostel_id != 'all':
        # If a specific hostel is selected, filter rooms by hostel_id
        if default_trimester_id:
            cur.execute('''
                SELECT rooms.*, hostel.name AS hostel_name,
                       COALESCE(occ.occupied, 0) AS occupied_count
                FROM rooms 
                JOIN hostel ON rooms.hostel_id = hostel.id 
                LEFT JOIN (
                  SELECT room_no, hostel_id, COUNT(*) AS occupied
                  FROM booking
                  WHERE trimester_id = %s
                  GROUP BY room_no, hostel_id
                ) occ ON occ.room_no = rooms.number AND occ.hostel_id = rooms.hostel_id
                WHERE rooms.hostel_id = %s
            ''', (default_trimester_id, selected_hostel_id))
        else:
            cur.execute('''
                SELECT rooms.*, hostel.name AS hostel_name,
                       COALESCE(occ.occupied, 0) AS occupied_count
                FROM rooms 
                JOIN hostel ON rooms.hostel_id = hostel.id 
                LEFT JOIN (
                  SELECT room_no, hostel_id, COUNT(*) AS occupied
                  FROM booking
                  GROUP BY room_no, hostel_id
                ) occ ON occ.room_no = rooms.number AND occ.hostel_id = rooms.hostel_id
                WHERE rooms.hostel_id = %s
            ''', (selected_hostel_id,))
    else:
        # If 'All Hostels' is selected or no hostel is selected, fetch all rooms
        if default_trimester_id:
            cur.execute('''
                SELECT rooms.*, hostel.name AS hostel_name,
                       COALESCE(occ.occupied, 0) AS occupied_count
                FROM rooms 
                JOIN hostel ON rooms.hostel_id = hostel.id
                LEFT JOIN (
                  SELECT room_no, hostel_id, COUNT(*) AS occupied
                  FROM booking
                  WHERE trimester_id = %s
                  GROUP BY room_no, hostel_id
                ) occ ON occ.room_no = rooms.number AND occ.hostel_id = rooms.hostel_id
            ''', (default_trimester_id,))
        else:
            cur.execute('''
                SELECT rooms.*, hostel.name AS hostel_name,
                       COALESCE(occ.occupied, 0) AS occupied_count
                FROM rooms 
                JOIN hostel ON rooms.hostel_id = hostel.id
                LEFT JOIN (
                  SELECT room_no, hostel_id, COUNT(*) AS occupied
                  FROM booking
                  GROUP BY room_no, hostel_id
                ) occ ON occ.room_no = rooms.number AND occ.hostel_id = rooms.hostel_id
            ''')

    rooms = cur.fetchall()
    cur.close()

    # Render the template with rooms and hostels
    return render_template('room_manage.html', rooms=rooms, hostels=hostels, selected_hostel_id=selected_hostel_id)

# Admin Delete Room
@main.route('/admin/delete_room/<int:room_number>', methods=['POST'])
@admin_required
def delete_room(room_number):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Check if the room exists
    cur.execute('SELECT * FROM rooms WHERE number = %s', (room_number,))
    room = cur.fetchone()
    
    # Delete associated beds first
    cur.execute('DELETE FROM beds WHERE room_number = %s', (room_number,))
    
    # Now delete the room
    cur.execute('DELETE FROM rooms WHERE number = %s', (room_number,))
    
    mysql.connection.commit()    
    cur.close()
    flash(f'Room {room_number} and associated beds deleted successfully!', 'success')
    return redirect(url_for('manage_rooms'))

# Admin Room Change Request Approval
@main.route('/admin/room_change_requests', methods=['GET', 'POST'])
@admin_required
def admin_room_change_requests():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Initialize user_trimester_id to None at the start
    user_trimester_id = None

    if request.method == 'POST':
        request_id = request.form.get('request_id')
        action = request.form.get('action')

        # Retrieve the trimester_id for the specific room change request
        cur.execute("""
            SELECT trimester_id
            FROM room_change_requests
            WHERE request_id = %s
        """, (request_id,))
        result = cur.fetchone()
        user_trimester_id = result['trimester_id'] if result else None

        if action == 'approve':
            new_room_no = request.form.get('new_room_no')
            new_bed_id = request.form.get('new_bed_id')

            if not new_room_no or not new_bed_id:
                flash('Please select both a room and a bed.', 'error')
                return redirect(url_for('admin_room_change_requests'))

            try:
                # Retrieve the user_id and trimester_id for the specific room change request
                cur.execute("""
                    SELECT user_id, trimester_id
                    FROM room_change_requests
                    WHERE request_id = %s
                """, (request_id,))
                result = cur.fetchone()
                user_trimester_id = result['trimester_id'] if result else None
                user_id = result['user_id'] if result else None

                if not user_id or not user_trimester_id:
                    flash('Invalid room change request.', 'error')
                    return redirect(url_for('admin_room_change_requests'))

                # Get the user's current booking for the specific trimester
                cur.execute("""
                    SELECT b.booking_no, b.trimester_id, b.room_no, b.bed_number, b.hostel_id
                    FROM booking b
                    WHERE b.user_id = %s AND b.trimester_id = %s
                    ORDER BY b.booking_no DESC
                    LIMIT 1
                """, (user_id, user_trimester_id))
                current_booking = cur.fetchone()

                if not current_booking:
                    flash('No existing booking found for this user and trimester.', 'error')
                    return redirect(url_for('admin_room_change_requests'))

                # Verify the selected bed belongs to the selected room
                cur.execute(
                    """
                    SELECT id FROM beds WHERE id = %s AND room_number = %s
                    """,
                    (new_bed_id, new_room_no),
                )
                bed_match = cur.fetchone()
                if not bed_match:
                    flash('Selected bed does not belong to the chosen room.', 'error')
                    return redirect(url_for('admin_room_change_requests'))

                # Check if the new room and bed are already booked for this trimester
                cur.execute("""
                    SELECT bk.trimester_id, bk.user_id
                    FROM booking bk
                    WHERE bk.room_no = %s AND bk.bed_number = %s AND bk.trimester_id = %s
                    LIMIT 1
                """, (new_room_no, new_bed_id, user_trimester_id))
                existing_booking = cur.fetchone()

                if existing_booking:
                    flash('The selected bed is already booked for this trimester.', 'error')
                    return redirect(url_for('admin_room_change_requests'))

                # Get the hostel_id for the new room
                cur.execute("""
                    SELECT hostel_id
                    FROM rooms
                    WHERE number = %s
                """, (new_room_no,))
                room_info = cur.fetchone()
                if not room_info:
                    flash('Invalid room number selected.', 'error')
                    return redirect(url_for('admin_room_change_requests'))

                new_hostel_id = room_info['hostel_id']

                # Proceed with updating the booking
                cur.execute("""
                    UPDATE booking
                    SET room_no = %s, bed_number = %s, hostel_id = %s
                    WHERE booking_no = %s
                """, (new_room_no, new_bed_id, new_hostel_id, current_booking['booking_no']))

                # Update the room change request status
                cur.execute("UPDATE room_change_requests SET status = 'approved' WHERE request_id = %s", (request_id,))

                # Commit transaction
                mysql.connection.commit()
                flash('Room change request approved successfully.', 'success')

            except Exception as e:
                # Rollback transaction in case of any error
                mysql.connection.rollback()
                flash(f'An error occurred: {str(e)}', 'error')

        elif action == 'reject':
            # Update the request status
            cur.execute("UPDATE room_change_requests SET status = 'rejected' WHERE request_id = %s", (request_id,))
            mysql.connection.commit()
            flash('Room change request rejected.', 'info')

    # Fetch pending room change requests
    cur.execute("""
        SELECT rcr.*, u.name, u.email, b.trimester_id, t.term as trimester_term, b.room_no, bd.bed_letter, h.name as hostel_name, h.id as hostel_id
        FROM room_change_requests rcr
        JOIN users u ON rcr.user_id = u.id
        JOIN booking b ON u.id = b.user_id
        JOIN trimester t ON b.trimester_id = t.id
        JOIN beds bd ON b.bed_number = bd.id
        JOIN hostel h ON b.hostel_id = h.id
        WHERE rcr.status = 'pending'
        ORDER BY rcr.request_id ASC
    """)
    requests = cur.fetchall()

    # Fetch available rooms and beds with the user_trimester_id
    available_rooms, available_beds = get_available_rooms_and_beds(cur, user_trimester_id)

    cur.close()

    return render_template('admin_room_change_requests.html', 
                           requests=requests, 
                           available_rooms=available_rooms, 
                           available_beds=available_beds)

def get_available_rooms_and_beds(cur, user_trimester_id=None):
    # Fetch all rooms
    cur.execute("""
        SELECT r.number, r.hostel_id, h.name as hostel_name
        FROM rooms r
        JOIN hostel h ON r.hostel_id = h.id
        ORDER BY h.name, r.number
    """)
    available_rooms = cur.fetchall()

    # Fetch beds for each room
    available_beds = {}
    for room in available_rooms:
        if user_trimester_id:
            # show beds with occupant either none or in different trimester (allow override with warning)
            cur.execute("""
                SELECT b.id as bed_id, b.bed_letter, bk.trimester_id as occupant_trimester_id
                FROM beds b
                LEFT JOIN booking bk ON b.id = bk.bed_number AND bk.room_no = b.room_number
                WHERE b.room_number = %s
                ORDER BY b.bed_letter
            """, (room['number'],))
        else:
            cur.execute("""
                SELECT b.id as bed_id, b.bed_letter, bk.trimester_id as occupant_trimester_id
                FROM beds b
                LEFT JOIN booking bk ON b.id = bk.bed_number AND bk.room_no = b.room_number
                WHERE b.room_number = %s
                ORDER BY b.bed_letter
            """, (room['number'],))
        available_beds[room['number']] = cur.fetchall()

    return available_rooms, available_beds


# Room Swap Request
@main.route('/admin/room_swap_requests')
@admin_required
def admin_room_swap_requests():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("""
        SELECT rsr.*,
               u1.name AS requester_name, u1.email AS requester_email,
               u2.name AS other_name, u2.email AS other_email,
               b1.room_no AS requester_room, bb1.bed_letter AS requester_bed,
               b2.room_no AS other_room, bb2.bed_letter AS other_bed,
               h.name AS hostel_name,
               t.term AS trimester_term
        FROM room_swap_requests rsr
        JOIN users u1 ON rsr.user_id = u1.id
        JOIN users u2 ON rsr.other_user_id = u2.id
        JOIN booking b1 ON rsr.user_id = b1.user_id AND b1.trimester_id = rsr.trimester_id
        JOIN booking b2 ON rsr.other_user_id = b2.user_id AND b2.trimester_id = rsr.trimester_id
        JOIN beds bb1 ON b1.bed_number = bb1.id
        JOIN beds bb2 ON b2.bed_number = bb2.id
        JOIN hostel h ON b1.hostel_id = h.id
        JOIN trimester t ON rsr.trimester_id = t.id
        WHERE rsr.status IN ('approved_by_student', 'pending')
        ORDER BY rsr.created_at ASC
    """)
    swap_requests = cur.fetchall()
    cur.close()
    
    return render_template('admin_room_swap_requests.html', swap_requests=swap_requests)

# Room Swap Process
@main.route('/admin/process_room_swap', methods=['POST'])
@admin_required
def process_room_swap():
    swap_request_id = request.form.get('swap_request_id')
    action = request.form.get('action')
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    if action == 'approve':
        # Fetch the swap request details
        cur.execute("""
            SELECT user_id, other_user_id
            FROM room_swap_requests
            WHERE swap_id = %s
        """, (swap_request_id,))
        swap_request = cur.fetchone()

        if swap_request:
            # Fetch current room and bed details for both users (scoped to the swap's trimester)
            cur.execute("""
                SELECT b1.room_no AS room1, b1.bed_number AS bed1,
                       b2.room_no AS room2, b2.bed_number AS bed2
                FROM booking b1
                JOIN booking b2 
                  ON b2.user_id = %s
                 AND b2.trimester_id = (SELECT trimester_id FROM room_swap_requests WHERE swap_id = %s)
                WHERE b1.user_id = %s
                  AND b1.trimester_id = (SELECT trimester_id FROM room_swap_requests WHERE swap_id = %s)
            """, (swap_request['other_user_id'], swap_request_id, swap_request['user_id'], swap_request_id))
            rooms_beds = cur.fetchone()

            if rooms_beds:
                # Swap the room and bed assignments using temp variables
                room1, bed1 = rooms_beds['room1'], rooms_beds['bed1']
                room2, bed2 = rooms_beds['room2'], rooms_beds['bed2']
                
                # Update booking for user 1
                cur.execute("""
                    UPDATE booking
                    SET room_no = %s, bed_number = %s
                    WHERE user_id = %s AND trimester_id = (
                        SELECT trimester_id FROM room_swap_requests WHERE swap_id = %s
                    )
                """, (room2, bed2, swap_request['user_id'], swap_request_id))
                
                # Update booking for user 2
                cur.execute("""
                    UPDATE booking
                    SET room_no = %s, bed_number = %s
                    WHERE user_id = %s AND trimester_id = (
                        SELECT trimester_id FROM room_swap_requests WHERE swap_id = %s
                    )
                """, (room1, bed1, swap_request['other_user_id'], swap_request_id))

                # Mark the swap request as approved
                cur.execute("""
                    UPDATE room_swap_requests
                    SET status = 'approved'
                    WHERE swap_id = %s
                """, (swap_request_id,))
                
                mysql.connection.commit()
                flash('Room swap has been approved and processed.', 'success')
            else:
                flash('Could not fetch room and bed details for both users.', 'error')
        else:
            flash('Swap request not found.', 'error')
    
    elif action == 'reject':
        # Update the swap request status
        cur.execute("""
            UPDATE room_swap_requests
            SET status = 'rejected_by_admin'
            WHERE swap_id = %s
        """, (swap_request_id,))
        
        mysql.connection.commit()
        flash('Room swap request has been rejected.', 'info')
    
    cur.close()
    return redirect(url_for('admin_room_swap_requests'))

@main.route('/admin/manage_sections', methods=['GET'])
@admin_required
def manage_sections():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM ques_sections ORDER BY id")
    sections = cur.fetchall()
    cur.close()
    return render_template('section_manage.html', sections=sections)

@main.route('/admin/manage_questions', methods=['GET', 'POST'])
@admin_required
def manage_questions():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch all sections for the dropdown
    cur.execute("SELECT * FROM ques_sections ORDER BY id")
    sections = cur.fetchall()
    
    # Fetch questions based on the selected section filter
    selected_section_id = request.form.get('section_id') if request.method == 'POST' else None

    # Fetch questions based on the selected section filter
    if selected_section_id and selected_section_id != 'all':
        # If a specific section is selected, filter questions by section_id
        cur.execute('''
            SELECT q.*, s.name as section_name 
            FROM questions q
            JOIN ques_sections s ON q.section_id = s.id 
            WHERE q.section_id = %s
            ORDER BY q.id
        ''', (selected_section_id,))
    else:
        # If 'All Sections' is selected or no section is selected, fetch all questions
        cur.execute('''
            SELECT q.*, s.name as section_name 
            FROM questions q
            JOIN ques_sections s ON q.section_id = s.id 
            ORDER BY s.id, q.id
        ''')

    questions = cur.fetchall()
    cur.close()

    return render_template('question_manage.html', sections=sections, questions=questions, selected_section_id=selected_section_id)

@main.route('/admin/add_section', methods=['GET', 'POST'])
@admin_required
def add_section():
    if request.method == 'POST':
        section_name = request.form['section_name']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO ques_sections (name) VALUES (%s)", (section_name,))
        mysql.connection.commit()
        cur.close()
        flash('Section added successfully!', 'success')
        return redirect(url_for('manage_sections'))
    return render_template('section_add.html')

@main.route('/admin/edit_section/<int:section_id>', methods=['GET', 'POST'])
@admin_required
def edit_section(section_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        section_name = request.form['section_name']
        cur.execute("UPDATE ques_sections SET name = %s WHERE id = %s", (section_name, section_id))
        mysql.connection.commit()
        flash('Section updated successfully!', 'success')
        return redirect(url_for('edit_section', section_id=section_id))
    
    cur.execute("SELECT * FROM ques_sections WHERE id = %s", (section_id,))
    section = cur.fetchone()
    cur.close()
    return render_template('section_edit.html', section=section)

@main.route('/admin/delete_section/<int:section_id>', methods=['POST'])
@admin_required
def delete_section(section_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM ques_sections WHERE id = %s", (section_id,))
    mysql.connection.commit()
    cur.close()
    flash('Section deleted successfully!', 'success')
    return redirect(url_for('manage_sections'))

@main.route('/admin/add_question', methods=['GET', 'POST'])
@admin_required
def add_question():
    if request.method == 'POST':
        section_id = request.form['section_id']
        question_text = request.form['question_text']
        
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO questions (section_id, text) 
            VALUES (%s, %s)
        """, (section_id, question_text))
        mysql.connection.commit()
        cur.close()
        flash('Question added successfully!', 'success')
        return redirect(url_for('add_question'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM ques_sections ORDER BY id")
    sections = cur.fetchall()
    cur.close()
    return render_template('question_add.html', sections=sections)

@main.route('/admin/edit_question/<int:question_id>', methods=['GET', 'POST'])
@admin_required
def edit_question(question_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        section_id = request.form['section_id']
        question_text = request.form['question_text']
        
        cur.execute("""
            UPDATE questions 
            SET section_id = %s, text = %s
            WHERE id = %s
        """, (section_id, question_text, question_id))
        mysql.connection.commit()
        flash('Question updated successfully!', 'success')
        return redirect(url_for('edit_question', question_id=question_id))
    
    cur.execute("SELECT * FROM questions WHERE id = %s", (question_id,))
    question = cur.fetchone()
    cur.execute("SELECT * FROM ques_sections ORDER BY id")
    sections = cur.fetchall()
    cur.close()
    return render_template('question_edit.html', question=question, sections=sections)

@main.route('/admin/delete_question/<int:question_id>', methods=['POST'])
@admin_required
def delete_question(question_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM questions WHERE id = %s", (question_id,))
    mysql.connection.commit()
    cur.close()
    flash('Question deleted successfully!', 'success')
    return redirect(url_for('manage_questions'))

@main.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    admin_id = session.get('id')
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM admin WHERE id = %s", (admin_id,))
    admin = cur.fetchone()
    
    # Use a default admin profile image (or extend if you add image support)
    profile_pic_url = url_for('static', filename='images/default_profile_pic.jpg')
    return render_template('admin_profile.html',
        admin_id=admin[0],
        name=admin[1],
        email=admin[2],
        profile_pic_url=profile_pic_url
    )

@main.route('/admin/change_password', methods=['GET', 'POST'])
@admin_required
def admin_change_password():
    admin_id = session.get('id')
    
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT password FROM admin WHERE id=%s", [admin_id])
        admin_data = cur.fetchone()
        cur.close()

        if admin_data and bcrypt.check_password_hash(admin_data[0], current_password):
            if new_password == confirm_password:
                hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
                cur = mysql.connection.cursor()
                cur.execute("UPDATE admin SET password=%s WHERE id=%s", (hashed_password, admin_id))
                mysql.connection.commit()
                cur.close()
                flash('Your password has been changed successfully!', 'success')
                return redirect(url_for('admin_profile'))
            else:
                flash('Passwords do not match.', 'error')
                return redirect(url_for('admin_change_password'))
        else:
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('admin_change_password'))
        
    return render_template('admin_change_password.html')

# Admin Add Admin
@main.route('/admin/add_admin', methods=['GET', 'POST'])
@admin_required
def add_admin():
    if request.method == 'POST':
        admin_id = request.form['admin_id']
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        cur = mysql.connection.cursor()

        cur.execute("SELECT * FROM roles WHERE SoA_id=%s", (admin_id,))
        existing_role = cur.fetchone()
        
        if existing_role:
            flash('ID already exists in system.', 'error')
            cur.close()
            return redirect(url_for('add_admin'))

        cur.execute("INSERT INTO admin(id, name, email, password) VALUES(%s, %s, %s, %s)", 
                    (admin_id, name, email, hashed_password))

        cur.execute("INSERT INTO roles(SoA_id, role) VALUES(%s, %s)", (admin_id, 'admin'))

        mysql.connection.commit()
        flash('Admin added successfully!', 'success')

        cur.close()

    return render_template('add_admin.html')


# Admin Manage Admins
@main.route('/admin/manage_admins', methods=['GET'])
@admin_required
def manage_admins():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM admin")
    admins = cur.fetchall()
    cur.close()
    return render_template('admin_manage.html', admins=admins)

# Admin Delete Admin
@main.route('/admin/delete_admin/<int:admin_id>', methods=['POST'])
@admin_required
def delete_admin(admin_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("DELETE FROM roles WHERE SoA_id = %s AND role = 'admin'", (admin_id,))
    cur.execute("DELETE FROM admin WHERE id = %s", (admin_id,))
    
    mysql.connection.commit()
    cur.close()
    flash('Admin deleted successfully!', 'success')
    return redirect(url_for('manage_admins'))

# Booking Listing
@main.route('/admin/booking_listing', methods=['GET'])
@admin_required
def booking_listing():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch all bookings with the bed letter (A, B, or C)
    cur.execute("""
        SELECT 
            b.booking_no,
            t.term AS trimester_term,
            u.name AS student_name,
            h.name AS hostel_name,
            b.room_no,
            bd.bed_letter
        FROM booking b
        JOIN users u ON b.user_id = u.id
        JOIN trimester t ON b.trimester_id = t.id
        JOIN hostel h ON b.hostel_id = h.id
        JOIN beds bd ON b.bed_number = bd.id
        WHERE NOT EXISTS (
            SELECT 1 FROM room_change_requests rcr
            WHERE rcr.user_id = b.user_id
              AND rcr.status = 'pending'
        )
          AND NOT EXISTS (
            SELECT 1 FROM room_swap_requests rsr
            WHERE (rsr.user_id = b.user_id OR rsr.other_user_id = b.user_id)
              AND rsr.status = 'pending'
          )
        ORDER BY b.booking_no DESC
    """)
    bookings = cur.fetchall()

    cur.close()
    return render_template('booking_listing.html', bookings=bookings)


# Delete Booking Route
@main.route('/admin/delete_booking/<int:booking_no>', methods=['POST'])
@admin_required
def delete_booking(booking_no):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Retrieve booking details based on booking_no
    cur.execute("""
        SELECT 
            b.room_no, 
            b.bed_number, 
            r.category AS room_category
        FROM booking b
        JOIN rooms r ON b.room_no = r.number
        WHERE b.booking_no = %s
    """, (booking_no,))
    booking = cur.fetchone()
    
    room_no = booking['room_no']
    
    # Delete the booking from the 'booking' table
    cur.execute("DELETE FROM booking WHERE booking_no = %s", (booking_no,))
    
    mysql.connection.commit()
    
    cur.close()

    flash('Booking successfully deleted.', 'success')
    return redirect(url_for('booking_listing'))

@main.route('/admin/add_hostel', methods=['GET', 'POST'])
@admin_required
def add_hostel():
    if request.method == 'POST':
        hostel_name = request.form['hostel_name']
        gender = request.form['gender']

        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO hostel (name, gender) VALUES (%s, %s)", (hostel_name, gender))
        mysql.connection.commit()
        cur.close()

        flash('Hostel added successfully!', 'success')
        return redirect(url_for('manage_hostels'))
    return render_template('hostel_add.html')

@main.route('/admin/manage_hostels', methods=['GET', 'POST'])
@admin_required
def manage_hostels():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch distinct genders from the hostel table for the dropdown
    cur.execute("SELECT DISTINCT gender FROM hostel ORDER BY gender")
    genders = cur.fetchall()

    # Fetch hostels based on the selected gender filter
    selected_gender = request.args.get('gender')

    if selected_gender and selected_gender != 'all':
        # If a specific gender is selected, filter hostels by gender
        cur.execute('''
            SELECT * FROM hostel
            WHERE gender = %s
            ORDER BY id
        ''', (selected_gender,))
    else:
        # If 'All Genders' is selected or no gender is selected, fetch all hostels
        cur.execute('''
            SELECT * FROM hostel
            ORDER BY id
        ''')

    hostels = cur.fetchall()
    cur.close()

    return render_template('hostel_manage.html', genders=genders, hostels=hostels, selected_gender=selected_gender)

@main.route('/admin/edit_hostel/<int:hostel_id>', methods=['GET', 'POST'])
@admin_required
def edit_hostel(hostel_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    if request.method == 'POST':
        hostel_name = request.form['hostel_name']
        gender = request.form['gender']
        
        # Update the hostel details in the database
        cur.execute("UPDATE hostel SET name = %s, gender = %s WHERE id = %s", (hostel_name, gender, hostel_id))
        mysql.connection.commit()
        flash('Hostel updated successfully!', 'success')
        return redirect(url_for('manage_hostels'))
    
    # Fetch the existing hostel details for the form
    cur.execute("SELECT * FROM hostel WHERE id = %s", (hostel_id,))
    hostel = cur.fetchone()
    cur.close()
    
    return render_template('hostel_edit.html', hostel=hostel)

@main.route('/admin/delete_hostel/<int:hostel_id>', methods=['POST'])
@admin_required
def delete_hostel(hostel_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM hostel WHERE id = %s", (hostel_id,))
    mysql.connection.commit()
    cur.close()
    flash('Hostel deleted successfully!', 'success')
    return redirect(url_for('manage_hostels'))

#####################################################################

# Logout Route
@main.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.clear()
    return redirect(url_for('index'))

if __name__ == "__main__":
    main.run(debug=True)
