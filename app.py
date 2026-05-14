from flask import Flask, render_template, Response, request, redirect, url_for, session, jsonify
from twilio.rest import Client
import cv2
import mediapipe as mp
import time
import math
import sqlite3

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# --- Twilio SMS Configuration ---
TWILIO_ACCOUNT_SID = 'ACf6b51b7d7370818458f4da2282c7a055'
TWILIO_AUTH_TOKEN = '59d299ffaeba3dba2ab8bb9bf81fbf63'
TWILIO_PHONE_NUMBER = '+12184004819'

# --- System Configuration ---
EAR_THRESH = 0.22      
MAR_THRESH = 0.50      
TIME_THRESH = 3.0      

alarm_triggered = False
camera_active = False  
last_sms_time = 0      

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True)

LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
MOUTH = [13, 14, 78, 308]

def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, emergency_contact TEXT)''')
    conn.commit()
    conn.close()

init_db()

def euclidean_distance(p1, p2): return math.dist(p1, p2)

def calculate_ear(landmarks, eye_indices):
    p2_p6 = euclidean_distance(landmarks[eye_indices[1]], landmarks[eye_indices[5]])
    p3_p5 = euclidean_distance(landmarks[eye_indices[2]], landmarks[eye_indices[4]])
    p1_p4 = euclidean_distance(landmarks[eye_indices[0]], landmarks[eye_indices[3]])
    return (p2_p6 + p3_p5) / (2.0 * p1_p4)

def calculate_mar(landmarks):
    top_bottom = euclidean_distance(landmarks[MOUTH[0]], landmarks[MOUTH[1]])
    left_right = euclidean_distance(landmarks[MOUTH[2]], landmarks[MOUTH[3]])
    return top_bottom / left_right

def send_emergency_sms(username):
    global last_sms_time
    if time.time() - last_sms_time > 60:
        if username: # session check ku badhila direct ah username check panrom
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("SELECT emergency_contact FROM users WHERE username=?", (username,))
            result = c.fetchone()
            conn.close()
            
            if result and result[0]:
                try:
                    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                    message = client.messages.create(
                        body=f"URGENT: Drowsiness detected for driver {username}. Please contact them immediately!",
                        from_=TWILIO_PHONE_NUMBER,
                        to=result[0]
                    )
                    print(f"SMS Sent to {result[0]}!")
                    last_sms_time = time.time()
                except Exception as e:
                    print("SMS Error:", e)

def generate_frames(username): # username parameter add panniyachu
    global alarm_triggered, camera_active
    cap = cv2.VideoCapture(0)
    drowsy_start_time = None
    yawn_start_time = None

    while camera_active:
        success, frame = cap.read()
        if not success: break
            
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                coords = [(int(pt.x * w), int(pt.y * h)) for pt in face_landmarks.landmark]
                
                for idx in LEFT_EYE + RIGHT_EYE + MOUTH:
                    cv2.circle(frame, coords[idx], 2, (0, 255, 0), -1)

                ear = (calculate_ear(coords, LEFT_EYE) + calculate_ear(coords, RIGHT_EYE)) / 2.0
                mar = calculate_mar(coords)

                if ear < EAR_THRESH or mar > MAR_THRESH:
                    start_timer = drowsy_start_time if ear < EAR_THRESH else yawn_start_time
                    if start_timer is None:
                        if ear < EAR_THRESH: drowsy_start_time = time.time()
                        else: yawn_start_time = time.time()
                    elif time.time() - start_timer >= TIME_THRESH:
                        alarm_triggered = True
                        send_emergency_sms(username) # ingayum username pass panrom
                        cv2.putText(frame, "WARNING! WAKE UP!", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                else:
                    drowsy_start_time = None
                    yawn_start_time = None

                if ear >= EAR_THRESH and mar <= MAR_THRESH and drowsy_start_time is None and yawn_start_time is None:
                    alarm_triggered = False

                cv2.putText(frame, f"EAR: {ear:.2f}  MAR: {mar:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    cap.release()

# --- Page Routes ---
@app.route('/')
def index():
    if 'user' in session: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
        
    username = request.form['username']
    password = request.form['password']
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    user = c.fetchone()
    conn.close()
    
    if user:
        session['user'] = username
        return redirect(url_for('dashboard'))
    return "Invalid credentials. Please go back and try again."

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
        
    username = request.form['username']
    password = request.form['password']
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, emergency_contact) VALUES (?, ?, ?)", (username, password, ""))
        conn.commit()
    except:
        return "User already exists!"
    finally:
        conn.close()
        
    session['user'] = username
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html', user=session['user'])

@app.route('/emergency', methods=['GET', 'POST'])
def emergency():
    if 'user' not in session: return redirect(url_for('login'))
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        contact = request.form['contact']
        c.execute("UPDATE users SET emergency_contact=? WHERE username=?", (contact, session['user']))
        conn.commit()
        
    c.execute("SELECT emergency_contact FROM users WHERE username=?", (session['user'],))
    contact = c.fetchone()[0]
    conn.close()
    
    return render_template('emergency.html', contact=contact)

@app.route('/predict')
def predict():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('predict.html')

# --- API Routes ---
@app.route('/video_feed')
def video_feed():
    current_user = session.get('user') 
    return Response(generate_frames(current_user), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/camera_control', methods=['POST'])
def camera_control():
    global camera_active, alarm_triggered  # Added alarm_triggered to global
    data = request.json
    
    if data['action'] == 'start':
        camera_active = True
    else:
        camera_active = False
        alarm_triggered = False  # <--- FIX: Force reset the alarm when stopped
        
    return jsonify({"status": "success", "camera_active": camera_active})

@app.route('/alarm_status')
def alarm_status():
    return jsonify({"alarm": alarm_triggered})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, threaded=True)