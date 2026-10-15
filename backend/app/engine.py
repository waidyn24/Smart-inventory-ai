"""Deterministic accounting, forecasting and decision simulation. No LLM arithmetic."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from math import sqrt
from statistics import mean, pstdev
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from . import models as m

D = lambda x: Decimal(str(x))
def units(x): return float(D(x).quantize(D('0.001')))
def currency(x): return float(D(x).quantize(D('0.01')))
def roundup(x, multiple=1):
    mult=D(multiple)
    return int((D(x)/mult).to_integral_value(rounding=ROUND_CEILING)*mult)

def owned_product(db: Session, user, product_id):
    p=db.get(m.Product, product_id)
    if not p or p.tenant_id != user.tenant_id or not p.active: raise ValueError('Товар не найден')
    return p

def location(db:Session, user):
    loc=db.scalar(select(m.StockLocation).where(m.StockLocation.store_id==user.store_id,m.StockLocation.kind=='shop'))
    if not loc: raise ValueError('Торговая точка не настроена')
    return loc

def balance(db:Session,user, product_id, location_id=None):
    lid=location_id or location(db,user).id
    return db.scalar(select(m.StockBalance).where(m.StockBalance.tenant_id==user.tenant_id,m.StockBalance.store_id==user.store_id,m.StockBalance.location_id==lid,m.StockBalance.product_id==product_id).with_for_update())

def available_lots(db: Session,user, product_id, location_id=None):
    lid=location_id or location(db,user).id
    today=m.today()
    return db.scalars(select(m.Lot).where(m.Lot.tenant_id==user.tenant_id,m.Lot.store_id==user.store_id,m.Lot.location_id==lid,m.Lot.product_id==product_id,m.Lot.quantity>0).order_by(m.Lot.expires_at.asc().nulls_last(), m.Lot.received_at.asc()).with_for_update()).all()

def sellable(lots):
    return sum((D(l.quantity) for l in lots if not l.expires_at or l.expires_at>=m.today()),D(0))

def get_or_create_balance(db,user,product_id,location_id):
    b=balance(db,user,product_id,location_id)
    if b is None:
        b=m.StockBalance(tenant_id=user.tenant_id,store_id=user.store_id,location_id=location_id,product_id=product_id,quantity=0,reserved=0)
        db.add(b); db.flush()
    return b

def add_movement(db,user,product_id,lot,kind,change,source,source_id,line_id, idem):
    value=D(change)
    if value == 0:return
    b=get_or_create_balance(db,user,product_id,lot.location_id)
    if D(b.quantity)+value < 0 or D(lot.quantity)+value < 0: raise ValueError('Недостаточно остатков')
    lot.quantity=D(lot.quantity)+value
    b.quantity=D(b.quantity)+value
    db.add(m.StockMovement(tenant_id=user.tenant_id,store_id=user.store_id,location_id=lot.location_id,product_id=product_id,lot_id=lot.id,kind=kind,source_type=source,source_id=source_id,source_line_id=line_id,idempotency_key=idem,signed_quantity=value,actor_id=user.id))

def receive(db,user,product_id,quantity,lot_code,expires_at,source,source_id,line_id,idem):
    if D(quantity)<=0: raise ValueError('Количество должно быть положительным')
    owned_product(db,user,product_id)
    loc=location(db,user)
    lot=m.Lot(tenant_id=user.tenant_id,store_id=user.store_id,location_id=loc.id,product_id=product_id,lot_code=lot_code or f'REC-{source_id[:8]}',expires_at=expires_at,quantity=0)
    db.add(lot);db.flush()
    add_movement(db,user,product_id,lot,'RECEIVE' if source!='return' else 'RETURN',quantity,source,source_id,line_id,idem)
    return lot

def consume(db,user,product_id,quantity,kind,source,source_id,line_id,idem,include_expired=False):
    """FEFO deduction, caller must hold DB transaction and row locks. Applies no partial operation if caller rolls back."""
    n=D(quantity)
    if n<=0:raise ValueError('Количество должно быть положительным')
    b=balance(db,user,product_id)
    lots=available_lots(db,user,product_id)
    if not b or D(b.quantity)-D(b.reserved)<n or (sum((D(x.quantity) for x in lots),D(0)) if include_expired else sellable(lots))<n:raise ValueError('Недостаточно доступного товара для операции')
    left=n
    for lot in lots:
        if not include_expired and lot.expires_at and lot.expires_at<m.today():continue
        take=min(left,D(lot.quantity))
        if take>0:
            add_movement(db,user,product_id,lot,kind,-take,source,source_id,line_id,f'{idem}:{lot.id}')
            left-=take
        if left==0:break
    return n

def on_hand(db,user,pid):
    b=balance(db,user,pid)
    if not b:return D(0)
    return D(b.quantity)

def inbound(db,user,pid):
    q=db.execute(select(m.PurchaseOrderItem.quantity,m.PurchaseOrderItem.received_qty).join(m.PurchaseOrder,m.PurchaseOrder.id==m.PurchaseOrderItem.order_id).where(m.PurchaseOrder.tenant_id==user.tenant_id,m.PurchaseOrder.store_id==user.store_id,m.PurchaseOrder.status.in_(['approved','ordered','partial_received']),m.PurchaseOrderItem.product_id==pid)).all()
    return sum((max(D(0),D(a)-D(b)) for a,b in q),D(0))

def history(db,user,pid):
    rows=db.scalars(select(m.DailyDemand).where(m.DailyDemand.tenant_id==user.tenant_id,m.DailyDemand.store_id==user.store_id,m.DailyDemand.product_id==pid).order_by(m.DailyDemand.day)).all()
    items={x.day: {'quantity':D(x.quantity),'stockout':x.stockout,'synthetic':x.synthetic} for x in rows}
    # Live POS sales are included separately; preloaded history is explicitly synthetic.
    real=db.execute(select(func.date(m.Sale.created_at),func.sum(m.SaleItem.quantity)).join(m.SaleItem,m.SaleItem.sale_id==m.Sale.id).where(m.Sale.tenant_id==user.tenant_id,m.Sale.store_id==user.store_id,m.SaleItem.product_id==pid).group_by(func.date(m.Sale.created_at))).all()
    for day,v in real:
        if isinstance(day,str): day=date.fromisoformat(day[:10])
        item=items.setdefault(day,{'quantity':D(0),'stockout':False,'synthetic':False})
        item['quantity']+=D(v)
    return [{'date':d.isoformat(),**{k:(float(v) if isinstance(v,Decimal) else v) for k,v in val.items()}} for d,val in sorted(items.items())]

def forecast(db,user,p):
    data=history(db,user,p.id)
    valid=[x for x in data if not x['stockout']]
    recent=valid[-56:]
    n=len(valid)
    if n<14:
        rate=mean([x['quantity'] for x in valid[-7:]]) if valid else max(0.5,float(p.min_stock)/7)
        model='low_data_heuristic'; confidence='Низкая';factor=.40
    elif n<56:
        rate=mean([x['quantity'] for x in recent[-21:]])
        model='moving_average'; confidence='Средняя';factor=.27
    else:
        week=recent[-28:]
        weighted=sum(x['quantity']*(1+(i/len(week))) for i,x in enumerate(week))/sum(1+(i/len(week)) for i in range(len(week)))
        rate=weighted
        model='weekly_seasonal_baseline';confidence='Средняя';factor=.20
    rate=max(0.0,float(rate))
    day_of_week={}
    if n>=28:
        for dow in range(7):
            group=[x['quantity'] for x in recent if date.fromisoformat(x['date']).weekday()==dow]
            day_of_week[dow]=mean(group) if group else rate
        avg_dow=mean(day_of_week.values()) or 1
        day_of_week={k:v*rate/avg_dow for k,v in day_of_week.items()}
    series=[]
    for i in range(1,31):
        day=m.today()+timedelta(days=i)
        q=max(0,day_of_week.get(day.weekday(),rate))
        series.append({'date':day.isoformat(),'expected':round(q,2),'low':round(max(0,q*(1-factor)),2),'high':round(q*(1+factor),2)})
    wape=None;mae=None
    if n>=21:
        observed=valid[-7:]
        historical=valid[:-7]
        baseline=mean([r['quantity'] for r in historical[-14:]])
        errors=[abs(r['quantity']-baseline) for r in observed]
        mae=round(mean(errors),2)
        denominator=sum(r['quantity'] for r in observed)
        wape=round(100*sum(errors)/denominator,1) if denominator>0 else None
    return {'product_id':p.id,'name':p.name,'rate':round(rate,3),'history':data[-90:],'series':series,'model_type':model,'data_quality':confidence,'valid_days':n,'excluded_stockout_days':len(data)-n,'wape_percent':wape,'mae_units':mae,'explanation':f'Дней без наблюдаемого дефицита: {n}. Модель: {model}. Дни отсутствия товара исключены из обучения; праздники и акции не учитываются без данных.','generated_at':m.today().isoformat(),'synthetic_history':any(d['synthetic'] for d in data)}

def recommend(db,user,p):
    fc=forecast(db,user,p)
    b=balance(db,user,p.id)
    physical=D(b.quantity) if b else D(0)
    held=sellable(available_lots(db,user,p.id))
    reserved=D(b.reserved) if b else D(0)
    inbound_qty=inbound(db,user,p.id)
    supplier=db.get(m.Supplier,p.supplier_id) if p.supplier_id else None
    lead=supplier.lead_time_days if supplier else 3
    review=7
    rate=D(fc['rate'])
    safety=roundup(rate*D(1.3)) if fc['valid_days']>=14 else roundup(rate*D(2))
    position=held+inbound_qty-reserved
    target=rate*D(lead+review)+D(safety)
    raw=max(D(0),target-position)
    q=roundup(max(raw,D(p.min_order_qty)),p.pack_multiple) if raw>0 else 0
    constraints=[]
    if p.shelf_life_days:
        # Conservative inbound turnover bound: only order what may sell during shelf life.
        cap=max(0,roundup(max(D(0),rate*D(p.shelf_life_days)-max(D(0),held-reserved))))
        cap=(cap//p.pack_multiple)*p.pack_multiple
        if q>cap:
            q=cap;constraints.append('Лимит по сроку хранения и прогнозу продаж')
    if 0 < q < p.min_order_qty:
        q=0;constraints.append('Минимальная партия поставщика превышает допустимый заказ')
    if not supplier:
        constraints.append('Не указан поставщик')
    dleft=round(float((held-reserved)/rate),1) if rate>0 else None
    urgency='Срочно' if dleft is not None and dleft<lead else ('Планово' if q else 'Не требуется')
    cost=currency(D(q)*D(p.cost))
    return {'product_id':p.id,'name':p.name,'sku':p.sku,'supplier_id':p.supplier_id,'supplier_name':supplier.name if supplier else None,'lead_time_days':lead,'review_days':review,'stock':units(held),'physical_on_hand':units(physical),'reserved':units(reserved),'inbound':units(inbound_qty),'inventory_position':units(position),'daily_demand':fc['rate'],'safety_stock':safety,'target_stock':round(float(target),2),'raw_order_qty':round(float(raw),2),'quantity':q,'estimated_cost':cost,'expected_margin_per_unit':currency(D(p.price)-D(p.cost)),'days_to_stockout':dleft,'urgency':urgency,'constraints':constraints,'certainty':fc['data_quality'],'reason':f'Спрос {fc["rate"]} шт./день × {lead+review} дней + страховой запас {safety} − позиция {units(position)}. Кратность {p.pack_multiple}.','pack_multiple':p.pack_multiple,'min_order_qty':p.min_order_qty,'unit_cost':currency(p.cost),'shelf_life_days':p.shelf_life_days}

def recommendations(db,user):
    ps=db.scalars(select(m.Product).where(m.Product.tenant_id==user.tenant_id,m.Product.active==True).order_by(m.Product.name)).all()
    out=[recommend(db,user,p) for p in ps]
    return sorted(out,key=lambda x: (x['urgency']!='Срочно',-x['expected_margin_per_unit']*min(x['quantity'],x['daily_demand']*7)))

def budget_alloc(recs,budget):
    """Greedy pack allocation, NOT a globally optimal solver."""
    remaining=D(budget)
    if remaining<0:raise ValueError('Бюджет не может быть отрицательным')
    result={}
    candidates=[]
    for r in recs:
        if not r['supplier_id'] or r['quantity']<=0 or r['unit_cost']<=0:continue
        qty=int(r['quantity']);step=int(r['pack_multiple']);minimum=roundup(r['min_order_qty'],step)
        score=(2 if r['urgency']=='Срочно' else 1)*float(r['expected_margin_per_unit'])*max(0.1,r['daily_demand']) / max(1,r['unit_cost'])
        candidates.append((score,r,qty,step,minimum))
    for _,r,qty,step,minimum in sorted(candidates,key=lambda x:x[0],reverse=True):
        part=0
        unit=D(r['unit_cost'])
        while part+step<=qty and remaining>=unit*step:
            if part==0 and remaining<unit*minimum:break
            part+=step;remaining-=unit*step
        if part>=minimum:result[r['product_id']]=part
        elif part:
            remaining+=unit*part
    return {'allocations':result,'spent':currency(D(budget)-remaining),'unspent':currency(remaining),'method':'greedy_priority_packs (не глобальный оптимум)'}

def simulate(db,user,budget=150000,horizon=14,demand_factor=1.0,custom=None):
    if horizon<1 or horizon>90 or D(budget)<0 or not .5<=demand_factor<=1.5:raise ValueError('Неверные параметры сценария')
    ps=db.scalars(select(m.Product).where(m.Product.tenant_id==user.tenant_id,m.Product.active==True)).all()
    recs=[recommend(db,user,p) for p in ps]
    proposed={r['product_id']:int(r['quantity']) for r in recs if r['quantity']>0 and r['supplier_id']}
    allocated=budget_alloc(recs,budget)['allocations']
    if custom:
        bypid={p.id:p for p in ps}
        revised={}
        spent=D(0)
        for pid,q in custom.items():
            if pid not in bypid:raise ValueError('Неизвестный товар в сценарии')
            p=bypid[pid]
            r=next(r for r in recs if r['product_id']==pid)
            if int(q)<0 or int(q)%p.pack_multiple:raise ValueError('Количество должно быть неотрицательным и кратным упаковке')
            if int(q)>0 and (int(q)<p.min_order_qty or not p.supplier_id):raise ValueError('Не соблюдены ограничения поставщика')
            spent+=D(p.cost)*D(q)
            if q:revised[pid]=int(q)
        if spent>D(budget):raise ValueError('Сценарий превышает бюджет')
        allocated=revised
    cached={p.id:{'forecast':forecast(db,user,p),'lots':[(float(l.quantity),l.expires_at) for l in available_lots(db,user,p.id)],'inbound':float(inbound(db,user,p.id))} for p in ps}
    def run(orders,scale):
        totals={'revenue':D(0),'cogs':D(0),'purchase_spend':D(0),'lost_units':D(0),'lost_gross_margin':D(0),'expired_units':D(0),'expired_cost':D(0),'ending_stock':D(0),'stock_value':D(0)}
        daily=[]
        scenarios=[]
        for p in ps:
            fc=cached[p.id]['forecast']
            buckets=[{'q':q,'expiration':expiry} for q,expiry in cached[p.id]['lots']]
            arrival=next((r['lead_time_days'] for r in recs if r['product_id']==p.id),3)
            q_buy=int(orders.get(p.id,0))
            totals['purchase_spend']+=D(q_buy)*D(p.cost)
            for day_index in range(1,horizon+1):
                current=m.today()+timedelta(days=day_index)
                if day_index==max(1,arrival):
                    ex=current+timedelta(days=p.shelf_life_days) if p.shelf_life_days else None
                    if q_buy:buckets.append({'q':float(q_buy),'expiration':ex})
                    if cached[p.id]['inbound']:buckets.append({'q':cached[p.id]['inbound'],'expiration':ex})
                for b in buckets:
                    if b['expiration'] and b['expiration']<current and b['q']>0:
                        totals['expired_units']+=D(str(b['q']));totals['expired_cost']+=D(str(b['q']))*D(p.cost); b['q']=0
                buckets.sort(key=lambda b:b['expiration'] or date.max)
                wanted=D(fc['series'][day_index-1]['expected'])*D(scale)
                available=D(sum(b['q'] for b in buckets))
                sold=min(wanted,available)
                left=sold
                for b in buckets:
                    deducted=min(D(str(b['q'])),left)
                    b['q']=float(D(str(b['q']))-deducted);left-=deducted
                    if left<=0:break
                unmet=max(D(0),wanted-sold)
                totals['revenue']+=sold*D(p.price);totals['cogs']+=sold*D(p.cost)
                totals['lost_units']+=unmet
                totals['lost_gross_margin']+=unmet*(D(p.price)-D(p.cost))
                daily.append({'day':day_index,'product_id':p.id,'sold':float(sold),'lost':float(unmet)})
            ending=D(sum(b['q'] for b in buckets))
            totals['ending_stock']+=ending
            totals['stock_value']+=ending*D(p.cost)
        result={k:currency(v) if k not in ('lost_units','expired_units','ending_stock') else units(v) for k,v in totals.items()}
        result['gross_profit']=currency(totals['revenue']-totals['cogs'])
        result['estimated_writeoff_cost']=currency(totals['expired_cost'])
        result['orders']=len([v for v in orders.values() if v>0])
        return result
    baseline=run({},demand_factor)
    recommended=run(proposed,demand_factor)
    custom_result=run(allocated,demand_factor)
    custom_result['allocation']=budget_alloc(recs,budget) if not custom else {'allocations':allocated,'spent':currency(sum(D(next(p.cost for p in ps if p.id==pid))*D(q) for pid,q in allocated.items())),'method':'manual'}
    sensitivity={k:{'low':run(orders,.8)['lost_units'],'high':run(orders,1.2)['lost_units']} for k,orders in [('none',{}),('recommended',proposed),('budget',allocated)]}
    return {'scenarios':[{'key':'none','name':'Без закупки',**baseline},{'key':'recommended','name':'Рекомендованный заказ',**recommended},{'key':'budget','name':'Бюджет / свои количества',**custom_result}], 'sensitivity_lost_units':sensitivity,'assumptions':{'horizon_days':horizon,'demand_multiplier':demand_factor,'budget_kzt':budget,'arrival':'Поступление через lead_time_days поставщика','sales_rule':'min(спрос, доступный неистекший запас)','method':'детерминированная симуляция; без аренды, налогов и расходов на доставку','limitations':'Закупка полностью приходит в рассчитанный день; не моделирует цены и ограничения хранения; срок годности исходных партий учитывается'} ,'synthetic_demo':True}
