import csv, hashlib, io, os, re, secrets, time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from argon2 import PasswordHasher
from .db import get_db
from . import models as m, engine as e

app=FastAPI(title='Smart Inventory AI API',version='1.0.0',description='Standalone DEMO: учёт и расчётные рекомендации, НЕ фискальная ККМ.')
origins=os.getenv('CORS_ORIGINS','http://localhost:3000').split(',')
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type','X-CSRF-Token'])
SESSION_KEY=os.getenv('SESSION_SECRET','local-development-change-this-in-production')
serializer=URLSafeTimedSerializer(SESSION_KEY,salt='smart-inventory-session')
ph=PasswordHasher()
login_attempts=defaultdict(list)
COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true'

class LoginInput(BaseModel):
    email:str
    password:str
class ProductInput(BaseModel):
    name:str=Field(min_length=2,max_length=240)
    sku:str=Field(min_length=2,max_length=70)
    barcode:str=Field(min_length=4,max_length=100)
    category:str='Другое'
    unit:str='шт.'
    price:Decimal=Field(ge=0)
    cost:Decimal=Field(ge=0)
    supplier_id:Optional[str]=None
    min_order_qty:int=Field(default=1,ge=1)
    pack_multiple:int=Field(default=1,ge=1)
    shelf_life_days:Optional[int]=Field(default=None,ge=1)
    min_stock:int=Field(default=8,ge=0)
class ProductPatch(BaseModel):
    name:Optional[str]=None;category:Optional[str]=None;price:Optional[Decimal]=Field(default=None,ge=0);cost:Optional[Decimal]=Field(default=None,ge=0)
    supplier_id:Optional[str]=None;min_stock:Optional[int]=Field(default=None,ge=0);pack_multiple:Optional[int]=Field(default=None,ge=1);min_order_qty:Optional[int]=Field(default=None,ge=1);shelf_life_days:Optional[int]=Field(default=None,ge=1);active:Optional[bool]=None
class SupplierInput(BaseModel):
    name:str=Field(min_length=2,max_length=200)
    phone:str=''
    lead_time_days:int=Field(default=3,ge=0,le=365)
class Line(BaseModel):
    product_id:str
    quantity:Decimal=Field(gt=0,le=100000)
class SaleInput(BaseModel):
    items:list[Line]=Field(min_length=1)
    idempotency_key:str=Field(min_length=8,max_length=120)
class ReturnInput(BaseModel):
    items:list[Line]=Field(min_length=1)
    idempotency_key:str=Field(min_length=8,max_length=120)
class ReceiptLine(Line):
    lot_code:str=''
    expires_at:Optional[date]=None
    unit_cost:Optional[Decimal]=Field(default=None,ge=0)
class ReceiptInput(BaseModel):
    supplier_id:Optional[str]=None
    purchase_order_id:Optional[str]=None
    invoice_number:str=''
    items:list[ReceiptLine]=Field(min_length=1)
    idempotency_key:str=Field(min_length=8,max_length=120)
class WriteOffInput(BaseModel):
    lot_id:str
    quantity:Decimal=Field(gt=0)
    reason:str=Field(min_length=5,max_length=300)
    idempotency_key:str=Field(min_length=8,max_length=120)

class AdjustmentInput(BaseModel):
    product_id:str
    delta:Decimal
    reason:str=Field(min_length=5,max_length=300)
    idempotency_key:str=Field(min_length=8,max_length=120)
class CountInput(BaseModel):
    product_id:str
    quantity:Decimal=Field(ge=0)
class POInput(BaseModel):
    supplier_id:str
    items:list[Line]=Field(min_length=1)
class TwinInput(BaseModel):
    budget:Decimal=Field(default=Decimal('150000'),ge=0)
    horizon:int=Field(default=14,ge=1,le=30)
    demand_factor:float=Field(default=1.0,ge=.5,le=1.5)
    custom:Optional[dict[str,int]]=None
class AssistantInput(BaseModel):
    question:str=Field(min_length=3,max_length=1000)

@app.exception_handler(ValueError)
async def business_error(request:Request,exc:ValueError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400,content={'detail':str(exc)})

@app.exception_handler(IntegrityError)
async def constraint_error(request:Request,exc:IntegrityError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409,content={'detail':'Конфликт данных: SKU, штрихкод, повторная операция или нарушение ограничения'})

def current_user(request:Request,db:Session=Depends(get_db)):
    token=request.cookies.get('siai_session')
    if not token: raise HTTPException(401,'Войдите в систему')
    try: data=serializer.loads(token,max_age=12*3600)
    except (BadSignature,SignatureExpired):raise HTTPException(401,'Сессия истекла')
    u=db.get(m.User,data['uid'])
    if not u or not u.active or u.tenant_id!=data['tenant']:raise HTTPException(401,'Неверная сессия')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not secrets.compare_digest(str(request.headers.get('X-CSRF-Token','')),data['csrf']):raise HTTPException(403,'Не пройдена CSRF-проверка')
    return u

