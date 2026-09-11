"""Bounded public research. Never fetch credentials, local networks or hidden profiles."""
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin, urlencode
from urllib.robotparser import RobotFileParser
from .models import text, email
from .providers import search, request_json

AGENT = 'OpenServiceAgents/0.2 (+https://github.com/arinborgamer/open-service-agents)'


def public_url(url):
    parsed = urlsplit(text(url, 'URL', 2048))
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443) or any(ord(c) < 33 for c in url)):
        raise ValueError('Only public HTTP(S) URLs on standard ports are supported.')
    return parsed


def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(r[4][0]).is_global for r in addresses):
        raise ValueError('Private, loopback, reserved and link-local networks are blocked.')
    return addresses


def fetch(url, redirects=0, follow_redirects=True):
    """Pin a validated DNS answer for the actual socket, including HTTPS SNI."""
    if redirects > 3:
        raise ValueError('Too many redirects.')
    p = public_url(url)
    port = p.port or (443 if p.scheme == 'https' else 80)
    addresses = public_addresses(p.hostname, port)
    family, kind, protocol, _, address = addresses[0]
    conn = http.client.HTTPConnection(p.hostname, port, timeout=15)
    raw = socket.socket(family, kind, protocol)
    raw.settimeout(15)
    try:
        raw.connect(address)
        conn.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=p.hostname) if p.scheme == 'https' else raw
        conn.request('GET', urlunsplit(('', '', p.path or '/', p.query, '')),
                     headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
        response = conn.getresponse()
        status, headers = response.status, dict(response.getheaders())
        location = response.getheader('Location')
        kind = response.getheader('Content-Type', '').split(';')[0].strip().lower()
        data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError('Source exceeds the 1 MB limit.')
    finally:
        conn.close()
        raw.close()
    if status in (301, 302, 303, 307, 308) and location:
        final = urljoin(url, location)
        if not follow_redirects:
            return status, kind, data, final
        return fetch(final, redirects + 1)
    return status, kind, data, url


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_title = False
        self.title, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'noscript', 'svg'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'footer', 'noscript', 'svg'):
            self.skip = max(0, self.skip - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.skip and data.strip():
            self.parts.append(data.strip())


def read_source(url, rights='public_reference'):
    if rights not in ('owned', 'licensed', 'permission', 'public_reference'):
        raise ValueError('Unknown usage basis.')
    p = public_url(url)
    robots_url = urlunsplit((p.scheme, p.netloc, '/robots.txt', '', ''))
    status, _, data, _ = fetch(robots_url)
    if status in (401, 403) or status >= 500 or (status != 404 and status >= 400):
        raise ValueError('Robots policy unavailable or access disallowed; supply permissioned notes manually.')
    if status == 200:
        robot = RobotFileParser()
        robot.parse(data.decode('utf-8', errors='replace').splitlines())
        if not robot.can_fetch(AGENT, url):
            raise ValueError('Robots policy disallows fetching this source.')
        delay = robot.crawl_delay(AGENT)
        if delay:
            raise ValueError('This source requests a crawl delay; import notes manually or use its official API.')
    status, kind, raw, final = fetch(url, follow_redirects=False)
    # Do not follow a page redirect onto another path/site without checking its policy.
    if final != url:
        raise ValueError('Source redirected. Review and submit the final URL explicitly: ' + final)
    if status != 200 or kind not in ('text/html', 'text/plain'):
        raise ValueError('Source is unavailable or not HTML/plain text. No paywall or login bypass is attempted.')
    parser = Extractor()
    if kind == 'text/html':
        parser.feed(raw.decode('utf-8', errors='replace'))
        content = '\n'.join(parser.parts)
    else:
        content = raw.decode('utf-8', errors='replace')
    content = text(content, 'extracted content', 1_000_000)
    return {'title': ''.join(parser.title).strip()[:300] or p.hostname, 'url': final,
            'text': content[:5000], 'rights': rights, 'evidence_type': 'fetched_excerpt',
            'truncated': len(content) > 5000, 'retrieved': time.time()}


def discover_creators(query, source='brave'):
    query = text(query, 'search query', 300)
    if source == 'brave':
        rows = search(query)
        return [{'name': r['title'][:150], 'profile_url': r['url'], 'niche': query,
                 'audience_notes': r['text'][:2000] or 'Inspect source for audience fit.',
                 'evidence_type': 'search_snippet', 'email': None} for r in rows]
    if source != 'youtube':
        raise ValueError('Discovery source must be brave or youtube.')
    key = os.environ.get('OSA_YOUTUBE_API_KEY')
    if not key:
        raise ValueError('Configure OSA_YOUTUBE_API_KEY for YouTube discovery.')
    # Credentials in a header, never in query strings or application logs.
    headers = {'X-Goog-Api-Key': key}
    data = request_json('https://www.googleapis.com/youtube/v3/search?' + urlencode(
        {'part': 'snippet', 'type': 'channel', 'q': query, 'maxResults': 15}), headers=headers)
    ids = [r['id']['channelId'] for r in data.get('items', [])]
    if not ids:
        return []
    details = request_json('https://www.googleapis.com/youtube/v3/channels?' + urlencode(
        {'part': 'snippet,statistics', 'id': ','.join(ids)}), headers=headers)
    return [{'name': r['snippet']['title'][:150], 'profile_url': 'https://www.youtube.com/channel/' + r['id'],
             'niche': query, 'audience_notes': r['snippet'].get('description', '')[:1800] or 'Review channel content.',
             'email': None, 'evidence_type': 'youtube_api', 'statistics': r.get('statistics', {})}
            for r in details.get('items', [])]


def save_lead(store, data):
    url = text(data.get('profile_url'), 'profile URL', 2048)
    public_url(url)  # URL metadata is not automatically fetched.
    clean = {'name': text(data.get('name'), 'creator name', 150), 'profile_url': url,
             'niche': text(data.get('niche'), 'niche', 500),
             'audience_notes': text(data.get('audience_notes'), 'audience evidence', 2000),
             'email': email(data['email']) if data.get('email') else None,
             'contact_basis': str(data.get('contact_basis', ''))[:1000],
             'status': data.get('status', 'review'), 'evidence_type': str(data.get('evidence_type', 'operator_notes'))[:80]}
    if clean['status'] not in ('review', 'qualified', 'declined'):
        raise ValueError('Unknown lead status.')
    if clean['status'] == 'qualified' and not clean['contact_basis'].strip():
        raise ValueError('Record a specific contact basis before qualifying a lead.')
    lid = hashlib.sha256(url.encode()).hexdigest()[:24]
    with store.connect() as db:
        db.execute('INSERT INTO leads(id,profile_url,content,updated) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content,updated=excluded.updated',
                   (lid, url, json.dumps(clean), time.time()))
    return {'id': lid, **clean}


def read_youtube(url, rights='public_reference'):
    from urllib.parse import parse_qs
    p=public_url(url)
    host=p.hostname.lower()
    vid=(p.path.strip('/') if host=='youtu.be' else parse_qs(p.query).get('v',[''])[0])
    if host in ('youtube.com','www.youtube.com') and p.path.startswith(('/live/','/shorts/')):
        vid=p.path.split('/')[2]
    if host not in ('youtube.com','www.youtube.com','youtu.be') or not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid):
        raise ValueError('Supply a valid public YouTube video URL.')
    if rights not in ('owned','licensed','permission','public_reference'):
        raise ValueError('Unknown usage basis.')
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise ValueError('Install caption support with: pip install -e .[research]') from None
    try:
        track=YouTubeTranscriptApi().fetch(vid,languages=['en'])
        excerpt=' '.join(part.text for part in track)
    except Exception:
        raise ValueError('Public English captions unavailable or access blocked. Import permissioned notes manually; do not bypass restrictions.') from None
    return {'title':'YouTube caption excerpt · '+vid,'url':'https://www.youtube.com/watch?v='+vid,
        'text':text(excerpt,'caption text',2_000_000)[:5000],'rights':rights,'evidence_type':'public_caption_excerpt',
        'truncated':len(excerpt)>5000,'retrieved':time.time()}
