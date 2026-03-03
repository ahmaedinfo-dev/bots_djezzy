import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "API is running 🚀"

@app.route("/test")
def test_api():
    try:
        url = "https://apim.djezzy.dz/mobile-api/oauth2/registration"

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

        response = requests.post(url, params=params, json=data, headers=headers)

        return jsonify({
            "status_code": response.status_code,
            "response": response.text
        })

    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
