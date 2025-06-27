from flask import Flask, request, jsonify, render_template
import os
import json
import pandas as pd
import math
import hashlib # For password hashing

app = Flask(__name__, static_folder='static', template_folder='templates')
PROFILE_DATA_FILE = 'profile_data.json'
LOGO_FILE = 'logo.png' # This is no longer used by Python but kept for reference

# --- Helper Functions ---

def sanitize(obj):
    """
    MODIFIED: Recursively replace NaN/NaT values with None.
    The order of checks is important to prevent the ambiguous truth value error.
    """
    # First, handle collection types (dict, list) recursively.
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]

    # After handling collections, check for scalar "Not a Number" values.
    # This correctly handles float NaN, pandas NaT, etc., but avoids arrays.
    if pd.isna(obj):
        return None

    return obj

def hash_password(password):
    """Hashes a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_project_data_file(project_name):
    """Generates the filename for a project's data."""
    # Sanitize project name to be a valid filename
    safe_project_name = "".join(c for c in project_name if c.isalnum() or c in (' ', '_')).rstrip()
    return f"{safe_project_name.replace(' ', '_')}_data.json"

def initialize_profile_data():
    """Initializes the profile data file if it doesn't exist."""
    if not os.path.exists(PROFILE_DATA_FILE):
        super_admin_email = "aashutosh.aggarwal@adventz.com"
        # In a real app, this password would be set securely, not hardcoded.
        super_admin_password = hash_password("Simon#123")
        
        initial_data = {
            "users": [
                {
                    "email": super_admin_email,
                    "password": super_admin_password,
                    "role": "super_admin",
                    "status": "approved"
                }
            ],
            "projects": []
        }
        with open(PROFILE_DATA_FILE, 'w') as f:
            json.dump(initial_data, f, indent=4)


def build_task_hierarchy(df):
    """
    Builds a nested list of tasks from a DataFrame based on WBS numbers.
    """
    tasks_by_wbs = {}
    top_level_tasks = []

    # Map CSV columns to the keys expected by the frontend
    column_mapping = {
        'WBS': ['WBS', 'Activity ID', 'ID'],
        'Name': ['Name', 'Task Name', 'Activity Name'],
        'Duration': ['Duration'],
        'Start_Date': ['Start', 'start', 'Start_Date'],
        'Finish_Date': ['Finish', 'finish', 'Finish_Date'],
        'Predecessors': ['Predecessors', 'predecessors'],
        'Notes': ['Notes']
    }

    # Normalize DataFrame columns
    for target_key, possible_names in column_mapping.items():
        for name in possible_names:
            if name in df.columns:
                df.rename(columns={name: target_key}, inplace=True)
                break
    
    # First pass: create all task objects and map them by WBS
    for _, row in df.iterrows():
        if pd.isna(row.get('WBS')):
            continue
            
        wbs_str = str(row.get('WBS'))
        
        task = {
            'id': wbs_str,
            'wbs': wbs_str,
            'taskName': row.get('Name'),
            'plannedStartDate': row.get('Start_Date'),
            'plannedEndDate': row.get('Finish_Date'),
            'predecessorString': row.get('Predecessors', ''),
            'originalDurationDays': row.get('Duration'),
            'notes': [{'text': row.get('Notes'), 'timestamp': pd.Timestamp.now().isoformat(), 'source': 'import'}] if pd.notna(row.get('Notes')) else [],
            'actualStartDate': None,
            'actualEndDate': None,
            'progress': 0,
            'status': 'Not Started',
            'isClientDeliverable': False,
            'isCritical': False,
            'dependencies': [],
            'clientComments': [],
            'delayWeatherDays': 0,
            'delayContractorDays': 0,
            'delayClientDays': 0,
            'isExpanded': True,
            'subtasks': []
        }
        tasks_by_wbs[task['wbs']] = task

    # Second pass: build the hierarchy by linking tasks to their parents
    sorted_wbs_keys = sorted(tasks_by_wbs.keys())
    for wbs in sorted_wbs_keys:
        task = tasks_by_wbs[wbs]
        parent_wbs = '.'.join(wbs.split('.')[:-1])
        if parent_wbs and parent_wbs in tasks_by_wbs:
            tasks_by_wbs[parent_wbs]['subtasks'].append(task)
        else:
            top_level_tasks.append(task)

    return top_level_tasks


# --- API Endpoints ---

@app.route('/api/signup', methods=['POST'])
def admin_signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    with open(PROFILE_DATA_FILE, 'r+') as f:
        profiles = json.load(f)
        if any(user['email'] == email for user in profiles['users']):
            return jsonify({"status": "error", "message": "This email is already registered."}), 409
        
        new_admin = {
            "email": email,
            "password": hash_password(password),
            "role": "admin",
            "status": "pending"
        }
        profiles['users'].append(new_admin)
        f.seek(0)
        json.dump(profiles, f, indent=4)
        f.truncate()

    return jsonify({"status": "success", "message": "Signup successful! A Super Admin has been notified to approve your account."})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    login_type = data.get('type')
    
    with open(PROFILE_DATA_FILE, 'r') as f:
        profiles = json.load(f)

    if login_type == 'admin':
        email = data.get('email')
        password = data.get('password')
        hashed_pass = hash_password(password)
        
        for user in profiles['users']:
            if user['email'] == email and user['password'] == hashed_pass:
                if user['status'] == 'approved':
                    return jsonify({"status": "success", "userType": user['role'], "email": user['email']})
                elif user['status'] == 'pending':
                    return jsonify({"status": "error", "message": "Your account is pending approval."}), 403
        return jsonify({"status": "error", "message": "Invalid admin credentials."}), 401

    elif login_type == 'client':
        access_code = data.get('access_code')
        for project in profiles['projects']:
            if project['client_access_code'] == access_code:
                return jsonify({"status": "success", "userType": "client", "project": project['name']})
        return jsonify({"status": "error", "message": "Invalid Client Access Code."}), 401
        
    return jsonify({"status": "error", "message": "Invalid login type."}), 400

