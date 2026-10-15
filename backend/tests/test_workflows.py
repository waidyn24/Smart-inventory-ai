"""Integration tests with ephemeral SQLite DB. PostgreSQL row-lock concurrency needs separate integration testing."""
import os,tempfile,uuid
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import select,func

_dbfile=Path(tempfile.gettempdir())/f'smart_inventory_pytest_{os.getpid()}.db'
os.environ['DATABASE_URL']='sqlite:///'+str(_dbfile)
os.environ['DEMO_PASSWORD']='Demo2026!'
from fastapi.testclient import TestClient
from app.db import Base,engine,SessionLocal
from app.main import app,ph
from app.seed import fill
from app import models as m,engine as decision

@pytest.fixture(scope='module')
def client():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:fill(db)
    with TestClient(app) as c:
        resp=c.post('/auth/login',json={'email':'owner@demo.kz','password':'Demo2026!'})
        assert resp.status_code==200,resp.text
        c.headers['X-CSRF-Token']=resp.json()['csrf']
        yield c
    engine.dispose()
    _dbfile.unlink(missing_ok=True)

def choose(client):return next(x for x in client.get('/products').json() if x['name']=='Вода 1.5 л')
def key():return str(uuid.uuid4())
def stock(client,pid):return next(x['on_hand'] for x in client.get('/products').json() if x['id']==pid)

def test_01_create_product_barcode(client):
    r=client.post('/products',json={'name':'Тестовый батончик','sku':'TEST-ABC','barcode':'2990000000008','category':'Снеки','price':650,'cost':400})
    assert r.status_code==201,r.text
    assert client.get('/products/by-barcode/2990000000008').json()['sku']=='TEST-ABC'
    assert client.get('/products/by-barcode/https://example.org').status_code==400

def test_02_sale_ledger_atomic(client):
    p=choose(client);start=stock(client,p['id'])
    sales_count=len(client.get('/sales').json())
    r=client.post('/sales',json={'items':[{'product_id':p['id'],'quantity':3}],'idempotency_key':'unit-sale-02'})
    assert r.status_code==201,r.text
    assert stock(client,p['id'])==start-3
    assert len(client.get('/sales').json())==sales_count+1
    with SessionLocal() as db:
        sale=db.get(m.Sale,r.json()['id'])
        moves=db.scalars(select(m.StockMovement).where(m.StockMovement.source_id==sale.id)).all()
        assert sum(Decimal(x.signed_quantity) for x in moves)==-3

def test_03_return_ledger(client):
    pid=choose(client)['id'];sale=client.get('/sales').json()[0]
    start=stock(client,pid)
    r=client.post(f'/sales/{sale["id"]}/return',json={'items':[{'product_id':pid,'quantity':1}],'idempotency_key':'unit-return-03'})
    assert r.status_code==200,r.text
    assert stock(client,pid)==start+1
    with SessionLocal() as db:assert db.scalars(select(m.SaleReturnItem)).first() is not None

def test_04_idempotent_sale(client):
    p=choose(client);before=stock(client,p['id']);payload={'items':[{'product_id':p['id'],'quantity':1}],'idempotency_key':'unit-once-04'}
    first=client.post('/sales',json=payload);second=client.post('/sales',json=payload)
    assert first.status_code==201 and second.status_code==201
    assert second.json()['replayed'] is True and first.json()['id']==second.json()['id']
    assert stock(client,p['id'])==before-1

def test_05_oversell_rejected(client):
    p=choose(client);n=stock(client,p['id'])
    r=client.post('/sales',json={'items':[{'product_id':p['id'],'quantity':n+1}],'idempotency_key':'unit-oversell-05'})
    assert r.status_code==400 and stock(client,p['id'])==n

def test_06_stocktake_once(client):
    pid=choose(client)['id'];before=stock(client,pid)
    st=client.post('/stocktakes');assert st.status_code==201,st.text
    sid=st.json()['id']
    c=client.post(f'/stocktakes/{sid}/count',json={'product_id':pid,'quantity':before+2})
    assert c.status_code==200,c.text
    r=client.post(f'/stocktakes/{sid}/approve');assert r.status_code==200,r.text
    assert stock(client,pid)==before+2
    assert client.post(f'/stocktakes/{sid}/approve').status_code==409

def test_07_fefo_dispatch(client):
    p=choose(client);pid=p['id']
    r=client.post('/goods-receipts',json={'supplier_id':p['supplier_id'],'invoice_number':'FEFO001','items':[{'product_id':pid,'quantity':5,'lot_code':'SOON','expires_at':(date.today()+timedelta(days=2)).isoformat()}],'idempotency_key':'unit-fefo-receipt'})
    assert r.status_code==201,r.text
    with SessionLocal() as db:
        soon=db.scalar(select(m.Lot).where(m.Lot.product_id==pid,m.Lot.lot_code=='SOON'))
        assert float(soon.quantity)==5
    sale=client.post('/sales',json={'items':[{'product_id':pid,'quantity':3}],'idempotency_key':'unit-fefo-sale'})
    assert sale.status_code==201,sale.text
    with SessionLocal() as db:
        lot=db.scalar(select(m.Lot).where(m.Lot.product_id==pid,m.Lot.lot_code=='SOON'))
        assert float(lot.quantity)==2

