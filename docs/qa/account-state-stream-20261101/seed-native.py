from pathlib import Path
from app.readonly_accounts.repository import AccountRepository
root=Path(__file__).resolve().parents[3]/'output/account-state-stream-native-20261101/profile/data/readonly-accounts'
r=AccountRepository(root)
r.bind('NATIVE-SYNTHETIC-FIXTURE','',1704067200000)
r.status('error',error='ACCOUNT_NETWORK_UNAVAILABLE',enabled=False)
r.start_scan('fills',1704067200000,1704067260000)
value={'fillId':'native-fixture-fill','eventTimeMs':1704067200000,'contracts':'0.1234567890123456789','instrument':'BTC-USDT-SWAP','positionSide':'long','effect':'open','price':'30000.123456789','feeCashChange':'-0.000001','feeCurrency':'USDT'}
r.page('fills',None,[('native-fixture-fill',{'fixture':True,'billId':'native-fixture-fill'},value)],next_cursor=None,complete=True)
r.save_snapshot('balances',[{'details':[{'ccy':'USDT','eq':'1234.567890123456789','cashBal':'1000.000000000000001'}]}],1704067200000)
r.mark_gap('bills',1704067200000,1704067260000)
print('Synthetic disabled account fixture saved; no credentials, private session or real account data.')