@app.route('/api/pending_admins', methods=['GET'])
def get_pending_admins():
    with open(PROFILE_DATA_FILE, 'r') as f:
        profiles = json.load(f)
    pending = [user for user in profiles['users'] if user.get('status') == 'pending']
    return jsonify(pending)

@app.route('/api/approve_admin', methods=['POST'])
def approve_admin():
    data = request.get_json()
    email_to_approve = data.get('email')
    if not email_to_approve:
        return jsonify({"status": "error", "message": "Email is required for approval."}), 400
    
    with open(PROFILE_DATA_FILE, 'r+') as f:
        profiles = json.load(f)
        user_found = False
        for user in profiles['users']:
            if user['email'] == email_to_approve and user.get('status') == 'pending':
                user['status'] = 'approved'
                user_found = True
                break
        
        if not user_found:
            return jsonify({"status": "error", "message": "User not found or already approved."}), 404
            
        f.seek(0)
        json.dump(profiles, f, indent=4)
        f.truncate()
        
    return jsonify({"status": "success", "message": f"Admin '{email_to_approve}' has been approved."})

@app.route('/api/reject_admin', methods=['POST'])
def reject_admin():
    data = request.get_json()
    email_to_reject = data.get('email')
    if not email_to_reject:
        return jsonify({"status": "error", "message": "Email is required for rejection."}), 400
    
    with open(PROFILE_DATA_FILE, 'r+') as f:
        profiles = json.load(f)
        
        original_user_count = len(profiles['users'])
        profiles['users'] = [user for user in profiles['users'] if not (user['email'] == email_to_reject and user.get('status') == 'pending')]
        
        if len(profiles['users']) == original_user_count:
            return jsonify({"status": "error", "message": "User not found or not in a pending state."}), 404
            
        f.seek(0)
        json.dump(profiles, f, indent=4)
        f.truncate()
        
    return jsonify({"status": "success", "message": f"Admin request for '{email_to_reject}' has been rejected and removed."})


@app.route('/api/projects', methods=['GET', 'POST'])
def manage_projects():
    with open(PROFILE_DATA_FILE, 'r+') as f:
        profiles = json.load(f)
        
        if request.method == 'GET':
            return jsonify(profiles.get('projects', []))

        if request.method == 'POST':
            data = request.get_json()
            project_name = data.get('project_name')
            client_access_code = data.get('client_access_code')

            if not project_name or not client_access_code:
                return jsonify({"status": "error", "message": "Project Name and Client Access Code are required."}), 400

            if any(p['name'] == project_name for p in profiles['projects']):
                return jsonify({"status": "error", "message": "A project with this name already exists."}), 409
            
            if any(p['client_access_code'] == client_access_code for p in profiles['projects']):
                return jsonify({"status": "error", "message": "This client access code is already in use."}), 409

            new_project = {
                "name": project_name,
                "client_access_code": client_access_code
            }
            profiles['projects'].append(new_project)
            f.seek(0)
            json.dump(profiles, f, indent=4)
            f.truncate()

            project_file = get_project_data_file(project_name)
            with open(project_file, 'w') as pf:
                json.dump([], pf)
            
            return jsonify({"status": "success", "message": "Project added successfully.", "project": new_project})

@app.route('/api/load', methods=['GET'])
def load_data():
    project_name = request.args.get('project')
    if not project_name:
        return jsonify({"status": "error", "message": "Project name is required."}), 400
        
    data_file = get_project_data_file(project_name)
    if os.path.exists(data_file):
        with open(data_file, 'r') as f:
            data = json.load(f)
        data = sanitize(data)
        return jsonify(data)
    return jsonify([])

@app.route('/api/save', methods=['POST'])
def save_data():
    project_name = request.args.get('project')
    if not project_name:
        return jsonify({"status": "error", "message": "Project name is required."}), 400
        
    data_file = get_project_data_file(project_name)
    data = request.get_json()
    if data is None:
        return jsonify({"status": "error", "message": "No data received"}), 400
    data = sanitize(data)
    with open(data_file, 'w') as f:
        json.dump(data, f, indent=4)
    return jsonify({"status": "success", "rows": len(data) if isinstance(data, list) else 1})

@app.route('/api/upload', methods=['POST'])
def upload_csv():
    project_name = request.args.get('project')
    if not project_name:
        return jsonify({"status": "error", "message": "Project name is required."}), 400

    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
        
    data_file = get_project_data_file(project_name)
    try:
        df = pd.read_csv(file, on_bad_lines='skip', encoding='utf-8', encoding_errors='ignore')
        
        df = df.where(pd.notnull(df), None)

        hierarchical_data = build_task_hierarchy(df)
        
        data = sanitize(hierarchical_data)
        
        with open(data_file, 'w') as f:
            json.dump(data, f, indent=4)
        return jsonify({"status": "uploaded", "rows": len(df)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"An error occurred while processing the CSV: {str(e)}"}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    initialize_profile_data()
    app.run(debug=True, host='0.0.0.0', port=5125)
