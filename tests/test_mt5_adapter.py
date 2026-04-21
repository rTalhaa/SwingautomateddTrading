from __future__ import annotations

import unittest
from collections import namedtuple
from decimal import Decimal
from types import SimpleNamespace

from bos75 import (
    MT5AdapterConfig,
    MT5AdapterError,
    MT5OrderAdapter,
    OrderCommandType,
    PendingOrderType,
)
from bos75.orders import CancelPendingOrderCommand, PlacePendingLimitCommand


SYMBOL = "EURUSD"


def place_command(order_type: PendingOrderType = PendingOrderType.BUY_LIMIT) -> PlacePendingLimitCommand:
    return PlacePendingLimitCommand(
        id="cmd:place:setup-1",
        symbol=SYMBOL,
        order_type=order_type,
        setup_id="setup-1",
        entry=Decimal("91.00"),
        stop_loss=Decimal("88"),
        take_profit=Decimal("100"),
        source_bos_id="bos-1",
        timestamp="t1",
    )


def cancel_command(setup_id: str = "setup-1") -> CancelPendingOrderCommand:
    return CancelPendingOrderCommand(
        id="cmd:cancel:setup-1",
        symbol=SYMBOL,
        setup_id=setup_id,
        reason="opposite_bos_invalidation",
        timestamp="t2",
        replacement_bos_id="bos-2",
    )


class FakeMT5:
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008

    def __init__(self) -> None:
        self.initialized_with = None
        self.logged_in_with = None
        self.shutdown_called = False
        self.sent_requests = []
        self.next_retcode = self.TRADE_RETCODE_PLACED
        self.next_order_ticket = 12345
        self.orders = []

    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        return True

    def login(self, **kwargs):
        self.logged_in_with = kwargs
        return True

    def shutdown(self):
        self.shutdown_called = True

    def last_error(self):
        return (1, "fake error")

    def order_send(self, request):
        self.sent_requests.append(request)
        return SimpleNamespace(retcode=self.next_retcode, order=self.next_order_ticket)

    def orders_get(self, symbol):
        return [order for order in self.orders if order.symbol == symbol]


class FailingInitializeMT5(FakeMT5):
    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        return False


class MT5AdapterTests(unittest.TestCase):
    def test_connect_initializes_terminal_and_optional_login(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(
            MT5AdapterConfig(
                terminal_path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
                login=123,
                password="pass",
                server="broker",
            ),
            mt5_client=fake,
        )

        adapter.connect()
        adapter.shutdown()

        self.assertEqual(fake.initialized_with["path"], r"C:\Program Files\MetaTrader 5\terminal64.exe")
        self.assertEqual(fake.logged_in_with["login"], 123)
        self.assertTrue(fake.shutdown_called)

    def test_connect_failure_raises_adapter_error(self) -> None:
        adapter = MT5OrderAdapter(MT5AdapterConfig(), mt5_client=FailingInitializeMT5())

        with self.assertRaises(MT5AdapterError):
            adapter.connect()

    def test_build_buy_limit_request_from_command(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(MT5AdapterConfig(volume=0.25, deviation=7), mt5_client=fake)

        request = adapter.build_place_request(place_command())

        self.assertEqual(request["action"], fake.TRADE_ACTION_PENDING)
        self.assertEqual(request["symbol"], SYMBOL)
        self.assertEqual(request["volume"], 0.25)
        self.assertEqual(request["type"], fake.ORDER_TYPE_BUY_LIMIT)
        self.assertEqual(request["price"], 91.0)
        self.assertEqual(request["sl"], 88.0)
        self.assertEqual(request["tp"], 100.0)
        self.assertEqual(request["deviation"], 7)
        self.assertEqual(request["magic"], 750075)
        self.assertLessEqual(len(request["comment"]), 31)

    def test_build_sell_limit_request_from_command(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(mt5_client=fake)

        request = adapter.build_place_request(place_command(PendingOrderType.SELL_LIMIT))

        self.assertEqual(request["type"], fake.ORDER_TYPE_SELL_LIMIT)

    def test_place_pending_limit_sends_order_and_reports_ticket(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(mt5_client=fake)

        result = adapter.place_pending_limit(place_command())

        self.assertTrue(result.ok)
        self.assertEqual(result.command_type, OrderCommandType.PLACE_PENDING_LIMIT)
        self.assertEqual(result.order_ticket, 12345)
        self.assertEqual(fake.sent_requests[0]["action"], fake.TRADE_ACTION_PENDING)

    def test_cancel_pending_order_finds_matching_magic_and_comment(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(mt5_client=fake)
        Order = namedtuple("Order", "ticket symbol magic comment")
        fake.orders = [
            Order(111, SYMBOL, 1, "other"),
            Order(222, SYMBOL, 750075, adapter.comment_for_setup("setup-1")),
        ]
        fake.next_retcode = fake.TRADE_RETCODE_DONE

        result = adapter.cancel_pending_order(cancel_command())

        self.assertTrue(result.ok)
        self.assertEqual(result.command_type, OrderCommandType.CANCEL_PENDING_ORDER)
        self.assertEqual(result.order_ticket, 222)
        self.assertEqual(fake.sent_requests[0], {"action": fake.TRADE_ACTION_REMOVE, "order": 222})

    def test_cancel_pending_order_reports_missing_order_without_send(self) -> None:
        fake = FakeMT5()
        adapter = MT5OrderAdapter(mt5_client=fake)

        result = adapter.cancel_pending_order(cancel_command("missing-setup"))

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "pending order not found for cancellation")
        self.assertEqual(fake.sent_requests, [])


if __name__ == "__main__":
    unittest.main()
