from __future__ import annotations
import copy
from collections import defaultdict


def resolve_hideout(current,changes,stations,dependencies):
    maxima={s['name']:max((l['level'] for l in s['levels']),default=0) for s in stations}
    result=dict(current)
    rules={s['name']:{l['level']:l.get('requirements',[]) for l in s['levels']} for s in dependencies}
    for name,level in changes.items():
        if name not in maxima or type(level) is not int or not -1<=level<=maxima[name]:raise ValueError('Некорректный уровень модуля')
        if level<0:result.pop(name,None)
        else:result[name]=level
    visiting=set()
    def build(name,level):
        if name in visiting:raise ValueError('Циклическая зависимость модулей в справочнике')
        visiting.add(name)
        for n in range(1,level+1):
            for req in rules.get(name,{}).get(n,[]):
                other,required=req['name'],req['level']
                if other not in maxima:continue
                if result.get(other,0)<required:
                    result[other]=required;build(other,required)
        visiting.remove(name)
    for name,level in changes.items():
        if level>current.get(name,0):build(name,level)
    if any(level>=0 and level<current.get(name,0) for name,level in changes.items()):
        affected={name for name,level in changes.items() if level>=0 and level<current.get(name,0)}
        changed=True
        while changed:
            changed=False
            for name,level in list(result.items()):
                if level<=0:continue
                invalid=any(req['name'] in affected and result.get(req['name'],0)<req['level'] for n in range(1,level+1) for req in rules.get(name,{}).get(n,[]))
                if invalid:result[name]=0;affected.add(name);changed=True
    return result


class QuestProgress:
    def __init__(self,tasks,state):
        self.tasks={t['id']:t for t in tasks};self.state=state
        state.setdefault('quests',{})

    def value(self,qid):return self.state['quests'].get(qid,{'status':'locked','objectives':{}})

    def update(self,qid,status=None,objectives=None,inferred=False):
        if qid not in self.tasks:raise ValueError('Неизвестный квест')
        if status is not None and status not in ('locked','active','complete','failed'):raise ValueError('Некорректный статус квеста')
        q=self.tasks[qid];values=copy.deepcopy(self.value(qid));values.setdefault('objectives',{})
        lookup={o['id']:o for o in q['objectives']}
        for oid,progress in (objectives or {}).items():
            if oid not in lookup:raise ValueError('Неизвестный пункт квеста')
            count=progress.get('count',0);done=progress.get('done',False)
            if type(count) is not int or count<0 or type(done) is not bool:raise ValueError('Некорректный прогресс пункта')
            maximum=progress.get('target',lookup[oid].get('count') or 1)
            if type(maximum) is not int or maximum<1 or maximum>10000000:raise ValueError('Некорректная цель пункта')
            previous=values['objectives'].get(oid,{})
            values['objectives'][oid]={'count':min(count,maximum),'done':done or count>=maximum,'target':maximum}
            if 'optional' in previous:values['objectives'][oid]['optional']=previous['optional']
            if 'optional' in progress:
                if type(progress['optional']) is not bool:raise ValueError('Некорректный тип пункта')
                values['objectives'][oid]['optional']=progress['optional']
        if status is not None:values['status']=status
        elif objectives and values.get('status')=='locked':values['status']='active'
        if values.get('status')=='complete':
            for o in q['objectives']:
                if not o.get('optional'):
                    target=values['objectives'].get(o['id'],{}).get('target',o.get('count') or 1) or 1
                    values['objectives'][o['id']]={'done':True,'count':target,'target':target}
        values['inferred']=inferred
        self.state['quests'][qid]=values
        if values.get('status') in ('active','complete'):
            seen={qid}
            def parents(task):
                for req in task.get('taskRequirements',[]):
                    # Failed / alternative status gates never imply that a quest was completed.
                    parent=req.get('task')
                    if req.get('status')!=['complete'] or parent not in self.tasks or parent in seen:continue
                    seen.add(parent)
                    p=self.tasks[parent];old=copy.deepcopy(self.value(parent));old['status']='complete';old['inferred']=True
                    old.setdefault('objectives',{})
                    for o in p['objectives']:
                        if not o.get('optional'):old['objectives'][o['id']]={'done':True,'count':o.get('count') or 1,'target':o.get('count') or 1}
                    self.state['quests'][parent]=old;parents(p)
            parents(q)
        return copy.deepcopy(values)

    def targets(self,records):
        by_id={r['id']:name for name,r in records.items()};targets=defaultdict(list)
        for qid,q in self.tasks.items():
            value=self.value(qid)
            if value.get('status')!='active':continue
            for o in q['objectives']:
                progress=value.get('objectives',{}).get(o['id'],{})
                if progress.get('done'):continue
                if q['kind']=='story' and progress.get('optional',o.get('optional')):continue
                if o.get('type') not in ('findItem','giveItem','findQuestItem','giveQuestItem','plantItem','plantQuestItem','mark','useItem','buildWeapon'):continue
                remaining=max(0,(progress.get('target',o.get('count') or 1) or 1)-progress.get('count',0))
                if not remaining:continue
                for iid in o.get('items',[]):
                    if iid in by_id:targets[by_id[iid]].append({'quest_id':qid,'objective_id':o['id'],'quest':q['name_ru'],'remaining':remaining,'fir':o.get('foundInRaid',False)})
        return dict(targets)
