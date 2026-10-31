import unittest
from types import SimpleNamespace
from unittest.mock import patch
from diagnose_sources import summarize_response, diagnose

class DiagnosticTests(unittest.TestCase):
    def response(self, status=403, headers=None):
        return SimpleNamespace(status_code=status,headers=headers or {})
    def test_bare_forbidden_is_unknown(self):
        r=summarize_response(self.response(headers={'Server':'cloudflare'}),b'<title>403 Forbidden</title>Forbidden')
        self.assertEqual(r['assessment'],'forbidden_reason_unknown')
        self.assertFalse(any(r['evidence'].values()))
    def test_explicit_security_evidence(self):
        r=summarize_response(self.response(headers={'CF-Mitigated':'challenge'}),b'<title>Just a moment</title>Verify you are human')
        self.assertEqual(r['assessment'],'security_screening_evidence')
    def test_cookie_and_body_not_returned(self):
        r=summarize_response(self.response(headers={'Set-Cookie':'secret-value'}),b'<title>Forbidden</title>secret-value')
        self.assertNotIn('secret-value',str(r))
        self.assertEqual(r['title'],'Forbidden')
    def test_redirect_query_not_saved(self):
        r=summarize_response(self.response(302,{'Location':'https://example.com/login?token=secret-value'}),b'')
        self.assertEqual(r['assessment'],'redirect_not_followed')
        self.assertEqual(r['redirect_host'],'example.com')
        self.assertNotIn('secret-value',str(r))
    @patch('diagnose_sources.requests.get')
    def test_transport_errors_no_retry_and_no_exception_message(self,get):
        import requests
        get.side_effect=requests.Timeout('private-address')
        r=diagnose()
        self.assertEqual(get.call_count,2)
        self.assertNotIn('private-address',str(r))
        self.assertTrue(all(v['error_type']=='Timeout' for v in r['sources'].values()))

if __name__=='__main__':unittest.main()
