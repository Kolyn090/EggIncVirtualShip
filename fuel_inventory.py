"""Exact fixed Virtue fuel inventory, alongside the legacy four-fuel budget."""
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from fractions import Fraction
from functools import reduce
from math import gcd, lcm
import re

LEGACY_FUELS = ('curiousity', 'kindness', 'resilence', 'integrity')
INVENTORY_FUELS = (*LEGACY_FUELS, 'humility')
FUEL_NAMES = dict(zip(INVENTORY_FUELS, ('Curiosity', 'Kindness', 'Resilience', 'Integrity', 'Humility')))
ALIASES = {**{key: key for key in INVENTORY_FUELS}, 'curiosity': 'curiousity', 'resilience': 'resilence'}
TRILLION = 10**12


def parse_fuel_quantity(value):
    """New inventory quantities are eggs; legacy --fuel/--fuel-step remain T."""
    text = str(value).strip()
    match = re.fullmatch(r'((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([bBtT]?)', text)
    if not match:
        raise ValueError(f'Invalid fuel quantity {value!r}: use a nonnegative finite number, optionally followed by B or T')
    try:
        number = Decimal(match[1])
        sign, digits, exponent = number.as_tuple()
        if len(digits)>1000 or abs(exponent)>1000:
            raise ValueError('Fuel quantity exceeds supported decimal range')
        # Multiplication by powers of ten via the tuple is context-free: even
        # unusually precise values cannot round or underflow into extra fuel.
        quantity = Decimal((sign, digits, exponent + {'': 0, 'b': 9, 't': 12}[match[2].lower()]))
    except DecimalException as exc:
        raise ValueError('Fuel quantity exceeds supported decimal range') from exc
    if quantity > Decimal('1e27'):
        raise ValueError('Fuel quantity exceeds supported range (10^27 eggs)')
    return quantity


def parse_initial_fuel(entries):
    stock = dict.fromkeys(INVENTORY_FUELS, Fraction(0))
    seen = set()
    entries = entries.items() if isinstance(entries, dict) else (str(entry).partition('=')[::2] for entry in (entries or []))
    for key, value in entries:
        name = ALIASES.get(str(key).strip().lower())
        if name is None:
            raise ValueError(f'Unknown fuel type {key!r}; supported Virtue fuels: Curiosity, Kindness, Resilience, Integrity, Humility')
        if name in seen:
            raise ValueError(f'Duplicate starting fuel entry for {FUEL_NAMES[name]}')
        stock[name] = Fraction(parse_fuel_quantity(value)); seen.add(name)
    return stock


