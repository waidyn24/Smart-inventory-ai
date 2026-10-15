from __future__ import annotations
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import String, Integer, Numeric, DateTime, Date, ForeignKey, Boolean, UniqueConstraint, Index, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)
def today(): return datetime.now(ZoneInfo("Asia/Almaty")).date()
def pk(): return mapped_column(String(36), primary_key=True, default=uid)
def tenant(): return mapped_column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
def store(): return mapped_column(String(36), ForeignKey('stores.id'), nullable=False, index=True)
def created(): return mapped_column(DateTime(timezone=True), default=now, nullable=False)
def money(): return mapped_column(Numeric(16, 2), default=0, nullable=False)
def qty(): return mapped_column(Numeric(16, 3), default=0, nullable=False)

class Tenant(Base):
    __tablename__='tenants'
    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created()

class Store(Base):
    __tablename__='stores'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created()

class User(Base):
    __tablename__='users'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Supplier(Base):
    __tablename__='suppliers'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50), default='')
    lead_time_days: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Product(Base):
    __tablename__='products'
    __table_args__=(UniqueConstraint('tenant_id','sku'), UniqueConstraint('tenant_id','barcode'))
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    name: Mapped[str] = mapped_column(String(240))
    sku: Mapped[str] = mapped_column(String(70))
    barcode: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100), default='Другое')
    unit: Mapped[str] = mapped_column(String(15), default='шт.')
    price: Mapped[float] = money()
    cost: Mapped[float] = money()
    supplier_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('suppliers.id'), nullable=True)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1)
    pack_multiple: Mapped[int] = mapped_column(Integer, default=1)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_stock: Mapped[int] = mapped_column(Integer, default=8)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created()

class StockLocation(Base):
    __tablename__='stock_locations'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20), default='shop')

class Lot(Base):
    __tablename__='inventory_lots'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey('stock_locations.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'), index=True)
    lot_code: Mapped[str] = mapped_column(String(90))
    expires_at: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[float] = qty()
    received_at: Mapped[datetime] = created()

class StockBalance(Base):
    __tablename__='stock_balances'
    __table_args__=(UniqueConstraint('tenant_id','store_id','location_id','product_id'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey('stock_locations.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    quantity: Mapped[float] = qty()
    reserved: Mapped[float] = qty()

class StockMovement(Base):
    __tablename__='stock_movements'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),Index('ix_movement_sku_date','tenant_id','product_id','occurred_at'))
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey('stock_locations.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    lot_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('inventory_lots.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(35))
    source_type: Mapped[str] = mapped_column(String(45))
    source_id: Mapped[str] = mapped_column(String(36))
    source_line_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(220))
    signed_quantity: Mapped[float] = qty()
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('users.id'), nullable=True)
    occurred_at: Mapped[datetime] = created()

class Sale(Base):
    __tablename__='sales'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    cashier_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    total: Mapped[float] = money()
    cogs: Mapped[float] = money()
    created_at: Mapped[datetime] = created()

class SaleItem(Base):
    __tablename__='sale_items'
    id: Mapped[str] = pk()
    sale_id: Mapped[str] = mapped_column(String(36), ForeignKey('sales.id'), index=True)
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    quantity: Mapped[float] = qty()
    returned_qty: Mapped[float] = qty()
    unit_price: Mapped[float] = money()
    unit_cost: Mapped[float] = money()

class SaleReturn(Base):
    __tablename__='sale_returns'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    sale_id: Mapped[str] = mapped_column(String(36), ForeignKey('sales.id'))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = money()
    created_at: Mapped[datetime] = created()

class SaleReturnItem(Base):
    __tablename__='sale_return_items'
    id: Mapped[str] = pk()
    return_id: Mapped[str] = mapped_column(String(36), ForeignKey('sale_returns.id'), index=True)
    sale_item_id: Mapped[str] = mapped_column(String(36), ForeignKey('sale_items.id'))
    quantity: Mapped[float] = qty()
    unit_price: Mapped[float] = money()
    unit_cost: Mapped[float] = money()

class GoodsReceipt(Base):
    __tablename__='goods_receipts'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    supplier_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('suppliers.id'))
    purchase_order_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('purchase_orders.id'))
    invoice_number: Mapped[str] = mapped_column(String(100), default='')
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created()

class GoodsReceiptItem(Base):
    __tablename__='goods_receipt_items'
    id: Mapped[str] = pk()
    receipt_id: Mapped[str] = mapped_column(String(36), ForeignKey('goods_receipts.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey('inventory_lots.id'))
    quantity: Mapped[float] = qty()
    unit_cost: Mapped[float] = money()

class Stocktake(Base):
    __tablename__='stocktakes'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(20), default='draft')
    created_at: Mapped[datetime] = created()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class StocktakeItem(Base):
    __tablename__='stocktake_items'
    __table_args__=(UniqueConstraint('stocktake_id','product_id'),)
    id: Mapped[str] = pk()
    stocktake_id: Mapped[str] = mapped_column(String(36), ForeignKey('stocktakes.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    snapshot_qty: Mapped[float] = qty()
    counted_qty: Mapped[float | None] = mapped_column(Numeric(16,3), nullable=True)

class PurchaseOrder(Base):
    __tablename__='purchase_orders'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey('suppliers.id'))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(35), default='draft')
    created_at: Mapped[datetime] = created()

class PurchaseOrderItem(Base):
    __tablename__='purchase_order_items'
    id: Mapped[str] = pk()
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey('purchase_orders.id'))
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    quantity: Mapped[float] = qty()
    received_qty: Mapped[float] = qty()
    unit_cost: Mapped[float] = money()

class DailyDemand(Base):
    __tablename__='daily_demand'
    __table_args__=(UniqueConstraint('tenant_id','store_id','product_id','day'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey('products.id'))
    day: Mapped[datetime] = mapped_column(Date)
    quantity: Mapped[float] = qty()
    stockout: Mapped[bool] = mapped_column(Boolean, default=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

class AuditEvent(Base):
    __tablename__='audit_events'
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    store_id: Mapped[str] = store()
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(90))
    details: Mapped[str] = mapped_column(Text, default='')
    occurred_at: Mapped[datetime] = created()

class ImportJob(Base):
    __tablename__='import_jobs'
    __table_args__=(UniqueConstraint('tenant_id','sha256','kind'),)
    id: Mapped[str] = pk()
    tenant_id: Mapped[str] = tenant()
    kind: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = created()
