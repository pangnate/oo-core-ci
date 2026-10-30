#!/usr/bin/env python3
"""Require actual compilation vs exact binary reuse in staged Linux validation."""
import argparse
import json
from pathlib import Path


def validate(directory, target, phase):
    def read(name):
        matches = list(directory.rglob(f'{name}-{target}.json'))
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one {name} receipt')
        return json.loads(matches[0].read_text())
    reuse = read('core-reuse')
    producer = read('core-producer')
    metrics = read('build-metrics')
    if reuse.get('coreId') != producer.get('coreId') or metrics.get('exitCode') != 0:
        raise ValueError('Missing successful matching Core evidence')
    if phase == 'reuse':
        if reuse.get('reused') is not True:
            raise ValueError('Expected exact Core binary reuse, not recompilation')
        if list(directory.rglob(f'compiler-cache-quality-{target}.json')):
            raise ValueError('Binary reuse must skip compiler cache pipeline')
    else:
        if reuse.get('reused') is not False:
            raise ValueError('Forced compilation unexpectedly reused Core binary')
        quality, saved, restored = (read(n) for n in
                                   ('compiler-cache-quality', 'compiler-cache-saved', 'compiler-cache-restore'))
        if (quality.get('status') != 'passed' or quality.get('daemonStopped') is not True
                or quality.get('backend') != 'disk' or quality.get('requests', 0) <= 0
                or quality['hits'] + quality['misses'] != quality['requests']
                or saved.get('status') != 'passed'):
            raise ValueError('Missing successful disk compilation and confirmed save')
        if phase == 'warm' and (restored.get('status') != 'restored' or restored.get('coreId') != reuse['coreId']
                                or quality['hits'] <= 0):
            raise ValueError('Warm validation requires restored bytes and real compiler hits')
    return {'status': 'passed', 'phase': phase, 'target': target, 'coreId': reuse['coreId']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--target', choices=('linux_64', 'linux_arm64'), required=True)
    parser.add_argument('--phase', choices=('cold', 'warm', 'reuse'), required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.directory, args.target, args.phase)))
