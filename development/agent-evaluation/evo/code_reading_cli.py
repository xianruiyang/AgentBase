from __future__ import annotations

import json
from pathlib import Path

from .code_reading_catalog import import_catalog
from .spec import EvoError

ACTIONS = {'code-reading-import'}


def add_commands(commands):
    command = commands.add_parser('code-reading-import', help='freeze prepared code-reading snapshots and task answers')
    command.add_argument('--source', type=Path, required=True)
    command.add_argument('--snapshot-root', type=Path, required=True)
    command.add_argument('--output', type=Path, required=True)


def handle(args):
    if args.output.exists():
        raise EvoError('code-reading import output already exists')
    catalog = import_catalog(args.source, args.snapshot_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(catalog, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    return {'schema': 'agentbase-evo-code-reading-import/v1', 'output': str(args.output.resolve()),
            'id': catalog['id'], 'item_count': len(catalog['items']),
            'required_locations': sum(len(item['required_locations']) for item in catalog['items']),
            'queued': False, 'executed': False}