def allowed(*roles):
    def auth(u:m.User=Depends(current_user)):
        if u.role not in roles:raise HTTPException(403,'Недостаточно прав для операции')
        return u
    return auth

def scope(db,u,table):
    return select(table).where(table.tenant_id==u.tenant_id)

def audit(db,u,action,details=''):
    db.add(m.AuditEvent(tenant_id=u.tenant_id,store_id=u.store_id,actor_id=u.id,action=action,details=str(details)[:1500]))

def one_supplier(db,u,sid):
    x=db.get(m.Supplier,sid)
    if not x or x.tenant_id!=u.tenant_id or not x.active:raise ValueError('Поставщик не найден')
    return x

def product_out(db,u,p):
    b=e.balance(db,u,p.id)
    lots=e.available_lots(db,u,p.id)
    return {'id':p.id,'name':p.name,'sku':p.sku,'barcode':p.barcode,'category':p.category,'unit':p.unit,'price':float(p.price),'cost':float(p.cost) if u.role!='cashier' else None,'supplier_id':p.supplier_id if u.role!='cashier' else None,'min_order_qty':p.min_order_qty,'pack_multiple':p.pack_multiple,'shelf_life_days':p.shelf_life_days,'min_stock':p.min_stock,'active':p.active,'on_hand':float(b.quantity) if b else 0,'available':float(e.sellable(lots))-(float(b.reserved) if b else 0)}

@app.get('/health')
def health(db:Session=Depends(get_db)):
    db.execute(select(func.count()).select_from(m.Tenant)).scalar()
    return {'ok':True,'version':'1.0.0','mode':'standalone_demo'}

@app.post('/auth/login')
def login(body:LoginInput,response:Response,request:Request,db:Session=Depends(get_db)):
    ip=request.client.host if request.client else 'unknown'
    now=time.time();login_attempts[ip]=[t for t in login_attempts[ip] if now-t<60]
    if len(login_attempts[ip])>=12:raise HTTPException(429,'Слишком много попыток; повторите через минуту')
    login_attempts[ip].append(now)
    u=db.scalar(select(m.User).where(m.User.email==body.email.lower().strip(),m.User.active==True))
    try: ok=bool(u and ph.verify(u.password_hash,body.password))
    except Exception:ok=False
    if not ok:raise HTTPException(401,'Неверный email или пароль')
    login_attempts[ip].clear()
    csrf=secrets.token_urlsafe(24)
    response.set_cookie('siai_session',serializer.dumps({'uid':u.id,'tenant':u.tenant_id,'csrf':csrf}),max_age=12*3600,httponly=True,samesite='lax',secure=COOKIE_SECURE,path='/')
    return {'user':{'id':u.id,'name':u.name,'role':u.role,'email':u.email},'csrf':csrf,'demo':True}

@app.post('/auth/logout')
def logout(response:Response,u=Depends(current_user)):
    response.delete_cookie('siai_session',path='/')
    return {'ok':True}

@app.get('/auth/me')
def me(request:Request,u=Depends(current_user)):
    data=serializer.loads(request.cookies['siai_session'],max_age=12*3600)
    return {'user':{'id':u.id,'name':u.name,'role':u.role,'email':u.email},'csrf':data['csrf'],'demo':True}

@app.get('/products')
def products(search:str='',limit:int=Query(150,ge=1,le=500),db:Session=Depends(get_db),u=Depends(current_user)):
    q=scope(db,u,m.Product)
    if search:q=q.where(m.Product.name.ilike(f'%{search}%') | m.Product.sku.ilike(f'%{search}%') | m.Product.barcode.ilike(f'%{search}%'))
    return [product_out(db,u,p) for p in db.scalars(q.order_by(m.Product.name).limit(limit)).all()]

