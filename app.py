from flask import Flask, request, jsonify, render_template
import os
import json
import pandas as pd
import math

app = Flask(__name__, static_folder='static', template_folder='templates')
DATA_FILE = 'project_data.json'
LOGO_FILE = 'logo.png'

# Recursively replace NaN floats with None

def sanitize(obj):
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj

@app.route('/api/load', methods=['GET'])
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        data = sanitize(data)
        return jsonify(data)
    return jsonify([])

@app.route('/api/save', methods=['POST'])
def save_data():
    data = request.get_json()
    if data is None:
        return jsonify({"status": "error", "message": "No data received"}), 400
    # sanitize just in case
    data = sanitize(data)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)
    return jsonify({"status": "success", "rows": len(data) if isinstance(data, list) else 1})

@app.route('/api/upload', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
    try:
        df = pd.read_csv(file)
        # convert pandas NaN to None
        df = df.where(pd.notnull(df), None)
        data = df.to_dict(orient='records')
        data = sanitize(data)
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
        return jsonify({"status": "uploaded", "rows": len(data)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logo', methods=['POST'])
def upload_logo():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400
    try:
        if not os.path.exists(app.static_folder):
            os.makedirs(app.static_folder)
        logo_path = os.path.join(app.static_folder, LOGO_FILE)
        file.save(logo_path)
        # **FIXED LINE**
        return jsonify({"status": "uploaded", "path": f'/static/{LOGO_FILE}'})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logo', methods=['GET'])
def get_logo_path():
    logo_path = os.path.join(app.static_folder, LOGO_FILE)
    if os.path.exists(logo_path):
        # **FIXED LINE**
        return jsonify({'path': f'/static/{LOGO_FILE}'})
    return jsonify({'path': None})

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5125)