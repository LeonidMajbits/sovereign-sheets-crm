"""Frozen kind mappings and lifecycle graphs."""
FACETS = {
 'person':('patrons','patron_id'), 'organization':('patrons','patron_id'),
 'campaign':('campaigns','campaign_id'), 'project':('projects','project_id'),
 'stage':('work_items','work_item_id'), 'ticket':('work_items','work_item_id'),
 'opportunity':('commercial_records','commercial_id'), 'contract':('commercial_records','commercial_id'),
 'thread':('communication_threads','thread_id'), 'dispatch':('dispatch_attempts','dispatch_id')}
INITIAL = {'person':'lead','organization':'lead','campaign':'active','project':'active',
           'stage':'queued','ticket':'queued','opportunity':'lead','contract':'draft','thread':'open','dispatch':'queued'}
GRAPHS = {
 'person': {'lead':{'engaged','closed'},'engaged':{'closed'},'closed':{'engaged'}},
 'campaign': {'active':{'shelved','completed'},'shelved':{'active'},'completed':{'active'}},
 'stage': {'queued':{'running','blocked','cancelled'},'running':{'blocked','completed','cancelled'},'blocked':{'queued','running','cancelled'}},
 'opportunity': {'lead':{'qualified','lost'},'qualified':{'proposed','lost'},'proposed':{'won','lost'}},
 'contract': {'draft':{'signed','terminated'},'signed':{'fulfilled','terminated'}},
 'thread': {'open':{'closed'},'closed':{'open'}},
 'dispatch': {'queued':{'cooking','cancelled'},'cooking':{'harvested','error','unknown','cancelled'},'unknown':{'harvested','error','cancelled'}}}
GRAPHS['organization']=GRAPHS['person']; GRAPHS['project']=GRAPHS['campaign']; GRAPHS['ticket']=GRAPHS['stage']
TERMINAL = {'campaign':{'shelved','completed'},'project':{'shelved','completed'},
 'stage':{'completed','cancelled'},'ticket':{'completed','cancelled'},'opportunity':{'won','lost'},
 'contract':{'fulfilled','terminated'},'dispatch':{'harvested','error','cancelled'}}

def wire(obj):
    if type(obj) is int: return str(obj)
    if type(obj) is float: return format(obj,'.12g')
    if type(obj) is dict: return {k:wire(v) for k,v in obj.items()}
    if type(obj) in (list,tuple): return [wire(v) for v in obj]
    return obj

def effective_patron(c,tenant,eid):
    """Follow explicit reviewed merges; never infer identity from names/channels."""
    seen=set()
    for _ in range(32):
        if eid in seen:raise ValueError('merge cycle')
        seen.add(eid)
        row=c.execute('SELECT entity_id,display_name,deleted_at,merged_into_id FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,eid)).fetchone()
        if not row:return None
        if row['merged_into_id']:eid=row['merged_into_id'];continue
        return dict(row) if not row['deleted_at'] else None
    raise ValueError('merge depth')

def predecessors(c,tenant,eid,limit=128):
    found={eid};front=[eid]
    while front:
        cur=front.pop()
        for r in c.execute('SELECT entity_id FROM entities WHERE tenant_id=? AND merged_into_id=?',(tenant,cur)):
            if r[0] not in found:found.add(r[0]);front.append(r[0])
            if len(found)>limit:raise ValueError('merge fan-out')
    return sorted(found)
