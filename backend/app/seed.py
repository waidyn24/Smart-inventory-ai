"""Reproducible clearly labelled DEMO data. Never seed a production environment."""
from datetime import date, timedelta
from decimal import Decimal
from random import Random
from .db import Base, engine, SessionLocal
from . import models as m
from argon2 import PasswordHasher

CATALOG=[
 ('Молоко 1 л','Молочные',540,390,5),('Кефир 1 л','Молочные',620,440,7),('Сметана 20%','Молочные',690,450,10),('Йогурт клубника','Молочные',480,300,14),('Масло сливочное','Молочные',1550,1050,30),('Сыр Гауда 200 г','Молочные',1350,890,35),
 ('Хлеб белый','Выпечка',240,145,2),('Хлеб бородинский','Выпечка',320,190,3),('Батон нарезной','Выпечка',280,170,3),('Лаваш','Выпечка',380,220,4),('Круассан','Выпечка',550,300,4),('Булочка с изюмом','Выпечка',320,190,4),
 ('Яйца С1 10 шт.','Бакалея',1150,850,28),('Рис 1 кг','Бакалея',860,570,None),('Гречка 1 кг','Бакалея',780,500,None),('Макароны 400 г','Бакалея',510,320,None),('Сахар 1 кг','Бакалея',540,380,None),('Мука 2 кг','Бакалея',900,620,None),('Соль 1 кг','Бакалея',170,95,None),('Овсянка 500 г','Бакалея',490,290,None),
 ('Масло подсолнечное 1 л','Бакалея',1050,790,None),('Чай чёрный 100 г','Напитки',1100,720,None),('Кофе растворимый 100 г','Напитки',2600,1800,None),('Вода 0.5 л','Напитки',220,100,365),('Вода 1.5 л','Напитки',340,165,365),('Газировка Cola 1 л','Напитки',690,440,180),('Сок яблочный 1 л','Напитки',790,510,180),('Энергетик 0.45 л','Напитки',850,580,365),
 ('Бананы 1 кг','Фрукты',950,650,7),('Яблоки 1 кг','Фрукты',870,520,21),('Груши 1 кг','Фрукты',1350,910,15),('Апельсины 1 кг','Фрукты',1100,740,14),('Лимон 1 кг','Фрукты',1700,1190,20),('Виноград 1 кг','Фрукты',1950,1350,10),
 ('Картофель 1 кг','Овощи',310,170,35),('Лук 1 кг','Овощи',260,140,40),('Морковь 1 кг','Овощи',270,150,25),('Помидоры 1 кг','Овощи',1250,850,12),('Огурцы 1 кг','Овощи',980,630,12),('Капуста 1 кг','Овощи',350,200,30),
 ('Чипсы 100 г','Снеки',850,550,180),('Сухарики 80 г','Снеки',380,230,180),('Шоколад 90 г','Снеки',830,520,365),('Печенье 250 г','Снеки',750,490,180),('Вафли 200 г','Снеки',620,400,180),('Мармелад 150 г','Снеки',690,420,180),
 ('Курица 1 кг','Мясо',2300,1700,6),('Фарш 500 г','Мясо',1650,1190,5),('Сосиски 400 г','Мясо',1350,940,14),('Колбаса варёная','Мясо',1980,1450,16),('Пельмени 800 г','Заморозка',2300,1700,180),('Наггетсы 500 г','Заморозка',1700,1130,180),
 ('Мороженое пломбир','Заморозка',480,280,180),('Мороженое эскимо','Заморозка',560,330,180),('Средство для посуды','Бытовое',990,590,None),('Салфетки 100 шт.','Бытовое',450,220,None),('Мыло жидкое 500 мл','Бытовое',950,570,None),('Порошок 1 кг','Бытовое',1700,1120,None),('Туалетная бумага 4 шт.','Бытовое',1100,680,None),('Губки 5 шт.','Бытовое',390,180,None)
]

def ean13(number):
    stem=f'200{number:09d}'
    odd=sum(int(stem[i]) for i in range(0,12,2))
    even=sum(int(stem[i]) for i in range(1,12,2))
    return stem+str((10-(odd+3*even)%10)%10)

