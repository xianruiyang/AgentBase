from __future__ import annotations

from pathlib import Path

from .skill_cache import SkillCache


ACTIONS = {'skill-cache-status', 'skill-cache-prune'}


def add_commands(commands):
    status = commands.add_parser('skill-cache-status', help='validate and inspect fixed Evo skill payload versions')
    status.add_argument('--project-root', type=Path, required=True)
    status.add_argument('--state-root', type=Path, required=True)
    prune = commands.add_parser('skill-cache-prune', help='remove one explicitly identified unreferenced skill version')
    prune.add_argument('--project-root', type=Path, required=True)
    prune.add_argument('--state-root', type=Path, required=True)
    prune.add_argument('--version', required=True, help='short version alias from skill-cache-status')


def handle(args):
    cache = SkillCache(args.project_root, args.state_root)
    if args.action == 'skill-cache-status':
        return {**cache.status(), 'operation': args.action}
    identity = cache.remove_unreferenced_alias(args.version)
    return {'schema': 'agentbase-evo-skill-cache-prune/v1', 'operation': args.action,
            'version': args.version, 'identity_sha256': identity, 'removed': True}
