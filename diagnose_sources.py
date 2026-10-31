"""One ordinary request per source. No retries, cookies, authentication or bypass."""
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
import requests
from collect_sources import SOURCES

HEADER_NAMES = ('server', 'content-type', 'cf-mitigated', 'via', 'x-cache')

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'title': self.active = True
    def handle_endtag(self, tag):
        if tag.lower() == 'title': self.active = False
    def handle_data(self, data):
        if self.active: self.parts.append(data)


def summarize_response(response, body):
    headers = {k.lower():v for k,v in response.headers.items()}
    text = body.decode('utf-8', errors='replace')
    parser = TitleParser(); parser.feed(text)
    markers = {
        'human_verification': bool(re.search(r'verify (?:you are|that you are) human|checking your browser|captcha|人間であること',text,re.I)),
        'automated_traffic': bool(re.search(r'automated (?:traffic|queries|requests)|unusual traffic|bot detection',text,re.I)),
        'cloudflare_challenge': headers.get('cf-mitigated','').lower() == 'challenge',
    }
    # A vendor/server name or bare 403 is not evidence of a bot block.
    security = response.status_code >= 400 and any(markers.values())
    redirect = headers.get('location')
    target = urlsplit(redirect) if redirect else None
    return {'status':response.status_code, 'headers':{k:headers[k][:200] for k in HEADER_NAMES if k in headers},
            'title':' '.join(''.join(parser.parts).split())[:160],
            'sample_bytes':len(body), 'sample_sha256':hashlib.sha256(body).hexdigest(),
            'redirect_present':bool(redirect),
            'redirect_host':target.hostname if target else None,
            'evidence':markers,
            'assessment':'security_screening_evidence' if security else
                         'forbidden_reason_unknown' if response.status_code == 403 else
                         'redirect_not_followed' if 300 <= response.status_code < 400 else
                         'http_response_only'}


def diagnose():
    out = {'checked_at':datetime.now(timezone.utc).isoformat(),'sources':{},
           'method':'One GET per source with existing collector user agent; redirects not followed; first 16 KiB only.',
           'limitations':'Headers may identify a delivery layer, not the exact blocking rule. No raw body, cookies or credentials saved.'}
    for name in ('ana-slo','d-delta'):
        try:
            with requests.get(SOURCES[name], timeout=(10,20), allow_redirects=False, stream=True,
                              headers={'User-Agent':'Mozilla/5.0'}) as response:
                body = next(response.iter_content(chunk_size=16384), b'')
                out['sources'][name] = summarize_response(response,body)
        except requests.RequestException as error:
            # Exception messages can contain addresses or proxy details; save type only.
            out['sources'][name] = {'assessment':'transport_error','error_type':type(error).__name__}
    return out

if __name__ == '__main__':
    print(json.dumps(diagnose(),ensure_ascii=False,indent=2))
