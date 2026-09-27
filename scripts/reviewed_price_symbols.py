"""Reviewed Yahoo Finance symbols keyed by security identifier.

Mappings were checked against the security's ISIN/CUSIP search result and
Yahoo chart instrument metadata on 2026-09-27. Symbols intentionally omit
instruments for which an active, matching listing could not be confirmed.
NewAge Inc. (US6501941032) remains unmapped: no matching active Yahoo
instrument was found during review.
"""

REVIEWED_YAHOO_SYMBOLS: dict[str, str] = {
    "US7223041028": "9PDA.F",  # PDD Holdings, Frankfurt, EUR
    "DE0005313704": "AFX.DE",  # Carl Zeiss Meditec, Xetra, EUR
    "IE00BK5BCD43": "AIAI.SW",  # L&G Artificial Intelligence ETF, CHF
    "CA0084741085": "AEM",  # Agnico Eagle Mines, NYSE, USD
    "CA11777Q2099": "BTG",  # B2Gold, NYSE, USD
    "CA32076V1031": "AG",  # First Majestic Silver, NYSE, USD
    "CA3759161035": "GIL",  # Gildan Activewear, NYSE, USD
    "CA38141A6025": "GORO.V",  # Goldgroup Mining, TSX Venture, CAD
    "CA6979001089": "PAAS",  # Pan American Silver, NYSE, USD
    "CA96810C2004": "WILD.TO",  # WildBrain, Toronto, CAD
    "DE000FTG1111": "FTK.DE",  # flatexDEGIRO, Xetra, EUR
    "ES0177542018": "IAG.L",  # International Consolidated Airlines, London
    "GB00B63H8491": "RR.L",  # Rolls-Royce, London
    "GB00B7KR2P84": "EZJ.L",  # easyJet, London
    "GI000A0F6407": "EVOK.L",  # Evoke, London
    "LU1861132840": "GOAI.PA",  # Amundi Robotics & AI ETF, Paris, EUR
    "IE00B1XNHC34": "INRG.L",  # iShares Global Clean Energy ETF, London
    "IE00B3XXRP09": "VUSD.L",  # Vanguard S&P 500 UCITS ETF, London
    "IE00B3YCGJ38": "SPXS.L",  # Invesco S&P 500 UCITS ETF, London
    "IE00B43HR379": "IUHC.L",  # iShares S&P 500 Health Care ETF, London
    "IE00B5KQNG97": "HSPD.L",  # HSBC S&P 500 UCITS ETF, London
    "IE00B60SX287": "MXJP.L",  # Invesco MSCI Japan UCITS ETF, London
    "IE00BDZVHG35": "BTEE.L",  # iShares Nasdaq Biotechnology ETF, London
    "IE00BLNMYC90": "XDEW.L",  # Xtrackers S&P 500 Equal Weight ETF, London
    "IE00BNG8L278": "V3AA.L",  # Vanguard ESG Global All Cap ETF, London
    "IE00BYMS5W68": "FTEK.L",  # Invesco Nasdaq Fintech ETF, London
    "IE00BYPLS672": "USPY.L",  # L&G Cyber Security ETF, London
    "IE00BYVQ9F29": "NQSE.DE",  # iShares Nasdaq-100 EUR Hedged ETF, Xetra
    "IE00BYXG2H39": "BTEC.L",  # iShares Nasdaq Biotechnology ETF, London
    "IE00BZ163M45": "VDTY.L",  # Vanguard USD Treasury Bond ETF, London
    "IL0011284465": "PLUS.L",  # Plus500, London
    "KYG1144A1058": "BTBT",  # Bit Digital, Nasdaq, USD
    "LU0514695690": "LU0514695690-USD.LU",  # Xtrackers MSCI China ETF, Luxembourg
    "LU0839027447": "XDJP.DE",  # Xtrackers Nikkei 225 ETF, Xetra
    "LU1681045453": "AUEM.L",  # Amundi Emerging Markets ETF, London
    "PTSON0AM0001": "SON.LS",  # Sonae, Lisbon
    "SGXZ53262598": "DGNX",  # Diginex, Nasdaq, USD
    "US00123Q1040": "AGNC",  # AGNC Investment, Nasdaq, USD
    "US00206R1023": "T",  # AT&T, NYSE, USD
    "US0092791005": "EADSY",  # Airbus ADR, OTC Markets, USD
    "US0303711081": "AVD",  # American Vanguard, NYSE, USD
    "US0556221044": "BP",  # BP ADR, NYSE, USD
    "US05605H1005": "BWXT",  # BWX Technologies, NYSE, USD
    "US12769G1004": "CZR",  # Caesars Entertainment, Nasdaq, USD
    "US1858991011": "CLF",  # Cleveland-Cliffs, NYSE, USD
    "US1924461023": "CTSH",  # Cognizant, Nasdaq, USD
    "US3453708600": "F",  # Ford Motor, NYSE, USD
    "US3596781092": "FLL",  # Full House Resorts, Nasdaq, USD
    "US37045V1008": "GM",  # General Motors, NYSE, USD
    "US37247D1063": "GNW",  # Genworth Financial, NYSE, USD
    "US45170X2053": "INVE",  # Identiv, Nasdaq, USD
    "US45408X3089": "IGC",  # IGC Pharma, NYSE American, USD
    "US49446R1095": "KIM",  # Kimco Realty, NYSE, USD
    "US6904691010": "OVID",  # Ovid Therapeutics, Nasdaq, USD
    "US7170811035": "PFE",  # Pfizer, NYSE, USD
    "US7244791007": "PBI",  # Pitney Bowes, NYSE, USD
    "US72919P2020": "PLUG",  # Plug Power, Nasdaq, USD
    "US75508B1044": "RYAM",  # Rayonier Advanced Materials, NYSE, USD
    "US80004C2008": "SNDK",  # Sandisk, Nasdaq, USD
    "US8342EP1070": "XPL",  # Solitario Resources, NYSE American, USD
    "US86272A3059": "SSKN",  # Strata Skin Sciences, OTC Markets, USD
    "US9581021055": "WDC",  # Western Digital, Nasdaq, USD
    "IE00BDVPNG13": "WTAI.L",  # WisdomTree Artificial Intelligence ETF, London
    "IE00BGV5VN51": "XAID.L",  # Xtrackers Artificial Intelligence ETF, London
}
