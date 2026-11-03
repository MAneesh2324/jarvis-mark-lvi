"""ECB daily reference data and explicit arithmetic scenarios. No order execution."""
from datetime import date
import math,re,statistics,xml.etree.ElementTree as ET
from core import intelligence_cache as cache
ECB='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml'
def number(value,label):
    try:value=float(value)
    except (ValueError,TypeError):raise ValueError(label+' must be a finite number.')
    if not math.isfinite(value):raise ValueError(label+' must be finite.')
    return value
def parse_pair(pair):
    value=re.sub(r'[/\s-]','',str(pair)).upper()
    if not re.fullmatch('[A-Z]{6}',value) or value[:3]==value[3:]:raise ValueError('Use two different ISO currency codes, such as EUR/USD.')
    return value[:3],value[3:]
def parse_rates(text,base,quote):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('Unexpected XML declarations in the rate feed.')
    root=ET.fromstring(text);rows=[]
    for cube in root.iter():
        day=cube.attrib.get('time')
        if not day:continue
        date.fromisoformat(day);rates={'EUR':1.0}
        for item in cube:
            currency=item.attrib.get('currency');value=item.attrib.get('rate')
            if currency and value:
                rate=number(value,'Reference rate')
                if rate<=0:raise ValueError('Reference rates must be positive.')
                rates[currency]=rate
        if base in rates and quote in rates:rows.append({'date':day,'rate':rates[quote]/rates[base]})
    rows=sorted({r['date']:r for r in rows}.values(),key=lambda r:r['date'])
    if not rows:raise ValueError('No data for that pair in the ECB 90-day reference feed.')
    return rows

def indicators(rows):
    values=[r['rate'] for r in rows];last=values[-1]
    returns=[math.log(b/a) for a,b in zip(values,values[1:])]
    changes=[b-a for a,b in zip(values[-15:],values[-14:])] if len(values)>=15 else []
    rsi=None
    if len(changes)==14:
        gain=sum(max(0,v) for v in changes)/14;loss=sum(max(0,-v) for v in changes)/14
        rsi=(100 if gain else 50) if loss==0 else 100-100/(1+gain/loss)
    return {'latest':last,'previous_observation_change_percent':100*(last/values[-2]-1) if len(values)>1 else None,'period_change_percent':100*(last/values[0]-1),'sma20':statistics.mean(values[-20:]) if len(values)>=20 else None,'sma50':statistics.mean(values[-50:]) if len(values)>=50 else None,'rsi14_simple':rsi,'annualized_log_return_volatility_percent':statistics.stdev(returns)*math.sqrt(252)*100 if len(returns)>=2 else None,'observations':len(values),'indicator_note':'Computed from daily reference observations. RSI uses simple 14-observation means, not Wilder smoothing. No intraday candles, bid/ask spread, volume or trade signal.'}
def snapshot(pair='EUR/USD',refresh=False):
    base,quote=parse_pair(pair);data=cache.fetch(ECB,ttl=3600,force=refresh);rows=parse_rates(data['text'],base,quote)
    return {'pair':base+'/'+quote,'source':'European Central Bank daily reference feed','source_url':ECB,**cache.metadata(data),'as_of':rows[-1]['date'],'calendar_days_since_observation':(date.today()-date.fromisoformat(rows[-1]['date'])).days,'data_type':'Daily reference rates; not live or executable broker quotes','analysis':indicators(rows),'history':rows,'note':'Reference rates are for information. Market prices, spreads, commissions, financing and execution can differ. No investment recommendation or order execution.'}
def position_size(pair,equity,risk_percent,stop_pips,account_currency,quote_to_account=None):
    base,quote=parse_pair(pair);equity=number(equity,'Account equity');risk=number(risk_percent,'Risk percent');stop=number(stop_pips,'Stop distance')
    if equity<=0 or not 0<risk<=100 or stop<=0:raise ValueError('Equity/stop must be positive and risk must be greater than 0 and at most 100 percent.')
    account=str(account_currency).strip().upper()
    if not re.fullmatch('[A-Z]{3}',account):raise ValueError('Enter a three-letter account currency.')
    if quote==account:conversion=1.0
    else:
        if quote_to_account is None:raise ValueError('Provide an explicit quote-to-account conversion rate for this scenario.')
        conversion=number(quote_to_account,'Quote-to-account conversion')
        if conversion<=0:raise ValueError('Conversion rate must be positive.')
    pip=.01 if quote=='JPY' else .0001;budget=equity*risk/100;units=budget/(stop*pip*conversion)
    return {'pair':base+'/'+quote,'account_currency':account,'risk_amount':budget,'stop_pips':stop,'pip_size':pip,'quote_to_account':conversion,'base_currency_units':math.floor(units),'standard_lots_100000_units':math.floor(units)/100000,'note':'Arithmetic scenario using your inputs, before fees, spread, slippage, swaps or gaps. Not a broker-approved size, guaranteed maximum loss or trade recommendation.'}
