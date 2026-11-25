#!/usr/bin/env python3
"""Validate and standardize Apex CSV extracts without changing source files."""
import argparse
import csv
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {
 'invoices': ('Invoices_*.csv', ['source_row_id','invoice_id','vendor_id','property','invoice_date','doc_type','currency','gross_amount','supplier_ref','approval_ref'], ['invoice_id']),
 'payments': ('Payments.csv', ['payment_id','invoice_id','vendor_id','payment_date','currency','amount','bank_last4'], ['payment_id']),
 'vendors': ('Vendor_master.csv', ['vendor_id','vendor_name','category','currency'], ['vendor_id']),
 'bank_changes': ('Vendor_bank_changes.csv', ['vendor_id','requested','approved','approved_by','old_last4','new_last4'], []),
 'ledger_controls': ('Ledger_controls.csv', ['currency','period','documents','invoices_gross','payments_applied','closing_ap'], ['currency','period']),
 'rooms_sold': ('Rooms_sold.csv', ['property','property_name','month','rooms_available','rooms_sold'], ['property','month']),
}
AMOUNTS = {'gross_amount','amount','invoices_gross','payments_applied','closing_ap'}
INTEGERS = {'documents','rooms_available','rooms_sold'}
DATES = {'invoice_date','payment_date','requested','approved'}
REQUIRED = {'invoices':['source_row_id','invoice_id','vendor_id','property','invoice_date','doc_type','currency','gross_amount','supplier_ref'], 'payments':['payment_id','invoice_id','vendor_id','payment_date','currency','amount'], 'vendors':['vendor_id','vendor_name','category','currency'], 'bank_changes':['vendor_id','requested','new_last4'], 'ledger_controls':['currency','period','documents','invoices_gross','payments_applied','closing_ap'], 'rooms_sold':['property','month','rooms_available','rooms_sold']}

