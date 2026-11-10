import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import re
from app import app

client = app.test_client()

# 1. Get login page to extract CSRF token
r = client.get('/auth/login')
assert r.status_code == 200
html = r.data.decode('utf-8')
match = re.search(r'name="csrf_token" value="([^"]+)"', html)
csrf_token = match.group(1) if match else None
print('CSRF token found:', bool(csrf_token))

# 2. Login with CSRF token as admin (propietario)
r = client.post('/auth/login', data={'username': 'admin', 'password': 'admin123', 'csrf_token': csrf_token}, follow_redirects=True)
print('Login status:', r.status_code, 'Has Dashboard:', b'Dashboard General' in r.data or b'Dashboard' in r.data)

# 3. Check all core endpoints including Phase 2 additions
endpoints = [
    '/dashboard',
    '/products/',
    '/inventory/',
    '/inventory/audit',
    '/inventory/reconciliation',
    '/sales/',
    '/sales/pos',
    '/sales/abonos',
    '/purchases/',
    '/purchases/new',
    '/clients/',
    '/suppliers/',
    '/finances/',
    '/finances/export/excel',
    '/finances/export/pdf',
    '/receipts/',
    '/imports/',
    '/reports/',
    '/reports/daily',
    '/reports/monthly',
    '/reports/trends',
    '/settings/telegram',
    '/settings/users',
    '/settings/appearance',
    '/settings/backups',
    '/settings/audit'
]

passed_count = 0
for ep in endpoints:
    res = client.get(ep)
    print(f'Endpoint {ep:30} -> {res.status_code}')
    assert res.status_code == 200, f'Failed {ep}'
    passed_count += 1

print(f'SUCCESS: All {passed_count} core web endpoints responded with HTTP 200 OK!')
