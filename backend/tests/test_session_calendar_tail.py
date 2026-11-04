"""Calendar boundary oracle and a structural bound independent of runner speed."""
from datetime import datetime

import pytest

from app.data_engine.history.calendar import SessionCalendar


def ms(value):return int(datetime.fromisoformat(value).timestamp()*1000)


@pytest.mark.parametrize("zone,start,end",[
    ("UTC","2024-03-04T00:00:00+00:00","2024-03-15T20:00:00+00:00"),
    ("America/New_York","2024-03-07T00:00:00+00:00","2024-03-12T23:59:59+00:00"),
    ("America/New_York","2024-10-31T00:00:00+00:00","2024-11-05T23:59:59+00:00"),
])
@pytest.mark.parametrize("interval",["1m","30m","1h","4h","1d","1w","1M"])
@pytest.mark.parametrize("offset",[0,1,59_999])
def test_last_open_matches_enumerated_contract_across_breaks_overrides_and_dst(zone,start,end,interval,offset):
    calendar=SessionCalendar(calendar_id="qa.tail",timezone_name=zone,
        weekly_sessions={day:(("00:00","04:00"),("09:30","11:00"),("10:00","12:00"),("13:00","16:00"),("22:00","02:00")) for day in range(7)},
        holidays=["2024-03-08","2024-11-01"],overrides={"2024-03-11":(("12:45","15:00"),)})
    start_ms,end_ms=ms(start)+offset,ms(end)-offset
    expected=list(calendar.expected_opens(start_ms,end_ms,interval))
    assert calendar.last_expected_open(start_ms,end_ms,interval)==(expected[-1] if expected else None)
    if expected:
        for edge in (expected[-1]-1,expected[-1],expected[-1]+1):
            prefix=[stamp for stamp in expected if stamp<=edge]
            assert calendar.last_expected_open(start_ms,edge,interval)==(prefix[-1] if prefix else None)


def test_builtin_last_does_not_enumerate_ten_years_of_minute_buckets(monkeypatch):
    calendar=SessionCalendar(calendar_id="qa.work",timezone_name="UTC",
        weekly_sessions={day:(("09:30","16:00"),) for day in range(5)})
    original=SessionCalendar.expected_opens;emitted=[0]
    def observed(self,*args,**kwargs):
        for stamp in original(self,*args,**kwargs):
            emitted[0]+=1
            yield stamp
    monkeypatch.setattr(SessionCalendar,"expected_opens",observed)
    assert calendar.last_expected_open(ms("2014-11-04T00:00:00+00:00"),ms("2024-11-04T23:00:00+00:00"),"1m")==ms("2024-11-04T15:59:00+00:00")
    assert emitted[0]==0


def test_custom_expected_open_override_retains_its_calendar_contract():
    class AlternateMinutes(SessionCalendar):
        def expected_opens(self,start_ms,end_ms,interval):
            return (stamp for stamp in super().expected_opens(start_ms,end_ms,interval) if (stamp//60_000)%2==0)
    calendar=AlternateMinutes(calendar_id="custom",timezone_name="UTC",weekly_sessions={day:(("09:30","16:00"),) for day in range(5)})
    assert calendar.last_expected_open(ms("2024-11-04T09:30:00+00:00"),ms("2024-11-04T15:59:59+00:00"),"1m")==ms("2024-11-04T15:58:00+00:00")


def test_last_open_handles_empty_and_reversed_ranges():
    calendar=SessionCalendar(calendar_id="empty",timezone_name="UTC",weekly_sessions={})
    assert calendar.last_expected_open(0,10_000,"1m") is None
    assert calendar.last_expected_open(10_000,0,"1m") is None
