import requests
res = requests.post("http://127.0.0.1:8050/api/upload", files={"excel_file": ("test.xlsx", b"dummy")})
print(res.status_code, res.text)