def decimal_value(value):
    value = Fraction(value)
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def exact_text(value):
    text = format(decimal_value(value), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def readable_fuel(value):
    value = Fraction(value)
    if abs(value) >= TRILLION: return exact_text(value / TRILLION) + 'T'
    if abs(value) >= 10**6: return exact_text(value / 10**9) + 'B'
    return exact_text(value)


def fixed_fuel(args):
    return getattr(args, 'fuel_mode', 'default') == 'existing_inventory'


def fuel_names(args):
    return INVENTORY_FUELS if fixed_fuel(args) else LEGACY_FUELS


def validate_fuel_export(data):
    """Reject a stale/inconsistent fuel table when rebuilding a new-mode HTML."""
    metadata=data.get('metadata', {})
    if metadata.get('fuel_mode') != 'existing_inventory':return
    try:
        rows={row['fuel']:row for row in metadata['fuel_inventory']}
        allocation={row['fuel']:row for row in data['fuel_allocation']}
        if len(metadata['fuel_inventory'])!=len(INVENTORY_FUELS) or len(data['fuel_allocation'])!=len(INVENTORY_FUELS) or set(rows)!=set(INVENTORY_FUELS) or set(allocation)!=set(rows):
            raise ValueError('Missing or duplicate fuel types')
        total_start=Fraction(0);total_used=Fraction(0)
        for name,row in rows.items():
            start=Fraction(row['starting_eggs']);used=sum((Fraction(r[name+'_T'])*TRILLION for r in data['launch_plan']),Fraction(0))
            remaining=start-used;csv=allocation[name]
            if start<0 or used<0 or remaining<0 or Fraction(row['consumed_eggs'])!=used or Fraction(row['remaining_eggs'])!=remaining:
                raise ValueError('Fuel balance disagrees with launch costs')
            for column,value in [('allocated_T',start),('starting_T',start),('used_T',used),('unused_T',remaining),('remaining_T',remaining)]:
                if Fraction(csv[column])*TRILLION!=value:raise ValueError('Fuel allocation CSV disagrees with launch costs')
            for field,value in [('starting',start),('consumed',used),('remaining',remaining)]:
                if row[field]!=readable_fuel(value):raise ValueError('Readable fuel quantity disagrees with exact balance')
            total_start+=start;total_used+=used
        expected=dict(starting=readable_fuel(total_start),consumed=readable_fuel(total_used),remaining=readable_fuel(total_start-total_used))
        if metadata['fuel_inventory_totals']!=expected:raise ValueError('Combined fuel totals disagree with individual fuels')
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Fixed fuel summary cannot be generated: '+str(exc)) from exc


class FuelInventory:
    def __init__(self, entries, mission, available):
        self.stock = parse_initial_fuel(entries)
        self.available = list(available)
        self.costs = []
        for ship in available:
            row = []
            for name in INVENTORY_FUELS:
                try:
                    value = Decimal(str(mission.loc[ship, name]))
                    if not value.is_finite() or value < 0: raise ValueError()
                    row.append(Fraction(value) * TRILLION)
                except (KeyError, ValueError, InvalidOperation) as exc:
                    raise ValueError(f'Existing inventory mode requires explicit finite nonnegative {name} fuel cost for {ship}; missing fuel is not zero') from exc
            self.costs.append(row)
        self.rows = []
        totals = [sum(row) for row in self.costs]
        scale = lcm(*(value.denominator for value in totals))
        self.total_unit = Fraction(reduce(gcd, (int(value*scale) for value in totals), 0) or 1, scale)
        self.effort_costs = [int(value/self.total_unit) for value in totals]
        if max(self.effort_costs) > 2**50:
            raise ValueError('Total fuel cost scaling exceeds exact MILP integer range')
        for k, name in enumerate(INVENTORY_FUELS):
            costs = [row[k] for row in self.costs]
            scale = lcm(*(value.denominator for value in costs))
            divisor = reduce(gcd, (int(value * scale) for value in costs), 0)
            if not divisor: continue  # genuinely free on this axis
            unit = Fraction(divisor, scale)
            coefficients = [int(value / unit) for value in costs]
            capacity = int(self.stock[name] // unit)
            if max(*coefficients, capacity) > 2**50:
                raise ValueError(f'{FUEL_NAMES[name]} inventory/cost scaling exceeds exact MILP integer range')
            self.rows.append((coefficients, capacity))

    def launch_bound(self, j):
        bounds = [capacity // costs[j] for costs, capacity in self.rows if costs[j]]
        return min(bounds) if bounds else float('inf')

    def used(self, schedule):
        indices = {ship: i for i, ship in enumerate(self.available)}
        used = [Fraction(0) for _ in INVENTORY_FUELS]
        for row in schedule:
            for k, value in enumerate(self.costs[indices[row[2]]]): used[k] += value
        for name, value in zip(INVENTORY_FUELS, used):
            if value > self.stock[name]:
                raise ValueError(f'Independent exact fuel validation failed: {FUEL_NAMES[name]} consumed {readable_fuel(value)} exceeds inventory {readable_fuel(self.stock[name])}')
        return used

    def summary(self, schedule):
        rows = []
        for name, used in zip(INVENTORY_FUELS, self.used(schedule)):
            start = self.stock[name]; remaining = start - used
            rows.append(dict(fuel=name, fuel_name=FUEL_NAMES[name], starting_T=decimal_value(start/TRILLION),
                used_T=decimal_value(used/TRILLION), allocated_T=decimal_value(start/TRILLION), unused_T=decimal_value(remaining/TRILLION),
                remaining_T=decimal_value(remaining/TRILLION), percentage_consumed=float(used/start*100) if start else None,
                starting_eggs=exact_text(start), consumed_eggs=exact_text(used), remaining_eggs=exact_text(remaining),
                starting=readable_fuel(start), consumed=readable_fuel(used), remaining=readable_fuel(remaining)))
        return rows

    def totals(self, schedule):
        start = sum(self.stock.values()); used = sum(self.used(schedule))
        return dict(starting=readable_fuel(start), consumed=readable_fuel(used), remaining=readable_fuel(start-used))

    def physical_stages(self, stages):
        """Minimize in exact integer fuel units; present stage values in T."""
        converted=[]
        for original in stages:
            row=dict(original)
            if row['objective']=='fuel consumption':
                row['integer_fuel_unit_eggs']=exact_text(self.total_unit)
                for key in ['value','bound']:
                    if row.get(key) is not None:row[key]=float(Fraction(str(row[key]))*self.total_unit/TRILLION)
            converted.append(row)
        return converted
