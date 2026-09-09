"""Task-only Windows SWE catalogs; execution choices belong to the research spec."""
from __future__ import annotations

import copy
from pathlib import Path

from evaluation_core import EvaluationError, load_corpus, sha256_file
from .spec import EvoError, read_json


CATALOG_SCHEMA = 'agentbase-evo-swe-catalog/v1'


def import_corpus(corpus_path: Path) -> dict:
    """Only read task metadata; no model/profile, environment, selection or execution."""
    path = corpus_path.resolve()
    try:
        corpus = load_corpus(path)
        digest = sha256_file(path)
    except (EvaluationError, OSError) as exc:
        raise EvoError(str(exc)) from exc
    return {
        'schema': CATALOG_SCHEMA, 'id': corpus['id'], 'version': '1',
        'source': {'corpus_id': corpus['id'], 'corpus_sha256': digest, 'leaderboard_comparable': False},
        'items': [{'id': task['id'], 'family': task['repository'], 'input_version': digest,
                   'protocol': 'windows-swe-candidate-patch-verifier/v1'}
                  for task in corpus['tasks']],
        'groups': [{'id': identity, 'items': list(members)} for identity, members in corpus['suites'].items()]}


def load_catalog(path: Path, expected_sha256: str | None = None, *, corpus_path: Path | None = None) -> dict:
    try:
        if expected_sha256 is not None and sha256_file(path) != expected_sha256:
            raise EvoError('SWE catalog changed; update the explicit research catalog binding')
        catalog = read_json(path)
        if catalog.get('schema') != CATALOG_SCHEMA:
            raise EvoError(f'SWE catalog schema must be {CATALOG_SCHEMA}')
        if set(catalog) != {'schema', 'id', 'version', 'source', 'items', 'groups'}:
            raise EvoError('SWE catalog contains fields outside the task contract')
        source = catalog.get('source', {})
        if (not isinstance(source, dict) or set(source) != {'corpus_id', 'corpus_sha256', 'leaderboard_comparable'}
                or source['corpus_id'] != catalog['id'] or source['leaderboard_comparable'] is not False):
            raise EvoError('SWE catalog source must identify its corpus and Windows-derived scope')
        digest = source['corpus_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise EvoError('SWE catalog corpus_sha256 must be SHA-256')
        if not isinstance(catalog['items'], list) or not isinstance(catalog['groups'], list):
            raise EvoError('SWE catalog items/groups must be arrays')
        for item in catalog['items']:
            if (not isinstance(item, dict) or set(item) != {'id', 'family', 'input_version', 'protocol'}
                    or item['input_version'] != digest
                    or item['protocol'] != 'windows-swe-candidate-patch-verifier/v1'
                    or not isinstance(item['family'], str) or not item['family']):
                raise EvoError('SWE catalog item must contain only fixed task metadata')
        if any(not isinstance(group, dict) or set(group) != {'id', 'items'} for group in catalog['groups']):
            raise EvoError('SWE catalog groups must contain only id/items')
        from .spec import COMPONENT_KINDS, SPEC_SCHEMA, validate_spec
        validate_spec({'schema': SPEC_SCHEMA, 'id': catalog['id'], 'version': catalog['version'],
                       'components': {kind: [] for kind in COMPONENT_KINDS}, 'combinations': [],
                       'evaluations': {'items': catalog['items'], 'groups': catalog['groups']},
                       'fields': [], 'scoring': []})
        # An execution's environment resolves the corpus. Never bake its host path into the catalog.
        if corpus_path is not None and catalog != import_corpus(corpus_path):
            raise EvoError('SWE catalog is stale or edited; regenerate it from the local corpus with swe-import')
        return catalog
    except (KeyError, TypeError, OSError, EvaluationError) as exc:
        raise EvoError(f'invalid SWE catalog: {exc}') from exc


def resolve_catalog(spec: dict, spec_path: Path) -> dict:
    """Materialize a research reference for freezing; never modify its source files."""
    evaluations = spec.get('evaluations')
    if not isinstance(evaluations, dict) or 'catalog' not in evaluations:
        return spec
    if set(evaluations) - {'catalog', 'observations'}:
        raise EvoError('evaluations.catalog cannot coexist with inline items/groups')
    binding = evaluations['catalog']
    if not isinstance(binding, dict) or set(binding) != {'source', 'sha256'}:
        raise EvoError('evaluations.catalog requires source and sha256')
    if not all(isinstance(binding[key], str) and binding[key] for key in ('source', 'sha256')):
        raise EvoError('catalog source and sha256 must be nonempty strings')
    path = (spec_path.parent / binding['source']).resolve()
    runtime = spec.get('runtime', {})
    if not isinstance(runtime, dict):
        raise EvoError('research runtime must be an object')
    runtime_swe = runtime.get('swe', {})
    if not isinstance(runtime_swe, dict):
        raise EvoError('research runtime.swe must be an object')
    corpus_path = None
    if 'corpus' in runtime_swe:
        if not isinstance(runtime_swe['corpus'], str):
            raise EvoError('research runtime.swe.corpus must be an absolute path')
        corpus_path = Path(runtime_swe['corpus'])
        if not corpus_path.is_absolute():
            raise EvoError('research runtime.swe.corpus must be absolute')
    catalog = load_catalog(path, binding['sha256'], corpus_path=corpus_path)
    result = copy.deepcopy(spec)
    result['evaluations'] = {'items': [], 'groups': copy.deepcopy(catalog['groups'])}
    for item in catalog['items']:
        result['evaluations']['items'].append({**item,
            'observations': copy.deepcopy(evaluations.get('observations', [])), 'runtime': {'swe': {
            **copy.deepcopy(runtime_swe),
            'corpus_sha256': catalog['source']['corpus_sha256'], 'task': item['id']}}})
    result['catalog_source'] = {'source': str(path), 'sha256': binding['sha256']}
    return result
