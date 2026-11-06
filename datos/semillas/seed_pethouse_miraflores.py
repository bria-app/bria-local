"""PetHouse Miraflores: tienda de mascotas de prueba con más de 30 meses de operación.

Datos sintéticos de una simulación controlada: no son evidencia de campo ni pertenecen a una
tienda real. Crea su empresa (dueño demo30@pethouse.pe, vendedora cvega, plan Premium), tres
proveedores, categorías Perros y Gatos y 10 productos con su operación desde el 1 de mayo de
2024 hasta ayer: stock inicial, compras con sus ingresos (proveedores que se atrasan y dejan
quiebres reales), tickets de caja con sus salidas y ventas perdidas en los días sin stock.

Cinco productos venden de forma regular y cinco de forma irregular (ver CATALOG). Los 3 meses
siguientes se generan con el mismo proceso y se guardan, con la demanda esperada de cada día,
en verdad_pethouse_miraflores.json, sin cargarlos en la base. Ese archivo permite comparar un
pronóstico contra lo que se sabe que iba a pasar.

Variables: DATABASE_URL, DEMO_OWNER_PASSWORD, DEMO_SELLER_PASSWORD y, para repetir los mismos
datos, SEED_HOY=AAAA-MM-DD. La empresa solo se carga una vez; --reiniciar borra sus datos de
prueba y sus corridas, y la vuelve a generar.

    PYTHONPATH=<carpeta de bria-api> python seed_pethouse_miraflores.py [--reiniciar]
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy import delete, select  # noqa: E402

import app.bootstrap.routers  # noqa: E402,F401
from app.modules.billing.infrastructure.persistence.models import SubscriptionModel  # noqa: E402
from app.modules.companies.infrastructure.persistence.models import CompanyModel, UserModel  # noqa: E402
from app.modules.data_preparation.infrastructure.persistence.models import PreparedDatasetModel  # noqa: E402
from app.modules.forecasting.infrastructure.persistence.models import (  # noqa: E402
    ForecastMetricsModel,
    ForecastResultModel,
    ForecastRunModel,
)
from app.modules.inventory.infrastructure.persistence.models import InventoryMovementModel  # noqa: E402
from app.modules.invoicing.infrastructure.persistence.models import InvoiceModel  # noqa: E402
from app.modules.products.infrastructure.persistence.models import CategoryModel, ProductModel  # noqa: E402
from app.modules.purchases.infrastructure.persistence.models import PurchaseModel  # noqa: E402
from app.modules.recommendations.infrastructure.persistence.models import RecommendationModel  # noqa: E402
from app.modules.sales.infrastructure.persistence.models import (  # noqa: E402
    LostSaleModel,
    SaleModel,
    SalesBatchModel,
    SalesOrderModel,
)
from app.modules.suppliers.domain.ruc import ruc_check_digit  # noqa: E402
from app.modules.suppliers.infrastructure.persistence.models import SupplierModel  # noqa: E402
from app.shared.infrastructure.database import SessionLocal  # noqa: E402
from app.shared.infrastructure.security.hashing import hash_password  # noqa: E402

TAG = "seed_mype30"
OWNER = "demo30@pethouse.pe"
OWNER_PASSWORD = os.getenv("DEMO_OWNER_PASSWORD", "").strip()
SELLER_USERNAME, SELLER_NAME = "cvega", "Carla Vega"
SELLER_PASSWORD = os.getenv("DEMO_SELLER_PASSWORD", "").strip()
COMPANY_RUC10 = "2061444555"

LIMA = timezone(timedelta(hours=-5))
IGV = Decimal("0.18")
TWO = Decimal("0.01")
_hoy = os.getenv("SEED_HOY", "").strip()
TODAY = date.fromisoformat(_hoy) if _hoy else datetime.now(LIMA).date()
START = date(2024, 5, 1)
END = TODAY - timedelta(days=1)  # history reaches yesterday
FUTURE_END = TODAY + timedelta(days=91)  # hidden truth: the next 92 days, never loaded
WEEKDAY = [0.82, 0.88, 0.92, 1.0, 1.12, 1.4, 1.05]  # Mon..Sun: Saturday is the big day
TRUTH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verdad_pethouse_miraflores.json")


def money(v) -> Decimal:
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


def ean13(body12: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


def payday(d: date) -> float:
    """Quincena and fin de mes: people buy food when they get paid."""
    return 1.18 if d.day in (15, 16, 30, 31, 1) else 1.0


def gratificacion(d: date) -> float:
    """July (Fiestas Patrias) and December bonuses lift everything a little."""
    if d.month == 7 and 10 <= d.day <= 31:
        return 1.12
    if d.month == 12 and d.day <= 24:
        return 1.2
    return 1.0


def months_since(d: date) -> float:
    return (d - START).days / 30.4375


# ------------------------------------------------------------------ the 10 products
# Each `rate(d)` is the EXPECTED units on day d before weekday/payday/bonus effects.
PROMO = (date(2025, 7, 14), date(2025, 7, 20))  # Cyber week: arena at 2x1


def r_arena(d):  # REGULAR: steady staple, slight growth; one promo week (outlier)
    promo = 2.6 if PROMO[0] <= d <= PROMO[1] else 1.0
    return 4.2 * (1.006 ** months_since(d)) * promo


def r_croquetas(d):  # REGULAR: clear growth and a strong December
    return 2.4 * (1.016 ** months_since(d)) * (1.18 if d.month == 12 else 1.0)


def r_pipeta(d):  # REGULAR: strong summer season (fleas and ticks in Lima's heat)
    return 1.5 * (1 + 0.7 * math.cos(2 * math.pi * (d.timetuple().tm_yday - 35) / 365.25))


def r_sobre(d):  # REGULAR: high volume, grew fast and then levelled off (S curve)
    return 8.0 + 15.0 / (1 + math.exp(-(months_since(d) - 13) / 2.6))


def r_shampoo(d):  # IRREGULAR: stable, then -40% for good when a vet opened next door
    return 2.4 * (0.6 if d >= date(2026, 4, 1) else 1.0)


def r_casaca(d):  # IRREGULAR: winter clothing, almost nothing in summer
    return 0.04 + 2.3 * math.exp(-((d.timetuple().tm_yday - 198) / 42.0) ** 2)


def r_placa(d):  # IRREGULAR: intermittent, a few a month
    return 0.15


CLINIC_RATE = 4.5 / 77.5  # clinic orders: 3-6 beds every 55-100 days, on average


def r_cama(d):  # IRREGULAR: sporadic single beds (big clinic orders are added apart)
    return 0.05


LAUNCH_DENTAL = date(2026, 7, 6)


def r_dental(d):  # IRREGULAR: new product (launched July 2026), still ramping up
    if d < LAUNCH_DENTAL:
        return 0.0
    return 0.8 + 2.6 * (1 - math.exp(-((d - LAUNCH_DENTAL).days / 7) / 5))


def r_cachorro(d):  # IRREGULAR: steady growth, but the supplier fails three times
    return 2.7 * (1.01 ** months_since(d))


FORCED_GAPS = [
    (date(2024, 11, 4), date(2024, 11, 25)),
    (date(2025, 9, 8), date(2025, 9, 29)),
    (date(2026, 6, 15), date(2026, 7, 6)),
]

# sku, name, (brand, type), cost, price history, lead, safety, reorder, rate, regular?, pattern, supplier idx
CATALOG = [
    ("SKU-201", "Arena para Gatos Aglomerante 10 kg", ("Gatos", "Higiene"), 28.0,
     [(START, 44.90), (date(2026, 2, 1), 47.90)], 5, 15, 35, r_arena, True,
     "estable con crecimiento leve y una semana de promoción (2x1, jul. 2025)", 0),
    ("SKU-202", "Croquetas Perro Adulto 15 kg", ("Perros", "Alimento"), 98.0,
     [(START, 139.90), (date(2026, 2, 1), 149.90)], 6, 8, 20, r_croquetas, True,
     "crecimiento claro, diciembre fuerte y 3 compras grandes de un albergue", 0),
    ("SKU-203", "Pipeta Antipulgas Perro 10 a 20 kg", ("Perros", "Salud"), 22.0,
     [(START, 39.90)], 7, 8, 20, r_pipeta, True,
     "estacional: se vende el triple en verano (enero-febrero) que en invierno", 1),
    ("SKU-204", "Comida Húmeda Gato Sobre 85 g", ("Gatos", "Alimento"), 2.1,
     [(START, 3.20), (date(2025, 9, 1), 3.50)], 4, 60, 140, r_sobre, True,
     "alto volumen: creció rápido en 2025 y ahora se estabilizó", 0),
    ("SKU-205", "Snack Dental Perro x 7 Unidades", ("Perros", "Alimento"), 10.5,
     [(START, 18.90)], 5, 8, 18, r_dental, False,
     "producto nuevo: lanzado el 6 jul. 2026, todavía creciendo (4 meses de historia)", 0),
    ("SKU-206", "Shampoo Hipoalergénico Perro 500 ml", ("Perros", "Higiene"), 12.0,
     [(START, 22.90)], 7, 6, 15, r_shampoo, False,
     "estable hasta mar. 2026; desde abril vende 40 % menos (abrió una veterinaria al lado)", 1),
    ("SKU-207", "Casaca Polar para Perro Talla M", ("Perros", "Accesorios"), 24.0,
     [(START, 45.00)], 10, 3, 8, r_casaca, False,
     "invierno (may.-sep.); casi nada en verano; solo se repone de abril a agosto", 2),
    ("SKU-208", "Placa de Identificación Grabada", ("Perros", "Accesorios"), 9.0,
     [(START, 25.00)], 7, 2, 4, r_placa, False,
     "intermitente: unas 4 al mes, muchos días sin venta", 2),
    ("SKU-209", "Cama Ortopédica Perro Grande", ("Perros", "Accesorios"), 85.0,
     [(START, 159.00)], 12, 1, 3, r_cama, False,
     "esporádica: camas sueltas y, de vez en cuando, una clínica pide 3 a 6 de golpe", 2),
    ("SKU-210", "Alimento Cachorro Raza Pequeña 3 kg", ("Perros", "Alimento"), 36.0,
     [(START, 49.90), (date(2026, 3, 1), 52.90)], 6, 10, 24, r_cachorro, False,
     "crece parejo, pero el proveedor falló 3 veces (3 semanas sin stock, con ventas perdidas)", 1),
]

SUPPLIERS = [
    ("2060777888", "Distribuidora Mascotas del Sur S.A.C.", "Jorge Salas", "pedidos@mascotasdelsur.pe",
     "Av. Los Héroes 455, San Juan de Miraflores, Lima"),
    ("2055999111", "Laboratorio VetAndes S.A.C.", "Milagros Paredes", "ventas@vetandes.pe",
     "Calle Las Begonias 120, San Isidro, Lima"),
    ("2061987654", "Confecciones Pet Gamarra E.I.R.L.", "Rosa Quispe", "ventas@petgamarra.pe",
     "Jr. Gamarra 680, La Victoria, Lima"),
]
CATEGORY_TREE = {"Perros": ["Alimento", "Higiene", "Salud", "Accesorios"], "Gatos": ["Alimento", "Higiene"]}
BULK_ORDERS = {  # an albergue buys croquetas in bulk with factura: outliers in the history
    "SKU-202": [(date(2024, 12, 7), 18), (date(2025, 6, 14), 22), (date(2026, 5, 23), 20)],
}
CORPORATE_CLIENTS = [
    ("2054321098", "Albergue Patitas Felices S.A.C."),
    ("2060555444", "Clínica Veterinaria Miraflores E.I.R.L."),
]


def price_on(history, d: date) -> Decimal:
    price = history[0][1]
    for since, p in history:
        if d >= since:
            price = p
    return money(price)


def expected(rate, d: date) -> float:
    return rate(d) * WEEKDAY[d.weekday()] * payday(d) * gratificacion(d)


def clinic_orders(rng: random.Random) -> dict[date, int]:
    """Cama: about every 2-3 months a clinic orders 3-6 beds at once (lumpy demand)."""
    out, d = {}, START + timedelta(days=rng.randint(20, 60))
    while d <= FUTURE_END:
        out[d] = rng.randint(3, 6)
        d += timedelta(days=rng.randint(55, 100))
    return out


def ensure_company(session) -> tuple[CompanyModel, UserModel, UserModel]:
    owner = session.execute(select(UserModel).where(UserModel.email == OWNER)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if owner is None:
        ruc = COMPANY_RUC10 + str(ruc_check_digit(COMPANY_RUC10))
        company = CompanyModel(name="PetHouse Miraflores", tax_id=ruc, business_type="Tienda de mascotas",
                               address="Av. José Larco 812, Miraflores, Lima", phone="01 4459012",
                               email=OWNER, plan="premium", status="active")
        session.add(company)
        session.flush()
        owner = UserModel(company_id=company.id, email=OWNER, full_name="Demo PetHouse Miraflores",
                          hashed_password=hash_password(OWNER_PASSWORD), role="owner", status="active")
        session.add(owner)
        session.flush()
    company = session.get(CompanyModel, owner.company_id)
    seller = session.execute(select(UserModel).where(UserModel.username == SELLER_USERNAME)).scalar_one_or_none()
    if seller is None:
        seller = UserModel(company_id=company.id, email=None, username=SELLER_USERNAME, full_name=SELLER_NAME,
                           hashed_password=hash_password(SELLER_PASSWORD), role="seller", status="active")
        session.add(seller)
        session.flush()
    if session.execute(select(SubscriptionModel.id).where(SubscriptionModel.company_id == company.id)).first() is None:
        session.add(SubscriptionModel(company_id=company.id, plan_id="premium", status="active",
                                      current_period_start=now, current_period_end=now + timedelta(days=365)))
    return company, owner, seller


def clean(session, company_id) -> None:
    """Everything this script (and earlier test runs) wrote for the company."""
    pids = [p for (p,) in session.execute(select(ProductModel.id).where(ProductModel.company_id == company_id)).all()]
    if pids:
        for model in (SaleModel, LostSaleModel, PurchaseModel, InventoryMovementModel):
            session.execute(delete(model).where(model.company_id == company_id, model.product_id.in_(pids)))
    run_ids = select(ForecastRunModel.id).where(ForecastRunModel.company_id == company_id)
    session.execute(delete(ForecastMetricsModel).where(ForecastMetricsModel.run_id.in_(run_ids)))
    for model in (RecommendationModel, ForecastResultModel):
        session.execute(delete(model).where(model.company_id == company_id))
    session.execute(delete(ForecastRunModel).where(ForecastRunModel.company_id == company_id))
    session.execute(delete(PreparedDatasetModel).where(PreparedDatasetModel.company_id == company_id))
    session.execute(delete(InvoiceModel).where(InvoiceModel.company_id == company_id))
    session.execute(delete(SalesOrderModel).where(SalesOrderModel.company_id == company_id))
    session.execute(delete(SalesBatchModel).where(SalesBatchModel.company_id == company_id))
    session.flush()


def main() -> None:
    if not OWNER_PASSWORD or not SELLER_PASSWORD:
        sys.exit("seed_pethouse_miraflores: define DEMO_OWNER_PASSWORD y DEMO_SELLER_PASSWORD.")
    rng = random.Random(2030)
    session = SessionLocal()
    try:
        company, owner, seller = ensure_company(session)
        company_id = company.id
        loaded = session.execute(select(SalesBatchModel.id).where(
            SalesBatchModel.company_id == company_id, SalesBatchModel.source_file == TAG)).first()
        if loaded and "--reiniciar" not in sys.argv:
            print("seed_pethouse_miraflores: la empresa ya está cargada; no se cambia nada.")
            return
        clean(session, company_id)

        def who(dt: datetime):  # the owner sells mornings and weekend mornings; Carla the rest
            return owner if dt.weekday() >= 5 and dt.hour < 14 or dt.hour < 11 else seller

        batch = SalesBatchModel(company_id=company_id, source_file=TAG, status="completed", row_count=0)
        session.add(batch)
        session.flush()

        suppliers = []
        for ruc10, name, contact, email, address in SUPPLIERS:
            ruc = ruc10 + str(ruc_check_digit(ruc10))
            s = session.execute(select(SupplierModel).where(SupplierModel.company_id == company_id,
                                                            SupplierModel.ruc == ruc)).scalar_one_or_none()
            if s is None:
                s = SupplierModel(company_id=company_id, ruc=ruc, business_name=name, contact_name=contact,
                                  email=email, phone="01 4" + ruc10[-6:], address=address, custom_attributes={})
                session.add(s)
                session.flush()
            suppliers.append(s)

        cats = {}
        for brand, types in CATEGORY_TREE.items():
            parent = session.execute(select(CategoryModel).where(
                CategoryModel.company_id == company_id, CategoryModel.name == brand,
                CategoryModel.parent_id.is_(None))).scalar_one_or_none()
            if parent is None:
                parent = CategoryModel(company_id=company_id, name=brand, description=f"Productos para {brand.lower()}")
                session.add(parent)
                session.flush()
            for t in types:
                child = session.execute(select(CategoryModel).where(
                    CategoryModel.company_id == company_id, CategoryModel.name == t,
                    CategoryModel.parent_id == parent.id)).scalar_one_or_none()
                if child is None:
                    child = CategoryModel(company_id=company_id, name=t, description="", parent_id=parent.id)
                    session.add(child)
                    session.flush()
                cats[(brand, t)] = child

        products = {}
        for i, (sku, name, cat, cost, prices, lead, safety, reorder, *_r) in enumerate(CATALOG, start=201):
            p = session.execute(select(ProductModel).where(ProductModel.company_id == company_id,
                                                           ProductModel.sku == sku)).scalar_one_or_none()
            if p is None:
                p = ProductModel(company_id=company_id, sku=sku, name=name, description="", custom_attributes={},
                                 currency="PEN", unit_of_measure="unidad", is_active=True,
                                 barcode=ean13(f"77530000{i:04d}"), category_id=cats[cat].id,
                                 unit_cost=money(cost), unit_price=price_on(prices, TODAY))
                session.add(p)
            p.name, p.category_id, p.is_active = name, cats[cat].id, True
            p.unit_cost = p.last_cost = money(cost)
            p.unit_price = price_on(prices, TODAY)
            p.lead_time_days, p.safety_stock, p.reorder_point = lead, safety, reorder
            session.flush()
            products[sku] = p
        company.next_product_code = max(company.next_product_code or 1, 211)

        truth = {"generated_for": TODAY.isoformat(), "history": [START.isoformat(), END.isoformat()],
                 "future": [TODAY.isoformat(), FUTURE_END.isoformat()], "note": "synthetic controlled simulation",
                 "company": company.name, "products": {}}
        lines, moves, purchases, lost = [], [], [], []
        doc = 7000
        camas = clinic_orders(random.Random(77))
        for sku, name, _cat, cost, prices, lead, _s, reorder, rate, regular, kind, sup_idx in CATALOG:
            p = products[sku]
            supplier = suppliers[sup_idx]
            launch = LAUNCH_DENTAL if sku == "SKU-205" else START
            mean_daily = sum(expected(rate, launch + timedelta(days=k)) for k in range(60)) / 60
            cover = rng.choice([24, 30, 36])  # days one order should last
            order_qty = max(6, int(round(mean_daily * cover)))
            if sku == "SKU-207":
                order_qty = 24  # two dozen coats from the workshop
            if sku == "SKU-209":
                order_qty = 8
            reorder_level = max(reorder, int(round(mean_daily * (lead + 6))))
            stock = {"SKU-205": 0, "SKU-207": 6, "SKU-209": 6}.get(sku, int(round(mean_daily * 35)) + 4)
            if stock:
                moves.append(InventoryMovementModel(
                    company_id=company_id, product_id=p.id, movement_type="inbound", quantity=stock,
                    reason="Inventario inicial al empezar con bria", occurred_at=datetime.combine(START, time(7), LIMA),
                    unit_cost=money(cost), reference_type="adjustment"))
            # The new snack arrives with its launch order.
            pending: tuple[date, int] | None = (LAUNCH_DENTAL, 60) if sku == "SKU-205" else None
            days = {}
            recent: list[int] = []  # units sold (or asked) in the last 28 days
            d = START
            while d <= FUTURE_END:
                mu = expected(rate, d)
                demand = poisson(rng, mu)
                bulk = dict(BULK_ORDERS.get(sku, [])).get(d, 0)
                if sku == "SKU-209" and d in camas:
                    bulk = camas[d]
                hist = d <= END
                sold = bulk_sold = 0
                if hist:
                    if sku == "SKU-207" and d.month == 4 and d.day == 8:  # coats bought for the winter
                        pending = (d + timedelta(days=lead), 30)
                    if pending and d >= pending[0]:
                        qty = pending[1]
                        unit_cost = money(cost * rng.uniform(0.97, 1.04) * (1.03 if d.year == 2026 else 1.0))
                        doc += 1
                        ref = uuid4()
                        number = f"F{sup_idx + 1:03d}-{doc:06d}"
                        purchases.append(PurchaseModel(
                            id=ref, company_id=company_id, supplier_id=supplier.id, product_id=p.id, purchase_date=d,
                            quantity=qty, unit_cost=unit_cost, total_amount=money(unit_cost * qty),
                            document_number=number, notes=TAG))
                        moves.append(InventoryMovementModel(
                            company_id=company_id, product_id=p.id, movement_type="inbound", quantity=qty,
                            reason=f"Compra {number}", occurred_at=datetime.combine(d, time(8, 30), LIMA),
                            unit_cost=unit_cost, reference_type="purchase", reference_id=ref))
                        stock += qty
                        pending = None
                    sold = min(demand, max(stock, 0))
                    if sold:
                        lines.append((d, p, sold, price_on(prices, d), money(cost), False))
                        stock -= sold
                    missing = demand - sold
                    if bulk:
                        if stock >= bulk:
                            disc = 0.92 if sku == "SKU-202" else 0.95
                            lines.append((d, p, bulk, money(float(price_on(prices, d)) * disc), money(cost), True))
                            stock -= bulk
                            bulk_sold = bulk
                        elif sku == "SKU-209":
                            missing += bulk  # the clinic asked, the shelf could not cover it
                    if missing > 0:
                        for k in range(1 if missing <= 3 else 2):
                            lost.append(LostSaleModel(
                                company_id=company_id, product_id=p.id,
                                requested_quantity=max(1, missing // (1 if missing <= 3 else 2)),
                                available_quantity=max(stock, 0), seller_id=seller.id, seller_name=seller.full_name,
                                source="pos",
                                occurred_at=datetime.combine(d, time(rng.randint(10, 20), rng.randint(0, 59)), LIMA)))
                    # Replenishment at the reorder level; a late supplier 6% of the time; the
                    # puppy-food supplier fails three times; coats only restocked April-August.
                    recent = (recent + [sold + max(0, missing) if missing > 0 else sold])[-28:]
                    if sku not in ("SKU-207", "SKU-209") and len(recent) == 28 and d.day == 1:
                        # Once a month the owner resizes orders to what has been selling lately.
                        pace = sum(recent) / 28
                        order_qty = max(6, int(round(pace * cover)))
                        reorder_level = max(reorder, int(round(pace * (lead + 6))))
                    seasonal = sku == "SKU-207" and not 4 <= d.month <= 8
                    if not seasonal and pending is None and stock <= reorder_level and d >= launch:
                        delay = lead + (rng.randint(6, 14) if rng.random() < 0.06 else 0)
                        arrival = d + timedelta(days=delay)
                        for g0, g1 in FORCED_GAPS if sku == "SKU-210" else []:
                            if g0 - timedelta(days=lead + 12) <= d <= g1:
                                arrival = max(arrival, g1)
                        pending = (arrival, order_qty)
                # Expected demand of the day (what a perfect forecast would say). The clinic's
                # bed orders are part of the cama's demand on average; the albergue's three bulk
                # buys of croquetas are one-offs and are not.
                exp = mu + (CLINIC_RATE if sku == "SKU-209" else 0.0)
                days[d.isoformat()] = {"expected": round(exp, 4), "demand": demand,
                                       "bulk": bulk_sold, "bulk_asked": bulk, "sold": sold}
                d += timedelta(days=1)
            truth["products"][sku] = {"name": name, "kind": kind, "regular": regular, "product_id": str(p.id),
                                      "days": days}

        # ------------------------------------------------------------ POS tickets
        basket = {"SKU-204": [1, 2, 3, 4, 6, 6, 12], "SKU-201": [1, 1, 1, 2], "SKU-202": [1, 1, 1, 1, 2],
                  "SKU-210": [1, 1, 1, 2], "SKU-205": [1, 1, 2], "SKU-203": [1, 1, 1, 2]}
        by_day = defaultdict(list)
        for ln in lines:
            d, p, qty, pr, c, bulk = ln
            if bulk:
                by_day[d].append(ln)
                continue
            left = qty
            while left > 0:
                q = min(left, rng.choice(basket.get(p.sku, [1, 1, 1, 2])))
                by_day[d].append((d, p, q, pr, c, False))
                left -= q
        sales, orders = [], []
        for d in sorted(by_day):
            day_lines = by_day[d]
            rng.shuffle(day_lines)
            i = 0
            while i < len(day_lines):
                if day_lines[i][5]:  # bulk order: its own factura
                    chunk = [day_lines[i]]
                    i += 1
                else:
                    size = rng.choice([1, 1, 1, 2, 2, 3])
                    chunk, seen = [], set()
                    while i < len(day_lines) and len(chunk) < size and not day_lines[i][5] and day_lines[i][1].sku not in seen:
                        chunk.append(day_lines[i])
                        seen.add(day_lines[i][1].sku)
                        i += 1
                    if not chunk:
                        chunk = [day_lines[i]]
                        i += 1
                hour = rng.choices(range(9, 22), weights=[2, 4, 6, 6, 5, 4, 5, 6, 8, 9, 8, 5, 2])[0]
                sold_at = datetime.combine(d, time(hour, rng.randint(0, 59)), LIMA)
                total = sum((money(q * pr) for _, _, q, pr, _, _ in chunk), Decimal("0"))
                subtotal = money(total / (1 + IGV))
                if chunk[0][5]:
                    doc_type, pay = "factura", "transferencia"
                    cruc, cname = CORPORATE_CLIENTS[0] if chunk[0][1].sku == "SKU-202" else CORPORATE_CLIENTS[1]
                    client = ("ruc", cruc + str(ruc_check_digit(cruc)), cname)
                else:
                    doc_type = rng.choices(["boleta", "nota_venta", "factura"], weights=[82, 13, 5])[0]
                    pay = rng.choices(["efectivo", "yape", "tarjeta", "plin"], weights=[38, 36, 16, 10])[0]
                    if doc_type == "factura":
                        cruc, cname = rng.choice(CORPORATE_CLIENTS)
                        client = ("ruc", cruc + str(ruc_check_digit(cruc)), cname)
                    else:
                        client = ("none", "", "")
                user = who(sold_at)
                order = SalesOrderModel(
                    id=uuid4(), company_id=company_id, order_number=-(10_000_000 + len(orders)), seller_id=user.id,
                    seller_name=user.full_name or "", document_type=doc_type, client_doc_type=client[0],
                    client_doc_number=client[1], client_name=client[2], payment_method=pay,
                    amount_received=(money(math.ceil(float(total) / 10) * 10) if pay == "efectivo" else None),
                    subtotal=subtotal, igv=money(total - subtotal), total=money(total), currency="PEN",
                    status="completed", notes=TAG, sold_at=sold_at)
                orders.append(order)
                for _, p, q, pr, c, _b in chunk:
                    sales.append(SaleModel(
                        company_id=company_id, product_id=p.id, batch_id=batch.id, sale_date=d, quantity=q,
                        unit_price=pr, total_amount=money(q * pr), currency="PEN", unit_cost=c,
                        order_id=order.id, seller_id=user.id, seller_name=user.full_name or ""))
                    moves.append(InventoryMovementModel(
                        company_id=company_id, product_id=p.id, movement_type="outbound", quantity=q,
                        reason="Venta en caja", occurred_at=sold_at, unit_cost=c, reference_type="sale",
                        reference_id=order.id))
        session.add_all(orders)
        session.flush()
        session.add_all(sales + moves + purchases + lost)
        batch.row_count = len(sales)
        batch.period_start, batch.period_end = START, END
        for n, o in enumerate(sorted(orders, key=lambda o: o.sold_at), start=1):
            o.order_number = -n
        session.flush()
        for o in orders:
            o.order_number = -o.order_number
        session.commit()

        with open(TRUTH_FILE, "w", encoding="utf-8") as fh:
            json.dump(truth, fh, ensure_ascii=False)
        stock_now = defaultdict(int)
        for m in moves:
            stock_now[m.product_id] += m.quantity if m.movement_type == "inbound" else -m.quantity
        print(f"company={company.name} id={company_id}")
        print(f"orders={len(orders)} lines={len(sales)} purchases={len(purchases)} moves={len(moves)} lost={len(lost)}")
        for sku, *_ in CATALOG:
            p = products[sku]
            units = sum(s.quantity for s in sales if s.product_id == p.id)
            print(f"{sku} {p.name[:38]:38} units={units:5d} stock_now={stock_now[p.id]:4d} "
                  f"lost={sum(1 for x in lost if x.product_id == p.id)}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
