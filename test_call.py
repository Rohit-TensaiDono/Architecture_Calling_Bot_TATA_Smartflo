# --- CONFIG ---
ADMIN_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3NDgyNzMiLCJjciI6ZmFsc2UsImlzcyI6Imh0dHBzOi8vY2xvdWRwaG9uZS50YXRhdGVsZXNlcnZpY2VzLmNvbS90b2tlbi9nZW5lcmF0ZSIsImlhdCI6MTc3NDQzNDI5OSwiZXhwIjoyMDc0NDM0Mjk5LCJuYmYiOjE3NzQ0MzQyOTksImp0aSI6IldiVGdxOXlRa3VyRjVoM3gifQ.EyJS9aiivyCouCQJDXXI_kuUe0iWX21qM0fD-Mz9zSQ"


# import requests

# url = "https://cloudphone.tatateleservices.com/api/v1/profile"
# url2 = "https://cloudphone.tatateleservices.com/api/v1/click_to_call"
# url3 = "https://cloudphone.tatateleservices.com/v1/click_to_call"

# headers = {
#     "Authorization": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3NDgyNzMiLCJjciI6ZmFsc2UsImlzcyI6Imh0dHBzOi8vY2xvdWRwaG9uZS50YXRhdGVsZXNlcnZpY2VzLmNvbS90b2tlbi9nZW5lcmF0ZSIsImlhdCI6MTc3NDQzNDI5OSwiZXhwIjoyMDc0NDM0Mjk5LCJuYmYiOjE3NzQ0MzQyOTksImp0aSI6IldiVGdxOXlRa3VyRjVoM3gifQ.EyJS9aiivyCouCQJDXXI_kuUe0iWX21qM0fD-Mz9zSQ"
# }

# r = requests.get(url3, headers=headers, timeout=10)
# print(r.status_code)
# print(r.text)

# _______________________________________________________________________________________________________________________________

# import requests

# # ---- CONFIG ----
# API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI3NDgyNzMiLCJjciI6ZmFsc2UsImlzcyI6Imh0dHBzOi8vY2xvdWRwaG9uZS50YXRhdGVsZXNlcnZpY2VzLmNvbS90b2tlbi9nZW5lcmF0ZSIsImlhdCI6MTc3NDQzNDI5OSwiZXhwIjoyMDc0NDM0Mjk5LCJuYmYiOjE3NzQ0MzQyOTksImp0aSI6IldiVGdxOXlRa3VyRjVoM3gifQ.EyJS9aiivyCouCQJDXXI_kuUe0iWX21qM0fD-Mz9zSQ"

# CALLER_ID = "918065254018"
# CUSTOMER_NUMBER = "919878501189"

# url = "https://cloudphone.tatateleservices.com/api/v1/click_to_call"

# headers = {
#     "Authorization": f"Bearer {API_TOKEN}",
#     "Content-Type": "application/x-www-form-urlencoded"
# }

# payload = {
#     "agent_number": CALLER_ID,
#     "destination_number": CUSTOMER_NUMBER
# }

# print("Sending request...")

# try:
#     response = requests.post(
#         url,
#         data=payload,   # ⚠️ IMPORTANT → NOT json=
#         headers=headers,
#         timeout=15
#     )

#     print("STATUS:", response.status_code)
#     print("RESPONSE:", response.text)

# except Exception as e:
#     print("ERROR:", str(e))

#____________________________________________________________________________________________________________________________________


import requests

def make_call(customer_number: str):
    url = "https://api-smartflo.tatateleservices.com/v1/click_to_call_support"

    payload = {
        "async": 1,
        "customer_number": customer_number,
        "customer_ring_timeout": 15,
        "caller_id": "918065254018",  # YOUR DESIRED NUMBER
        "api_key": "315dfff2-dce7-498c-8647-c284ff7a83b1"
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, timeout=15)

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)

    return response.json()