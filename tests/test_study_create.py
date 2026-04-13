"""
Legt testweise eine leere Lichess-Studie an und gibt die URL aus.
Ausfuehren: python tests/test_study_create.py
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path='.env')

TOKEN = os.getenv('LICHESS_TOKEN', '')
if not TOKEN:
    print('FEHLER: LICHESS_TOKEN nicht in .env gefunden.')
    exit(1)

headers = {'Authorization': f'Bearer {TOKEN}'}

print('Lege Studie an...')
r = requests.post(
    'https://lichess.org/api/study',
    data={
        'name':       'Test-Studie',
        'visibility': 'unlisted',
        'computer':   'everyone',
        'explorer':   'everyone',
        'cloneable':  'everyone',
        'shareable':  'everyone',
        'chat':       'everyone',
    },
    headers=headers,
    timeout=15,
)

print(f'HTTP {r.status_code}')
print(r.text[:500])

if r.status_code == 200:
    data = r.json()
    study_id = data.get('id', '')
    print(f'\nStudy-ID : {study_id}')
    print(f'URL      : https://lichess.org/study/{study_id}')
