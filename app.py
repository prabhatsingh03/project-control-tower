from flask import Flask, request, jsonify, render_template
from datetime import datetime, timedelta
import os
import json
import pandas as pd
import math
import hashlib
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='templates')
PROFILE_DATA_FILE = 'profile_data.json'
ACTIVITY_LOG_FILE = 'activity_log.json' # New log file

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
    if pd.isna(obj):
        return None

    return obj

def hash_password(password):
    """Hashes a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_name_from_email(email):
    """Creates a display name from an email address."""
    try:
        name_part = email.split('@')[0]
        # Replace dots or underscores with spaces and capitalize
        return ' '.join(word.capitalize() for word in name_part.replace('.', ' ').replace('_', ' ').split())
    except:
        return "Admin" # Fallback

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

def initialize_activity_log():
    """Creates an empty log file if one doesn't exist."""
    if not os.path.exists(ACTIVITY_LOG_FILE):
        with open(ACTIVITY_LOG_FILE, 'w') as f:
            json.dump([], f)

def log_activity(user_email, project_name, action, details):
    """Logs an admin's action to the activity log file."""
    try:
        with open(ACTIVITY_LOG_FILE, 'r+') as f:
            log_data = json.load(f)
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user": user_email,
                "project": project_name,
                "action": action,
                "details": details
            }
            log_data.insert(0, log_entry) # Add new logs to the top
            f.seek(0)
            json.dump(log_data, f, indent=4)
            f.truncate()
    except (IOError, json.JSONDecodeError) as e:
        # If file is empty or corrupt, start a new list
        with open(ACTIVITY_LOG_FILE, 'w') as f:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user": user_email,
                "project": project_name,
                "action": action,
                "details": details
            }
            json.dump([log_entry], f, indent=4)
        print(f"Log file was empty or corrupt. Created a new one. Error: {e}")


