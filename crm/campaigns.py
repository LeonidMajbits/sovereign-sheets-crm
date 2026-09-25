"""Campaign membership and sequential-plan mutations, called only by Work."""
from .codec import integer
from .errors import Conflict


def membership(w,p):
    cid,eid=p['campaign_id'],p['entity_id']
    w.get(cid,kind='campaign'); row=w.get(eid)
    if row['entity_kind']=='campaign': raise Conflict('CAMPAIGN_NESTING_NOT_ALLOWED')
    w.depend(cid,('status',),('memberships',)); w.depend(eid,guards=('memberships',))
    existing=w.c.execute('SELECT * FROM campaign_memberships WHERE tenant_id=? AND campaign_id=? AND entity_id=?',(w.tenant,cid,eid)).fetchone()
    if not p['present'] and p['is_primary']: raise Conflict('REMOVAL_CANNOT_BE_PRIMARY')
    if p['present']:
        if existing and existing['is_primary']==int(p['is_primary']): return
        if p['is_primary']:
            previous=w.c.execute('SELECT campaign_id FROM campaign_memberships WHERE tenant_id=? AND entity_id=? AND is_primary=1',(w.tenant,eid)).fetchall()
            for r in previous:
                w.depend(r[0],guards=('memberships',));w.guard(r[0],'memberships')
            w.c.execute('UPDATE campaign_memberships SET is_primary=0 WHERE tenant_id=? AND entity_id=?',(w.tenant,eid))
        if existing:
            w.c.execute('UPDATE campaign_memberships SET is_primary=? WHERE tenant_id=? AND campaign_id=? AND entity_id=?',(int(p['is_primary']),w.tenant,cid,eid))
        else:
            w.insert('campaign_memberships',dict(tenant_id=w.tenant,campaign_id=cid,entity_id=eid,is_primary=int(p['is_primary']),joined_commit_seq=w.seq))
    else:
        if not existing:return
        w.c.execute('DELETE FROM campaign_memberships WHERE tenant_id=? AND campaign_id=? AND entity_id=?',(w.tenant,cid,eid))
    w.edit(eid,('campaign_memberships',));w.guard(eid,'memberships');w.guard(cid,'memberships')
    w.add_event('campaign.membership',p,eid)


def select_plan(w,p):
    eid=p['project_id']; version=integer(p['plan_version'],1)
    w.get(eid,kind='project');w.depend(eid,('active_plan_version','status'),('work_items',))
    facet=w.facet(eid)
    if facet['active_plan_version']==version:return
    rows=w.c.execute("SELECT w.*,e.status,e.deleted_at FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.project_id=? AND w.plan_version=? AND w.entity_kind='stage' ORDER BY stage_ordinal",(w.tenant,eid,version)).fetchall()
    if not rows or [r['stage_ordinal'] for r in rows]!=list(range(1,len(rows)+1)) or any(r['deleted_at'] for r in rows):
        raise Conflict('PLAN_NOT_CONTIGUOUS')
    if facet['active_plan_version']:
        open_old=w.c.execute("SELECT 1 FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.project_id=? AND w.plan_version=? AND e.deleted_at IS NULL AND e.status NOT IN ('completed','cancelled') LIMIT 1",(w.tenant,eid,facet['active_plan_version'])).fetchone()
        if open_old: raise Conflict('OLD_PLAN_UNFINISHED')
    w.update_facet(eid,{'active_plan_version':version});w.guard(eid,'work_items')


def assert_complete(w,eid):
    row=w.get(eid)
    if row['entity_kind']=='project':
        w.depend(eid,('active_plan_version',),('work_items',)); f=w.facet(eid)
        if f['active_plan_version']==0: raise Conflict('NO_SELECTED_PLAN')
        rows=w.c.execute("SELECT e.status,w.required FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.project_id=? AND w.plan_version=? AND e.deleted_at IS NULL",(w.tenant,eid,f['active_plan_version'])).fetchall()
        if not rows or any(r['required'] and r['status']!='completed' for r in rows):raise Conflict('PROJECT_WORK_UNFINISHED')
    elif row['entity_kind']=='campaign':
        w.depend(eid,guards=('memberships',))
        rows=w.c.execute('SELECT e.* FROM campaign_memberships m JOIN entities e ON e.tenant_id=m.tenant_id AND e.entity_id=m.entity_id WHERE m.tenant_id=? AND m.campaign_id=?',(w.tenant,eid)).fetchall()
        for r in rows:
            if r['deleted_at']: continue
            w.depend(r['entity_id'],('status',))
            if r['entity_kind'] in ('project','stage','ticket') and r['status']!='completed':raise Conflict('CAMPAIGN_WORK_UNFINISHED')
    elif row['entity_kind']=='stage':
        w.depend(eid,guards=('children',))
        if w.c.execute("SELECT 1 FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.parent_work_item_id=? AND e.deleted_at IS NULL AND e.status!='completed' LIMIT 1",(w.tenant,eid)).fetchone():raise Conflict('STAGE_CHILDREN_UNFINISHED')