def test_08_replenishment_formula_71():
    position=48+20-4
    target=12*(3+7)+15
    assert position==64 and target==135 and max(0,target-position)==71
    assert decision.roundup(71,6)==72

def test_09_budget_respected(client):
    r=client.get('/recommendations');assert r.status_code==200
    alloc=decision.budget_alloc(r.json(),150000)
    assert alloc['spent']<=150000 and alloc['unspent']>=0
    assert alloc['spent']+alloc['unspent']==150000
    twin=client.post('/decision-twin/simulate',json={'budget':90000,'horizon':14})
    assert twin.status_code==200,twin.text
    third=twin.json()['scenarios'][2]
    assert third['purchase_spend']<=90000
    assert twin.json()['scenarios'][0]['purchase_spend']==0

def test_10_cross_tenant_forbidden(client):
    p=choose(client)
    with SessionLocal() as db:
        t=m.Tenant(name='Second independent company');db.add(t);db.flush()
        s=m.Store(tenant_id=t.id,name='Second store');db.add(s);db.flush()
        u=m.User(tenant_id=t.id,store_id=s.id,email='cross@demo.kz',name='Other owner',role='owner',password_hash=ph.hash('SecondDemo123!'));db.add(u);db.commit()
    with TestClient(app) as stranger:
        login=stranger.post('/auth/login',json={'email':'cross@demo.kz','password':'SecondDemo123!'})
        stranger.headers['X-CSRF-Token']=login.json()['csrf']
        assert stranger.get('/products/'+p['id']).status_code==400
        assert stranger.get('/products').json()==[]
        assert stranger.get('/inventory/balances').json()==[]

def test_11_no_history_low_data(client):
    p=client.get('/products/by-barcode/2990000000008').json()
    forecast=client.get('/forecast/'+p['id'])
    assert forecast.status_code==200
    assert forecast.json()['model_type']=='low_data_heuristic'
    assert forecast.json()['data_quality']=='Низкая'

def test_12_po_receiving(client):
    rec=next(x for x in client.get('/recommendations').json() if x['supplier_id'] and x['quantity']>0)
    po=client.post('/purchase-orders',json={'supplier_id':rec['supplier_id'],'items':[{'product_id':rec['product_id'],'quantity':rec['quantity']}]})
    assert po.status_code==201,po.text
    poid=po.json()['id']
    approved=client.post('/purchase-orders/'+poid+'/approve');assert approved.status_code==200,approved.text
    before=stock(client,rec['product_id'])
    body={'purchase_order_id':poid,'supplier_id':rec['supplier_id'],'idempotency_key':'unit-po-receipt','items':[{'product_id':rec['product_id'],'quantity':rec['quantity'],'lot_code':'FROM-PO'}]}
    r=client.post('/purchase-orders/'+poid+'/receive',json=body)
    assert r.status_code==200,r.text
    assert stock(client,rec['product_id'])==before+rec['quantity']
    repeat=client.post('/purchase-orders/'+poid+'/receive',json=body)
    assert repeat.status_code==200 and repeat.json()['replayed']
    assert stock(client,rec['product_id'])==before+rec['quantity']

def test_13_rbac_and_csrf(client):
    p=choose(client)
    with TestClient(app) as cashier:
        login=cashier.post('/auth/login',json={'email':'cashier@demo.kz','password':'Demo2026!'})
        assert login.status_code==200
        fields=cashier.get('/products/'+p['id']).json()
        assert fields['cost'] is None and fields['supplier_id'] is None
        cashier.headers['X-CSRF-Token']=login.json()['csrf']
        r=cashier.post('/products',json={'name':'Not allowed','sku':'NOT-ALLOWED','barcode':'33331234','price':100,'cost':30})
        assert r.status_code==403
    with TestClient(app) as no_csrf:
        logged=no_csrf.post('/auth/login',json={'email':'owner@demo.kz','password':'Demo2026!'})
        assert logged.status_code==200
        forbidden=no_csrf.post('/stocktakes')
        assert forbidden.status_code==403

def test_14_writeoff_expired_lot(client):
    p=choose(client)
    expire=(date.today()-timedelta(days=3)).isoformat()
    body={'supplier_id':p['supplier_id'],'invoice_number':'EXP001','items':[{'product_id':p['id'],'quantity':2,'lot_code':'EXPIRED-LOT','expires_at':expire}],'idempotency_key':'unit-expired-receipt-14'}
    before=stock(client,p['id'])
    received=client.post('/goods-receipts',json=body)
    assert received.status_code==201,received.text
    assert stock(client,p['id'])==before+2
    lots=client.get('/inventory/lots?product_id='+p['id']).json()
    target=next(l for l in lots if l['lot_code']=='EXPIRED-LOT')
    written=client.post('/inventory/write-off',json={'lot_id':target['id'],'quantity':2,'reason':'Истёк срок годности','idempotency_key':'unit-write-off-14'})
    assert written.status_code==200,written.text
    assert stock(client,p['id'])==before
    replay=client.post('/inventory/write-off',json={'lot_id':target['id'],'quantity':2,'reason':'Истёк срок годности','idempotency_key':'unit-write-off-14'})
    assert replay.json()['replayed'] is True