@app.post('/products',status_code=201)
def add_product(body:ProductInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    if body.supplier_id:one_supplier(db,u,body.supplier_id)
    p=m.Product(tenant_id=u.tenant_id,**body.model_dump())
    db.add(p);db.flush();audit(db,u,'PRODUCT_CREATE',p.sku);db.commit()
    return product_out(db,u,p)

@app.get('/products/by-barcode/{value:path}')
def barcode(value:str,db:Session=Depends(get_db),u=Depends(current_user)):
    if value.startswith('http'):raise HTTPException(400,'Обычная URL-ссылка QR не является GTIN. Введите SKU/штрихкод.')
    p=db.scalar(select(m.Product).where(m.Product.tenant_id==u.tenant_id,m.Product.barcode==value,m.Product.active==True))
    if not p:raise HTTPException(404,'Штрихкод не найден')
    return product_out(db,u,p)

@app.get('/products/{id}')
def get_product(id:str,db:Session=Depends(get_db),u=Depends(current_user)):
    return product_out(db,u,e.owned_product(db,u,id))

@app.patch('/products/{id}')
def patch_product(id:str,body:ProductPatch,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    p=e.owned_product(db,u,id)
    for k,v in body.model_dump(exclude_unset=True).items():
        if k=='supplier_id' and v:one_supplier(db,u,v)
        setattr(p,k,v)
    audit(db,u,'PRODUCT_UPDATE',p.sku);db.commit()
    return product_out(db,u,p)

@app.get('/suppliers')
def suppliers(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    return [{'id':s.id,'name':s.name,'phone':s.phone,'lead_time_days':s.lead_time_days,'active':s.active} for s in db.scalars(scope(db,u,m.Supplier).where(m.Supplier.active==True).order_by(m.Supplier.name)).all()]

@app.post('/suppliers',status_code=201)
def add_supplier(body:SupplierInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    s=m.Supplier(tenant_id=u.tenant_id,**body.model_dump());db.add(s);db.flush();audit(db,u,'SUPPLIER_CREATE',s.name);db.commit()
    return {'id':s.id,'name':s.name}

@app.get('/inventory/balances')
def inventory(db:Session=Depends(get_db),u=Depends(current_user)):
    return [product_out(db,u,p) for p in db.scalars(scope(db,u,m.Product).where(m.Product.active==True).order_by(m.Product.name)).all()]

@app.get('/inventory/lots')
def lots(product_id:Optional[str]=None,db:Session=Depends(get_db),u=Depends(current_user)):
    q=scope(db,u,m.Lot).where(m.Lot.store_id==u.store_id,m.Lot.quantity>0)
    if product_id:q=q.where(m.Lot.product_id==product_id)
    rows=db.scalars(q.order_by(m.Lot.expires_at.asc().nulls_last()).limit(300)).all()
    return [{'id':x.id,'product_id':x.product_id,'lot_code':x.lot_code,'expires_at':x.expires_at.isoformat() if x.expires_at else None,'quantity':float(x.quantity),'location_id':x.location_id} for x in rows]

@app.get('/inventory/movements')
def movements(limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    rows=db.scalars(scope(db,u,m.StockMovement).where(m.StockMovement.store_id==u.store_id).order_by(m.StockMovement.occurred_at.desc()).limit(limit)).all()
    return [{'id':x.id,'product_id':x.product_id,'kind':x.kind,'signed_quantity':float(x.signed_quantity),'source_id':x.source_id,'occurred_at':x.occurred_at.isoformat()} for x in rows]

@app.post('/inventory/adjust')
def adjust(body:AdjustmentInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    p=e.owned_product(db,u,body.product_id)
    dup=db.scalar(select(m.StockMovement).where(m.StockMovement.tenant_id==u.tenant_id,m.StockMovement.idempotency_key.like(f'adjust:{body.idempotency_key}:%')))
    if dup:return {'ok':True,'replayed':True}
    if body.delta==0:raise ValueError('Корректировка не может равняться нулю')
    doc=m.uid()
    if body.delta>0:e.receive(db,u,p.id,body.delta,'ADJ',None,'adjustment',doc,m.uid(),f'adjust:{body.idempotency_key}:{doc}')
    else:e.consume(db,u,p.id,-body.delta,'STOCKTAKE_ADJUSTMENT','adjustment',doc,m.uid(),f'adjust:{body.idempotency_key}',include_expired=True)
    audit(db,u,'STOCK_ADJUST',f'{p.sku} {body.delta}: {body.reason}');db.commit()
    return {'ok':True,'replayed':False}

@app.post('/inventory/write-off')
def writeoff(body:WriteOffInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    old=db.scalar(select(m.StockMovement).where(m.StockMovement.tenant_id==u.tenant_id,m.StockMovement.idempotency_key==f'writeoff:{body.idempotency_key}'))
    if old:return {'ok':True,'replayed':True}
    lot=db.scalar(select(m.Lot).where(m.Lot.id==body.lot_id,m.Lot.tenant_id==u.tenant_id,m.Lot.store_id==u.store_id).with_for_update())
    if not lot:raise HTTPException(404,'Партия не найдена')
    if Decimal(lot.quantity)<body.quantity:raise ValueError('Нельзя списать больше остатка в партии')
    doc=m.uid()
    e.add_movement(db,u,lot.product_id,lot,'WRITE_OFF',-body.quantity,'writeoff',doc,lot.id,f'writeoff:{body.idempotency_key}')
    audit(db,u,'WRITE_OFF',f'{lot.lot_code}: -{body.quantity}; {body.reason}')
    db.commit()
    return {'ok':True,'replayed':False}

@app.post('/sales',status_code=201)
def create_sale(body:SaleInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','cashier'))):
    existing=db.scalar(select(m.Sale).where(m.Sale.tenant_id==u.tenant_id,m.Sale.idempotency_key==body.idempotency_key))
    if existing:return {'id':existing.id,'total':float(existing.total),'replayed':True}
    merged=defaultdict(Decimal)
    for x in body.items:merged[x.product_id]+=x.quantity
    sale=m.Sale(tenant_id=u.tenant_id,store_id=u.store_id,cashier_id=u.id,idempotency_key=body.idempotency_key,total=0,cogs=0)
    db.add(sale);db.flush()
    total=Decimal(0);cost=Decimal(0)
    for pid,n in merged.items():
        p=e.owned_product(db,u,pid)
        if p.unit=='шт.' and n%1:raise ValueError('Штучный товар продаётся только целыми единицами')
        item=m.SaleItem(sale_id=sale.id,product_id=pid,quantity=n,returned_qty=0,unit_price=p.price,unit_cost=p.cost)
        db.add(item);db.flush()
        e.consume(db,u,pid,n,'SALE','sale',sale.id,item.id,body.idempotency_key+':sale:'+item.id)
        total+=n*Decimal(p.price);cost+=n*Decimal(p.cost)
    sale.total=total;sale.cogs=cost
    audit(db,u,'SALE',f'{sale.id}, {total} KZT');db.commit()
    return {'id':sale.id,'total':float(total),'cogs':float(cost),'replayed':False}

@app.get('/sales')
def sales(limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db),u=Depends(allowed('owner','manager','cashier'))):
    result=[]
    for s in db.scalars(scope(db,u,m.Sale).where(m.Sale.store_id==u.store_id).order_by(m.Sale.created_at.desc()).limit(limit)).all():
        lines=db.scalars(select(m.SaleItem).where(m.SaleItem.sale_id==s.id)).all()
        result.append({'id':s.id,'total':float(s.total),'cogs':float(s.cogs) if u.role!='cashier' else None,'created_at':s.created_at.isoformat(),'items':[{'product_id':i.product_id,'quantity':float(i.quantity),'returned_qty':float(i.returned_qty),'price':float(i.unit_price)} for i in lines]})
    return result

@app.post('/sales/{id}/return')
def sale_return(id:str,body:ReturnInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','cashier'))):
    s=db.get(m.Sale,id)
    if not s or s.tenant_id!=u.tenant_id or s.store_id!=u.store_id:raise HTTPException(404,'Продажа не найдена')
    old=db.scalar(select(m.SaleReturn).where(m.SaleReturn.tenant_id==u.tenant_id,m.SaleReturn.idempotency_key==body.idempotency_key))
    if old:return {'id':old.id,'amount':float(old.amount),'replayed':True}
    merged=defaultdict(Decimal)
    for x in body.items:merged[x.product_id]+=x.quantity
    amount=Decimal(0)
    ret=m.SaleReturn(tenant_id=u.tenant_id,sale_id=id,idempotency_key=body.idempotency_key,amount=0)
    db.add(ret);db.flush()
    for pid,n in merged.items():
        item=db.scalar(select(m.SaleItem).where(m.SaleItem.sale_id==id,m.SaleItem.product_id==pid).with_for_update())
        if not item or Decimal(item.returned_qty)+n>Decimal(item.quantity):raise ValueError('Возврат превышает проданное количество')
        item.returned_qty+=n
        db.add(m.SaleReturnItem(return_id=ret.id,sale_item_id=item.id,quantity=n,unit_price=item.unit_price,unit_cost=item.unit_cost))
        returned_product=e.owned_product(db,u,pid)
        # Perishable returns are physically counted but quarantined as unsellable until written off.
        quarantine_expiry=m.today()-__import__('datetime').timedelta(days=1) if returned_product.shelf_life_days else None
        e.receive(db,u,pid,n,f'RETURN-{ret.id[:8]}',quarantine_expiry,'return',ret.id,item.id,f'return:{body.idempotency_key}:{item.id}')
        amount+=n*Decimal(item.unit_price)
    ret.amount=amount;audit(db,u,'SALE_RETURN',f'{id} -{amount}');db.commit()
    return {'id':ret.id,'amount':float(amount),'replayed':False}

@app.post('/goods-receipts',status_code=201)
def goods_receipt(body:ReceiptInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    old=db.scalar(select(m.GoodsReceipt).where(m.GoodsReceipt.tenant_id==u.tenant_id,m.GoodsReceipt.idempotency_key==body.idempotency_key))
    if old:return {'id':old.id,'replayed':True}
    if body.supplier_id:one_supplier(db,u,body.supplier_id)
    po=None
    if body.purchase_order_id:
        po=db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.id==body.purchase_order_id,m.PurchaseOrder.tenant_id==u.tenant_id,m.PurchaseOrder.store_id==u.store_id).with_for_update())
        if not po or po.status not in ('approved','ordered','partial_received'):raise ValueError('Заказ не утверждён')
        if body.supplier_id and po.supplier_id!=body.supplier_id:raise ValueError('Не совпадает поставщик заказа')
    rec=m.GoodsReceipt(tenant_id=u.tenant_id,store_id=u.store_id,supplier_id=po.supplier_id if po else body.supplier_id,purchase_order_id=po.id if po else None,invoice_number=body.invoice_number,idempotency_key=body.idempotency_key)
    db.add(rec);db.flush()
    for line_num,line in enumerate(body.items):
        p=e.owned_product(db,u,line.product_id)
        if p.unit=='шт.' and line.quantity%1:raise ValueError('Штучный товар принимается только целыми единицами')
        if po:
            oi=db.scalar(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.order_id==po.id,m.PurchaseOrderItem.product_id==p.id).with_for_update())
            if not oi or Decimal(oi.received_qty)+line.quantity>Decimal(oi.quantity):raise ValueError('Приёмка превышает остаток заказа')
            oi.received_qty+=line.quantity
        item_id=m.uid()
        lot=e.receive(db,u,p.id,line.quantity,line.lot_code,line.expires_at,'goods_receipt',rec.id,item_id,f'goods:{body.idempotency_key}:{line_num}')
        db.add(m.GoodsReceiptItem(id=item_id,receipt_id=rec.id,product_id=p.id,lot_id=lot.id,quantity=line.quantity,unit_cost=line.unit_cost if line.unit_cost is not None else p.cost))
    if po:
        po_items=db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.order_id==po.id)).all()
        db.flush()
        po.status='received' if all(Decimal(x.received_qty)>=Decimal(x.quantity) for x in po_items) else 'partial_received'
    audit(db,u,'GOODS_RECEIPT',rec.id);db.commit()
    return {'id':rec.id,'replayed':False}

@app.get('/goods-receipts')
def receipts(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    return [{'id':x.id,'supplier_id':x.supplier_id,'purchase_order_id':x.purchase_order_id,'invoice_number':x.invoice_number,'created_at':x.created_at.isoformat()} for x in db.scalars(scope(db,u,m.GoodsReceipt).where(m.GoodsReceipt.store_id==u.store_id).order_by(m.GoodsReceipt.created_at.desc()).limit(100)).all()]

@app.post('/stocktakes',status_code=201)
def start_stocktake(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    st=m.Stocktake(tenant_id=u.tenant_id,store_id=u.store_id,created_by=u.id,status='draft')
    db.add(st);db.flush()
    for p in db.scalars(scope(db,u,m.Product).where(m.Product.active==True)).all():
        db.add(m.StocktakeItem(stocktake_id=st.id,product_id=p.id,snapshot_qty=e.on_hand(db,u,p.id)))
    audit(db,u,'STOCKTAKE_START',st.id);db.commit()
    return {'id':st.id,'status':'draft'}

@app.get('/stocktakes')
def stocktakes(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    result=[]
    for s in db.scalars(scope(db,u,m.Stocktake).where(m.Stocktake.store_id==u.store_id).order_by(m.Stocktake.created_at.desc()).limit(20)).all():
        items=db.scalars(select(m.StocktakeItem).where(m.StocktakeItem.stocktake_id==s.id)).all()
        result.append({'id':s.id,'status':s.status,'created_at':s.created_at.isoformat(),'items':[{'product_id':i.product_id,'snapshot_qty':float(i.snapshot_qty),'counted_qty':float(i.counted_qty) if i.counted_qty is not None else None} for i in items]})
    return result

@app.post('/stocktakes/{id}/count')
def count_stocktake(id:str,body:CountInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    st=db.get(m.Stocktake,id)
    if not st or st.tenant_id!=u.tenant_id or st.store_id!=u.store_id:raise HTTPException(404,'Не найдено')
    if st.status!='draft':raise ValueError('Инвентаризация уже закрыта')
    item=db.scalar(select(m.StocktakeItem).where(m.StocktakeItem.stocktake_id==id,m.StocktakeItem.product_id==body.product_id))
    if not item:raise ValueError('Товар не в инвентаризации')
    item.counted_qty=body.quantity;db.commit()
    return {'ok':True,'difference':float(body.quantity-Decimal(item.snapshot_qty))}

@app.post('/stocktakes/{id}/approve')
def approve_stocktake(id:str,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    st=db.scalar(select(m.Stocktake).where(m.Stocktake.id==id,m.Stocktake.tenant_id==u.tenant_id,m.Stocktake.store_id==u.store_id).with_for_update())
    if not st:raise HTTPException(404,'Не найдено')
    if st.status!='draft':raise HTTPException(409,'Инвентаризация уже применена')
    items=db.scalars(select(m.StocktakeItem).where(m.StocktakeItem.stocktake_id==id)).all()
    if not any(x.counted_qty is not None for x in items):raise ValueError('Нет пересчитанных товаров')
    # Reject stale snapshots rather than silently overwriting stock changes after stocktake opened.
    for i in items:
        if i.counted_qty is None:continue
        if e.on_hand(db,u,i.product_id)!=Decimal(i.snapshot_qty):raise HTTPException(409,'Остатки изменились после создания акта. Создайте новую инвентаризацию.')
    differences=[]
    for i in items:
        if i.counted_qty is None:continue
        diff=Decimal(i.counted_qty)-Decimal(i.snapshot_qty)
        if diff>0:e.receive(db,u,i.product_id,diff,f'STK-{id[:8]}',None,'stocktake',id,i.id,f'stocktake:{id}:{i.id}')
        if diff<0:e.consume(db,u,i.product_id,-diff,'STOCKTAKE_ADJUSTMENT','stocktake',id,i.id,f'stocktake:{id}:{i.id}',include_expired=True)
        if diff:differences.append({'product_id':i.product_id,'delta':float(diff)})
    st.status='approved';st.approved_at=datetime.now(timezone.utc)
    audit(db,u,'STOCKTAKE_APPROVE',str(differences));db.commit()
    return {'ok':True,'differences':differences}

@app.post('/purchase-orders',status_code=201)
def create_po(body:POInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    one_supplier(db,u,body.supplier_id)
    merged=defaultdict(Decimal)
    for i in body.items:merged[i.product_id]+=i.quantity
    po=m.PurchaseOrder(tenant_id=u.tenant_id,store_id=u.store_id,supplier_id=body.supplier_id,created_by=u.id,status='draft')
    db.add(po);db.flush()
    for pid,n in merged.items():
        p=e.owned_product(db,u,pid)
        if p.supplier_id!=body.supplier_id:raise ValueError('Поставщик не совпадает с карточкой товара')
        if n<p.min_order_qty or n%p.pack_multiple:raise ValueError('Несоблюдён минимум/кратность упаковки')
        db.add(m.PurchaseOrderItem(order_id=po.id,product_id=pid,quantity=n,received_qty=0,unit_cost=p.cost))
    audit(db,u,'PO_CREATE',po.id);db.commit()
    return {'id':po.id,'status':po.status}

@app.get('/purchase-orders')
def list_po(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    result=[]
    for x in db.scalars(scope(db,u,m.PurchaseOrder).where(m.PurchaseOrder.store_id==u.store_id).order_by(m.PurchaseOrder.created_at.desc()).limit(100)).all():
        items=db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.order_id==x.id)).all()
        result.append({'id':x.id,'supplier_id':x.supplier_id,'status':x.status,'created_at':x.created_at.isoformat(),'total':sum(float(y.quantity)*float(y.unit_cost) for y in items),'items':[{'product_id':y.product_id,'quantity':float(y.quantity),'received_qty':float(y.received_qty),'unit_cost':float(y.unit_cost)} for y in items]})
    return result

@app.post('/purchase-orders/{id}/approve')
def approve_po(id:str,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    po=db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.id==id,m.PurchaseOrder.tenant_id==u.tenant_id,m.PurchaseOrder.store_id==u.store_id).with_for_update())
    if not po:raise HTTPException(404,'Заказ не найден')
    if po.status!='draft':raise HTTPException(409,'Можно утвердить только черновик')
    po.status='approved';audit(db,u,'PO_APPROVE',id);db.commit()
    return {'id':id,'status':po.status}

@app.post('/purchase-orders/{id}/receive')
def receive_po(id:str,body:ReceiptInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    if body.purchase_order_id!=id:raise ValueError('purchase_order_id не совпадает с URL')
    return goods_receipt(body,db,u)

@app.get('/analytics/summary')
def summary(db:Session=Depends(get_db),u=Depends(current_user)):
    today=m.today()
    allsales=db.scalars(scope(db,u,m.Sale).where(m.Sale.store_id==u.store_id)).all()
    recent=[s for s in allsales if s.created_at.date()==today]
    ps=db.scalars(scope(db,u,m.Product).where(m.Product.active==True)).all()
    stock_value=Decimal(0);low=0;expiring=0
    for p in ps:
        stock=e.on_hand(db,u,p.id)
        stock_value+=stock*Decimal(p.cost)
        if stock<=p.min_stock:low+=1
    lots=db.scalars(scope(db,u,m.Lot).where(m.Lot.store_id==u.store_id,m.Lot.quantity>0,m.Lot.expires_at.is_not(None))).all()
    expiring=sum(1 for x in lots if x.expires_at<=today+__import__('datetime').timedelta(days=7))
    returns=db.scalars(scope(db,u,m.SaleReturn)).all()
    refunds=Decimal(0);refunded_cost=Decimal(0)
    for ret in returns:
        if ret.created_at.date()==today:
            refunds+=Decimal(ret.amount)
            lines=db.scalars(select(m.SaleReturnItem).where(m.SaleReturnItem.return_id==ret.id)).all()
            refunded_cost+=sum((Decimal(x.quantity)*Decimal(x.unit_cost) for x in lines),Decimal(0))
    return {'revenue_today':e.currency(sum((Decimal(s.total) for s in recent),Decimal(0))-refunds),'gross_profit_today':e.currency(sum((Decimal(s.total)-Decimal(s.cogs) for s in recent),Decimal(0))-refunds+refunded_cost) if u.role!='cashier' else None,'inventory_value':e.currency(stock_value) if u.role!='cashier' else None,'low_stock_count':low,'expiring_lot_count':expiring,'products_count':len(ps),'transactions_today':len(recent),'mode':'DEMO: показатели POS относятся к проведённым операциям. Исторический спрос синтетический.'}

@app.get('/analytics/daily-sales')
def daily_sales(days:int=Query(30,ge=7,le=90),db:Session=Depends(get_db),u=Depends(current_user)):
    dates=[m.today()-__import__('datetime').timedelta(days=i) for i in range(days-1,-1,-1)]
    daily={d.isoformat():{'date':d.isoformat(),'revenue':0.0,'units':0.0,'synthetic_revenue':0.0} for d in dates}
    ps={p.id:p for p in db.scalars(scope(db,u,m.Product)).all()}
    hist=db.scalars(scope(db,u,m.DailyDemand).where(m.DailyDemand.store_id==u.store_id,m.DailyDemand.day>=dates[0])).all()
    for item in hist:
        if item.day.isoformat() in daily and item.product_id in ps:
            daily[item.day.isoformat()]['synthetic_revenue']+=float(item.quantity)*float(ps[item.product_id].price)
    rows=db.execute(select(m.Sale,m.SaleItem).join(m.SaleItem,m.SaleItem.sale_id==m.Sale.id).where(m.Sale.tenant_id==u.tenant_id,m.Sale.store_id==u.store_id)).all()
    for s,item in rows:
        key=s.created_at.date().isoformat()
        if key in daily:
            daily[key]['revenue']+=float(item.unit_price)*float(item.quantity)
            daily[key]['units']+=float(item.quantity)
    return list(daily.values())

@app.get('/forecast/{product_id}')
def product_forecast(product_id:str,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    return e.forecast(db,u,e.owned_product(db,u,product_id))

@app.get('/recommendations')
def get_recs(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    return e.recommendations(db,u)

@app.post('/recommendations/recompute')
def recalc(db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    return {'items':e.recommendations(db,u),'generated_at':datetime.now(timezone.utc).isoformat(),'algorithm':'deterministic_baseline'}

@app.post('/decision-twin/simulate')
def twin(body:TwinInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    return e.simulate(db,u,body.budget,body.horizon,body.demand_factor,body.custom)

@app.post('/assistant/ask')
def assistant(body:AssistantInput,db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    q=body.question.lower()
    recs=e.recommendations(db,u)
    if any(w in q for w in ('бюджет','потратить','денег','тенге','закупку на')):
        found=re.search(r'(\d[\d\s]{2,9})',q)
        budget=int(re.sub(r'\D','',found.group(1))) if found else 150000
        plan=e.budget_alloc(recs,budget)
        chosen=[f'{next(r["name"] for r in recs if r["product_id"]==pid)}: {qty} шт.' for pid,qty in plan['allocations'].items()]
        ans=f'Бюджет: {budget:,.0f} ₸. Распределение: {plan["spent"]:,.0f} ₸, остаток {plan["unspent"]:,.0f} ₸.\n'+('\n'.join(chosen[:12]) or 'Закупки в рамках ограничений не найдены.')+'\nАлгоритм: приоритетная жадная упаковочная эвристика, не математический глобальный оптимум.'
    elif any(w in q for w in ('почему','объясни','предложила')):
        names=[r for r in recs if r['name'].lower() in q or any(len(word)>3 and word in q for word in r['name'].lower().split())]
        r=names[0] if names else next((r for r in recs if r['quantity']>0),None)
        ans=f'{r["name"]}: рекомендовано {r["quantity"]} шт. {r["reason"]} Ориентировочная сумма {r["estimated_cost"]:,.0f} ₸. Данные: остатки склада, заказы поставщикам, исторический спрос.' if r else 'Сейчас рекомендаций к закупке нет.'
    elif any(w in q for w in ('испорт','срок','просроч')):
        soon=db.scalars(scope(db,u,m.Lot).where(m.Lot.store_id==u.store_id,m.Lot.quantity>0,m.Lot.expires_at.is_not(None))).all()
        soon=[x for x in soon if x.expires_at<=m.today()+__import__('datetime').timedelta(days=7)]
        ans='Партии с истекающим сроком (7 дней): '+('; '.join(f'{e.owned_product(db,u,x.product_id).name}: {float(x.quantity):g} шт., до {x.expires_at}' for x in soon[:12]) or 'не обнаружены')
    else:
        urgent=[r for r in recs if r['urgency']=='Срочно']
        ans='Срочные риски дефицита: '+('; '.join(f'{r["name"]}: остаток {r["stock"]:g}, спрос {r["daily_demand"]:g}/день, заказать {r["quantity"]}' for r in urgent[:12]) or 'сейчас не обнаружены')
    return {'answer':ans,'engine':'Локальный аналитический ассистент (без внешней LLM)','sources':['inventory_lots','stock_balances','daily_demand','purchase_order_items'],'synthetic_data':True}

@app.get('/audit')
def events(db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    return [{'action':x.action,'details':x.details,'occurred_at':x.occurred_at.isoformat()} for x in db.scalars(scope(db,u,m.AuditEvent).where(m.AuditEvent.store_id==u.store_id).order_by(m.AuditEvent.occurred_at.desc()).limit(100)).all()]

@app.get('/inventory/export.csv')
def export_inventory(db:Session=Depends(get_db),u=Depends(allowed('owner','manager','warehouse'))):
    sio=io.StringIO();w=csv.writer(sio);w.writerow(['sku','barcode','name','category','on_hand','unit','cost_kzt','price_kzt'])
    for p in db.scalars(scope(db,u,m.Product).where(m.Product.active==True)).all():
        w.writerow([p.sku,p.barcode,p.name,p.category,e.on_hand(db,u,p.id),p.unit,p.cost,p.price])
    return StreamingResponse(iter([sio.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="inventory.csv"'})

async def read_csv(file:UploadFile):
    raw=await file.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('CSV больше 2 МБ')
    try:rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    except UnicodeDecodeError:raise ValueError('CSV должен быть в UTF-8')
    if not rows or len(rows)>2000:raise ValueError('Нужно 1–2000 строк')
    return raw,rows

@app.post('/imports/products-csv')
async def import_products(file:UploadFile=File(...),db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    raw,rows=await read_csv(file);sha=hashlib.sha256(raw).hexdigest()
    if db.scalar(select(m.ImportJob).where(m.ImportJob.tenant_id==u.tenant_id,m.ImportJob.sha256==sha,m.ImportJob.kind=='products')):return {'replayed':True,'rows':0}
    required={'sku','barcode','name','category','cost','price'}
    if not required.issubset(rows[0]):raise ValueError('Обязательные колонки: '+', '.join(sorted(required)))
    seen=set()
    for n,row in enumerate(rows,2):
        try:
            sku=row['sku'].strip();code=row['barcode'].strip()
            if not sku or not code or sku in seen:raise ValueError('пустой или повторный SKU')
            seen.add(sku)
            data=ProductInput(name=row['name'],sku=sku,barcode=code,category=row['category'],cost=Decimal(row['cost']),price=Decimal(row['price']))
            existing=db.scalar(select(m.Product).where(m.Product.tenant_id==u.tenant_id,m.Product.sku==sku))
            if existing:raise ValueError('SKU уже существует')
            db.add(m.Product(tenant_id=u.tenant_id,**data.model_dump()))
        except Exception as ex:raise ValueError(f'Строка {n}: {ex}')
    db.add(m.ImportJob(tenant_id=u.tenant_id,kind='products',sha256=sha,rows=len(rows)))
    audit(db,u,'IMPORT_PRODUCTS',str(len(rows)));db.commit()
    return {'rows':len(rows),'replayed':False}

@app.post('/imports/sales-csv')
async def import_history(file:UploadFile=File(...),db:Session=Depends(get_db),u=Depends(allowed('owner','manager'))):
    raw,rows=await read_csv(file);sha=hashlib.sha256(raw).hexdigest()
    if db.scalar(select(m.ImportJob).where(m.ImportJob.tenant_id==u.tenant_id,m.ImportJob.sha256==sha,m.ImportJob.kind=='demand')):return {'replayed':True,'rows':0}
    if not {'sku','date','quantity'}.issubset(rows[0]):raise ValueError('Обязательные колонки: sku,date,quantity; stockout необязательна')
    for idx,row in enumerate(rows,2):
        try:
            p=db.scalar(select(m.Product).where(m.Product.tenant_id==u.tenant_id,m.Product.sku==row['sku']))
            if not p:raise ValueError('SKU не найден')
            day=date.fromisoformat(row['date']);quantity=Decimal(row['quantity'])
            if quantity<0:raise ValueError('Отрицательное количество')
            old=db.scalar(select(m.DailyDemand).where(m.DailyDemand.tenant_id==u.tenant_id,m.DailyDemand.store_id==u.store_id,m.DailyDemand.product_id==p.id,m.DailyDemand.day==day))
            if old:raise ValueError('Уже есть строка спроса за эту дату/SKU (сначала удалите демо-данные)')
            db.add(m.DailyDemand(tenant_id=u.tenant_id,store_id=u.store_id,product_id=p.id,day=day,quantity=quantity,stockout=row.get('stockout','').lower() in ('true','1','yes'),synthetic=False))
        except Exception as ex:raise ValueError(f'Строка {idx}: {ex}')
    db.add(m.ImportJob(tenant_id=u.tenant_id,kind='demand',sha256=sha,rows=len(rows)))
    audit(db,u,'IMPORT_HISTORY',str(len(rows)));db.commit()
    return {'rows':len(rows),'replayed':False}

@app.post('/settings/reset-demo')
def reset_demo(db:Session=Depends(get_db),u=Depends(allowed('owner'))):
    if os.getenv('ALLOW_DEMO_RESET','true').lower()!='true':raise HTTPException(403,'Демо-сброс отключён')
    from .seed import reset_and_seed
    reset_and_seed(db)
    return {'ok':True,'message':'Демо-данные восстановлены. Войдите снова.'}
