from __future__ import annotations

import json
from pathlib import Path

from .spec import EvoError
from .swe_catalog import import_corpus


ACTIONS = {'swe-import'}


def add_commands(commands):
    command = commands.add_parser('swe-import', help='import a local task-only SWE catalog without queueing or execution')
    command.add_argument('--corpus', type=Path, required=True)
    command.add_argument('--output', type=Path, required=True)


def handle(args):
    if args.output.exists():
        raise EvoError('SWE import output already exists; choose a new local catalog path')
    catalog = import_corpus(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(catalog, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    return {'schema': 'agentbase-evo-swe-import/v1', 'output': str(args.output.resolve()),
            'id': catalog['id'], 'item_count': len(catalog['items']),
            'groups': [{'id': g['id'], 'items': len(g['items'])} for g in catalog['groups']],
            'queued': False, 'executed': False}
