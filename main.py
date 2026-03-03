import requests

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

print(response.status_code)
print(response.text)
