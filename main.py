import os
import platform
import psutil
import shutil
import socket
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "Server Info API Running 🚀"

@app.route("/server-info")
def server_info():

    # RAM
    ram = psutil.virtual_memory()

    # CPU
    cpu_count = psutil.cpu_count(logical=True)
    cpu_percent = psutil.cpu_percent(interval=1)

    # Disk
    total, used, free = shutil.disk_usage("/")

    # System Info
    system_info = {
        "system": platform.system(),
        "node_name": platform.node(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }

    # User / Root Check
    try:
        is_root = (os.geteuid() == 0)
    except AttributeError:
        is_root = False  # Windows fallback

    current_user = os.getenv("USER")

    # IP Address
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    return jsonify({
        "RAM": {
            "total_MB": round(ram.total / (1024**2), 2),
            "used_MB": round(ram.used / (1024**2), 2),
            "free_MB": round(ram.available / (1024**2), 2),
            "usage_percent": ram.percent
        },
        "CPU": {
            "cores": cpu_count,
            "usage_percent": cpu_percent
        },
        "Disk": {
            "total_GB": round(total / (1024**3), 2),
            "used_GB": round(used / (1024**3), 2),
            "free_GB": round(free / (1024**3), 2)
        },
        "System": system_info,
        "User": current_user,
        "Is_Root": is_root,
        "Hostname": hostname,
        "Local_IP": local_ip
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
