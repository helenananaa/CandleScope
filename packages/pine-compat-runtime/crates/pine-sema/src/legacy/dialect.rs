use pine_syntax::{Diagnostic, Program, Span};

pub const MIN_PINE_LANGUAGE_VERSION: u16 = 1;
pub const MAX_PINE_LANGUAGE_VERSION: u16 = 6;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum PineDialect {
    V1,
    V2,
    V3,
    V4,
    V5,
    V6,
}

impl PineDialect {
    #[must_use]
    pub const fn from_version(version: u16) -> Option<Self> {
        match version {
            1 => Some(Self::V1),
            2 => Some(Self::V2),
            3 => Some(Self::V3),
            4 => Some(Self::V4),
            5 => Some(Self::V5),
            6 => Some(Self::V6),
            _ => None,
        }
    }

    #[must_use]
    pub const fn version(self) -> u16 {
        match self {
            Self::V1 => 1,
            Self::V2 => 2,
            Self::V3 => 3,
            Self::V4 => 4,
            Self::V5 => 5,
            Self::V6 => 6,
        }
    }

    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::V1 => "v1",
            Self::V2 => "v2",
            Self::V3 => "v3",
            Self::V4 => "v4",
            Self::V5 => "v5",
            Self::V6 => "v6",
        }
    }

    #[must_use]
    pub const fn is_legacy(self) -> bool {
        matches!(self, Self::V1 | Self::V2 | Self::V3 | Self::V4)
    }

    /// Returns the first Pine version that accepts a qualified built-in name
    /// in source code. Legacy aliases are checked separately, before their
    /// canonical targets reach the analyzer, so this gate must describe the
    /// spelling used by the source rather than the lowered call name.
    #[must_use]
    pub(crate) fn qualified_builtin_min_version(name: &str, is_call: bool) -> Option<u16> {
        if is_call && name == "alertcondition" {
            return Some(2);
        }
        let namespace = name.split_once('.')?.0;
        if is_call {
            match namespace {
                // These namespaces expose callable helpers only in the modern
                // API, even when an older dialect already had value members
                // under the same prefix.
                "input" | "syminfo" | "timeframe" => return Some(5),
                _ => {}
            }
        }

        let exact_min_version = match name {
            // Individual members can arrive after the namespace itself.
            "box.set_xloc"
            | "label.set_text_formatting"
            | "box.set_text_formatting"
            | "table.cell_set_text_formatting"
            | "strategy.closedtrades.first_index"
            | "ta.rci" => Some(6),
            "strategy.opentrades.capital_held" => Some(5),

            // Calls and values added after their namespaces first appeared.
            "array.new_linefill"
            | "array.new<chart.point>"
            | "array.first"
            | "array.last"
            | "array.every"
            | "array.some"
            | "array.binary_search"
            | "array.binary_search_leftmost"
            | "array.binary_search_rightmost"
            | "array.abs"
            | "array.percentile_nearest_rank"
            | "array.percentile_linear_interpolation"
            | "array.percentrank"
            | "array.sort_indices"
            | "label.set_point"
            | "label.set_text_font_family"
            | "label.copy"
            | "line.set_first_point"
            | "line.set_second_point"
            | "line.copy"
            | "box.set_top_left_point"
            | "box.set_bottom_right_point"
            | "box.set_text"
            | "box.set_text_color"
            | "box.set_text_size"
            | "box.set_text_halign"
            | "box.set_text_valign"
            | "box.set_text_wrap"
            | "box.set_text_font_family"
            | "box.copy"
            | "table.merge_cells"
            | "table.cell_set_tooltip"
            | "table.cell_set_text_font_family"
            | "box.all"
            | "label.all"
            | "line.all"
            | "table.all"
            | "plot.style_stepline_diamond" => Some(5),

            // Project extensions absent from the frozen official references:
            // keep their floor aligned with the v5 polyline/text.wrap types
            // they depend on.
            "array.new_polyline" | "table.cell_set_text_wrap" => Some(5),

            // These string helpers already used the str.* spelling in v4.
            "str.length" | "str.replace_all" | "str.format" | "str.split" => Some(4),

            // Strategy trade-introspection helpers use the v5 namespace API.
            "strategy.convert_to_account"
            | "strategy.convert_to_symbol"
            | "strategy.default_entry_qty"
            | "strategy.closedtrades.entry_price"
            | "strategy.closedtrades.entry_comment"
            | "strategy.closedtrades.entry_id"
            | "strategy.closedtrades.exit_price"
            | "strategy.closedtrades.exit_comment"
            | "strategy.closedtrades.exit_id"
            | "strategy.closedtrades.entry_bar_index"
            | "strategy.closedtrades.exit_bar_index"
            | "strategy.closedtrades.entry_time"
            | "strategy.closedtrades.exit_time"
            | "strategy.closedtrades.commission"
            | "strategy.closedtrades.size"
            | "strategy.closedtrades.profit"
            | "strategy.closedtrades.profit_percent"
            | "strategy.closedtrades.max_runup"
            | "strategy.closedtrades.max_runup_percent"
            | "strategy.closedtrades.max_drawdown"
            | "strategy.closedtrades.max_drawdown_percent"
            | "strategy.opentrades.entry_price"
            | "strategy.opentrades.entry_comment"
            | "strategy.opentrades.entry_id"
            | "strategy.opentrades.entry_bar_index"
            | "strategy.opentrades.entry_time"
            | "strategy.opentrades.size"
            | "strategy.opentrades.profit"
            | "strategy.opentrades.profit_percent"
            | "strategy.opentrades.commission"
            | "strategy.opentrades.max_runup"
            | "strategy.opentrades.max_runup_percent"
            | "strategy.opentrades.max_drawdown"
            | "strategy.opentrades.max_drawdown_percent"
            | "strategy.account_currency"
            | "strategy.avg_losing_trade"
            | "strategy.avg_losing_trade_percent"
            | "strategy.avg_trade"
            | "strategy.avg_trade_percent"
            | "strategy.avg_winning_trade"
            | "strategy.avg_winning_trade_percent"
            | "strategy.grossloss_percent"
            | "strategy.grossprofit_percent"
            | "strategy.margin_liquidation_price"
            | "strategy.max_drawdown_percent"
            | "strategy.max_runup"
            | "strategy.max_runup_percent"
            | "strategy.netprofit_percent"
            | "strategy.openprofit_percent" => Some(5),

            // Mixed-version bar-state inventory.
            "barstate.isfirst"
            | "barstate.islast"
            | "barstate.ishistory"
            | "barstate.isrealtime"
            | "barstate.isnew" => Some(1),
            "barstate.isconfirmed" => Some(3),
            "barstate.islastconfirmedhistory" => Some(4),

            // Session option strings predate the live session-state values.
            "session.regular" | "session.extended" => Some(3),
            "session.ismarket" | "session.ispremarket" | "session.ispostmarket" => Some(4),
            "session.isfirstbar"
            | "session.islastbar"
            | "session.isfirstbar_regular"
            | "session.islastbar_regular" => Some(5),

            // syminfo values were introduced in several historical waves.
            "syminfo.mintick" | "syminfo.pointvalue" | "syminfo.prefix" | "syminfo.root"
            | "syminfo.session" | "syminfo.timezone" => Some(3),
            "syminfo.basecurrency"
            | "syminfo.currency"
            | "syminfo.description"
            | "syminfo.ticker"
            | "syminfo.tickerid"
            | "syminfo.type" => Some(4),
            "syminfo.country" | "syminfo.industry" | "syminfo.sector" | "syminfo.volumetype"
            | "syminfo.minmove" | "syminfo.pricescale" => Some(5),
            "syminfo.main_tickerid" | "syminfo.mincontract" => Some(6),

            // The original timeframe value family is a v4 namespace. Later
            // additions must not leak backwards through the shared registry.
            "timeframe.period"
            | "timeframe.isseconds"
            | "timeframe.isminutes"
            | "timeframe.isintraday"
            | "timeframe.isdaily"
            | "timeframe.isweekly"
            | "timeframe.ismonthly"
            | "timeframe.isdwm"
            | "timeframe.multiplier" => Some(4),
            "timeframe.isticks" => Some(5),
            "timeframe.main_period" => Some(6),

            // The classic currency set is present in the earliest supported
            // dialect. All other registered currency constants are modern.
            "currency.AUD" | "currency.CAD" | "currency.CHF" | "currency.EUR" | "currency.GBP"
            | "currency.HKD" | "currency.JPY" | "currency.NOK" | "currency.NONE"
            | "currency.NZD" | "currency.RUB" | "currency.SEK" | "currency.SGD"
            | "currency.TRY" | "currency.USD" | "currency.ZAR" => Some(1),
            "currency.BTC" | "currency.ETH" | "currency.MYR" | "currency.KRW" | "currency.USDT"
            | "currency.INR" => Some(5),
            "currency.BDT" | "currency.BHD" | "currency.BRL" | "currency.CLP" | "currency.CNY"
            | "currency.COP" | "currency.CZK" | "currency.DKK" | "currency.EGP"
            | "currency.HUF" | "currency.IDR" | "currency.ILS" | "currency.ISK"
            | "currency.KES" | "currency.KWD" | "currency.LKR" | "currency.MAD"
            | "currency.MXN" | "currency.NGN" | "currency.PEN" | "currency.PHP"
            | "currency.PKR" | "currency.PLN" | "currency.QAR" | "currency.RON"
            | "currency.RSD" | "currency.SAR" | "currency.THB" | "currency.TND"
            | "currency.TWD" | "currency.VES" | "currency.VND" => Some(6),

            // Display and text option families also have member-level version
            // boundaries despite sharing one namespace.
            "display.all" | "display.none" => Some(4),
            "display.pane"
            | "display.price_scale"
            | "display.status_line"
            | "display.data_window" => Some(5),
            "text.align_left" | "text.align_center" | "text.align_right" | "text.align_top"
            | "text.align_bottom" => Some(4),
            "text.wrap_none" | "text.wrap_auto" => Some(5),
            "text.format_none" | "text.format_bold" | "text.format_italic" => Some(6),
            "math.e" | "math.pi" | "math.phi" | "math.rphi" => Some(4),
            _ => None,
        };
        if exact_min_version.is_some() {
            return exact_min_version;
        }

        Some(match namespace {
            // Namespaces introduced by the v5 reorganization (or later).
            "ta"
            | "math"
            | "request"
            | "str"
            | "matrix"
            | "map"
            | "chart"
            | "ticker"
            | "linefill"
            | "polyline"
            | "runtime"
            | "log"
            | "backadjustment"
            | "settlement_as_close"
            | "font" => 5,
            // input.* values in v4 were overload selectors such as
            // input.integer. The callable input.int/input.string family is a
            // v5 API and must not be confused with those constants.
            "input" => 4,
            // Collections, drawings, colors, and their option namespaces are
            // available under qualified names beginning with Pine v4.
            "array" | "color" | "label" | "line" | "box" | "table" | "plot" | "hline"
            | "format" | "xloc" | "yloc" | "extend" | "alert" | "dayofweek" | "order"
            | "position" => 4,
            // Historical option namespaces are older than most v4 drawing
            // namespaces. Mixed namespaces use exact overrides above, then a
            // conservative fallback for newer/unknown members.
            "location" | "shape" => 1,
            "scale" => 2,
            "adjustment" | "size" => 3,
            "currency" => 6,
            // Every currently registered member of these mixed namespaces is
            // classified above. Unknown future members default to the newest
            // supported dialect until their historical boundary is reviewed.
            "barstate" | "session" | "display" | "text" | "syminfo" | "timeframe" => 6,
            // barmerge constants were already part of the v3 security API.
            "barmerge" => 3,
            // These namespaces predate the v3/v4 migration surface. Strategy
            // references are independently rejected by legacy indicator
            // admission, while bar-state and currency constants remain valid
            // in old indicator expressions.
            "strategy" => 1,
            // No version claim is made for names outside the versioned
            // namespace inventory; normal built-in/unknown-name validation
            // remains authoritative for them.
            _ => return None,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum VersionOrigin {
    ExplicitDirective,
    ImplicitV1,
}

impl VersionOrigin {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::ExplicitDirective => "explicit",
            Self::ImplicitV1 => "implicit",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LanguageSelection {
    pub(crate) raw_version: u16,
    pub(crate) origin: VersionOrigin,
    pub(crate) dialect: Option<PineDialect>,
    pub(crate) span: Span,
}

impl LanguageSelection {
    pub(crate) fn from_program_with_implicit(
        program: &Program,
        implicit_dialect: PineDialect,
    ) -> Self {
        match program.version {
            Some(version) => Self {
                raw_version: version.version,
                origin: VersionOrigin::ExplicitDirective,
                dialect: PineDialect::from_version(version.version),
                span: version.span,
            },
            None => Self {
                raw_version: implicit_dialect.version(),
                origin: if implicit_dialect == PineDialect::V1 {
                    VersionOrigin::ImplicitV1
                } else {
                    VersionOrigin::ExplicitDirective
                },
                dialect: Some(implicit_dialect),
                span: Span::new(0, 0),
            },
        }
    }

    pub(crate) fn unsupported_diagnostic(self) -> Option<Diagnostic> {
        self.dialect.is_none().then(|| {
            Diagnostic::error(
                "E_LANGUAGE_VERSION_UNSUPPORTED",
                format!(
                    "Pine language version {} is unsupported; expected {} through {}",
                    self.raw_version, MIN_PINE_LANGUAGE_VERSION, MAX_PINE_LANGUAGE_VERSION
                ),
                self.span,
            )
        })
    }
}
