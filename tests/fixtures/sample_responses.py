"""Sample API responses based on the v1.23 spec examples."""

from __future__ import annotations

GET_CHARGER_INFO_OK: dict = {
    "response": {
        "header": {
            "resultCode": "00",
            "resultMsg": "NORMAL SERVICE.",
            "totalCount": 2,
            "pageNo": 1,
            "numOfRows": 10,
        },
        "body": {
            "items": {
                "item": [
                    {
                        "statNm": "기후대기관",
                        "statId": "28260005",
                        "chgerId": "02",
                        "chgerType": "03",
                        "addr": "인천광역시 서구 환경로 42",
                        "addrDetail": "지상주차장",
                        "lat": "37.569620",
                        "lng": "126.641973",
                        "useTime": "24시간 이용가능",
                        "busiId": "ME",
                        "bnm": "환경부",
                        "busiNm": "한국자동차환경협회",
                        "busiCall": "1661-9408",
                        "stat": "2",
                        "statUpdDt": "20190829121020",
                        "lastTsdt": "20210801121020",
                        "lastTedt": "20210801123020",
                        "nowTsdt": "20210802131020",
                        "powerType": "급속(100kW동시)",
                        "output": "50",
                        "method": "단독",
                        "zcode": "28",
                        "zscode": "28260",
                        "kind": "F0",
                        "kindDetail": "F002",
                        "parkingFree": "Y",
                        "note": "공사로 인해 이용 불가",
                        "limitYn": "N",
                        "limitDetail": "",
                        "delYn": "N",
                        "delDetail": "",
                        "trafficYn": "N",
                        "year": "2025",
                        "floorNum": "1",
                        "floorType": "F",
                    },
                    {
                        # minimal row missing optional fields, exercising fallback paths
                        "statNm": "강남센터",
                        "statId": "11680001",
                        "chgerId": "01",
                        "chgerType": "04",
                        "addr": "서울특별시 강남구 테헤란로 123",
                        "addrDetail": "",
                        "lat": "37.500000",
                        "lng": "127.030000",
                        "useTime": "24시간 이용가능",
                        "busiId": "EV",
                        "bnm": "민간",
                        "busiNm": "에버온",
                        "busiCall": "",
                        "stat": "3",
                        "statUpdDt": "20260430090000",
                        "lastTsdt": "",
                        "lastTedt": "",
                        "nowTsdt": "20260430090000",
                        "output": "",
                        "method": "",
                        "zcode": "11",
                        "zscode": "11680",
                        "kind": "",
                        "kindDetail": "",
                        "parkingFree": "",
                        "note": "",
                        "limitYn": "N",
                        "limitDetail": "",
                        "delYn": "N",
                        "delDetail": "",
                        "trafficYn": "Y",
                        "year": "2024",
                        "floorNum": "",
                        "floorType": "",
                    },
                ]
            }
        },
    }
}


GET_CHARGER_STATUS_OK: dict = {
    "response": {
        "header": {
            "resultCode": "00",
            "resultMsg": "NORMAL SERVICE.",
            "totalCount": 1,
            "pageNo": 1,
            "numOfRows": 10,
        },
        "body": {
            "items": {
                "item": [
                    {
                        "busiId": "ME",
                        "statId": "28260005",
                        "chgerId": "02",
                        "stat": "2",
                        "statUpdDt": "20190829121020",
                        "lastTsdt": "20210801121020",
                        "lastTedt": "20210801123020",
                        "nowTsdt": "20210802131020",
                    }
                ]
            }
        },
    }
}


GET_CHARGER_INFO_ERROR: dict = {
    "response": {
        "header": {
            "resultCode": "30",
            "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR.",
        },
        "body": {"items": ""},
    }
}


GET_CHARGER_STATUS_SINGLE_ITEM_DICT: dict = {
    # Some endpoints collapse a single-item list into a dict — confirm we still parse it.
    "response": {
        "header": {
            "resultCode": "00",
            "resultMsg": "NORMAL SERVICE.",
            "totalCount": 1,
            "pageNo": 1,
            "numOfRows": 10,
        },
        "body": {
            "items": {
                "item": {
                    "busiId": "ME",
                    "statId": "28260005",
                    "chgerId": "02",
                    "stat": "3",
                    "statUpdDt": "20260430120000",
                    "lastTsdt": "",
                    "lastTedt": "",
                    "nowTsdt": "20260430120000",
                }
            }
        },
    }
}


def make_info_page(total_count: int, page_no: int, num_of_rows: int) -> dict:
    """Build a synthetic page sized to test the iterator pagination logic."""
    rows = []
    start = (page_no - 1) * num_of_rows + 1
    end = min(start + num_of_rows - 1, total_count)
    for idx in range(start, end + 1):
        rows.append(
            {
                "statNm": f"station-{idx}",
                "statId": f"{idx:08d}",
                "chgerId": "01",
                "chgerType": "04",
                "addr": "테스트 주소",
                "addrDetail": "",
                "lat": "37.500000",
                "lng": "127.000000",
                "useTime": "24시간 이용가능",
                "busiId": "EV",
                "bnm": "민간",
                "busiNm": "에버온",
                "busiCall": "",
                "stat": "2",
                "statUpdDt": "20260430000000",
                "lastTsdt": "",
                "lastTedt": "",
                "nowTsdt": "",
                "output": "50",
                "method": "단독",
                "zcode": "11",
                "zscode": "11680",
                "kind": "",
                "kindDetail": "",
                "parkingFree": "",
                "note": "",
                "limitYn": "N",
                "limitDetail": "",
                "delYn": "N",
                "delDetail": "",
                "trafficYn": "N",
                "year": "2024",
                "floorNum": "",
                "floorType": "",
            }
        )
    return {
        "response": {
            "header": {
                "resultCode": "00",
                "resultMsg": "NORMAL SERVICE.",
                "totalCount": total_count,
                "pageNo": page_no,
                "numOfRows": num_of_rows,
            },
            "body": {"items": {"item": rows}},
        }
    }
