"""Fetch only pinned public GitHub inputs and verify their recorded digests."""
import hashlib
import json
import urllib.request
from pathlib import Path

B=Path(__file__).parent
p=json.loads((B/'provenance.json').read_text())
r=json.loads((B/'prediction-accuracy-review-2026-11-02.json').read_text())
for name,commit in [('data-current.json',p['baseline_commit']),('data-morning.json',p['morning_commit'])]:
    url=f"https://raw.githubusercontent.com/{p['repository']}/{commit}/data.json"
    content=urllib.request.urlopen(url, timeout=90).read()
    if hashlib.sha256(content).hexdigest()!=r['sha256'][name]:
        raise ValueError(f'Pinned input digest mismatch: {name}')
    (B/name).write_bytes(content)
    print(f'{name}: verified')
for name, expected in p['archive_sha256'].items():
    url=f"https://raw.githubusercontent.com/{p['repository']}/{p['baseline_commit']}/{name}"
    content=urllib.request.urlopen(url, timeout=90).read()
    if hashlib.sha256(content).hexdigest()!=expected:
        raise ValueError(f'Pinned archive digest mismatch: {name}')
    target=B/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(content)
    print(f'{name}: verified')
