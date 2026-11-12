from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path


def normalized(text: str) -> str:
    return re.sub(r'[^\w]+', ' ', text.casefold()).strip()


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


class State:
    def __init__(self, path: Path):
        self.path = path
        self.value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        for key in ('levels', 'inventory', 'regions'):
            self.value.setdefault(key, {})
        for key, default in {'manual': {}, 'active_targets': {}, 'published': [],
                             'all_levels': False, 'published_at': None,
                             'threshold': .88, 'slot_size': 64, 'interval': .05}.items():
            self.value.setdefault(key, default)
        self.value.setdefault('hideout_fir_required', True)
        for key, default in {'overlay_labels': True, 'overlay_outlines': True, 'protect_surplus': True,
                             'snapshot_scopes': {}, 'color_needed': '#9cdc61', 'color_surplus': '#7f8790',
                             'color_uncertain': '#ffbc57', 'color_other': '#72b9eb'}.items():
            self.value.setdefault(key, default)

    def save(self):
        save_json(self.path, self.value)

    def snapshot_scope(self, slot):
        return self.value['snapshot_scopes'].get(slot, 'character' if any(word in slot.casefold() for word in ('персонаж','character','рейд','raid')) else 'stash')

    def owned(self, fir=False, raid_inventory=None):
        total = Counter()
        for slot, snapshot in self.value['inventory'].items():
            if self.snapshot_scope(slot) == 'character' and (raid_inventory is not None or not self.value['protect_surplus']):
                continue
            for name, value in snapshot.items():
                total[name] += (value.get('fir' if fir else 'count', 0) if isinstance(value, dict)
                                else (0 if fir else value))
        if raid_inventory is not None and self.value['protect_surplus']:
            for name, value in raid_inventory.items():
                total[name] += value['fir' if fir else 'count']
        return total

    def needed(self, catalog, all_levels=False, include_manual=True, raid_inventory=None):
        required = Counter()
        fir_required = Counter()
        uses = {}
        for station in catalog.get('stations', []):
            # Unknown stations are deliberately excluded until the user confirms a level.
            if station['name'] not in self.value['levels']:
                continue
            current = self.value['levels'][station['name']]
            for upgrade in station['levels']:
                if upgrade['level'] <= current or (not all_levels and upgrade['level'] != current + 1):
                    continue
                for item in upgrade['items']:
                    required[item['name']] += item['count']
                    if item.get('fir') and self.value['hideout_fir_required']:
                        fir_required[item['name']] += item['count']
                    uses.setdefault(item['name'], []).append(f"{station['name']} {upgrade['level']}")
        if include_manual:
            for name, target in self.value['manual'].items():
                required[name] += target['count']
                if target.get('fir'):
                    fir_required[name] += target['count']
                uses.setdefault(name, []).append('Ручной поиск')
        owned = self.owned(raid_inventory=raid_inventory)
        fir_owned = self.owned(fir=True, raid_inventory=raid_inventory)
        return {name: {'required': count, 'owned': owned[name],
                       'fir_required': fir_required[name], 'fir_owned': fir_owned[name],
                       'remaining': max(0, count - owned[name], fir_required[name] - fir_owned[name]), 'uses': uses[name]}
                for name, count in required.items()}
