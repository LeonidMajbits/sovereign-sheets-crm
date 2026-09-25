"""Bounded lexical retrieval over approved content; ranking is not identity proof."""
from __future__ import annotations
import json, re, time, sqlite3
from .codec import text, normalize_name, ULID_RE
from .errors import CRMError,Conflict
from .model import wire, effective_patron, predecessors


def refresh_entities(c,tenant,ids,seq):
    generation=c.execute('SELECT search_generation FROM ledger_state').fetchone()[0]
    for eid in sorted(ids):
        e=c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,eid)).fetchone()
        if not e:continue
        old=c.execute('SELECT search_doc_id FROM entity_search_documents WHERE tenant_id=? AND entity_id=?',(tenant,eid)).fetchone()
        if old:
            c.execute('DELETE FROM entity_fts WHERE rowid=?',(old[0],));c.execute('DELETE FROM name_grams WHERE tenant_id=? AND search_doc_id=?',(tenant,old[0]))
        if e['deleted_at']:
            # Stable integer mapping is retained; current FTS document is removed.
            continue
        aliases=[r[0] for r in c.execute('SELECT original_value FROM entity_aliases WHERE tenant_id=? AND entity_id=? AND retired_at IS NULL ORDER BY alias_id',(tenant,eid))]
        for prior in predecessors(c,tenant,eid):
            if prior==eid:continue
            aliases.append(c.execute('SELECT display_name FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,prior)).fetchone()[0])
            aliases.extend(r[0] for r in c.execute('SELECT original_value FROM entity_aliases WHERE tenant_id=? AND entity_id=? AND retired_at IS NULL ORDER BY alias_id',(tenant,prior)))
        tags=[r[0] for r in c.execute('SELECT tag FROM entity_tags WHERE tenant_id=? AND entity_id=? ORDER BY tag',(tenant,eid))]
        alias_text='\n'.join(aliases+tags)
        org=c.execute('SELECT e.display_name FROM patrons p JOIN entities e ON e.tenant_id=p.tenant_id AND e.entity_id=p.organization_id WHERE p.tenant_id=? AND p.patron_id=? AND e.deleted_at IS NULL',(tenant,eid)).fetchone()
        fields={'tenant_id':tenant,'entity_id':eid,'entity_kind':e['entity_kind'],'display_name':e['display_name'],'aliases':alias_text,'organization_name':org[0] if org else '', 'summary':e['note'] or '', 'next_action':e['next_action'] or '', 'source_entity_rev':e['entity_rev'],'source_projection_seq':seq,'search_generation':generation}
        if len(alias_text.encode())>4096 or sum(len(fields[k].encode()) for k in ('display_name','aliases','organization_name','summary','next_action'))>8192:raise CRMError('SEARCH_DOCUMENT_TOO_LARGE')
        if old:
            docid=old[0];keys=list(fields)
            c.execute('UPDATE entity_search_documents SET '+','.join(k+'=?' for k in keys)+' WHERE search_doc_id=?',(*fields.values(),docid))
        else:
            cur=c.execute('INSERT INTO entity_search_documents('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(fields.values()));docid=cur.lastrowid
        c.execute('INSERT INTO entity_fts(rowid,'+','.join(fields)+') VALUES('+','.join('?' for _ in range(len(fields)+1))+')',(docid,*fields.values()))
        grams=set()
        for name in [e['display_name'],*aliases]:
            n=normalize_name(name)
            grams.update(n[i:i+3] for i in range(max(0,len(n)-2)))
        if len(grams)>2048:raise CRMError('NAME_GRAM_LIMIT')
        c.executemany('INSERT INTO name_grams VALUES(?,?,?,?)',((tenant,'nfkc-casefold-ws-v1',g,docid) for g in sorted(grams)))


def refresh_interactions(c,tenant,renamed,seq,ids=(),limit=128):
    targets=set(ids)
    for eid in renamed:
        for r in c.execute('SELECT interaction_id FROM interactions WHERE tenant_id=? AND (patron_id=? OR thread_id=?) LIMIT ?',(tenant,eid,eid,limit+1)):targets.add(r[0])
    if len(targets)>limit:raise CRMError('INTERACTION_REFRESH_FANOUT_LIMIT')
    gen=c.execute('SELECT search_generation FROM ledger_state').fetchone()[0]
    for iid in sorted(targets):
        r=c.execute('SELECT * FROM interactions WHERE tenant_id=? AND interaction_id=?',(tenant,iid)).fetchone()
        old=c.execute('SELECT search_doc_id FROM interaction_search_documents WHERE tenant_id=? AND interaction_id=?',(tenant,iid)).fetchone()
        if old:c.execute('DELETE FROM interaction_fts WHERE rowid=?',(old[0],))
        if not r or r['record_kind']=='retraction' or c.execute('SELECT 1 FROM interactions WHERE tenant_id=? AND supersedes_interaction_id=?',(tenant,iid)).fetchone():continue
        patron=effective_patron(c,tenant,r['patron_id'])
        if not patron:continue
        f={'tenant_id':tenant,'interaction_id':iid,'patron_id':patron['entity_id'],'communication_thread_id':r['thread_id'],'subject':r['subject'],'participants':patron['display_name'],'summary':r['summary'] or '', 'excerpt':r['approved_excerpt'] or '', 'occurred_at':r['occurred_at'],'recorded_at':r['recorded_at'],'source_commit_seq':seq,'search_generation':gen}
        if sum(len(f[k].encode()) for k in ('subject','participants','summary','excerpt'))>8192:raise CRMError('SEARCH_DOCUMENT_TOO_LARGE')
        if old:
            did=old[0];c.execute('UPDATE interaction_search_documents SET '+','.join(k+'=?' for k in f)+' WHERE search_doc_id=?',(*f.values(),did))
        else:
            cur=c.execute('INSERT INTO interaction_search_documents('+','.join(f)+') VALUES('+','.join('?' for _ in f)+')',tuple(f.values()));did=cur.lastrowid
        c.execute('INSERT INTO interaction_fts(rowid,'+','.join(f)+') VALUES('+','.join('?' for _ in range(len(f)+1))+')',(did,*f.values()))


def compile_query(value):
    text(value,256)
    tokens=re.findall(r'[^\W_]+',value,flags=re.UNICODE)
    if not tokens or len(tokens)>8:raise CRMError('QUERY_TOKEN_LIMIT')
    # Every token is quoted. User operators/column selectors never reach MATCH.
    return ' AND '.join('"'+x.replace('"','""')+'"' for x in tokens)


def distance(a,b,max_distance=None):
    if max_distance is not None:
        # Exact unit-cost Levenshtein inside the admitted edit band. A returned
        # cutoff+1 means outside the band, not a fabricated exact larger distance.
        cap=max_distance;inf=cap+1
        if abs(len(a)-len(b))>cap:return inf
        prev={j:j for j in range(min(len(b),cap)+1)}
        for i,x in enumerate(a,1):
            cur={0:i} if i<=cap else {}
            for j in range(max(1,i-cap),min(len(b),i+cap)+1):
                cur[j]=min(cur.get(j-1,inf)+1,prev.get(j,inf)+1,prev.get(j-1,inf)+(x!=b[j-1]))
            if min(cur.values(),default=inf)>cap:return inf
            prev=cur
        return min(prev.get(len(b),inf),inf)
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]


def search(c,tenant,query,*,scope='entities',limit=20,fuzzy=False,budget_ms=25):
    """Cooperative query budget; never return a truncated answer as complete.

    The private broker serializes connection ownership, so installing/restoring
    this per-connection progress hook cannot interrupt another command.
    This is not a hard OS scheduling deadline or a sub-millisecond guarantee.
    """
    deadline=time.monotonic_ns()+int(budget_ms*1_000_000)
    c.set_progress_handler(lambda:int(time.monotonic_ns()>=deadline),1000)
    try:
        result=_search(c,tenant,query,scope=scope,limit=limit,fuzzy=fuzzy)
        if time.monotonic_ns()>=deadline:raise CRMError('QUERY_BUDGET','Refine the query; no partial answer was returned.',10)
        return result
    except sqlite3.OperationalError as exc:
        if 'interrupted' in str(exc).lower():raise CRMError('QUERY_BUDGET','Refine the query; no partial answer was returned.',10) from exc
        raise
    finally:c.set_progress_handler(None,0)


def _search(c,tenant,query,*,scope='entities',limit=20,fuzzy=False):
    if type(limit) is not int or not 1<=limit<=20:raise CRMError('QUERY_LIMIT')
    if scope not in ('entities','interactions') or (fuzzy and scope!='entities'):raise CRMError('QUERY_SCOPE')
    text(query,256)
    if scope=='entities' and query.startswith(('email:','domain:','phone:')):
        kind,value=query.split(':',1);extension=None
        if kind in ('email','domain'):
            import idna
            domain=value if kind=='domain' else value.rsplit('@',1)[-1]
            try:domain=idna.encode(domain.rstrip('.').lower(),uts46=False).decode().lower()
            except (idna.IDNAError,UnicodeError) as exc:raise CRMError('INVALID_DOMAIN') from exc
            if kind=='email':
                if value.count('@')!=1 or not value.split('@')[0]:raise CRMError('INVALID_EMAIL')
                normalized=value.rsplit('@',1)[0]+'@'+domain
            else:normalized=domain
        else:
            from .errors import Unsupported
            try:import phonenumbers
            except ImportError:raise Unsupported('PHONE_NORMALIZER_UNAVAILABLE','Install the optional maintained phone parser.')
            if not value.startswith('+'):raise CRMError('PHONE_QUERY_REQUIRES_INTERNATIONAL_FORM')
            try:
                parsed=phonenumbers.parse(value,None)
                if not phonenumbers.is_possible_number(parsed):raise ValueError()
                normalized=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.E164);extension=parsed.extension or None
            except Exception as exc:raise CRMError('INVALID_PHONE') from exc
        rows=c.execute('SELECT patron_id FROM contact_channels WHERE tenant_id=? AND channel_kind=? AND normalized_value=? AND extension IS ? AND retired_at IS NULL ORDER BY patron_id LIMIT ?',
                       (tenant,kind,normalized,extension,limit+1)).fetchall()
        matches={}
        for row in rows:
            item=effective_patron(c,tenant,row['patron_id'])
            if item:matches[item['entity_id']]=dict(item)
        return {'matches':[matches[k] for k in sorted(matches)[:limit]],'match_mode':'channel_candidates',
                'truncated_candidates':len(rows)>limit,'identity_merge_permitted':False}
    compiled=compile_query(query)
    if scope=='entities' and ULID_RE.fullmatch(query):
        r=c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=? AND deleted_at IS NULL',(tenant,query)).fetchone()
        return {'matches':[dict(r)] if r else [],'match_mode':'exact_id','truncated_candidates':False}
    if scope=='entities':
        exact=c.execute("SELECT DISTINCT e.* FROM entity_aliases a JOIN entities e ON e.tenant_id=a.tenant_id AND e.entity_id=a.entity_id WHERE a.tenant_id=? AND a.normalizer_version='nfkc-casefold-ws-v1' AND a.normalized_key=? AND a.retired_at IS NULL AND e.deleted_at IS NULL ORDER BY e.entity_id LIMIT ?",(tenant,normalize_name(query),limit)).fetchall()
        if exact:return {'matches':[dict(x) for x in exact],'match_mode':'alias_candidates','truncated_candidates':False}
        rows=c.execute('''SELECT e.entity_id,e.entity_kind,e.display_name,e.status,e.entity_rev,
             d.source_projection_seq,d.search_generation,bm25(entity_fts,0,0,0,5,3,2,1,1,0,0,0) score
             FROM entity_fts JOIN entity_search_documents d ON d.search_doc_id=entity_fts.rowid
             JOIN entities e ON e.tenant_id=d.tenant_id AND e.entity_id=d.entity_id
             WHERE entity_fts MATCH ? AND e.tenant_id=? AND e.deleted_at IS NULL
             ORDER BY score,e.entity_id LIMIT ?''',(compiled,tenant,limit)).fetchall()
    else:
        rows=c.execute('''SELECT i.interaction_id,i.patron_id,d.patron_id resolved_patron_id,i.subject,i.occurred_at,d.source_commit_seq,d.search_generation,
            bm25(interaction_fts,0,0,0,0,2,2,1,1,0,0,0,0) score FROM interaction_fts
            JOIN interaction_search_documents d ON d.search_doc_id=interaction_fts.rowid
            JOIN interactions i ON i.tenant_id=d.tenant_id AND i.interaction_id=d.interaction_id
            JOIN entities e ON e.tenant_id=d.tenant_id AND e.entity_id=d.patron_id
            WHERE interaction_fts MATCH ? AND i.tenant_id=? AND e.deleted_at IS NULL
              AND i.record_kind!='retraction' AND NOT EXISTS(SELECT 1 FROM interactions n WHERE n.tenant_id=i.tenant_id AND n.supersedes_interaction_id=i.interaction_id)
            ORDER BY score,i.interaction_id LIMIT ?''',(compiled,tenant,limit)).fetchall()
    if rows or not fuzzy:return {'matches':[dict(x) for x in rows],'match_mode':'fts5','truncated_candidates':False}
    q=normalize_name(query)
    if len(q)<5:return {'matches':[],'match_mode':'bounded_fuzzy','truncated_candidates':False}
    grams=sorted(set(q[i:i+3] for i in range(len(q)-2)))
    counts=[]
    for g in grams:
        count=c.execute('SELECT count(*) FROM name_grams WHERE tenant_id=? AND normalizer_version=? AND gram=?',(tenant,'nfkc-casefold-ws-v1',g)).fetchone()[0]
        if count:counts.append((count,g))
    candidates={};truncated=False
    for n,g in sorted(counts)[:4]:
        truncated |= n>128
        for r in c.execute('SELECT search_doc_id FROM name_grams WHERE tenant_id=? AND normalizer_version=? AND gram=? ORDER BY search_doc_id LIMIT 128',(tenant,'nfkc-casefold-ws-v1',g)):
            candidates[r[0]]=candidates.get(r[0],0)+1
    truncated |= len(candidates)>64
    scored=[]
    for did in sorted(candidates,key=lambda k:(-candidates[k],k))[:64]:
        r=c.execute('SELECT d.*,e.status,e.entity_rev,e.deleted_at FROM entity_search_documents d JOIN entities e ON e.tenant_id=d.tenant_id AND e.entity_id=d.entity_id WHERE d.tenant_id=? AND d.search_doc_id=?',(tenant,did)).fetchone()
        if not r or r['deleted_at']:continue
        # Tags assist lexical retrieval but do not become person-name evidence.
        names=[r['display_name']]+[x[0] for x in c.execute(
            'SELECT original_value FROM entity_aliases WHERE tenant_id=? AND entity_id=? AND retired_at IS NULL',
            (tenant,r['entity_id']))]
        best=None
        for value in names:
            candidate=normalize_name(value);width=max(len(q),len(candidate))
            if not width:continue
            maxedits=1 if len(q)<10 else 2;floor=0.80 if len(q)<10 else 0.85
            dist=distance(q,candidate,maxedits);similarity=1-dist/width
            if dist>maxedits or similarity<floor:continue
            a,b=set(q.split()),set(candidate.split());jaccard=len(a&b)/len(a|b) if a|b else 0.0
            key=(-similarity,-jaccard,r['entity_id'])
            if best is None or key<best:best=key
        if best is not None:
            result=dict(r);result['name_similarity']=format(-best[0],'.6f')
            scored.append((*best,result))
    return {'matches':[x[3] for x in sorted(scored,key=lambda x:x[:3])[:limit]],'match_mode':'bounded_fuzzy_candidates','truncated_candidates':truncated,'candidate_count':len(candidates)}
