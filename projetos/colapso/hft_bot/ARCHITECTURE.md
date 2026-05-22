# HFT BOT ARCHITECTURE

## OBJECTIVE

Simple HFT scalping architecture for MetaTrader 5 using:

* microstructure
* tick momentum
* velocity
* acceleration
* micro breakout

System priorities:

1. low latency
2. execution stability
3. risk protection
4. thread safety
5. netting support
6. simplicity

NOT allowed:

* AI
* machine learning
* RSI
* MACD
* heavy indicators
* overengineering
* multi-strategy framework
* excessive abstractions

---

# ARCHITECTURE RULES

Each module must have SINGLE responsibility.

core/

* mt5_connector.py → MT5 communication only
* tick_engine.py → tick processing only
* signal_engine.py → signal orchestration only
* execution_engine.py → order execution only
* risk_engine.py → risk validation only
* position_manager.py → position sync only
* watchdog.py → monitoring only

strategies/

* momentum_burst.py → strategy logic only

main.py

* orchestration only

---

# PERFORMANCE RULES

Avoid:

* unnecessary MT5 calls
* excessive logging
* heavy numpy usage
* nested loops
* duplicated calculations
* excessive locks

---

# EXECUTION RULES

Must have:

* execution lock
* slippage measurement
* retry protection
* circuit breaker
* latency protection
* watchdog
* reconnect
* session filter

---

# NETTING RULES

System is NETTING-FIRST.

Must support:

* reversal
* single net position
* synchronized position state

---

# RISK RULES

System must stop trading when:

* max loss hit
* latency too high
* spread too high
* consecutive errors
* circuit breaker triggered

---

# DEVELOPMENT RULES

Before creating code:

1. verify if module responsibility is respected
2. avoid adding complexity
3. avoid duplicate logic
4. keep HFT-oriented design
5. keep low latency priority

Always prioritize:

* simplicity
* execution
* stability
* low latency
