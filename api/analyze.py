from http.server import BaseHTTPRequestHandler
from datetime import date
from decimal import Decimal, InvalidOperation
from collections import defaultdict, Counter
import csv, io, json

LIMIT=3_000_000

def parse_csv(text, required, name):
    if not isinstance(text,str) or not text.strip(): raise ValueError(f'{name} is required, including its header if it has no data rows.')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff'),newline=''))
    if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not required.issubset(reader.fieldnames):
        raise ValueError(f'{name} is missing required headers: {", ".join(sorted(required-set(reader.fieldnames or [])))}')
    rows=list(reader)
    if any(None in r or any(v is None for v in r.values()) for r in rows): raise ValueError(f'{name} contains malformed CSV rows.')
    return rows

def amount(s):
    try:
        n=Decimal(s)
        if not n.is_finite() or n.as_tuple().exponent < -2: raise ValueError('Invalid currency amount')
        return n
    except (InvalidOperation,TypeError): raise ValueError('Invalid numeric amount in cleaned file')

def analyze(data):
    cutoff=date.fromisoformat(data.get('as_of',''))
    inv=parse_csv(data.get('invoices'),{'invoice_id','vendor_id','property','invoice_date','doc_type','currency','gross_amount'},'invoices_clean.csv')
    pay=parse_csv(data.get('payments'),{'payment_id','invoice_id','vendor_id','payment_date','currency','amount'},'payments_clean.csv')
    iq=parse_csv(data.get('invoice_quarantine'),{'invoice_id'},'invoices_quarantine.csv')
    pq=parse_csv(data.get('payment_quarantine'),{'payment_id'},'payments_quarantine.csv')
    vendors=parse_csv(data['vendors'],{'vendor_id','vendor_name'},'vendors_clean.csv') if data.get('vendors','').strip() else []
    vendor_names={}
    for v in vendors:
        key=v['vendor_id'].strip()
        if not key or key in vendor_names: raise ValueError('Vendor IDs in the master must be present and unique.')
        vendor_names[key]=v['vendor_name'].strip() or key
    for rows,key,label in [(inv,'invoice_id','invoice'),(pay,'payment_id','payment')]:
        keys=[r[key].strip() for r in rows]
        if '' in keys or any(n>1 for n in Counter(keys).values()): raise ValueError(f'Clean {label} IDs must be present and unique. Run data cleaning first.')
    payments=defaultdict(list)
    for p in pay:
        if not p['invoice_id'].strip() or not p['vendor_id'].strip() or not p['currency'].strip(): raise ValueError('Payments require invoice ID, vendor ID, and currency.')
        if date.fromisoformat(p['payment_date'])<=cutoff:
            amount(p['amount']); payments[p['invoice_id']].append(p)
    ids={i['invoice_id'] for i in inv}; unlinked=[p for k,ps in payments.items() if k not in ids for p in ps]
    detail=[]; totals=defaultdict(lambda:defaultdict(lambda:[0,Decimal('0')]))
    for i in inv:
        if any(not i[x].strip() for x in ('invoice_id','vendor_id','currency','property')): raise ValueError('Invoices require ID, vendor, currency, and property.')
        when=date.fromisoformat(i['invoice_date']); gross=amount(i['gross_amount'])
        if i['doc_type'] not in ('INV','CRN'): raise ValueError('Document type must be INV or CRN.')
        if when>cutoff: continue
        ps=payments.get(i['invoice_id'],[]); age=(cutoff-when).days
        mismatch=any(p['vendor_id']!=i['vendor_id'] or p['currency']!=i['currency'] for p in ps)
        paid=sum((amount(p['amount']) for p in ps),Decimal('0')) if not mismatch else None
        balance=gross-paid if paid is not None else None
        if mismatch: status='Review: vendor or currency mismatch'
        elif i['doc_type']=='CRN' or gross<0: status='Credit note - review allocation'
        elif balance>0: status='Open >30 days' if age>30 else 'Open 0-30 days'
        elif balance<0: status='Overpaid - review'
        else: status='Settled'
        if balance is not None:
            t=totals[i['currency']][status];t[0]+=1;t[1]+=balance
        detail.append({'invoice_id':i['invoice_id'],'vendor_id':i['vendor_id'],'vendor_name':vendor_names.get(i['vendor_id'], i['vendor_id']),'property':i['property'],'invoice_date':i['invoice_date'],'age_days':age,'doc_type':i['doc_type'],'currency':i['currency'],'invoice_amount':str(gross),'payment_count':len(ps),'payment_total':str(paid) if paid is not None else '', 'balance':str(balance) if balance is not None else '', 'status':status,'source_file':i.get('source_file',''),'source_row_id':i.get('source_row_id','')})
    charts=chart_data(detail)
    return {'charts':charts, 'as_of':cutoff.isoformat(),'summary':{cur:{s:{'count':n,'balance':str(b)} for s,(n,b) in cats.items()} for cur,cats in totals.items()},'detail':detail,'quarantined_invoices':len(iq),'quarantined_payments':len(pq),'unmatched_payments':len(unlinked),'mismatch_invoices':sum(x['status'].startswith('Review:') for x in detail)}


