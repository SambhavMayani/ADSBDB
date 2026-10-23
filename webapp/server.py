"""Loopback-only web UI. Read-only media and bounded, serialized CPU queries."""
from __future__ import annotations
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import logging
import mimetypes
import os
import threading
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).with_name('static')
LOGGER = logging.getLogger('ecosentinel.web')
MAX_BODY = 14 * 1024 * 1024


def validate_key(key):
    parts = PurePosixPath(key).parts
    if len(parts) != 3 or parts[0] not in ('images', 'audio', 'text') or '..' in parts or '\\' in key:
        raise ValueError('Invalid media reference')
    return key


def query_upload(payload):
    data = base64.b64decode(payload.get('data', ''), validate=True)
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError('Upload must be 1 byte–10 MB')
    modality = payload.get('modality')
    if modality == 'images':
        from PIL import Image
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('Image exceeds 20 megapixels')
            image.verify()
    elif modality == 'audio':
        import soundfile as sf
        with sf.SoundFile(BytesIO(data)) as audio:
            if audio.frames / audio.samplerate > 30:
                raise ValueError('Audio query exceeds 30 seconds')
    else:
        raise ValueError('Invalid upload modality')
    return data


def make_handler(service, media_loader=None):
    jobs = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(60)

        def log_message(self, fmt, *args):
            LOGGER.info('%s %s', self.command, urlsplit(self.path).path)

        def reply(self, body, content_type='application/json; charset=utf-8', status=200):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def safe_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.safe_host():
                self.reply({'error': 'Invalid host'}, status=403)
                return
            parsed = urlsplit(self.path)
            try:
                if parsed.path == '/api/status':
                    self.reply({'collections': service.status(), 'device': 'cpu', 'index_mode': 'snapshot'})
                elif parsed.path == '/api/media':
                    key = validate_key(parse_qs(parsed.query).get('key', [''])[0])
                    if media_loader is None:
                        raise ValueError('Media store is unavailable')
                    data, kind = media_loader(key)
                    self.reply(data, kind)
                else:
                    filenames = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
                    filename = filenames.get(parsed.path)
                    if filename is None:
                        self.reply({'error': 'Not found'}, status=404)
                        return
                    self.reply((STATIC / filename).read_bytes(), mimetypes.guess_type(filename)[0] + '; charset=utf-8')
            except (ValueError, KeyError):
                self.reply({'error': 'Invalid or unavailable media reference'}, status=400)
            except Exception:
                LOGGER.exception('Read request failed')
                self.reply({'error': 'Storage unavailable; see the local server log'}, status=503)

        def do_POST(self):
            if not jobs.acquire(blocking=False):
                self.reply({'error': 'Another CPU query is running; try again shortly'}, status=429)
                return
            try:
                self.handle_post()
            finally:
                jobs.release()

        def handle_post(self):
            origin = self.headers.get('Origin')
            if not self.safe_host() or (origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')):
                self.reply({'error': 'Invalid origin'}, status=403)
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.reply({'error': 'JSON required'}, status=415)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                path = urlsplit(self.path).path
                limit = payload.get('limit', 8)
                if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                    raise ValueError('Limit must be 1–50')
                species = payload.get('species') or None
                if species is not None and (not isinstance(species, str) or len(species) > 100):
                    raise ValueError('Invalid species filter')
                if path == '/api/search':
                    result = service.text(payload.get('query'), mode=payload.get('mode', 'multimodal'),
                                          limit=limit, species=species, modality=payload.get('filter') or None)
                elif path == '/api/similar':
                    result = service.by_record(payload.get('id'), payload.get('space'), limit=limit,
                                               species=species, modality=payload.get('filter') or None,
                                               same_modality=bool(payload.get('same_modality')),
                                               mixed=bool(payload.get('mixed')))
                elif path == '/api/upload':
                    data = query_upload(payload)
                    result = service.media(data, payload['modality'], mixed=bool(payload.get('mixed')), limit=limit, species=species)
                elif path == '/api/describe':
                    from multimodal_tasks.generate import describe
                    data = query_upload({**payload, 'modality': 'images'})
                    # No implicit network downloads from a web request.
                    with service.lock:
                        service.encoders.release_all()
                    result = describe(data, service, limit=limit)
                else:
                    self.reply({'error': 'Not found'}, status=404)
                    return
                self.reply({'results': result})
            except (ValueError, TypeError, KeyError) as exc:
                self.reply({'error': str(exc)[:200]}, status=400)
            except Exception:
                LOGGER.exception('Query failed')
                self.reply({'error': 'Query unavailable. Check local model cache and server logs.'}, status=503)
    return Handler


def load_media(key):
    from exploitation_zone.source import TrustedRepository, create_minio_client
    repository = TrustedRepository(create_minio_client(), os.getenv('ECOSENTINEL_TRUSTED_BUCKET', 'trusted-zone'))
    info = repository.source_info(key)
    if info['size'] > 200 * 1024 * 1024:
        raise ValueError('Media exceeds serving size limit')
    return repository.get(key), {'images': 'image/jpeg', 'audio': 'audio/flac', 'text': 'text/plain; charset=utf-8'}[key.split('/')[0]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--index', type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    from multimodal_tasks.search import SearchService
    service = SearchService(args.index)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    with ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(service, load_media)) as server:
        server.daemon_threads = True
        server.timeout = 60
        print(f'EcoSentinel local: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
