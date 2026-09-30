"""Versioned course knowledge shared by trading chat and Manager delegation.

This is retrieval of an authored course, not model retraining or market evidence.
"""
import json
import math
import re
from functools import lru_cache
from pathlib import Path

CORE = '''ADRIAN day-trading course knowledge, September 2026 edition.
Teach one step at a time, with a worked example when useful. Educational questions
may be answered without live market data; actual trade decisions require fresh evidence.
Course scope: liquid US stocks/unlevered ETFs, long-only whole shares, regular hours.
Course paper-practice defaults: 0.25% equity risk per attempt, 1% daily loss limit,
at most three attempts, one position, no averaging down, flat before the session ends.
These are teaching limits, NOT changes to the saved broker settings or approval rules.
Risk = entry minus structural stop. Shares = floor((equity*risk_fraction-cost_reserve)/risk),
capped by available cash and remaining daily loss budget. Nonpositive budgets mean skip.
Allow for spread, slippage, fees and currency costs; stops can fill worse than planned.
Course ORB hypothesis: first 15-minute regular-session range, completed five-minute
close above its high AND session VWAP, volume above the mean of the previous three
completed five-minute bars, permitted 09:45-11:00 Toronto window; verify quote, spread,
liquidity, calendar and news. Structural stop and target must fit risk/reward and cash.
This is an unvalidated educational hypothesis, distinct from ADRIAN's existing
15-minute ATR research/execution screen. Never label one strategy as the other.
Synthetic chart prices and examples in this course are NOT quotes or trade proposals.
TradingView Paper and Alpaca Paper are separate simulators; IEX is partial-market data.
Replay is historical; ordinary order panels/alerts can remain real-time during replay.
No income guarantee, no claimed edge from an AI confidence score. Journal all attempts,
include costs and losses; test consistent rules over 30-50 forward-paper trades before
reviewing readiness. Past performance or a small sample does not establish profitability.
Paper broker execution retains authenticated email approval and existing hard guards.
Bracket stops/targets do not guarantee flat by close. Do not claim an automatic time exit
unless actual capabilities confirm it; verify open positions and orders with the broker.
Course sources were checked September 29, 2026; verify changing rules/eligibility now.
Use supplied current account settings and evidence over historical course assumptions.
'''

def tokens(text):
    return set(re.findall(r'[a-z0-9]+', text.lower())) - set(
        'a an and are as at be by for from how i in is it me my of on or that the this to what with you'.split())

@lru_cache(maxsize=1)
def library():
    data = json.loads(Path(__file__).with_name('trading_course_knowledge.json').read_text(encoding='utf-8'))
    if data.get('version') != 1 or len(data.get('pages', [])) != 37:
        raise ValueError('Invalid trading course knowledge library')
    return data

def context(question, max_pages=6):
    data = library()
    query = tokens(question)
    docs = [(page, tokens(page['text'])) for page in data['pages']]
    def score(item):
        page, terms = item
        return sum(math.log(1 + len(docs)/(1 + sum(word in t for _, t in docs)))
                   for word in query & terms) + 2 * len(query & tokens(page['title']))
    selected = sorted(docs, key=score, reverse=True)
    selected = [page for page, terms in selected if score((page, terms)) > 0][:max_pages]
    excerpts = '\n\n'.join('COURSE PAGE '+str(p['number'])+' / '+p['title']+'\n'+p['text'] for p in selected)
    sources = '\n'.join(s['url'] for s in data['sources'])
    return CORE + '\nRETRIEVED COURSE LESSONS (educational reference):\n' + excerpts + '\nOFFICIAL COURSE SOURCE LINKS:\n' + sources

def educational_question(message):
    return bool(re.search(r'(?i)\b(course|lesson|teach|explain|learn|learning|practice|practise|quiz|worksheet|replay|calculate|calculation|position siz|risk math|what is|what does|how does)\b', message))
