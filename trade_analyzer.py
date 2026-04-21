"""
Arbitrage Trade Analyzer
Berechnet ob ein Trade profitabel ist NACH Gebühren
"""

def calculate_real_spread(buy_exchange: str, sell_exchange: str, buy_price: float, sell_price: float, 
                         volume: float, fee_tiers: dict = None) -> dict:
    """
    Berechnet ob ein Arbitrage Trade profitabel ist.
    
    Args:
        buy_exchange: 'MEXC' oder 'KuCoin'
        sell_exchange: 'MEXC' oder 'KuCoin'  
        buy_price: Preis zu dem gekauft wird
        sell_price: Preis zu dem verkauft wird
        volume: Menge in MPC
        fee_tiers: Dictionary mit Fee-Prozenten pro Exchange
        
    Returns:
        dict mit Berechnungsergebnissen
    """
    import yaml
    
    # Default fee tiers (Taker fees für beide Exchanges)
    if fee_tiers is None:
        fee_tiers = {
            'MEXC': 0.001,   # 0.1% Taker
            'KuCoin': 0.001   # 0.1% Taker  
        }
    
    # Fee berechnen basierend auf Trade-Richtung
    buy_fee_pct = fee_tiers.get(buy_exchange, 0.001)
    sell_fee_pct = fee_tiers.get(sell_exchange, 0.001)
    
    # Kosten & Erlöse
    cost_buy = volume * buy_price
    revenue_sell = volume * sell_price
    
    # Gebühren in USDT
    fee_buy = cost_buy * buy_fee_pct
    fee_sell = revenue_sell * sell_fee_pct
    fee_total = fee_buy + fee_sell
    
    # Brutto Gewinn (vor Gebühren)
    gross_profit = revenue_sell - cost_buy
    
    # Netto Gewinn (nach Gebühren)
    net_profit = gross_profit - fee_total
    
    # Spread in Prozent (vom Buy-Preis)
    spread_pct = ((sell_price - buy_price) / buy_price) * 100
    
    # Gebühren als % des Brutto-Gewinns
    fee_ratio = (fee_total / gross_profit * 100) if gross_profit > 0 else 0
    
    # Empfohlener Threshold: Netto Profit + Buffer
    min_profit_usdt = 0.01  # Minimaler Gewinn
    recommended_threshold = ((fee_total + min_profit_usdt) / cost_buy) * 100
    
    return {
        'direction': f'{buy_exchange}->{sell_exchange}',
        'buy_exchange': buy_exchange,
        'sell_exchange': sell_exchange,
        'buy_price': buy_price,
        'sell_price': sell_price,
        'volume': volume,
        'cost_buy': cost_buy,
        'revenue_sell': revenue_sell,
        'gross_profit': gross_profit,
        'fee_buy': fee_buy,
        'fee_sell': fee_sell,
        'fee_total': fee_total,
        'net_profit': net_profit,
        'spread_pct': spread_pct,
        'fee_ratio_pct': fee_ratio,
        'recommended_threshold_pct': recommended_threshold,
        'is_profitable': net_profit > min_profit_usdt,
        'min_profit_usdt': min_profit_usdt
    }


def check_tradeViability(buy_exchange: str, sell_exchange: str, buy_price: float, 
                         sell_price: float, volume: float, current_threshold: float = 0.5) -> dict:
    """
    Prüft ob ein Trade ausgeführt werden sollte.
    
    Entscheidungslogik:
    1. Spread NACH Gebühren berechnen
    2. Wenn Spread <= 0 → NICHT handeln (Verlust!)
    3. Wenn Spread > 0 ABER < current_threshold → Threshold anpassen vorschlagen
    4. Wenn Spread > threshold → HANDELN
    """
    result = calculate_real_spread(buy_exchange, sell_exchange, buy_price, sell_price, volume)
    
    spread_after_fees = result['net_profit']
    current_threshold_usdt = volume * buy_price * (current_threshold / 100)
    
    # Entscheidung
    if spread_after_fees <= 0:
        decision = '❌ NICHT HANDELN'
        reason = f'Verlust! Netto: ${spread_after_fees:.4f}'
        recommendation = f'Threshold muss auf ≥{result["recommended_threshold_pct"]:.2f}% erhöht werden'
    elif spread_after_fees < current_threshold_usdt:
        decision = '⚠️ MARGE ZU NIEDRIG'
        reason = f'Netto: ${spread_after_fees:.4f} < Threshold: ${current_threshold_usdt:.4f}'
        recommendation = f'Threshold auf ≥{result["recommended_threshold_pct"]:.2f}% erhöhen'
    else:
        decision = '✅ HANDELN'
        reason = f'Netto Profit: ${spread_after_fees:.4f}'
        recommendation = f'Threshold {current_threshold}% ist OK'
    
    result['decision'] = decision
    result['reason'] = reason
    result['recommendation'] = recommendation
    result['current_threshold_usdt'] = current_threshold_usdt
    
    return result


def get_effective_spread(mexc_bid: float, mexc_ask: float, kucoin_bid: float, kucoin_ask: float) -> dict:
    """
    Berechnet die effektiven Spreads für beide Arbitrage-Richtungen.
    
    MEXC Bid/Ask = aktuelle Buy/Sell Preise auf MEXC
    KuCoin Bid/Ask = aktuelle Buy/Sell Preise auf KuCoin
    """
    # Direction 1: MEXC Buy -> KuCoin Sell
    # Buy auf MEXC (Ask), Sell auf KuCoin (Bid)
    result_m_to_k = calculate_real_spread(
        'MEXC', 'KuCoin',
        mexc_ask, kucoin_bid,
        volume=100  # Annahme 100 MPC
    )
    
    # Direction 2: KuCoin Buy -> MEXC Sell
    # Buy auf KuCoin (Ask), Sell auf MEXC (Bid)  
    result_k_to_m = calculate_real_spread(
        'KuCoin', 'MEXC',
        kucoin_ask, mexc_bid,
        volume=100
    )
    
    return {
        'M->K': result_m_to_k,
        'K->M': result_k_to_m
    }


if __name__ == '__main__':
    # Test mit deinem Original Trade
    print("=== TRADE ANALYSE (Original Trade) ===")
    result = check_tradeViability(
        buy_exchange='MEXC',
        sell_exchange='KuCoin', 
        buy_price=0.01584,
        sell_price=0.016057,
        volume=79.81,
        current_threshold=0.5
    )
    
    print(f"\n{result['decision']}")
    print(f"Grund: {result['reason']}")
    print(f"\n=== DETAILS ===")
    print(f"Buy:  {result['buy_exchange']} @ ${result['buy_price']}")
    print(f"Sell: {result['sell_exchange']} @ ${result['sell_price']}")
    print(f"Volume: {result['volume']} MPC")
    print(f"Kosten: ${result['cost_buy']:.4f}")
    print(f"Erlös: ${result['revenue_sell']:.4f}")
    print(f"Brutto: ${result['gross_profit']:.4f}")
    print(f"Fees: ${result['fee_total']:.4f} ({result['fee_ratio_pct']:.1f}% des Gewinns)")
    print(f"Netto: ${result['net_profit']:.4f}")
    print(f"Spread: {result['spread_pct']:.3f}%")
    print(f"\n→ {result['recommendation']}")
