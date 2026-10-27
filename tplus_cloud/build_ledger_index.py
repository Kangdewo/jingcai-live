"""Build public, de-identified date index from already reviewed daily ticket-ledger JSONs.

No scraping, no result inference, no private tickets, no independent AI score promotions.
Every amount derives from auditable ticket-level values. A day with missing/unfinished
settlement is excluded from cumulative ROI until a trusted, complete record arrives.
"""
from __future__ import annotations
import json
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'docs/data/ledger/days'
DEST = ROOT/'docs/data/ledger/index.json'


def validate_day(obj: dict, filename_date: str) -> dict:
    dt.date.fromisoformat(filename_date)
    if obj.get('schema_version') != 'TPlusLedgerDay.4' or obj.get('date_bjt') != filename_date:
        raise ValueError('DAY_SCHEMA_OR_DATE_MISMATCH:'+filename_date)
    if obj.get('not_formal_ai_evaluation') is not True:
        raise ValueError('SOURCE_CATEGORY_NOT_DECLARED:'+filename_date)
    tickets = obj.get('tickets')
    if not isinstance(tickets,list):
        raise ValueError('TICKETS_MUST_BE_ARRAY:'+filename_date)
    names = [x['id'] for x in tickets]
    if len(names) != len(set(names)):
        raise ValueError('DUPLICATE_TICKET_ID:'+filename_date)
    for t in tickets:
        if t.get('attribution_quality') not in ('unattributed','partial_selection_only','group_only','ticket_plan_association','provisional_only','verified_individual'):
            raise ValueError('UNRECOGNIZED_MODEL_ATTRIBUTION:'+filename_date)
        if float(t.get('stake',-1)) != int(t.get('bet_count',-1))*2:
            raise ValueError('STAKE_VS_BET_UNIT_DISAGREEMENT:'+filename_date)
        if t.get('winning_bets') is not None and not (0 <= int(t['winning_bets']) <= int(t.get('bet_count',-1))):
            raise ValueError('INVALID_WINNING_UNITS:'+filename_date)
        if float(t['stake']) < 0 or (t.get('theoretical_return') is not None and float(t['theoretical_return']) < 0):
            raise ValueError('NEGATIVE_TICKET_VALUE:'+filename_date)
        if t.get('theoretical_return') is not None and t.get('theoretical_net') is not None and abs(float(t['theoretical_net'])-(float(t['theoretical_return'])-float(t['stake'])))>0.015:
            raise ValueError('TICKET_NET_MISMATCH:'+filename_date)
    summary=obj.get('summary')
    if summary is None:
        if tickets:raise ValueError('TICKET_EXISTS_BUT_MISSING_SUMMARY:'+filename_date)
        return {'date_bjt':filename_date,'status':'pending','summary':None}
    if not isinstance(summary,dict) or summary.get('cashout_verified') is not False:
        raise ValueError('INVALID_SETTLEMENT_CLASSIFICATION:'+filename_date)
    if summary.get('fully_reconciled') is not True:
        if int(summary.get('tickets',-1))!=len(tickets) or int(summary.get('bet_units',-1))!=sum(int(t['bet_count']) for t in tickets) or abs(float(summary.get('stake_cny',-1))-sum(float(t['stake']) for t in tickets))>0.015:
            raise ValueError('PENDING_TICKET_TOTAL_MISMATCH:'+filename_date)
        if summary.get('theoretical_return_cny') is not None or summary.get('theoretical_net_cny') is not None:
            raise ValueError('PENDING_MUST_NOT_HAVE_SETTLEMENT_VALUE:'+filename_date)
        return {'date_bjt':filename_date,'status':'pending_settlement','summary':{'tickets':len(tickets),'bet_units':sum(int(t['bet_count']) for t in tickets),'stake_cny':round(sum(float(t['stake']) for t in tickets),2),'theoretical_return_cny':None,'theoretical_net_cny':None,'fully_reconciled':False}}
    if any(t.get('theoretical_return') is None or t.get('theoretical_net') is None or t.get('winning_bets') is None for t in tickets):
        raise ValueError('FULL_SETTLEMENT_MISSING_TICKET_RESULT:'+filename_date)
    expected={'tickets':len(tickets),'bet_units':sum(int(t['bet_count']) for t in tickets),
              'winning_units':sum(int(t['winning_bets']) for t in tickets),
              'stake_cny':round(sum(float(t['stake']) for t in tickets),2),
              'theoretical_return_cny':round(sum(float(t['theoretical_return']) for t in tickets),2)}
    expected['theoretical_net_cny']=round(expected['theoretical_return_cny']-expected['stake_cny'],2)
    for k,v in expected.items():
        if abs(float(summary.get(k, -999999))-v)>0.015:
            raise ValueError('SUMMARY_VS_TICKETS_MISMATCH:'+filename_date+':'+k)
    if expected['stake_cny'] <= 0:
        raise ValueError('FULLY_RECONCILED_WITHOUT_STAKE:'+filename_date)
    return {'date_bjt':filename_date,'status':'reviewed_theoretical','summary':expected}


def build(folder:Path=FOLDER,dest:Path=DEST)->dict:
    rows=[]
    for f in sorted(folder.glob('????-??-??.json')):
        obj=json.loads(f.read_text(encoding='utf-8-sig'))
        ent=validate_day(obj,f.stem)
        ent['path']='data/ledger/days/'+f.name
        rows.append(ent)
    stake=returned=0
    cumulative=[]
    for row in rows:
        s=row['summary']
        if s is not None and row['status']=='reviewed_theoretical':
            stake+=s['stake_cny'];returned+=s['theoretical_return_cny']
            cumulative.append({'date_bjt':row['date_bjt'],'stake_cny':round(stake,2),'theoretical_return_cny':round(returned,2),'net_cny':round(returned-stake,2)})
    summary={'settled_days':len(cumulative),'stake_cny':round(stake,2),'theoretical_return_cny':round(returned,2),'net_cny':round(returned-stake,2),
             'roi_pct':round((returned-stake)/stake*100,4) if stake else None,'cashout_verified':False}
    out={'schema_version':'TPlusLedgerIndex.4','date_basis':'Asia/Shanghai issue date, not kickoff date','currency':'CNY','scope':'audited theoretical ticket accounting; independent AI metrics separate',
         'dates':rows,'cumulative':summary,'cumulative_points':cumulative,
         'privacy':'never publish names, ticket photos, barcodes, tokens, identifying fingerprints',
         'rules':['Only ticket-complete settled days enter ROI','Missing/pending days are not zero-return or zero-stake days','No individual-model ROI without ticket-plan ID/time evidence','No post-match edits to originally frozen records','Formal TPlus dual-source evaluation.json is separate']}
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return out

if __name__=='__main__':
    o=build()
    print('Ledger index:',len(o['dates']),'dates, cumulative',o['cumulative'])
