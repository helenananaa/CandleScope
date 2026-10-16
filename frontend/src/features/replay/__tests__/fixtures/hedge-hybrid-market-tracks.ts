// Captured isolated QA wire response, retained for contract regression.
export const hedgeHybridMarketTracksFixture = {
  "protocol": "replay.v3",
  "run_id": "a7398609bcea412abab595d2613c167e",
  "ordering_version": "replay.global-order.v1",
  "launch_context": {
    "schema_version": "replay.launch-context.v1",
    "source": "DIRECT_HUB",
    "exchange": "binance",
    "market_type": "futures",
    "symbol": "LTCUSDT",
    "display_interval": "1m",
    "watchlist_snapshot": {
      "schema_version": "replay.watchlist-snapshot.v1",
      "groups": []
    }
  },
  "viewer_state": {
    "run_id": "a7398609bcea412abab595d2613c167e",
    "selected_track_id": "track-1",
    "display_interval": "1m",
    "chart_type": "candles",
    "visible_range": null,
    "pane_layout": {},
    "rail_layout": {},
    "semantic_view_revision": 1
  },
  "tracks": [
    {
      "run_id": "a7398609bcea412abab595d2613c167e",
      "track_id": "track-1",
      "stable_ordinal": 1,
      "adapter_session_id": "784744393add4588a0a43a16538858bf",
      "exchange": "binance",
      "market_type": "futures",
      "symbol": "LTCUSDT",
      "settlement_asset": "USDT",
      "state": "READY",
      "source_kind": "AGG_TRADE",
      "subscription_tier": "FULL",
      "cursor": {
        "virtual_time_ms": 1791590460773,
        "source_sequence": 55,
        "revision": 64
      },
      "forced_full_reasons": [
        "LIQUIDATION_RISK",
        "OPEN_POSITION",
        "VIEWED"
      ],
      "capabilities": {
        "HISTORICAL_FEE_POLICY": "AVAILABLE_APPROX",
        "HISTORICAL_FUNDING": "OFF_NOT_REQUESTED",
        "HISTORICAL_INSTRUMENT_RULE": "AVAILABLE_APPROX",
        "HISTORICAL_L2": "OFF_NOT_REQUESTED",
        "HISTORICAL_MARK_INDEX": "AVAILABLE_APPROX",
        "SIMULATED_ADL_COHORT": "AVAILABLE_MATERIALIZED_ACCOUNT_WIDE",
        "SIMULATED_INSURANCE_FUND": "AVAILABLE_MATERIALIZED_ACCOUNT_WIDE"
      },
      "public_price": "63.43",
      "position": {
        "long": {
          "entry_price": "63.446344",
          "leverage": "3",
          "mark_price": "63.43",
          "notional": "63.43",
          "quantity": "1",
          "realized_pnl": "0",
          "unrealized_pnl": "-0.016344"
        },
        "position_mode": "HEDGE",
        "short": {
          "entry_price": "63.433656",
          "leverage": "3",
          "mark_price": "63.43",
          "notional": "63.43",
          "quantity": "-1",
          "realized_pnl": "0",
          "unrealized_pnl": "0.003656"
        }
      },
      "open_order_count": 0,
      "degraded_reason": null,
      "account": {
        "available_equity": "9957.63720531",
        "cash_balance": "9999.93655999",
        "equity": "9999.92387199",
        "fees_paid": "0.06344001",
        "margin_used": "42.28666668",
        "quote_asset": "USDT",
        "realized_pnl": "0",
        "reserved_margin": "0",
        "unrealized_pnl": "-0.012688"
      },
      "historical_book": {
        "mode": "OFF",
        "capability_state": "UNSUPPORTED_NO_HISTORY",
        "status": "OFF",
        "execution_fidelity": "NO_BOOK_TOUCH_OR_TAPE_APPROX",
        "queue_exact": false,
        "as_of_virtual_time_ms": null,
        "last_update_id": null,
        "bids": [],
        "asks": [],
        "book_hash": null,
        "message": "\u5386\u53f2\u76d8\u53e3\u6a21\u5f0f\u672a\u542f\u7528"
      }
    },
    {
      "run_id": "a7398609bcea412abab595d2613c167e",
      "track_id": "track-2",
      "stable_ordinal": 2,
      "adapter_session_id": "7772ae3f2c85432c9b610dd8014c71dc",
      "exchange": "binance",
      "market_type": "futures",
      "symbol": "DOGEUSDT",
      "settlement_asset": "USDT",
      "state": "READY",
      "source_kind": "AGG_TRADE",
      "subscription_tier": "FULL",
      "cursor": {
        "virtual_time_ms": 1791590460773,
        "source_sequence": 120,
        "revision": 11
      },
      "forced_full_reasons": [],
      "capabilities": {
        "HISTORICAL_FEE_POLICY": "AVAILABLE_APPROX",
        "HISTORICAL_FUNDING": "OFF_NOT_REQUESTED",
        "HISTORICAL_INSTRUMENT_RULE": "AVAILABLE_APPROX",
        "HISTORICAL_L2": "OFF_NOT_REQUESTED",
        "HISTORICAL_MARK_INDEX": "AVAILABLE_APPROX",
        "SIMULATED_ADL_COHORT": "AVAILABLE_MATERIALIZED_ACCOUNT_WIDE",
        "SIMULATED_INSURANCE_FUND": "AVAILABLE_MATERIALIZED_ACCOUNT_WIDE"
      },
      "public_price": null,
      "position": {
        "long": {
          "entry_price": null,
          "leverage": "3",
          "mark_price": "0.08532",
          "notional": "0",
          "quantity": "0",
          "realized_pnl": "0",
          "unrealized_pnl": "0"
        },
        "position_mode": "HEDGE",
        "short": {
          "entry_price": null,
          "leverage": "3",
          "mark_price": "0.08532",
          "notional": "0",
          "quantity": "0",
          "realized_pnl": "0",
          "unrealized_pnl": "0"
        }
      },
      "open_order_count": 0,
      "degraded_reason": null,
      "account": {
        "available_equity": "10000",
        "cash_balance": "10000",
        "equity": "10000",
        "fees_paid": "0",
        "margin_used": "0",
        "quote_asset": "USDT",
        "realized_pnl": "0",
        "reserved_margin": "0",
        "unrealized_pnl": "0"
      },
      "historical_book": {
        "mode": "OFF",
        "capability_state": "UNSUPPORTED_NO_HISTORY",
        "status": "OFF",
        "execution_fidelity": "NO_BOOK_TOUCH_OR_TAPE_APPROX",
        "queue_exact": false,
        "as_of_virtual_time_ms": null,
        "last_update_id": null,
        "bids": [],
        "asks": [],
        "book_hash": null,
        "message": "\u5386\u53f2\u76d8\u53e3\u6a21\u5f0f\u672a\u542f\u7528"
      }
    }
  ],
  "portfolio": {
    "schema_version": "replay.training.portfolio.v2",
    "account_model": "TOUCH_OR_TAPE_V2",
    "execution_model": "TOUCH_OR_TAPE_V2",
    "execution_fidelity": "NO_BOOK_TOUCH_OR_TAPE_APPROX",
    "settlement_account_shared": true,
    "position_mode": "HEDGE",
    "margin_mode": "CROSS",
    "funding_mode": "OFF",
    "status": "ACTIVE",
    "initial_equity": "10000",
    "cash_balance": "9999.93655999",
    "equity": "9999.92387199",
    "available_equity": "9957.64387199",
    "reserved_margin": "0",
    "margin_used": "42.28",
    "maintenance_margin": "0.6342",
    "realized_pnl": "0",
    "unrealized_pnl": "-0.012688",
    "fees_paid": "0.06344001",
    "funding_cashflow": "0",
    "liquidation_fees_paid": "0",
    "risk_ratio": "15767.77652473982970671712394",
    "positions": [
      {
        "track_id": "track-1",
        "symbol": "LTCUSDT",
        "position_side": "LONG",
        "position": {
          "quantity": "1",
          "entry_price": "63.446344",
          "mark_price": "63.42",
          "notional": "63.42",
          "realized_pnl": "0",
          "unrealized_pnl": "-0.026344",
          "leverage": "3"
        },
        "initial_margin": "21.14",
        "maintenance_margin": "0.3171",
        "liquidation_price": "0",
        "bankruptcy_price": "0",
        "accumulated_funding": "0",
        "trading_fees": "0.03172318",
        "liquidation_fees": "0",
        "protection": {
          "orders": []
        },
        "risk_tier": 1,
        "position_leg_hash": "sha256:316771b85e86e27035afcb715f15f803c7849896642610b2e05b89f70cabca55",
        "leverage": "3",
        "isolated_margin": "0",
        "isolated_allocation_key": "track-1:LONG",
        "account_notional": "63.42",
        "margin_equity": "9999.92387199",
        "risk_ratio": "31535.55304947965941343424787",
        "rule_revision": 1,
        "rule_hash": "sha256:8953755576b05bc89f9c6a1449ff09bcd1e5b7fdecef4c7ae2ad12f1f9e0339c",
        "mark_fidelity": "REVEALED_BAR_OR_TAPE_PRICE_PROXY",
        "maintenance_margin_proof": {
          "schema_version": "replay.maintenance-margin-proof.v1",
          "rule_revision": 1,
          "rule_hash": "sha256:8953755576b05bc89f9c6a1449ff09bcd1e5b7fdecef4c7ae2ad12f1f9e0339c",
          "rule_fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
          "risk_tier": 1,
          "last_tier_notional_cap": "30000",
          "position_notional": "63.42",
          "position_tier_extrapolated": false,
          "liquidation_price_notional": "0",
          "liquidation_tier_extrapolated": false,
          "fidelity": "VERSIONED_MAINTENANCE_TIER_APPLIED",
          "explanation": null,
          "proof_hash": "sha256:548b30c404a5e536ba0d0d13be62716e6fe9d344e59c3bd8665b532a7a557f73"
        }
      },
      {
        "track_id": "track-1",
        "symbol": "LTCUSDT",
        "position_side": "SHORT",
        "position": {
          "quantity": "-1",
          "entry_price": "63.433656",
          "mark_price": "63.42",
          "notional": "63.42",
          "realized_pnl": "0",
          "unrealized_pnl": "0.013656",
          "leverage": "3"
        },
        "initial_margin": "21.14",
        "maintenance_margin": "0.3171",
        "liquidation_price": "10012.96196217",
        "bankruptcy_price": "10063.34387199",
        "accumulated_funding": "0",
        "trading_fees": "0.03171683",
        "liquidation_fees": "0",
        "protection": {
          "orders": []
        },
        "risk_tier": 1,
        "position_leg_hash": "sha256:3bd0af69f6894ece5074e673a15767af0986c812cfc70ff77180ae2793299320",
        "leverage": "3",
        "isolated_margin": "0",
        "isolated_allocation_key": "track-1:SHORT",
        "account_notional": "63.42",
        "margin_equity": "9999.92387199",
        "risk_ratio": "31535.55304947965941343424787",
        "rule_revision": 1,
        "rule_hash": "sha256:8953755576b05bc89f9c6a1449ff09bcd1e5b7fdecef4c7ae2ad12f1f9e0339c",
        "mark_fidelity": "REVEALED_BAR_OR_TAPE_PRICE_PROXY",
        "maintenance_margin_proof": {
          "schema_version": "replay.maintenance-margin-proof.v1",
          "rule_revision": 1,
          "rule_hash": "sha256:8953755576b05bc89f9c6a1449ff09bcd1e5b7fdecef4c7ae2ad12f1f9e0339c",
          "rule_fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
          "risk_tier": 1,
          "last_tier_notional_cap": "30000",
          "position_notional": "63.42",
          "position_tier_extrapolated": false,
          "liquidation_price_notional": "10012.96196217",
          "liquidation_tier_extrapolated": false,
          "fidelity": "VERSIONED_MAINTENANCE_TIER_APPLIED",
          "explanation": null,
          "proof_hash": "sha256:1978b95bb6753887e5008306c9e81b57bb328bf9449cbae941a2d0b019f62076"
        }
      }
    ],
    "orders": [],
    "fills": [],
    "history": {
      "orders_total": 2,
      "active_orders": 0,
      "historical_orders": 2,
      "fills_total": 2,
      "ledger_entries_total": 145,
      "page_limit_max": 200
    },
    "active_fee_policy": {
      "revision": 1,
      "effective_virtual_time_ms": 1791590400000,
      "maker_fee_bps": "2",
      "taker_fee_bps": "5",
      "liquidation_fee_bps": "50",
      "policy_version": "RUN_CONFIGURED_FEE_V1",
      "account_tier": "RUN_CONFIGURED",
      "source_kind": "PUBLIC",
      "source_id": "hybrid-public-dd31521c580377c111c9b7ef0c6e869e",
      "source_event_sequence": 0,
      "extension_hash": "sha256:ad99c39d9342bf257f24a2b5a27a9ae9dc1854a3fbc10dd3055faeb6712a5f86",
      "policy_hash": "sha256:8b1d7b6f69cb7edd79d3e234826015538cf74bc57d7dd33f89bdf97e44364910",
      "fidelity": "CONFIGURED_RUN_FEE_POLICY"
    },
    "instrument_rules": [
      {
        "track_id": "track-1",
        "revision": 1,
        "rule_hash": "sha256:8953755576b05bc89f9c6a1449ff09bcd1e5b7fdecef4c7ae2ad12f1f9e0339c",
        "fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
        "rule": {
          "contract_size": "1",
          "effective_virtual_time_ms": 1791590400000,
          "liquidation_fee_bps": "50",
          "maintenance_tiers": [
            {
              "maintenance_deduction": "0",
              "maintenance_rate": "0.005",
              "notional_cap": "30000"
            }
          ],
          "mark_fidelity": "REVEALED_BAR_OR_TAPE_PRICE_PROXY",
          "max_leverage": "3",
          "max_notional": "30000",
          "max_quantity": "1000000000",
          "min_notional": "0.01",
          "min_quantity": "0.00000001",
          "price_tick": "0.00000001",
          "quantity_step": "0.00000001",
          "quote_step": "0.00000001",
          "rule_fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
          "rule_version": "CANDLESCOPE_LINEAR_CONTRACT_V1",
          "source_kind": "AGG_TRADE",
          "track_id": "track-1"
        }
      },
      {
        "track_id": "track-2",
        "revision": 1,
        "rule_hash": "sha256:764d75b352da67146c9ce2acd02d567d6b54c32125de127a188dbfc8236fdbb2",
        "fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
        "rule": {
          "contract_size": "1",
          "effective_virtual_time_ms": 1791590400000,
          "liquidation_fee_bps": "50",
          "maintenance_tiers": [
            {
              "maintenance_deduction": "0",
              "maintenance_rate": "0.005",
              "notional_cap": "30000"
            }
          ],
          "mark_fidelity": "REVEALED_BAR_OR_TAPE_PRICE_PROXY",
          "max_leverage": "3",
          "max_notional": "30000",
          "max_quantity": "1000000000",
          "min_notional": "0.01",
          "min_quantity": "0.00000001",
          "price_tick": "0.00000001",
          "quantity_step": "0.00000001",
          "quote_step": "0.00000001",
          "rule_fidelity": "VERSIONED_APPROXIMATE_INSTRUMENT_RULE",
          "rule_version": "CANDLESCOPE_LINEAR_CONTRACT_V1",
          "source_kind": "AGG_TRADE",
          "track_id": "track-2"
        }
      }
    ],
    "isolated_allocations": {},
    "next_funding_time_ms": null,
    "liquidations": [],
    "liquidation_recoveries": [],
    "hedge_state": {
      "schema_version": "replay.hedge-relational-state.v1",
      "position_legs": [
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "track_id": "track-1",
          "position_side": "LONG",
          "signed_quantity": "1",
          "absolute_quantity": "1",
          "entry_price": "63.446344",
          "mark_price": "63.42",
          "notional": "63.42",
          "realized_pnl": "0",
          "unrealized_pnl": "-0.026344",
          "initial_margin": "21.14",
          "maintenance_margin": "0.3171",
          "leverage": "3",
          "margin_mode": "CROSS",
          "isolated_wallet": "0",
          "liquidation_price": "0",
          "bankruptcy_price": "0",
          "accumulated_funding": "0",
          "trading_fees": "0.03172318",
          "liquidation_fees": "0",
          "risk_tier": 1,
          "rule_revision": 1,
          "protection_json": "{\"orders\":[]}",
          "component_revision": 29,
          "component_hash": "sha256:316771b85e86e27035afcb715f15f803c7849896642610b2e05b89f70cabca55",
          "created_at_ms": 1791778166406,
          "updated_at_ms": 1791781290785
        },
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "track_id": "track-1",
          "position_side": "SHORT",
          "signed_quantity": "-1",
          "absolute_quantity": "1",
          "entry_price": "63.433656",
          "mark_price": "63.42",
          "notional": "63.42",
          "realized_pnl": "0",
          "unrealized_pnl": "0.013656",
          "initial_margin": "21.14",
          "maintenance_margin": "0.3171",
          "leverage": "3",
          "margin_mode": "CROSS",
          "isolated_wallet": "0",
          "liquidation_price": "10012.96196217",
          "bankruptcy_price": "10063.34387199",
          "accumulated_funding": "0",
          "trading_fees": "0.03171683",
          "liquidation_fees": "0",
          "risk_tier": 1,
          "rule_revision": 1,
          "protection_json": "{\"orders\":[]}",
          "component_revision": 29,
          "component_hash": "sha256:3bd0af69f6894ece5074e673a15767af0986c812cfc70ff77180ae2793299320",
          "created_at_ms": 1791778166406,
          "updated_at_ms": 1791781290785
        }
      ],
      "leg_accounting": [
        {
          "schema_version": "replay.hedge-leg-accounting.v1",
          "track_id": "track-1",
          "position_side": "LONG",
          "accumulated_funding": "0",
          "trading_fees": "0.03172318",
          "liquidation_fees": "0",
          "funding_settlement_count": 0,
          "fee_entry_count": 1,
          "mutation_entry_count": 57,
          "ledger_entry_count": 58,
          "last_ledger_sequence": 142,
          "last_ledger_hash": "sha256:043e20b4c879568d37d7224af6bbfc1d6f0c1232f96f9962b21c7a84c02eb2e3",
          "position_component_hash": "sha256:316771b85e86e27035afcb715f15f803c7849896642610b2e05b89f70cabca55"
        },
        {
          "schema_version": "replay.hedge-leg-accounting.v1",
          "track_id": "track-1",
          "position_side": "SHORT",
          "accumulated_funding": "0",
          "trading_fees": "0.03171683",
          "liquidation_fees": "0",
          "funding_settlement_count": 0,
          "fee_entry_count": 1,
          "mutation_entry_count": 57,
          "ledger_entry_count": 58,
          "last_ledger_sequence": 144,
          "last_ledger_hash": "sha256:a147663e5de5da5550bafe90c5e7673a522fe8ee39880a6876adc356bb1793af",
          "position_component_hash": "sha256:3bd0af69f6894ece5074e673a15767af0986c812cfc70ff77180ae2793299320"
        }
      ],
      "margin_buckets": [
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "bucket_id": "cross:USDT",
          "bucket_kind": "CROSS",
          "track_id": null,
          "position_side": null,
          "asset": "USDT",
          "wallet_balance": "9999.93655999",
          "initial_margin": "42.28",
          "maintenance_margin": "0.6342",
          "reserved_margin": "0",
          "available_balance": "9957.64387199",
          "component_revision": 29,
          "component_hash": "sha256:4f179aea56ac040a845e2a9cc901a0f3b69bdc258cd729f7a2fffe71578ca851",
          "updated_at_ms": 1791781290785
        },
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "bucket_id": "position:track-1:LONG",
          "bucket_kind": "POSITION",
          "track_id": "track-1",
          "position_side": "LONG",
          "asset": "USDT",
          "wallet_balance": "0",
          "initial_margin": "21.14",
          "maintenance_margin": "0.3171",
          "reserved_margin": "0",
          "available_balance": "0",
          "component_revision": 28,
          "component_hash": "sha256:7f2c877c4cb044c5bb937e02a5fc7b5c7d7bab6d8a1f8276a82149444741a697",
          "updated_at_ms": 1791781290785
        },
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "bucket_id": "position:track-1:SHORT",
          "bucket_kind": "POSITION",
          "track_id": "track-1",
          "position_side": "SHORT",
          "asset": "USDT",
          "wallet_balance": "0",
          "initial_margin": "21.14",
          "maintenance_margin": "0.3171",
          "reserved_margin": "0",
          "available_balance": "0",
          "component_revision": 28,
          "component_hash": "sha256:21d182222b244f529068f45c501a86f4b60bd57f590709c873898cc2b6153b9f",
          "updated_at_ms": 1791781290785
        }
      ],
      "risk_snapshots": [],
      "liquidation_leg_price_proofs": [],
      "liquidation_book_executions": [],
      "liquidation_book_snapshots": [],
      "insurance_funds": [
        {
          "run_id": "a7398609bcea412abab595d2613c167e",
          "asset": "USDT",
          "model_version": "BINANCE_USDM_LINEAR_HEDGE_DETERMINISTIC_SIMULATION_V1",
          "opening_balance": "3000000",
          "current_balance": "3000000",
          "ledger_tail_hash": "sha256:94b3d8105756ce04578898907693700522dff0592c2e908c95385b685b4bf549",
          "revision": 0,
          "updated_at_ms": 1791778166406
        }
      ],
      "insurance_postings": [],
      "adl_snapshots": [],
      "adl_candidates": [],
      "adl_events": [],
      "adl_selections": [],
      "adl_counterparty_ledger": [],
      "liquidation_case_hashes": [],
      "state_hash": "sha256:5a86e973820d29a592a93dc27e924f6a3331a465eff832e9b7bdafd52608c993"
    },
    "hedge_inputs": {
      "schema_version": "replay.hedge-input-view.v2",
      "status": "ACTIVE",
      "degraded_reason": null,
      "input_proof_hash": "sha256:2827c604b997f43b703daedec2146118696b862b3bb10c0457df8e970c91d3d5",
      "time_domain": "ACTUAL",
      "bound_range_start_ms": 1791590400000,
      "bound_range_end_ms": 1791676800000,
      "public": {
        "archive_id": "hybrid-public-dd31521c580377c111c9b7ef0c6e869e",
        "generation": 1,
        "dataset_epoch": "sha256:f7408a2e157e711227d7b1bb4d5662a4cfa04d7e7854aa294a31bbca0a0cde76",
        "checksum_sha256": "sha256:fa50f87efde2619a3f3cc0ca10d3242066146ee6d26611802447e6e54b64e8d3",
        "event_chain_tail": "sha256:1b8270303d869374f6d5259d86c93286f31d98e2075df7e2a5755ab015e34d2e",
        "proof_hash": "sha256:1746fb77781a20246c8930539a3909c6ea6143de3b2e896258cfa9dc56772c1a",
        "health": "READY"
      },
      "simulation": {
        "manifest_id": "hybrid-simulation-dd31521c580377c111c9b7ef0c6e869e",
        "generation": 1,
        "dataset_epoch": "sha256:ad131b628afd738e5dd58d9159a38f7090a98a9e5d92ab54d5a3fff1af9afab6",
        "checksum_sha256": "sha256:65f1c4cecaed3e7b7ca656b5585d590b2a05ba6ddfd899649fe8f7de28a6149d",
        "contract_hash": "sha256:eb93972d289057909f7c8fd8ef66376876f7e0c60b2e46dbe6c5ca4c609f9c4b",
        "model_version": "BINANCE_USDM_LINEAR_HEDGE_DETERMINISTIC_SIMULATION_V1",
        "proof_hash": "sha256:baf27b4b8fe851fc24ffe91f1c6b51551d134381794962a212346506d5f5d537",
        "health": "READY"
      },
      "projections": [
        {
          "schema_version": "replay.hedge-input-public-projection.v1",
          "source_kind": "PUBLIC",
          "last_event_sequence": 5,
          "as_of_time_ms": 1791590460000,
          "time_domain": "ACTUAL",
          "state_hash": "sha256:2826d79f595d35faf2a69d37b1cfc22baabb4fa5617ee1d0095ba0e4a98333bf",
          "input_chain_hash": "sha256:4362e33bccd02961e3a343e2b6d12cc581c6c9c760c4c02eda82dc29c6d64d52",
          "source_component_hash": "sha256:3f41f00725dca1c0c1c8a08ec028ea10a4863640dce8781dbbb174f84a46aa7a"
        },
        {
          "schema_version": "replay.hedge-input-public-projection.v1",
          "source_kind": "SIMULATION",
          "last_event_sequence": 2,
          "as_of_time_ms": 1791590400000,
          "time_domain": "ACTUAL",
          "state_hash": "sha256:3d40458a88fa3fe04b77f6fc46971ae0e68bfd2610cb3c1ba8455d8ca432045c",
          "input_chain_hash": "sha256:94b3d8105756ce04578898907693700522dff0592c2e908c95385b685b4bf549",
          "source_component_hash": "sha256:76669576b75d7e9c2e4db453c57e4e3ec53e67b2929ffc13d39851115daedb4a"
        }
      ],
      "track_public": [
        {
          "track_id": "track-1",
          "archive_id": "hybrid-public-dd31521c580377c111c9b7ef0c6e869e",
          "generation": 1,
          "dataset_epoch": "sha256:f7408a2e157e711227d7b1bb4d5662a4cfa04d7e7854aa294a31bbca0a0cde76",
          "checksum_sha256": "sha256:fa50f87efde2619a3f3cc0ca10d3242066146ee6d26611802447e6e54b64e8d3",
          "event_chain_tail": "sha256:1b8270303d869374f6d5259d86c93286f31d98e2075df7e2a5755ab015e34d2e",
          "input_proof_hash": "sha256:a1b45cda6e29e51a9996eec273d2f1f444a4fab8d337730476437137db8b0520",
          "status": "ACTIVE",
          "degraded_reason": null,
          "projection": {
            "schema_version": "replay.hedge-track-public-projection.v2",
            "run_id": "a7398609bcea412abab595d2613c167e",
            "track_id": "track-1",
            "last_event_sequence": 5,
            "as_of_time_ms": 1791590460000,
            "time_domain": "ACTUAL",
            "state_hash": "sha256:2826d79f595d35faf2a69d37b1cfc22baabb4fa5617ee1d0095ba0e4a98333bf",
            "input_chain_hash": "sha256:4362e33bccd02961e3a343e2b6d12cc581c6c9c760c4c02eda82dc29c6d64d52",
            "source_component_hash": "sha256:f87ee46c5646d3234267e8a5f317d0c75959e81045cf83e72113cdcc88a2b046"
          }
        },
        {
          "track_id": "track-2",
          "archive_id": "hybrid-public-eeb7a8a3539681d6496c10582019343d",
          "generation": 1,
          "dataset_epoch": "sha256:2b166530c8dcd5e9fd4be2b4e7e540a49042873d04332a64b1157d38b55dfc59",
          "checksum_sha256": "sha256:31d44903a868c23a90066f141184c16d7261276af536809d56cea467a2364ec4",
          "event_chain_tail": "sha256:4f61ee6f16f520149f832f0b3998125a827dd8f8bfa0f7f522f893f86903b6f4",
          "input_proof_hash": "sha256:d98295880b586f8fa6e08e3fd4f990006e047ec2d3f3549b56607116cffacb04",
          "status": "ACTIVE",
          "degraded_reason": null,
          "projection": {
            "schema_version": "replay.hedge-track-public-projection.v2",
            "run_id": "a7398609bcea412abab595d2613c167e",
            "track_id": "track-2",
            "last_event_sequence": 5,
            "as_of_time_ms": 1791590460773,
            "time_domain": "ACTUAL",
            "state_hash": "sha256:04f746c69c116cf9b2a8f8922e96041dce8a98cb78981342ef5dfd2782de469f",
            "input_chain_hash": "sha256:e819b421ae662d3c403dbb69586dfb38db463068f02c06f7240c57ae55bcf1fb",
            "source_component_hash": "sha256:67d43253df42a8f996e81bf48df0e67d3707cd0c20676a7655f27cf382ca9d2a"
          }
        }
      ],
      "auditor": {
        "status": "PASS",
        "proof_hash": "sha256:9a6cfd22482fa552a3edee6c90f0be78c7a0ed023057120a59ce288ff9e3b6d9",
        "difference_count": 0,
        "difference_hashes": []
      },
      "hybrid_extensions": [
        {
          "track_id": "track-2",
          "schema_version": "replay.hybrid-adl-extension.v1",
          "as_of_time_ms": 1791590460773,
          "time_domain": "ACTUAL",
          "component_hash": "sha256:080a9d44d04161c6a7d56ca6551513df5d540289b30559842315b90d3f851715"
        }
      ]
    },
    "account_history": {
      "mode": "DETERMINISTIC_SIMULATION",
      "status": "ACTIVE",
      "fidelity": "PINNED_PUBLIC_INPUTS_DETERMINISTIC_SIMULATED_PRIVATE_STATE",
      "archive_proof_hash": null,
      "bindings": [],
      "auditor": {
        "status": "PASS",
        "proof_hash": "sha256:c62bef48ba3ef95300626aa94c913e5e48a9edb062cd4cad5b16262be39f78ef",
        "differences": []
      }
    },
    "liquidation_channels": {
      "simulated_account": {
        "label": "\u6a21\u62df\u8d26\u6237\u5f3a\u5e73",
        "source": "MODELLED_ACCOUNT",
        "fidelity": "DETERMINISTIC_SIMULATION_NOT_HISTORICAL_EXCHANGE_FACT"
      },
      "historical_market": {
        "label": "\u5386\u53f2\u5e02\u573a\u7206\u4ed3",
        "source": "INDEPENDENT_MARKET_LIQUIDATION_FEED",
        "fidelity": "UNSUPPORTED_NO_HISTORY"
      }
    },
    "ledger": {
      "chain_version": "replay.training.contract-ledger.v1",
      "entry_count": 145,
      "tail_hash": "sha256:d918eb6ea6e910962556f674ab9ad24e2727092ba6633ac2d05d9b5be2560f32",
      "cash_total": "9999.93655999",
      "reconciliation_delta": "0",
      "entries": []
    },
    "fidelity": {
      "hedge_public_history_ref": {
        "archive_id": "hybrid-public-dd31521c580377c111c9b7ef0c6e869e",
        "checksum_sha256": "sha256:fa50f87efde2619a3f3cc0ca10d3242066146ee6d26611802447e6e54b64e8d3",
        "dataset_epoch": "sha256:f7408a2e157e711227d7b1bb4d5662a4cfa04d7e7854aa294a31bbca0a0cde76",
        "schema_version": "replay.hedge-public-history-ref.v1"
      },
      "simulation_manifest_ref": {
        "checksum_sha256": "sha256:65f1c4cecaed3e7b7ca656b5585d590b2a05ba6ddfd899649fe8f7de28a6149d",
        "contract_hash": "sha256:eb93972d289057909f7c8fd8ef66376876f7e0c60b2e46dbe6c5ca4c609f9c4b",
        "dataset_epoch": "sha256:ad131b628afd738e5dd58d9159a38f7090a98a9e5d92ab54d5a3fff1af9afab6",
        "manifest_id": "hybrid-simulation-dd31521c580377c111c9b7ef0c6e869e",
        "model_version": "BINANCE_USDM_LINEAR_HEDGE_DETERMINISTIC_SIMULATION_V1",
        "schema_version": "replay.hedge-simulation-manifest-ref.v1"
      },
      "simulation_contract_hash": "sha256:eb93972d289057909f7c8fd8ef66376876f7e0c60b2e46dbe6c5ca4c609f9c4b",
      "simulation_model_version": "BINANCE_USDM_LINEAR_HEDGE_DETERMINISTIC_SIMULATION_V1",
      "account": "PINNED_PUBLIC_INPUTS_DETERMINISTIC_SIMULATED_PRIVATE_STATE",
      "insurance_adl": "DETERMINISTIC_SIMULATION_NOT_HISTORICAL_EXCHANGE_FACT",
      "instrument_rules": "PINNED_PUBLIC_HISTORY_VERSIONED_RULE",
      "maintenance_margin": "VERSIONED_MAINTENANCE_TIER_APPLIED",
      "liquidation_projection": "VERSIONED_MAINTENANCE_TIER_APPLIED",
      "maintenance_tier_extrapolation": {
        "applied": false,
        "position_count": 0,
        "liquidation_projection_count": 0,
        "reason": null,
        "admission_policy": "STRICT_VERSIONED_ORDER_LIMITS_UNCHANGED"
      },
      "fees": "PINNED_HISTORICAL_FEE_POLICY",
      "funding": "OFF",
      "mark": "PINNED_PUBLIC_HISTORY_MARK",
      "liquidation": "DETERMINISTIC_SIMULATION_NOT_HISTORICAL_EXCHANGE_FACT",
      "liquidation_execution": "TOUCH_OR_TAPE_MARK_SLIPPAGE_V1"
    }
  },
  "global_clock": {
    "contract": "replay.playback.v1",
    "mode": "ORDERED",
    "state": "PAUSED",
    "basis": "VIRTUAL_TIME",
    "rate": 1,
    "speed": 1,
    "display_interval": null,
    "viewer_revision": null,
    "profile_revision": 0,
    "reason": null,
    "generation": 0,
    "tick": 0,
    "supported_bases": [
      "DISPLAY_BAR",
      "BASE_BAR",
      "VIRTUAL_TIME"
    ],
    "playback_bases": [
      "DISPLAY_BAR",
      "BASE_BAR",
      "VIRTUAL_TIME"
    ],
    "max_count": 100000,
    "virtual_time_quantum_ms": 1
  }
};
