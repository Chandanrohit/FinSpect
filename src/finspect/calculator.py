"""FinSpect deterministic financial calculator.

Python 3.11+ | Decimal-only arithmetic | No eval/exec.

Formula provenance
------------------
* BENCHMARK: formulas stated explicitly in finspect_benchmark_v02_clean(2).json.
* BENCHMARK-DERIVED: the benchmark names a calculation but does not specify its
  equation; the implementation below makes the operational definition explicit.
* FINANCEQA-COMMON: supplementary financial-analysis equations commonly used
  to answer numerical financial-statement questions. These are not claimed to
  be formulas present in the FinSpect benchmark JSON.

The module accepts normalized numeric values. Retrieval, evidence selection,
period matching, currency conversion, and sign normalization belong upstream.
All percentage outputs are expressed in percentage points (e.g. 12.5 means 12.5%).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from enum import StrEnum
from typing import Callable, Mapping, Sequence

D = Decimal
ZERO = D("0")
HUNDRED = D("100")


class FormulaError(ValueError):
    """Invalid inputs or mathematically undefined calculation."""


class FormulaSource(StrEnum):
    BENCHMARK = "benchmark_json"
    BENCHMARK_DERIVED = "benchmark_derived_definition"
    FINANCEQA_COMMON = "financeqa_common_extension"


@dataclass(frozen=True, slots=True)
class CalculationResult:
    formula_id: str
    value: Decimal | None
    unit: str
    expression: str
    inputs: Mapping[str, Decimal]
    source: FormulaSource
    notes: tuple[str, ...] = ()
    metrics: Mapping[str, Decimal] | None = None


def dec(value: Decimal | int | str) -> Decimal:
    """Convert a numeric input without introducing binary-float artifacts."""
    if isinstance(value, float):
        raise TypeError("Pass Decimal, int, or str; float inputs are not accepted.")
    try:
        result = value if isinstance(value, Decimal) else D(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FormulaError(f"Invalid decimal input: {value!r}") from exc
    if not result.is_finite():
        raise FormulaError("Financial inputs must be finite Decimal values.")
    return result


def _div(numerator: Decimal, denominator: Decimal, *, label: str) -> Decimal:
    if denominator == ZERO:
        raise FormulaError(f"{label}: denominator is zero; result is undefined.")
    with localcontext() as ctx:
        ctx.prec = 28
        return numerator / denominator


def _pct(numerator: Decimal, denominator: Decimal, *, label: str) -> Decimal:
    return _div(numerator * HUNDRED, denominator, label=label)


def _result(fid: str, value: Decimal, unit: str, expression: str,
            inputs: Mapping[str, Decimal], source: FormulaSource,
            *notes: str) -> CalculationResult:
    return CalculationResult(fid, value, unit, expression, dict(inputs), source, tuple(notes))


# ---------------------------------------------------------------------------
# FinSpect benchmark Q01-Q15, Q18
# ---------------------------------------------------------------------------

def revenue_growth(current: Decimal, prior: Decimal) -> CalculationResult:
    c, p = dec(current), dec(prior)
    delta = c - p
    return _result("Q01", _pct(delta, p, label="revenue growth"), "percent",
                   "(current_revenue - prior_revenue) / prior_revenue * 100",
                   {"current_revenue": c, "prior_revenue": p}, FormulaSource.BENCHMARK)


def segment_growth_contribution(segment_current: Decimal, segment_prior: Decimal,
                                 total_current: Decimal, total_prior: Decimal) -> CalculationResult:
    sc, sp, tc, tp = map(dec, (segment_current, segment_prior, total_current, total_prior))
    return _result("Q02", _pct(sc-sp, tc-tp, label="segment growth contribution"), "percent",
                   "(segment_current - segment_prior) / (total_current - total_prior) * 100",
                   {"segment_current": sc, "segment_prior": sp, "total_current": tc, "total_prior": tp},
                   FormulaSource.BENCHMARK,
                   "Apply to each segment; select the largest absolute positive increase per the benchmark rule.")


def margin_change(current_income: Decimal, current_revenue: Decimal,
                  prior_income: Decimal, prior_revenue: Decimal) -> CalculationResult:
    ci, cr, pi, pr = map(dec, (current_income, current_revenue, prior_income, prior_revenue))
    cm, pm = _pct(ci, cr, label="current margin"), _pct(pi, pr, label="prior margin")
    return _result("Q03", cm-pm, "percentage_points",
                   "(current_income/current_revenue*100) - (prior_income/prior_revenue*100)",
                   {"current_income": ci, "current_revenue": cr, "prior_income": pi, "prior_revenue": pr},
                   FormulaSource.BENCHMARK, f"current_margin={cm}; prior_margin={pm}")


def expense_growth_contribution(category_current: Decimal, category_prior: Decimal,
                                opex_current: Decimal, opex_prior: Decimal) -> CalculationResult:
    cc, cp, oc, op = map(dec, (category_current, category_prior, opex_current, opex_prior))
    return _result("Q04", _pct(cc-cp, oc-op, label="expense growth contribution"), "percent",
                   "(category_current-category_prior)/(total_opex_current-total_opex_prior)*100",
                   {"category_current": cc, "category_prior": cp, "opex_current": oc, "opex_prior": op},
                   FormulaSource.BENCHMARK)


def earnings_change_relationship(net_current: Decimal, net_prior: Decimal,
                                  operating_current: Decimal, operating_prior: Decimal) -> CalculationResult:
    nc, np, oc, op = map(dec, (net_current, net_prior, operating_current, operating_prior))
    return _result("Q05", _pct(nc-np, oc-op, label="earnings change relationship"), "percent",
                   "(net_income_current-net_income_prior)/(operating_income_current-operating_income_prior)*100",
                   {"net_current": nc, "net_prior": np, "operating_current": oc, "operating_prior": op},
                   FormulaSource.BENCHMARK,
                   "This is a change relationship, not a causal attribution measure.")


def balance_change(ending: Decimal, beginning: Decimal, *, formula_id: str = "Q06") -> CalculationResult:
    e, b = dec(ending), dec(beginning)
    return _result(formula_id, e-b, "currency", "ending_balance - beginning_balance",
                   {"ending": e, "beginning": b}, FormulaSource.BENCHMARK)


def liquid_asset_contribution(liquid_end: Decimal, liquid_begin: Decimal,
                              assets_end: Decimal, assets_begin: Decimal) -> CalculationResult:
    le, lb, ae, ab = map(dec, (liquid_end, liquid_begin, assets_end, assets_begin))
    return _result("Q07", _pct(le-lb, ae-ab, label="liquid asset contribution"), "percent",
                   "(liquid_end-liquid_begin)/(total_assets_end-total_assets_begin)*100",
                   {"liquid_end": le, "liquid_begin": lb, "assets_end": ae, "assets_begin": ab},
                   FormulaSource.BENCHMARK)


def growth_comparison(ar_current: Decimal, ar_prior: Decimal,
                      revenue_current: Decimal, revenue_prior: Decimal) -> CalculationResult:
    ac, ap, rc, rp = map(dec, (ar_current, ar_prior, revenue_current, revenue_prior))
    ag, rg = _pct(ac-ap, ap, label="receivables growth"), _pct(rc-rp, rp, label="revenue growth")
    return _result("Q08", ag-rg, "percentage_points", "receivables_growth - revenue_growth",
                   {"ar_current": ac, "ar_prior": ap, "revenue_current": rc, "revenue_prior": rp},
                   FormulaSource.BENCHMARK, f"receivables_growth={ag}; revenue_growth={rg}")


def inventory_revenue_growth_comparison(inventory_current: Decimal, inventory_prior: Decimal,
                                        revenue_current: Decimal, revenue_prior: Decimal) -> CalculationResult:
    ic, ip, rc, rp = map(dec, (inventory_current, inventory_prior, revenue_current, revenue_prior))
    ig, rg = _pct(ic-ip, ip, label="inventory growth"), _pct(rc-rp, rp, label="revenue growth")
    return _result("Q09", ig-rg, "percentage_points", "inventory_growth - revenue_growth",
                   {"inventory_current": ic, "inventory_prior": ip, "revenue_current": rc, "revenue_prior": rp},
                   FormulaSource.BENCHMARK_DERIVED,
                   f"inventory_growth={ig}; revenue_growth={rg}",
                   "Benchmark specifies the comparison but not an equation; this defines it as growth-rate difference.",
                   "Inventory is a point-in-time balance; revenue is a period flow. Compare matching fiscal endpoints and comparable revenue durations.")


def capital_allocation_ratio(amount: Decimal, operating_cash_flow: Decimal, *, formula_id: str = "Q10",
                             input_name: str = "share_repurchase_cash") -> CalculationResult:
    a, c = dec(amount), dec(operating_cash_flow)
    return _result(formula_id, _pct(a, c, label="capital allocation ratio"), "percent",
                   f"{input_name} / operating_cash_flow * 100",
                   {input_name: a, "operating_cash_flow": c}, FormulaSource.BENCHMARK)


def dilution_ratio(basic_shares: Decimal, diluted_shares: Decimal) -> CalculationResult:
    b, d = dec(basic_shares), dec(diluted_shares)
    effect = d-b
    if effect < ZERO:
        raise FormulaError("Diluted weighted-average shares cannot be below basic shares for this calculation.")
    return _result("Q11", _pct(effect, b, label="dilution ratio"), "percent",
                   "(diluted_weighted_average_shares-basic_weighted_average_shares)/basic_weighted_average_shares*100",
                   {"basic_shares": b, "diluted_shares": d, "dilutive_effect": effect},
                   FormulaSource.BENCHMARK,
                   "The dilutive effect is derived as diluted shares minus basic shares.")


def equity_component_contribution(component_amount: Decimal, ending_equity: Decimal,
                                   *, component_name: str = "component") -> CalculationResult:
    c, e = dec(component_amount), dec(ending_equity)
    return _result("Q12", _pct(c, e, label="equity component contribution"), "percent",
                   "largest_equity_component / ending_equity * 100",
                   {component_name: c, "ending_equity": e}, FormulaSource.BENCHMARK_DERIVED,
                   "Benchmark names this calculation but does not define the equation; provide the selected component amount.")


def cash_conversion(operating_cash_flow: Decimal, net_income: Decimal) -> CalculationResult:
    c, n = dec(operating_cash_flow), dec(net_income)
    return _result("Q13", _pct(c, n, label="cash conversion"), "percent",
                   "operating_cash_flow / net_income * 100", {"operating_cash_flow": c, "net_income": n},
                   FormulaSource.BENCHMARK)


def cash_allocation(share_repurchase: Decimal, dividends: Decimal, capex: Decimal,
                    operating_cash_flow: Decimal) -> CalculationResult:
    r, d, x, c = map(dec, (share_repurchase, dividends, capex, operating_cash_flow))
    # The caller must normalize cash outflows to positive economic amounts.
    return _result("Q14", _pct(r+d+x, c, label="cash allocation"), "percent",
                   "(share_repurchase + dividends + capital_expenditure) / operating_cash_flow * 100",
                   {"share_repurchase": r, "dividends": d, "capital_expenditure": x, "operating_cash_flow": c},
                   FormulaSource.BENCHMARK,
                   "Cash outflows must be passed as positive economic amounts, as required by the benchmark.")


def commitment_liquidity(near_term_commitments: Decimal, total_commitments: Decimal,
                         liquid_resources: Decimal) -> CalculationResult:
    n, t, l = map(dec, (near_term_commitments, total_commitments, liquid_resources))
    near_share = _pct(n, t, label="near-term commitment share")
    coverage = _div(l, n, label="liquid resource coverage of near-term commitments")
    return _result("Q15", coverage, "x", "liquid_resources / near_term_commitments",
                   {"near_term_commitments": n, "total_commitments": t, "liquid_resources": l},
                   FormulaSource.BENCHMARK_DERIVED,
                   f"near_term_commitment_share={near_share}%",
                   "Benchmark asks for both near-term share and liquidity comparison; coverage is shown as liquid resources divided by near-term commitments.")


def sensitivity_ratio(sensitivity_amount: Decimal, relevant_measure: Decimal) -> CalculationResult:
    s, m = dec(sensitivity_amount), dec(relevant_measure)
    return _result("Q18", _pct(s, m, label="market-risk sensitivity ratio"), "percent",
                   "disclosed_sensitivity_amount / relevant_financial_measure * 100",
                   {"sensitivity_amount": s, "relevant_measure": m}, FormulaSource.BENCHMARK_DERIVED,
                   "The filing determines the sensitivity definition and the appropriate denominator; do not infer either from this function.")


# ---------------------------------------------------------------------------
# FinanceQA-common extensions (not specified in the benchmark JSON)
# ---------------------------------------------------------------------------
def gross_profit(revenue: Decimal, cost_of_revenue: Decimal) -> Decimal:
    return dec(revenue)-dec(cost_of_revenue)


def gross_margin(revenue: Decimal, cost_of_revenue: Decimal) -> Decimal:
    r, c = dec(revenue), dec(cost_of_revenue)
    return _pct(r-c, r, label="gross margin")


def operating_margin(operating_income: Decimal, revenue: Decimal) -> Decimal:
    return _pct(dec(operating_income), dec(revenue), label="operating margin")


def net_profit_margin(net_income: Decimal, revenue: Decimal) -> Decimal:
    return _pct(dec(net_income), dec(revenue), label="net profit margin")


def current_ratio(current_assets: Decimal, current_liabilities: Decimal) -> Decimal:
    return _div(dec(current_assets), dec(current_liabilities), label="current ratio")


def quick_ratio(current_assets: Decimal, inventory: Decimal, current_liabilities: Decimal,
                prepaid_expenses: Decimal = ZERO) -> Decimal:
    return _div(dec(current_assets)-dec(inventory)-dec(prepaid_expenses), dec(current_liabilities), label="quick ratio")


def cash_ratio(cash_and_equivalents: Decimal, current_liabilities: Decimal,
               short_term_investments: Decimal = ZERO) -> Decimal:
    return _div(dec(cash_and_equivalents)+dec(short_term_investments), dec(current_liabilities), label="cash ratio")


def working_capital(current_assets: Decimal, current_liabilities: Decimal) -> Decimal:
    return dec(current_assets)-dec(current_liabilities)


def debt_to_equity(total_debt: Decimal, total_equity: Decimal) -> Decimal:
    return _div(dec(total_debt), dec(total_equity), label="debt-to-equity")


def debt_ratio(total_liabilities: Decimal, total_assets: Decimal) -> Decimal:
    return _div(dec(total_liabilities), dec(total_assets), label="debt ratio")


def return_on_assets(net_income: Decimal, average_total_assets: Decimal) -> Decimal:
    return _pct(dec(net_income), dec(average_total_assets), label="return on assets")


def return_on_equity(net_income: Decimal, average_equity: Decimal) -> Decimal:
    return _pct(dec(net_income), dec(average_equity), label="return on equity")


def asset_turnover(revenue: Decimal, average_total_assets: Decimal) -> Decimal:
    return _div(dec(revenue), dec(average_total_assets), label="asset turnover")


def inventory_turnover(cost_of_revenue: Decimal, average_inventory: Decimal) -> Decimal:
    return _div(dec(cost_of_revenue), dec(average_inventory), label="inventory turnover")


def days_inventory_outstanding(average_inventory: Decimal, cost_of_revenue: Decimal,
                               days: Decimal = D("365")) -> Decimal:
    return _div(dec(average_inventory)*dec(days), dec(cost_of_revenue), label="days inventory outstanding")


def receivables_turnover(net_credit_sales: Decimal, average_receivables: Decimal) -> Decimal:
    return _div(dec(net_credit_sales), dec(average_receivables), label="receivables turnover")


def days_sales_outstanding(average_receivables: Decimal, net_credit_sales: Decimal,
                           days: Decimal = D("365")) -> Decimal:
    return _div(dec(average_receivables)*dec(days), dec(net_credit_sales), label="days sales outstanding")


def eps(net_income_attributable_to_common: Decimal, weighted_average_shares: Decimal) -> Decimal:
    return _div(dec(net_income_attributable_to_common), dec(weighted_average_shares), label="EPS")


def book_value_per_share(total_common_equity: Decimal, common_shares_outstanding: Decimal) -> Decimal:
    return _div(dec(total_common_equity), dec(common_shares_outstanding), label="book value per share")


def dividend_payout_ratio(dividends: Decimal, net_income: Decimal) -> Decimal:
    return _pct(dec(dividends), dec(net_income), label="dividend payout ratio")


def dividend_yield(dividend_per_share: Decimal, market_price_per_share: Decimal) -> Decimal:
    return _pct(dec(dividend_per_share), dec(market_price_per_share), label="dividend yield")


def price_earnings_ratio(market_price_per_share: Decimal, earnings_per_share: Decimal) -> Decimal:
    return _div(dec(market_price_per_share), dec(earnings_per_share), label="P/E ratio")


def cagr(beginning_value: Decimal, ending_value: Decimal, years: Decimal) -> Decimal:
    b, e, y = map(dec, (beginning_value, ending_value, years))
    if b <= ZERO or e < ZERO or y <= ZERO:
        raise FormulaError("CAGR requires beginning > 0, ending >= 0, and years > 0.")
    # Decimal has no general fractional power across all supported Python versions.
    # Use exp(ln(x)/n) under a local Decimal context.
    with localcontext() as ctx:
        ctx.prec = 28
        try:
            rate = (e / b).ln() / y
            growth = rate.exp() - D(1)
        except (InvalidOperation, DivisionByZero) as exc:
            raise FormulaError("CAGR is undefined for these inputs.") from exc
    return growth * HUNDRED


def percentage_change(current: Decimal, prior: Decimal) -> Decimal:
    c, p = dec(current), dec(prior)
    return _pct(c-p, p, label="percentage change")


def percentage_of_total(part: Decimal, total: Decimal) -> Decimal:
    return _pct(dec(part), dec(total), label="percentage of total")


def absolute_change(current: Decimal, prior: Decimal) -> Decimal:
    return dec(current)-dec(prior)


def largest_increase_contributor(
    segment_changes: Mapping[str, Decimal],
    total_revenue_change: Decimal,
) -> tuple[str, CalculationResult]:
    """Select the segment with the largest increase and calculate its contribution (Q02)."""
    if not segment_changes:
        raise FormulaError("At least one disclosed segment change is required.")
    normalized = {name: dec(value) for name, value in segment_changes.items()}
    # Only increases qualify; do not silently select a decline when all segments fell.
    positive = {name: value for name, value in normalized.items() if value > ZERO}
    if not positive:
        raise FormulaError("No segment has a positive revenue increase.")
    name, change = max(positive.items(), key=lambda item: item[1])
    total = dec(total_revenue_change)
    result = _result(
        "Q02", _pct(change, total, label="segment growth contribution"), "percent",
        "largest_positive_segment_increase / total_revenue_increase * 100",
        {"selected_segment_increase": change, "total_revenue_increase": total},
        FormulaSource.BENCHMARK, f"selected_segment={name}"
    )
    return name, result


def largest_component_contribution(
    components: Mapping[str, Decimal], ending_equity: Decimal
) -> tuple[str, CalculationResult]:
    """Select the largest disclosed equity component and calculate its share (Q12)."""
    if not components:
        raise FormulaError("At least one disclosed equity component is required.")
    normalized = {name: dec(value) for name, value in components.items()}
    name, amount = max(normalized.items(), key=lambda item: abs(item[1]))
    return name, equity_component_contribution(amount, ending_equity, component_name=name)


def commitment_metrics(near_term_commitments: Decimal, total_commitments: Decimal,
                       liquid_resources: Decimal) -> Mapping[str, Decimal]:
    """Return both Q15 outputs explicitly: near-term share and liquid-resource coverage."""
    n, t, l = map(dec, (near_term_commitments, total_commitments, liquid_resources))
    return {
        "near_term_commitment_share_percent": _pct(n, t, label="near-term commitment share"),
        "liquid_resource_coverage_x": _div(l, n, label="liquid resource coverage"),
        "liquid_resources_less_near_term_commitments": l-n,
    }


# Explicit registry: dispatch is by trusted formula ID, never by executing strings.
BENCHMARK_FORMULAS: Mapping[str, Callable[..., CalculationResult]] = {
    "Q01": revenue_growth, "Q02": segment_growth_contribution,
    "Q03": margin_change, "Q04": expense_growth_contribution,
    "Q05": earnings_change_relationship, "Q06": balance_change,
    "Q07": liquid_asset_contribution, "Q08": growth_comparison,
    "Q09": inventory_revenue_growth_comparison, "Q10": capital_allocation_ratio,
    "Q11": dilution_ratio, "Q12": equity_component_contribution,
    "Q13": cash_conversion, "Q14": cash_allocation,
    "Q15": commitment_liquidity, "Q18": sensitivity_ratio,
}

# Q16, Q17, Q19, and Q20 are retrieval/interpretation tasks, not calculator formulas.
NON_CALCULATION_BENCHMARK_IDS = ("Q16", "Q17", "Q19", "Q20")

__all__ = [name for name in globals() if not name.startswith("_")]
