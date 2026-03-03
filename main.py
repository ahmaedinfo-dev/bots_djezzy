import os
import socket
import traceback
import requests
from flask import Flask, jsonify

app = Flask(__name__)

TARGET_HOST = "apim.djezzy.dz"
TARGET_URL = "https://apim.djezzy.dz/mobile-api/oauth2/registration"

@app.route("/")
def home():
    return "Diagnostic API running 🚀"

@app.route("/test")
def test_api():
    debug = {}

    # 1️⃣ اختبار DNS
    try:
        ip = socket.gethostbyname(TARGET_HOST)
        debug["dns_resolution"] = ip
    except Exception as e:
        debug["dns_error"] = str(e)

    # 2️⃣ اختبار اتصال TCP
    try:
        sock = socket.create_connection((TARGET_HOST, 443), timeout=5)
        sock.close()
        debug["tcp_connection"] = "Success"
    except Exception as e:
        debug["tcp_error"] = str(e)

    # 3️⃣ اختبار HTTPS request
    try:
        params = {
            "msisdn": "213795291083",
            "client_id": "87pIExRhxBb3_wGsA5eSEfyATloa",
            "scope": "smsotp"
        }

        headers = {
            "User-Agent": "MobileApp/3.0.0",
            "Content-Type": "application/json"
        }

        data = {
            "consent-agreement": [{"marketing-notifications": False}],
            "is-consent": True
        }

        response = requests.post(
            TARGET_URL,
            params=params,
            json=data,
            headers=headers,
            timeout=10
        )

        debug["http_status"] = response.status_code
        debug["http_response"] = response.text[:1000]

    except Exception as e:
        debug["request_error"] = str(e)
        debug["error_type"] = type(e).__name__
        debug["traceback"] = traceback.format_exc()

    return jsonify(debug)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
