"""Find a different proposal without increasing unfinished-workload imbalance."""

from collections import defaultdict
from random import Random


def alternative_pairs(pairs, candidates, load, seed=0):
    """Exchange one equal/better-load member or follow an alternating cycle.

    Every edge moves a proposed assignment to another eligible expert of the
    same project. Cycles keep all expert loads unchanged; a direct exchange
    is accepted only when it does not increase the sum of squared workloads.
    Existing assignments never appear in pairs or candidate sets.
    """
    chosen = defaultdict(set)
    for pid, eid in pairs:
        chosen[pid].add(eid)
    graph = defaultdict(dict)
    rng = Random(seed)
    projects = sorted(chosen)
    rng.shuffle(projects)
    for pid in projects:
        sources = sorted(chosen[pid])
        targets = sorted(set(candidates[pid]) - chosen[pid])
        rng.shuffle(sources)
        rng.shuffle(targets)
        for source in sources:
            for target in targets:
                if load[source] > load[target]:
                    return (pairs - {(pid, source)}) | {(pid, target)}
                graph[source].setdefault(target, pid)

    state, parent = {}, {}
    for root in sorted(graph):
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(graph[root].items()))]
        while stack:
            source, edges = stack[-1]
            edge = next(edges, None)
            if edge is None:
                state[source] = 2
                stack.pop()
                continue
            target, pid = edge
            if target not in state:
                state[target] = 1
                parent[target] = (source, pid)
                stack.append((target, iter(graph.get(target, {}).items())))
            elif state[target] == 1:
                moves = [(pid, source, target)]
                current = source
                while current != target:
                    previous, project = parent[current]
                    moves.append((project, previous, current))
                    current = previous
                return (pairs - {(p, a) for p, a, _ in moves}) | {
                    (p, b) for p, _, b in moves
                }
    return None
