"""IB Gateway client via ib_async. The only module that imports ib_async."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ib_async import IB, LimitOrder, Stock

from rsi_cross_swing_bot.core.errors import DataUnavailableError
from rsi_cross_swing_bot.core.models import Bar, BrokerFill, Quote

ET = ZoneInfo("America/New_York")


class IbClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return
        try:
            self._ib.connect(self._host, self._port, clientId=self._client_id, readonly=False)
        except Exception as exc:  # noqa: BLE001 - surface as data error
            raise DataUnavailableError(f"IB Gateway connect failed: {exc}") from exc
        self._connected = True

    def disconnect(self) -> None:
        if self._connected:
            self._ib.disconnect()
            self._connected = False

    def accounts(self) -> list[str]:
        self.connect()
        return list(self._ib.managedAccounts())

    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]:
        self.connect()
        contract = Stock(symbol, "SMART", "USD")
        self._ib.qualifyContracts(contract)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=ET)
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime=end_dt,
            durationStr=f"{max(days, 1)} D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        out: list[Bar] = []
        for b in bars:
            raw = b.date
            if isinstance(raw, datetime):
                session = raw.astimezone(ET).date()
            else:
                session = date.fromisoformat(str(raw)[:10])
            out.append(
                Bar(
                    session_date=session,
                    open=float(b.open),
                    high=float(b.high),
                    low=float(b.low),
                    close=float(b.close),
                    volume=float(b.volume or 0),
                )
            )
        return out

    def quote(self, symbol: str) -> Quote:
        self.connect()
        contract = Stock(symbol, "SMART", "USD")
        self._ib.qualifyContracts(contract)
        tickers = self._ib.reqTickers(contract)
        if not tickers:
            raise DataUnavailableError(f"no quote for {symbol}")
        t = tickers[0]
        bid = float(t.bid or 0)
        ask = float(t.ask or 0)
        last = float(t.last or t.close or 0)
        delayed = bool(getattr(t, "delayed", False)) or (
            t.marketDataType is not None and int(t.marketDataType) >= 3
        )
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last,
            delayed=delayed,
            as_of=datetime.now(ET),
        )

    def available_usd_cash(self, account: str) -> float:
        self.connect()
        tags = self._ib.accountValues(account)
        for row in tags:
            if (
                row.tag in {"AvailableFunds", "TotalCashValue", "CashBalance"}
                and row.currency == "USD"
            ):
                try:
                    return float(row.value)
                except ValueError:
                    continue
        return 0.0

    def position_qty(self, account: str, symbol: str) -> int:
        self.connect()
        total = 0
        for pos in self._ib.positions(account):
            if getattr(pos.contract, "symbol", "") == symbol:
                total += int(pos.position)
        return total

    def place_limit(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float,
        order_ref: str,
        account: str,
    ) -> tuple[str, str]:
        self.connect()
        contract = Stock(symbol, "SMART", "USD")
        self._ib.qualifyContracts(contract)
        order = LimitOrder(side, quantity, limit_price)
        order.orderRef = order_ref
        order.account = account
        order.tif = "DAY"
        order.outsideRth = False
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(1)
        return str(trade.order.orderId), str(trade.orderStatus.status)

    def cancel_order(self, broker_order_id: str) -> str:
        self.connect()
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == broker_order_id:
                self._ib.cancelOrder(trade.order)
                self._ib.sleep(0.5)
                return str(trade.orderStatus.status)
        return "Cancelled"

    def order_status(self, broker_order_id: str) -> tuple[str, int, float]:
        self.connect()
        for trade in self._ib.trades():
            if str(trade.order.orderId) == broker_order_id:
                filled = int(trade.orderStatus.filled or 0)
                avg = float(trade.orderStatus.avgFillPrice or 0)
                return str(trade.orderStatus.status), filled, avg
        return "Cancelled", 0, 0.0

    def fills_for(self, order_ref: str) -> list[BrokerFill]:
        self.connect()
        out: list[BrokerFill] = []
        for trade in self._ib.trades():
            if getattr(trade.order, "orderRef", "") != order_ref:
                continue
            for fill in trade.fills:
                fill_time = fill.time
                if fill_time.tzinfo is None:
                    fill_time = fill_time.replace(tzinfo=ET)
                out.append(
                    BrokerFill(
                        order_ref=order_ref,
                        symbol=str(trade.contract.symbol),
                        side=str(trade.order.action),
                        quantity=int(fill.execution.shares),
                        price=float(fill.execution.price),
                        time=fill_time,
                        broker_order_id=str(trade.order.orderId),
                    )
                )
        return out


class FakeIbClient:
    """In-memory IB stand-in for tests and offline paths."""

    def __init__(
        self,
        *,
        bars: list[Bar] | None = None,
        quotes: dict[str, Quote] | None = None,
        cash: float = 100_000.0,
        positions: dict[str, int] | None = None,
        accounts: list[str] | None = None,
        place_calls: list[dict[str, object]] | None = None,
    ) -> None:
        self._bars = bars or []
        self._quotes = quotes or {}
        self._cash = cash
        self._positions = positions or {}
        self._accounts = accounts or ["DU123456"]
        self.place_calls = place_calls if place_calls is not None else []
        self._order_seq = 1
        self._fills: dict[str, list[BrokerFill]] = {}

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def accounts(self) -> list[str]:
        return list(self._accounts)

    def daily_bars(self, symbol: str, end: date, days: int) -> list[Bar]:
        cutoff = end - timedelta(days=days * 2)
        return [b for b in self._bars if cutoff <= b.session_date <= end]

    def quote(self, symbol: str) -> Quote:
        if symbol not in self._quotes:
            raise DataUnavailableError(f"no quote for {symbol}")
        return self._quotes[symbol]

    def available_usd_cash(self, account: str) -> float:
        return self._cash

    def position_qty(self, account: str, symbol: str) -> int:
        return int(self._positions.get(symbol, 0))

    def place_limit(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        limit_price: float,
        order_ref: str,
        account: str,
    ) -> tuple[str, str]:
        self.place_calls.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "limit_price": limit_price,
                "order_ref": order_ref,
                "account": account,
            }
        )
        oid = str(self._order_seq)
        self._order_seq += 1
        q = self.quote(symbol)
        px = q.ask if side == "BUY" else q.bid
        self._fills[order_ref] = [
            BrokerFill(
                order_ref=order_ref,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=px,
                time=q.as_of,
                broker_order_id=oid,
            )
        ]
        signed = quantity if side == "BUY" else -quantity
        self._positions[symbol] = int(self._positions.get(symbol, 0)) + signed
        return oid, "Filled"

    def cancel_order(self, broker_order_id: str) -> str:
        return "Cancelled"

    def order_status(self, broker_order_id: str) -> tuple[str, int, float]:
        return "Filled", 0, 0.0

    def fills_for(self, order_ref: str) -> list[BrokerFill]:
        return list(self._fills.get(order_ref, []))
