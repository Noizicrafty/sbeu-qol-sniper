"""Screen observations, never loot acquisition guesses or per-frame additions."""
from __future__ import annotations

import copy


def intersects(a, b):
    x,y,w,h=a; X,Y,W,H=b
    return max(0,min(x+w,X+W)-max(x,X))*max(0,min(y+h,Y+H)-max(y,Y)) > min(w*h,W*H)*.25


class RaidInventory:
    def __init__(self):
        self.reset()

    def reset(self):
        self.tracks = []
        self.items = None
        self.signature = None
        self.stable = 0
        self.last_at = None

    def observe(self, hits, analysis, at):
        if not analysis.get('panel_visible', bool(hits)):
            return False
        waiting = analysis.get('waiting', [])
        # Retain previously observed contents only where the screen is currently occluded.
        retained = [old for old in self.tracks if any(intersects(old['box'], box) for box in waiting)
                    and not any(intersects(old['box'], hit['box']) for hit in hits)]
        current = retained + [hit for hit in hits if not hit.get('ambiguous') and hit.get('name')]
        aggregate = {}
        for hit in current:
            value = aggregate.setdefault(hit['name'], {'count': 0, 'fir': 0})
            count = hit.get('count', 1)
            value['count'] += count
            value['fir'] += count if hit.get('fir') == 'yes' else 0
        signature = tuple(sorted((name,value['count'],value['fir']) for name,value in aggregate.items()))
        self.stable = self.stable+1 if signature == self.signature else 1
        self.signature = signature
        if self.stable < 2:
            return False
        changed = aggregate != self.items
        self.items, self.tracks, self.last_at = aggregate, copy.deepcopy(current), at
        return changed


class RevealQueue:
    def __init__(self):
        self.regions = {}
        self.revealed = {}

    def observe(self, kind, hits, analysis):
        previous = self.regions.get(kind, [])
        newly = sum(any(intersects(box, hit['box']) for hit in hits) for box in previous)
        self.revealed[kind] = self.revealed.get(kind, 0)+newly
        if analysis.get('panel_visible', bool(hits)):
            self.regions[kind] = copy.deepcopy(analysis.get('waiting', []))
        return {'waiting': len(self.regions.get(kind, [])), 'revealed': self.revealed.get(kind, 0)}