def recalculate_progress_recursively(tasks):
    """
    NEW: Recursively calculates parent progress based on weighted child progress.
    """
    for task in tasks:
        if task.get('subtasks') and len(task['subtasks']) > 0:
            # First, recurse to ensure children are calculated
            task['subtasks'] = recalculate_progress_recursively(task['subtasks'])
            
            # Now, calculate this task's progress
            total_weight = 0
            weighted_progress_sum = 0
            for subtask in task['subtasks']:
                # MODIFIED: Use 0.0 as the default and fix logic to handle 0 weightage correctly.
                weight = float(subtask.get('weightage', 0.0))
                progress = float(subtask.get('progress', 0) or 0)
                total_weight += weight
                weighted_progress_sum += progress * weight
            
            if total_weight > 0:
                task['progress'] = round(weighted_progress_sum / total_weight)
            else:
                task['progress'] = 0 # Avoid division by zero
    return tasks


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
        'Weightage': ['Weightage', 'Weightage (%)', 'weightage'],
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

        # MODIFIED: Handle decimal weightage from CSV, defaulting to 0.
        try:
            # Get the value. Default to 0.0 if the column/value is missing.
            raw_val = row.get('Weightage', 0.0)
            # If the value from the CSV is empty/null, also treat it as 0.0.
            if raw_val is None or pd.isna(raw_val):
                weightage_val = 0.0
            else:
                # Try converting the retrieved value to a float.
                weightage_val = float(raw_val)
        except (ValueError, TypeError):
            # If conversion fails (e.g., for non-numeric text), default to 0.0.
            weightage_val = 0.0

        task = {
            'id': wbs_str,
            'wbs': wbs_str,
            'taskName': row.get('Name'),
            'plannedStartDate': row.get('Start_Date'),
            'plannedEndDate': row.get('Finish_Date'),
            'predecessorString': row.get('Predecessors', ''),
            'originalDurationDays': row.get('Duration'),
            'weightage': weightage_val, # Use the converted float value
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

    # After building hierarchy, calculate progress
    return recalculate_progress_recursively(top_level_tasks)


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
    
    log_activity(email, None, "User Signup", f"New admin account created for {email}, awaiting approval.")
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
                    log_activity(email, None, "User Login", "Admin successfully logged in.")
                    return jsonify({
                        "status": "success", 
                        "userType": user['role'], 
                        "email": user['email'],
                        "name": get_name_from_email(user['email']) # Return name
                    })
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
        log_activity(email_to_approve, None, "Approval", f"Admin account approved for {email_to_approve}.")
        
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
        log_activity(email_to_reject, None, "Rejection", f"Admin account rejected for {email_to_reject}.")
        
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

@app.route('/api/activity_log', methods=['GET'])
def get_activity_log():
    """Serves the content of the activity log file."""
    if not os.path.exists(ACTIVITY_LOG_FILE):
        return jsonify([])
    try:
        with open(ACTIVITY_LOG_FILE, 'r') as f:
            logs = json.load(f)
        return jsonify(logs)
    except (IOError, json.JSONDecodeError):
        return jsonify([])

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
    if not project_name: return jsonify({"status": "error", "message": "Project name is required."}), 400
    
    payload = request.get_json()
    if not payload: return jsonify({"status": "error", "message": "No data received"}), 400

    new_tasks_data = payload.get('tasks')
    user_email = payload.get('user_email') # This will be None for clients

    if new_tasks_data is None:
        return jsonify({"status": "error", "message": "Payload must include tasks"}), 400

    data_file = get_project_data_file(project_name)
    
    # --- MODIFIED: Conditional Logging ---
    # Only perform logging if an email is provided (i.e., the user is an admin)
    if user_email:
        old_tasks = {}
        if os.path.exists(data_file):
            with open(data_file, 'r') as f:
                try:
                    old_data_list = json.load(f)
                    def task_to_dict(tasks_list, task_dict):
                        for t in tasks_list:
                            task_dict[t['id']] = t
                            if t.get('subtasks'): task_to_dict(t['subtasks'], task_dict)
                    task_to_dict(old_data_list, old_tasks)
                except (json.JSONDecodeError, TypeError):
                    pass

        new_tasks = {}
        def task_to_dict_new(tasks_list, task_dict):
            for t in tasks_list:
                task_dict[t['id']] = t
                if t.get('subtasks'): task_to_dict_new(t['subtasks'], task_dict)
        task_to_dict_new(new_tasks_data, new_tasks)
        
        added_tasks = set(new_tasks.keys()) - set(old_tasks.keys())
        deleted_tasks = set(old_tasks.keys()) - set(new_tasks.keys())
        common_tasks = set(new_tasks.keys()) & set(old_tasks.keys())

        for task_id in added_tasks: log_activity(user_email, project_name, "Task Added", f"Task '{new_tasks[task_id]['taskName']}' (WBS: {new_tasks[task_id]['wbs']}) was created.")
        for task_id in deleted_tasks: log_activity(user_email, project_name, "Task Deleted", f"Task '{old_tasks[task_id]['taskName']}' (WBS: {old_tasks[task_id]['wbs']}) was deleted.")
        for task_id in common_tasks:
            if json.dumps(old_tasks[task_id], sort_keys=True) != json.dumps(new_tasks[task_id], sort_keys=True):
                 log_activity(user_email, project_name, "Task Edited", f"Task '{new_tasks[task_id]['taskName']}' (WBS: {new_tasks[task_id]['wbs']}) was modified.")
    # --- End Conditional Logging ---

    # Recalculate progress and save (runs for both admins and clients)
    final_data = sanitize(recalculate_progress_recursively(new_tasks_data))
    with open(data_file, 'w') as f:
        json.dump(final_data, f, indent=4)
    return jsonify({"status": "success"})


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
        
        # Log this action. Assumes user info is not available here, so generic log.
        user_email = request.form.get('user_email', 'Unknown User')
        log_activity(user_email, project_name, "CSV Upload", f"{len(df)} rows imported from '{file.filename}'.")

        return jsonify({"status": "uploaded", "rows": len(df)})
    except Exception as e:
        return jsonify({"status": "error", "message": f"An error occurred while processing the CSV: {str(e)}"}), 500

# NEW: Route for the charts page
@app.route('/charts')
def charts_page():
    # We can pass the project name to the template if needed
    project_name = request.args.get('project', 'Default Project')
    return render_template('charts.html', project_name=project_name)

def get_s_curve_data(tasks):
    """Calculates data for a planned vs actual progress S-Curve."""
    all_leaf_tasks = []
    def flatten_tasks(task_list):
        for task in task_list:
            # S-curves are based on leaf tasks (tasks with no subtasks) that have weightage
            if not task.get('subtasks') and task.get('weightage', 0) > 0:
                 all_leaf_tasks.append(task)
            elif task.get('subtasks'): # Recurse into parent tasks
                flatten_tasks(task['subtasks'])
    flatten_tasks(tasks)

    if not all_leaf_tasks:
        return {}

    # Determine project date range from planned and actual dates
    try:
        all_dates = []
        for t in all_leaf_tasks:
            if t.get('plannedStartDate'): all_dates.append(datetime.fromisoformat(t['plannedStartDate']))
            if t.get('plannedEndDate'): all_dates.append(datetime.fromisoformat(t['plannedEndDate']))
            if t.get('actualEndDate'): all_dates.append(datetime.fromisoformat(t['actualEndDate']))

        if not all_dates: return {}
        project_start_date = min(all_dates)
        project_end_date = max(all_dates)
    except (ValueError, TypeError):
        return {} # Return empty if dates are invalid

    # Calculate total weightage of all leaf tasks
    total_weightage = sum(t.get('weightage', 0) for t in all_leaf_tasks)
    if total_weightage == 0:
        return {} # Avoid division by zero

    # Generate S-curve data points
    s_curve_data = {'dates': [], 'planned_progress': [], 'actual_progress': []}
    current_date = project_start_date
    
    # MODIFICATION: The loop will now stop at today's date or the project end date, whichever is earlier.
    loop_end_date = min(project_end_date, datetime.now())

    while current_date <= loop_end_date:
        date_str = current_date.strftime('%d-%b-%y')

        # Planned progress: sum of weightages of tasks *planned* to be finished by this date
        planned_weight_done = sum(
            t.get('weightage', 0) for t in all_leaf_tasks
            if t.get('plannedEndDate') and datetime.fromisoformat(t['plannedEndDate']).date() <= current_date.date()
        )

        # Actual progress: sum of weightages of tasks *actually* finished by this date
        actual_weight_done = sum(
            t.get('weightage', 0) for t in all_leaf_tasks
            if t.get('actualEndDate') and datetime.fromisoformat(t['actualEndDate']).date() <= current_date.date()
        )

        s_curve_data['dates'].append(date_str)
        s_curve_data['planned_progress'].append(round((planned_weight_done / total_weightage) * 100, 2))
        s_curve_data['actual_progress'].append(round((actual_weight_done / total_weightage) * 100, 2))

        current_date += timedelta(days=1)

    return s_curve_data

# In app.py, replace the entire function

@app.route('/api/chart_data')
def get_chart_data():
    project_name = request.args.get('project')
    if not project_name:
        return jsonify({"status": "error", "message": "Project name is required."}), 400

    data_file = get_project_data_file(project_name)
    if not os.path.exists(data_file):
        return jsonify({
            'status_counts': {}, 'total_delays': {}, 's_curve_data': {}, 
            'overall_actual_progress': 0, 'next_critical_activity': None
        })

    with open(data_file, 'r') as f:
        tasks = json.load(f)

    # Flatten the task list to get all tasks
    all_tasks = []
    def flatten_tasks(task_list):
        for task in task_list:
            all_tasks.append(task)
            if task.get('subtasks'):
                flatten_tasks(task['subtasks'])
    flatten_tasks(tasks)

    # 1. Task Status Distribution
    status_counts = {}
    for task in all_tasks:
        status = task.get('status', 'Not Started')
        status_counts[status] = status_counts.get(status, 0) + 1

    # 2. Total Delays by Type
    total_delays = { 'weather': 0, 'contractor': 0, 'client': 0 }
    for task in all_tasks:
        total_delays['weather'] += task.get('delayWeatherDays', 0) or 0
        total_delays['contractor'] += task.get('delayContractorDays', 0) or 0
        total_delays['client'] += task.get('delayClientDays', 0) or 0

    # 3. Overall Actual Progress
    overall_actual_progress = tasks[0].get('progress', 0) if tasks else 0

    # 4. S-Curve Data
    s_curve_data = get_s_curve_data(tasks)

    # 5. Find the next single critical activity (CORRECTED LOGIC)
    future_critical_tasks = []
    today = datetime.now().date()

    for task in all_tasks:
        if task.get('isCritical'):
            try:
                start_date_str = task.get('plannedStartDate')
                if start_date_str and datetime.fromisoformat(start_date_str).date() >= today:
                    future_critical_tasks.append(task)
            except (ValueError, TypeError):
                continue

    next_critical_activity_obj = None
    if future_critical_tasks:
        next_critical_activity_obj = min(future_critical_tasks, key=lambda x: datetime.fromisoformat(x['plannedStartDate']))

    next_critical_activity_data = None
    if next_critical_activity_obj:
        next_critical_activity_data = {
            'wbs': next_critical_activity_obj.get('wbs', ''),
            'taskName': next_critical_activity_obj.get('taskName', '')
        }

    # The return statement is now correctly placed at the end of the function
    return jsonify({
        'status_counts': status_counts,
        'total_delays': total_delays,
        's_curve_data': s_curve_data,
        'overall_actual_progress': overall_actual_progress,
        'next_critical_activity': next_critical_activity_data
    })

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    initialize_profile_data()
    initialize_activity_log() # Initialize log file on startup
    app.run(debug=True, host='0.0.0.0', port=5125)
