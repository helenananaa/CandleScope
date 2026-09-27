"""Failures for which an ingestion event must not be acknowledged as delivered."""


class BarDeliveryUnavailable(RuntimeError):
    code = "BAR_DELIVERY_UNAVAILABLE"
