"""
中文用途：创建一期最小闭环测试批次。

用法：
bench --site development.localhost execute overseas_costing.scripts.seed_test_batch.seed_hpcu5155607
"""

from __future__ import annotations

import json

from overseas_costing.services.import_service import import_main_excel


def build_hpcu5155607_block() -> dict:
    return {
        "id": "HPCU5155607",
        "sourceSheet": "2026年YUEWEI",
        "sourceRange": "2026年YUEWEI!79:100",
        "remark": "第一票海运测试批次",
        "projectCollection": "原料采购",
        "transportMode": "海运",
        "customsNo": "26 16 1681 6000151",
        "waybillNo": "HPCU5155607",
        "chinaMiscRmb": 10157,
        "chinaMiscMxn": 26408.2,
        "oceanUsd": 900,
        "chinaToMexicoFreightRmb": 13976.3,
        "mexicoInlandMiscRmb": 1800,
        "items": [
            [
                "YL000098",
                "TPU-HF-8695AU",
                14.3575,
                5000,
                71787.5,
                "PLASTICO TPU EN FORMAS PRIMARIAS",
                "39079101",
                "00",
                None,
                None,
                None,
                {
                    "sourceSheet": "2026年YUEWEI",
                    "sourceRow": 79,
                    "igiRate": 0.07,
                    "igiAmount": 5025.13,
                    "ivaRate": 0.16,
                    "ivaAmount": 12202.0,
                    "mexicoCustomsRmb": 6850.0,
                    "grossWeightKg": 1200,
                    "chinaToMexicoFreightRmb": 13976.3,
                },
            ],
            [
                "YL000098",
                "TPU-HF-1190A-1",
                13.4961,
                8000,
                107968.8,
                "PLASTICO TPU EN FORMAS PRIMARIAS",
                "39079101",
                "00",
                None,
                None,
                None,
                {
                    "sourceSheet": "2026年YUEWEI",
                    "sourceRow": 80,
                    "igiRate": 0.07,
                    "igiAmount": 7557.82,
                    "ivaRate": 0.16,
                    "ivaAmount": 18355.0,
                    "mexicoCustomsRmb": 9900.0,
                    "grossWeightKg": 1800,
                },
            ],
            [
                "YL000058",
                "PC-LXTY1609T-11",
                11.9167,
                7000,
                83416.9,
                "POLICARBONATO EN FORMAS PRIMARIAS",
                "39074004",
                "99",
                None,
                None,
                None,
                {
                    "sourceSheet": "2026年YUEWEI",
                    "sourceRow": 81,
                    "igiRate": 0.05,
                    "igiAmount": 4170.85,
                    "ivaRate": 0.16,
                    "ivaAmount": 14000.0,
                    "mexicoCustomsRmb": 8100.0,
                    "grossWeightKg": 1500,
                },
            ],
            [
                "FL003987",
                "TPU抽粒料（粉色2043C）",
                42,
                1000,
                42000,
                "PLASTICO TPU EN FORMAS PRIMARIAS",
                "39079101",
                "00",
                None,
                None,
                None,
                {
                    "sourceSheet": "2026年YUEWEI",
                    "sourceRow": 82,
                    "igiRate": 0.07,
                    "igiAmount": 2940,
                    "ivaRate": 0.16,
                    "ivaAmount": 7200.0,
                    "mexicoCustomsRmb": 4200.0,
                    "grossWeightKg": 500,
                },
            ],
        ],
    }


def seed_hpcu5155607() -> dict:
    block = build_hpcu5155607_block()
    return import_main_excel(
        source_name="墨西哥进口物料综合成本核算.xlsx",
        source_type="excel",
        transport_mode="SEA",
        source_sheet="2026年YUEWEI",
        project_collection="原料采购",
        version_type="Estimated",
        blocks_json=json.dumps([block], ensure_ascii=False),
        fx_rmb_to_mxn=2.6,
    )
