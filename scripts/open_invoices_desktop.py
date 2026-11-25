#!/usr/bin/env python3
"""Open invoice report at a selected date; run normally for a local graphical window."""
import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
import argparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / '04_Outputs' / 'clean_run_2026_11_25'

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def report(folder, cutoff):
    invoices=read(folder/'invoices_clean.csv'); payments=read(folder/'payments_clean.csv')
    quarantine=read(folder/'invoices_quarantine.csv')
    try: payment_quarantine=read(folder/'payments_quarantine.csv')
    except FileNotFoundError: payment_quarantine=[]
    by_id=defaultdict(list)
    for p in payments:
        if date.fromisoformat(p['payment_date']) <= cutoff: by_id[p['invoice_id']].append(p)
    known={i['invoice_id'] for i in invoices}; unlinked=[p for key,rows in by_id.items() if key not in known for p in rows]
    rows=[]; totals=defaultdict(lambda:defaultdict(lambda: [0,Decimal('0')]))
    for i in invoices:
        when=date.fromisoformat(i['invoice_date'])
        if when>cutoff: continue
        ps=by_id.get(i['invoice_id'],[])
        if any(p['currency']!=i['currency'] or p['vendor_id']!=i['vendor_id'] for p in ps):
            status='REVIEW: payment vendor/currency mismatch'; paid=None; balance=None
        else:
            paid=sum((Decimal(p['amount']) for p in ps),Decimal('0'))
            balance=Decimal(i['gross_amount'])-paid
            if i['doc_type']=='CRN' or Decimal(i['gross_amount'])<0: status='Credit note - review allocation'
            elif balance>0: status='Open >30 days' if (cutoff-when).days>30 else 'Open 0-30 days'
            elif balance<0: status='Overpaid - review'
            else: status='Settled'
        age=(cutoff-when).days
        if balance is not None:
            cell=totals[i['currency']][status];cell[0]+=1;cell[1]+=balance
        rows.append({'as_of_date':cutoff.isoformat(),'invoice_id':i['invoice_id'],'vendor_id':i['vendor_id'],'property':i['property'],'invoice_date':i['invoice_date'],'age_days':age,'doc_type':i['doc_type'],'currency':i['currency'],'invoice_amount':i['gross_amount'],'payment_count_to_date':len(ps),'payment_amount_to_date':f'{paid:.2f}' if paid is not None else '', 'balance':f'{balance:.2f}' if balance is not None else '', 'status':status,'source_file':i['source_file'],'source_row_id':i['source_row_id']})
    return rows,totals,len(quarantine),len(payment_quarantine),len(unlinked)

def summary(rows,totals,qi,qp,unlinked,cutoff):
    lines=[f'Open invoices at {cutoff.isoformat()}','Age is calendar days since invoice date; >30 means 31 days or more.','']
    for cur in sorted(totals):
        lines.append(cur)
        for label in ('Open >30 days','Open 0-30 days','Settled','Overpaid - review','Credit note - review allocation'):
            n,amount=totals[cur][label]
            lines.append(f'  {label}: {n} invoices; balance {amount:,.2f}')
    lines += ['',f'Invoice rows quarantined and excluded: {qi}',f'Payment rows quarantined and excluded: {qp}',f'Payments by cutoff without a unique clean invoice: {unlinked}',f'Invoices with payment vendor/currency mismatch: {sum(r["status"].startswith("REVIEW") for r in rows)}','', 'Results use the supplied extracts and are not reconciled to the general ledger. Age is not overdue days; due dates are unavailable. Credits are not netted against other invoices.']
    return '\n'.join(lines)

def save(path,rows):
    fields=['as_of_date','invoice_id','vendor_id','property','invoice_date','age_days','doc_type','currency','invoice_amount','payment_count_to_date','payment_amount_to_date','balance','status','source_file','source_row_id']
    with open(path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def gui():
    window=tk.Tk();window.title('Apex | Open invoices');window.geometry('780x660')
    frm=ttk.Frame(window,padding=20);frm.pack(fill='both',expand=True)
    ttk.Label(frm,text='Open invoices by date',font=('Arial',20,'bold')).pack(anchor='w')
    ttk.Label(frm,text='Select the folder containing the cleaned invoice and payment CSV files.').pack(anchor='w',pady=(10,4))
    folder=tk.StringVar(value=str(DEFAULT)); line=ttk.Frame(frm);line.pack(fill='x')
    ttk.Entry(line,textvariable=folder).pack(side='left',fill='x',expand=True)
    ttk.Button(line,text='Choose folder',command=lambda:folder.set(filedialog.askdirectory() or folder.get())).pack(side='left',padx=6)
    date_row=ttk.Frame(frm);date_row.pack(fill='x',pady=12);ttk.Label(date_row,text='As of date (YYYY-MM-DD):').pack(side='left'); asof=tk.StringVar(value='2026-03-31');ttk.Entry(date_row,textvariable=asof,width=15).pack(side='left',padx=8)
    box=tk.Text(frm,height=20,wrap='word');box.pack(fill='both',expand=True); state={'rows':None}
    def run():
        try:
            d=date.fromisoformat(asof.get());rows,tot,qi,qp,u=report(Path(folder.get()),d);state['rows']=rows
            box.delete('1.0','end');box.insert('1.0',summary(rows,tot,qi,qp,u,d))
        except Exception as e: state['rows']=None;messagebox.showerror('Unable to create report',str(e))
    def export():
        if state['rows'] is None: messagebox.showinfo('Run report first','Select a date and click Run report.');return
        path=filedialog.asksaveasfilename(title='Save invoice detail',defaultextension='.csv',initialfile='open_invoice_detail.csv',filetypes=[('CSV files','*.csv')])
        if path:
            try: save(path,state['rows']);messagebox.showinfo('Saved',f'Saved to {path}')
            except OSError as e: messagebox.showerror('Unable to save',str(e))
    buttons=ttk.Frame(frm);buttons.pack(fill='x',pady=12);ttk.Button(buttons,text='Run report',command=run).pack(side='left');ttk.Button(buttons,text='Save invoice detail CSV',command=export).pack(side='left',padx=8)
    window.mainloop()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--as-of');p.add_argument('--input',type=Path,default=DEFAULT);p.add_argument('--output',type=Path);args=p.parse_args()
    if args.as_of:
        d=date.fromisoformat(args.as_of);rows,tot,qi,qp,u=report(args.input,d);print(summary(rows,tot,qi,qp,u,d))
        if args.output: save(args.output,rows)
    else: gui()
