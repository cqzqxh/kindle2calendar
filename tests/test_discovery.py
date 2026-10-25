"""Run the actual Kindle shell implementation against local HTTP command fixtures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NOW = 1793021400  # 2026-10-26 21:30 Asia/Shanghai
CONFIG = {"access_key": "fixture-ak", "secret_key": "fixture-secret6", "bucket": "calendar-test",
          "screen_id": "kindle-pw3", "domain": "https://images.example"}
PREFIX = "family-calendar/kindle-pw3/20261026/"
MOCK = r'''import json, os, pathlib, sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs
root = pathlib.Path(os.environ['MOCK_ROOT'])
args=sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == 'date':
    stamp = int(os.environ['MOCK_NOW'])
    if args[0] == '-d': stamp=int(args[1][1:])
    elif args[0] == '-r': stamp=int(args[1])
    fmt=args[-1][1:]
    if fmt == '%s': print(stamp)
    else:
        tz=timezone.utc if '-u' in args else timezone(timedelta(hours=8))
        print(datetime.fromtimestamp(stamp,tz).strftime(fmt))
    sys.exit(0)
from qiniu import Auth
config=json.loads((root/'discovery.json').read_text())
content=pathlib.Path(args[args.index('--config')+1]).read_text()
lines=content.splitlines()
url=next(x.split('"')[1] for x in lines if x.startswith('url = '))
headers=dict(x.split('"')[1].split(': ',1) for x in lines if x.startswith('header = '))
parsed=urlsplit(url)
signing='GET '+parsed.path+'?'+parsed.query+'\nHost: '+parsed.netloc
signing+='\nContent-Type: '+headers['Content-Type']+'\nX-Qiniu-Date: '+headers['X-Qiniu-Date']+'\n\n'
expected='Qiniu '+Auth(config['access_key'],config['secret_key']).token(signing)
if expected != headers['Authorization']: sys.exit(22)
calls=root/'calls.jsonl'
previous=calls.read_text().splitlines() if calls.exists() else []
with calls.open('a') as out: out.write(json.dumps({'params':parse_qs(parsed.query,keep_blank_values=True),'args':args})+'\n')
responses=json.loads((root/'pages.json').read_text())
entry=responses[min(len(previous),len(responses)-1)]
if entry.get('offline'): sys.exit(7)
body=entry.get('body', {'items':[], 'marker':''})
pathlib.Path(args[args.index('--output')+1]).write_text(json.dumps(body))
print(entry.get('status',200),end='')
'''


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.bin=self.root/'bin'
        self.bin.mkdir()
        self.lock=self.root/'lock'
        self.lock.mkdir()
        self.config=self.root/'discovery.json'
        self.config.write_text(json.dumps(CONFIG))
        self.config.chmod(0o600)
        for name in ('curl','date'):
            tool=self.bin/name
            tool.write_text('#!'+sys.executable+'\n'+MOCK)
            tool.chmod(0o700)
        self.output=self.root/'download.conf'

    def run_discovery(self, pages, *, config=None, now=NOW, allow_http=False):
        if config is not None:
            self.config.write_text(json.dumps(config))
        (self.root/'pages.json').write_text(json.dumps(pages))
        result=subprocess.run(['sh','-c',
            '. "$1"; LOCK=$2; run_child() { "$@"; }; umask 077; discover_calendar "$3" ca.pem "$4"',
            'test',str(ROOT/'kindle/discover.sh'),str(self.lock),str(self.config),str(self.output)],
            env={**os.environ,'PATH':str(self.bin)+':'+os.environ['PATH'], 'MOCK_ROOT':str(self.root),
                 'MOCK_NOW':str(now),'ALLOW_HTTP_DOWNLOAD': '1' if allow_http else '0','TZ':'CST-8'},capture_output=True,timeout=15)
        self.assertNotIn(CONFIG['secret_key'].encode(),result.stdout+result.stderr)
        self.assertFalse((self.lock/'discovery').exists())
        return result

    def calls(self):
        path=self.root/'calls.jsonl'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_complete_pagination_sort_and_sdk_signatures(self):
        result=self.run_discovery([
            {'body':{'items':[{'key':PREFIX+'20261026212259.png'}, {'key':PREFIX+'20261026235959.png'}],'marker':'next+/='}},
            {'body':{'items':[{'key':PREFIX+'20261026212500.png'}, {'key':PREFIX+'20261026999999.png'},
                              {'key':PREFIX+'20261026212000.png'}, {'key':'family-calendar/other/20261026/20261026212900.png'}]}}])
        self.assertEqual(result.returncode,0,result.stderr)
        from qiniu import Auth
        url=CONFIG['domain']+'/'+PREFIX+'20261026212500.png'
        from unittest.mock import patch
        with patch('qiniu.auth.time.time',return_value=NOW):
            expected=Auth(CONFIG['access_key'],CONFIG['secret_key']).private_download_url(url,expires=300)
        self.assertEqual(self.output.read_text(),'url = "'+expected+'"\n')
        self.assertEqual(self.output.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.calls()[1]['params']['marker'],['next+/='])
        self.assertNotIn(CONFIG['secret_key'],json.dumps(self.calls()))

    def test_empty_today_falls_back_to_previous_day(self):
        result=self.run_discovery([{'body':{'items':[]}}, {'body':{'items':[{'key':'family-calendar/kindle-pw3/20261025/20261025235959.png'}]}}])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('20261025235959.png',self.output.read_text())
        self.assertEqual(len(self.calls()),2)

    def test_midnight_falls_back_across_month(self):
        now = int(datetime(2026, 10, 31, 16, tzinfo=timezone.utc).timestamp())
        result = self.run_discovery([{'body': {'items': []}}, {'body': {'items': [
            {'key': 'family-calendar/kindle-pw3/20261031/20261031235959.png'}]}}], now=now)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]['params']['prefix'], ['family-calendar/kindle-pw3/20261101/'])
        self.assertEqual(self.calls()[1]['params']['prefix'], ['family-calendar/kindle-pw3/20261031/'])
        self.assertIn('20261031235959.png', self.output.read_text())

    def test_failed_second_page_never_uses_incomplete_list(self):
        self.assertNotEqual(self.run_discovery([
            {'body':{'items':[{'key':PREFIX+'20261026212259.png'}],'marker':'next'}},
            {'offline':True}]).returncode,0)
        self.assertFalse(self.output.exists())

    def test_list_errors_do_not_fall_back_as_empty(self):
        for response in ({'status':403},{'body':{'error':'no access'}},
                         {'body':{'items':[],'marker':12}}, {'body':{'items':[{'key':12}]}}):
            with self.subTest(response=response):
                self.assertNotEqual(self.run_discovery([response]).returncode,0)
                self.assertFalse(self.output.exists())

    def test_repeated_marker_and_no_images_are_bounded(self):
        self.assertNotEqual(self.run_discovery([{'body':{'items':[],'marker':'repeat'}}]).returncode,0)
        self.assertEqual(len(self.calls()),2)
        (self.root/'calls.jsonl').unlink()
        self.assertNotEqual(self.run_discovery([{'body':{'items':[]}}]).returncode,0)
        self.assertEqual(len(self.calls()),7)

    def test_credentials_permissions_and_domain_injection(self):
        self.config.chmod(0o644)
        self.assertNotEqual(self.run_discovery([{}]).returncode,0)
        self.assertEqual(self.calls(),[])
        self.config.chmod(0o600)
        for domain in ('http://example','https://example/secret','https://user@example',
                       'https://example?x=y','https://example/"\noutput=x'):
            with self.subTest(domain=domain):
                self.assertNotEqual(self.run_discovery([{}],config={**CONFIG,'domain':domain}).returncode,0)
                self.assertFalse(self.output.exists())

    def test_http_requires_explicit_demo_opt_in(self):
        config = {**CONFIG, 'domain': 'http://images.example'}
        pages = [{'body': {'items': [{'key': PREFIX + '20261026212259.png'}]}}]
        self.assertNotEqual(self.run_discovery(pages, config=config).returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.run_discovery(pages, config=config, allow_http=True).returncode, 0)
        self.assertTrue(self.output.read_text().startswith('url = "http://images.example/'))
        self.assertIn('=https', self.calls()[0]['args'])

    def test_long_hmac_key(self):
        result=self.run_discovery([{'body':{'items':[{'key':PREFIX+'20261026212259.png'}]}}],
                                  config={**CONFIG,'secret_key':'fixture6'*12})
        self.assertEqual(result.returncode,0,result.stderr)
