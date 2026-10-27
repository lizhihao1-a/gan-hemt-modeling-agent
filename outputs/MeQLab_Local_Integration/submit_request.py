"""Read one JSON request from stdin and send it to the local session host."""
from pathlib import Path
import argparse
import json
import sys
import time
import uuid


def issue_request(session_dir, request, request_id=None, wait=5):
    root = Path(session_dir)
    name = request_id or uuid.uuid4().hex
    if not name.replace('_', '').replace('-', '').isalnum():
        raise ValueError('Request id must be alphanumeric, underscore or hyphen')
    inbox = root / 'commands' / (name + '.json')
    outbox = root / 'responses' / (name + '.json')
    if inbox.exists():
        raise FileExistsError('Request id already exists; do not replay mutations')
    temp = inbox.with_suffix('.tmp')
    temp.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    temp.replace(inbox)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and not outbox.exists():
        time.sleep(0.15)
    if outbox.exists():
        return json.loads(outbox.read_text(encoding='utf-8'))
    return {'status': 'pending', 'response_file': str(outbox)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session-dir', required=True)
    parser.add_argument('--id')
    parser.add_argument('--wait', type=float, default=5)
    parser.add_argument('--max-chars', type=int, default=7000)
    args = parser.parse_args()
    request = json.loads(sys.stdin.read().lstrip('\ufeff'))
    result = issue_request(args.session_dir, request, args.id, args.wait)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if result.get('status') != 'pending':
        print(text[:args.max_chars])
        if len(text) > args.max_chars:
            print('Full response is saved in the session responses directory')
    else:
        print(text)


if __name__ == '__main__':
    main()