def fill(db):
    rng=Random(20261010);tenant=m.Tenant(name='Demo Retail Kazakhstan');db.add(tenant);db.flush()
    store=m.Store(tenant_id=tenant.id,name='Smart Market • Алматы');db.add(store);db.flush()
    shop=m.StockLocation(tenant_id=tenant.id,store_id=store.id,name='Торговый зал',kind='shop')
    warehouse=m.StockLocation(tenant_id=tenant.id,store_id=store.id,name='Склад',kind='warehouse');db.add_all([shop,warehouse]);db.flush()
    supplier_specs=[('Almaty Dairy Distribution',3),('Kaz Bakery',1),('Fresh Line Produce',2),('City Wholesale',4),('Food Market Logistics',5)]
    suppliers=[]
    for name,lead in supplier_specs:
        s=m.Supplier(tenant_id=tenant.id,name=name,phone='+7 700 000 00 00',lead_time_days=lead);db.add(s);suppliers.append(s)
    db.flush()
    pwd=__import__('os').getenv('DEMO_PASSWORD','Demo2026!')
    for role,name in [('owner','Владелец'),('manager','Менеджер'),('cashier','Кассир'),('warehouse','Кладовщик')]:
        db.add(m.User(tenant_id=tenant.id,store_id=store.id,email=f'{role}@demo.kz',name=name,role=role,password_hash=PasswordHasher().hash(pwd)))
    db.flush()
    root=db.query(m.User).filter_by(role='owner').first()
    low_indices={0,1,6,12,23,28,34,40,46}
    near_expiry={2,7,29,37,48}
    today=m.today()
    for idx,(name,category,price,cost,expiry) in enumerate(CATALOG):
        sup=suppliers[2 if category in ('Фрукты','Овощи') else 0 if category=='Молочные' else 1 if category=='Выпечка' else idx%2+3]
        p=m.Product(tenant_id=tenant.id,name=name,sku=f'SKU-{idx+1:04d}',barcode=ean13(idx+1),category=category,unit='кг' if '1 кг' in name and category in ('Фрукты','Овощи') else 'шт.',price=price,cost=cost,supplier_id=sup.id,min_order_qty=2 if idx%4 else 6,pack_multiple=1 if idx%5 else 6,shelf_life_days=expiry,min_stock=8)
        db.add(p);db.flush()
        start=rng.randint(5,14) if idx in low_indices else rng.randint(65,145)
        lot=m.Lot(tenant_id=tenant.id,store_id=store.id,location_id=shop.id,product_id=p.id,lot_code=f'SEED-{idx+1:04d}',expires_at=today+timedelta(days=3+idx%4) if idx in near_expiry else (today+timedelta(days=max(expiry or 500,16)) if expiry else None),quantity=start)
        db.add(lot);db.flush()
        db.add(m.StockBalance(tenant_id=tenant.id,store_id=store.id,location_id=shop.id,product_id=p.id,quantity=start,reserved=0))
        db.add(m.StockMovement(tenant_id=tenant.id,store_id=store.id,location_id=shop.id,product_id=p.id,lot_id=lot.id,kind='RECEIVE',source_type='demo_seed',source_id=tenant.id,source_line_id=p.id,idempotency_key=f'seed:{p.id}',signed_quantity=start,actor_id=root.id))
        base=11.8 if idx in low_indices else rng.uniform(.9,5.0)
        for i in range(90,0,-1):
            day=today-timedelta(days=i)
            weekend=1.3 if day.weekday()>=5 else 1.0
            seasonal=1.0+.10*((i%14)-7)/7
            demand=max(0,round(base*weekend*seasonal+rng.uniform(-base*.3,base*.3)))
            db.add(m.DailyDemand(tenant_id=tenant.id,store_id=store.id,product_id=p.id,day=day,quantity=demand,stockout=(i%37==0 and idx%7==0),synthetic=True))
    db.add(m.AuditEvent(tenant_id=tenant.id,store_id=store.id,actor_id=root.id,action='DEMO_SEED',details=f'{len(CATALOG)} SKU, 90 дней СИНТЕТИЧЕСКОГО спроса.'))
    db.commit()
    return {'products':len(CATALOG),'tenant':tenant.id}

def reset_and_seed(db):
    db.rollback();db.close()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as fresh:return fill(fresh)

if __name__=='__main__':
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        if not session.query(m.Tenant).first():print(fill(session))
        else:print('Data exists, seed skipped')
