use pine_ir::CallSiteId;

pub(crate) fn default_random_seed(call_site_id: CallSiteId) -> u64 {
    mix_random_seed(0x9e37_79b9_7f4a_7c15_u64 ^ u64::from(call_site_id.0))
}

pub(crate) fn mix_random_seed(seed: u64) -> u64 {
    let mut state = seed.wrapping_add(0x9e37_79b9_7f4a_7c15);
    state = (state ^ (state >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    state = (state ^ (state >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    state ^ (state >> 31)
}

pub(crate) fn next_random_state(state: u64) -> u64 {
    state
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407)
}

pub(crate) fn random_unit_interval(state: u64) -> f64 {
    ((state >> 11) as f64) * (1.0 / ((1_u64 << 53) as f64))
}