def chart_data(detail):
    """Outstanding positive invoices only; aggregate separately by currency."""
    ranges=['0–30','31–60','61–90','91–120','121+']
    buckets=defaultdict(lambda: {name:[0,Decimal('0')] for name in ranges})
    suppliers=defaultdict(lambda:defaultdict(lambda:[0,Decimal('0')]))
    for row in detail:
        if row['status'] not in ('Open >30 days','Open 0-30 days'): continue
        cur=row['currency']; age=row['age_days']; balance=Decimal(row['balance'])
        bucket=ranges[0 if age<=30 else 1 if age<=60 else 2 if age<=90 else 3 if age<=120 else 4]
        buckets[cur][bucket][0]+=1; buckets[cur][bucket][1]+=balance
        key=(row['vendor_id'],row['vendor_name']); suppliers[cur][key][0]+=1; suppliers[cur][key][1]+=balance
    charts={}
    for cur in sorted(buckets):
        top=sorted(suppliers[cur].items(),key=lambda x:(-x[1][1],x[0][0]))[:10]
        charts[cur]={'aging':[{'bucket':k,'count':buckets[cur][k][0],'balance':str(buckets[cur][k][1])} for k in ranges],
          'suppliers':[{'vendor_id':k[0],'vendor_name':k[1],'count':v[0],'balance':str(v[1])} for k,v in top]}
    return charts

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>LIMIT: raise ValueError('Input must be less than 3 MB.')
            result=analyze(json.loads(self.rfile.read(size)))
            body=json.dumps(result).encode(); self.send_response(200)
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
            body=json.dumps({'error':str(e)}).encode(); self.send_response(400)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Analyze cleaned invoices and payments as at a selected date.')
    parser.add_argument('--input',required=True,type=Path,help='Folder containing the four cleaned and quarantine CSV files')
    parser.add_argument('--as-of',required=True,help='Date YYYY-MM-DD')
    parser.add_argument('--output',type=Path,help='Save analysis JSON to this path')
    args=parser.parse_args()
    files={'invoices':'invoices_clean.csv','payments':'payments_clean.csv','invoice_quarantine':'invoices_quarantine.csv','payment_quarantine':'payments_quarantine.csv'}
    payload={'as_of':args.as_of, **{k:(args.input/v).read_text(encoding='utf-8-sig') for k,v in files.items()}}
    vendor_file=args.input/'vendors_clean.csv'
    if vendor_file.exists(): payload['vendors']=vendor_file.read_text(encoding='utf-8-sig')
    output=json.dumps(analyze(payload),indent=2,ensure_ascii=False)
    if args.output: args.output.write_text(output,encoding='utf-8')
    else: print(output)