def write_csv(path, columns, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=ROOT/'raw')
    p.add_argument('--output', type=Path, required=True, help='New empty output directory; do not use raw')
    p.add_argument('--invoice-date-format', choices=['iso','dmy'], help='Explicit date format for all invoice files. Default: Jan/Feb 2026 DMY; March 2026 ISO only.')
    args=p.parse_args(); source=args.input.resolve(); out=args.output.resolve()
    if out == source or source in out.parents or out in source.parents:
        p.error('Output must be separate from the source directory.')
    if out.exists() and any(out.iterdir()): p.error('Output directory must be new or empty; existing files will not be overwritten.')
    records={}; issues=[]
    def issue(dataset,row,field,code,detail,severity='error'):
        issues.append({'dataset':dataset,'source_file':row['source_file'],'source_line':row['source_line'],'source_row_id':row.get('original_source_row_id',''),'field':field,'code':code,'severity':severity,'detail':detail})
        if severity=='error': row['_invalid']=True
    for name,(pattern,columns,key) in SCHEMAS.items():
        files=sorted(source.glob(pattern))
        if not files: raise ValueError(f'Missing input for {name}: {pattern}')
        rows=[]
        for file in files:
            with file.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.DictReader(f)
                if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not set(columns).issubset(reader.fieldnames):
                    raise ValueError(f'{file.name}: missing or duplicate headers; expected {columns}')
                for line,raw in enumerate(reader,2):
                    if None in raw: raise ValueError(f'{file.name} line {line}: extra CSV fields')
                    row={'source_file':file.name,'source_line':line,'_invalid':False}
                    for col in columns:
                        val=raw.get(col) or ''; row['original_'+col]=val; row[col]=val.strip()
                    for col in REQUIRED[name]:
                        if not row[col]: issue(name,row,col,'missing_required','Required value is blank')
                    if 'vendor_id' in row and row['vendor_id']:
                        v=row['vendor_id']
                        if not v.isdigit() or len(v)>5: issue(name,row,'vendor_id','invalid_vendor_id','Expected up to five numeric digits')
                        else: row['vendor_id']=v.zfill(5)
                    for col in ('property','currency','doc_type'):
                        if col in row: row[col]=row[col].upper()
                    for col in DATES.intersection(columns):
                        if not row[col]: continue
                        fmt='%Y-%m-%d'
                        if col=='invoice_date':
                            if args.invoice_date_format: fmt='%d/%m/%Y' if args.invoice_date_format=='dmy' else '%Y-%m-%d'
                            elif file.name in ('Invoices_2026-01.csv','Invoices_2026-02.csv'): fmt='%d/%m/%Y'
                            elif file.name!='Invoices_2026-03.csv':
                                issue(name,row,col,'unknown_date_format','Provide --invoice-date-format after confirming the source format'); continue
                        try: row[col]=datetime.strptime(row[col],fmt).date().isoformat()
                        except ValueError: issue(name,row,col,'invalid_date',f'Expected valid date in {fmt}')
                    for col in AMOUNTS.intersection(columns):
                        if not row[col]: continue
                        value=row[col]
                        if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?',value):
                            issue(name,row,col,'invalid_amount','Expected number with optional valid thousands separators and up to two decimals'); continue
                        try: row[col]=format(Decimal(value.replace(',','')),'.2f')
                        except InvalidOperation: issue(name,row,col,'invalid_amount','Cannot parse amount')
                    for col in INTEGERS.intersection(columns):
                        if row[col] and not row[col].isdigit(): issue(name,row,col,'invalid_integer','Expected nonnegative whole number')
                    for col in ('bank_last4','old_last4','new_last4'):
                        if col in row and row[col] and not re.fullmatch(r'\d{4}',row[col]): issue(name,row,col,'invalid_bank_last4','Expected exactly four digits')
                    if name=='invoices' and row['doc_type'] not in ('INV','CRN'): issue(name,row,'doc_type','invalid_document_type','Expected INV or CRN')
                    if name=='invoices' and not row['approval_ref']: issue(name,row,'approval_ref','missing_approval','Approval reference absent; investigate', 'warning')
                    if name=='rooms_sold' and row['rooms_sold'].isdigit() and row['rooms_available'].isdigit() and int(row['rooms_sold'])>int(row['rooms_available']): issue(name,row,'rooms_sold','rooms_exceed_capacity','Rooms sold exceeds rooms available')
                    rows.append(row)
        if key:
            counts=Counter(tuple(row[k] for k in key) for row in rows if all(row[k] for k in key))
            for row in rows:
                if all(row[k] for k in key) and counts[tuple(row[k] for k in key)]>1: issue(name,row,','.join(key),'duplicate_key','All records with this key require review')
        records[name]=rows
    vendors={r['vendor_id'] for r in records['vendors'] if not r['_invalid']}
    invoices={r['invoice_id'] for r in records['invoices'] if not r['_invalid']}
    for name in ('invoices','payments','bank_changes'):
        for row in records[name]:
            if row['vendor_id'] and row['vendor_id'] not in vendors: issue(name,row,'vendor_id','vendor_not_in_valid_master','No unique valid vendor master match','warning')
            if name=='payments' and row['invoice_id'] and row['invoice_id'] not in invoices: issue(name,row,'invoice_id','invoice_not_in_valid_invoices','No unique valid invoice match; check quarantine','warning')
    out.mkdir(parents=True,exist_ok=True)
    for name,(_,cols,_) in SCHEMAS.items():
        fields=['source_file','source_line']+cols+['original_'+c for c in cols]
        write_csv(out/f'{name}_clean.csv',fields,[r for r in records[name] if not r['_invalid']])
        write_csv(out/f'{name}_quarantine.csv',fields,[r for r in records[name] if r['_invalid']])
    write_csv(out/'issues.csv',['dataset','source_file','source_line','source_row_id','field','code','severity','detail'],issues)
    summary=[{'dataset':k,'input_rows':len(v),'clean_rows':sum(not r['_invalid'] for r in v),'quarantined_rows':sum(r['_invalid'] for r in v)} for k,v in records.items()]
    write_csv(out/'row_counts.csv',['dataset','input_rows','clean_rows','quarantined_rows'],summary)
    for r in summary: print(f"{r['dataset']}: {r['input_rows']} input = {r['clean_rows']} clean + {r['quarantined_rows']} quarantined")
    print(f'{len(issues)} issue entries. Review issues.csv before using the clean files.')

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,csv.Error) as e: print(f'Error: {e}',file=sys.stderr); sys.exit(1)
