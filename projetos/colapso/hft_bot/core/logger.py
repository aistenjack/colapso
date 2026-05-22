import logging
import os
from logging.handlers import RotatingFileHandler


class Log:
    _initialized = False
    _loggers: dict[str, logging.Logger] = {}

    @classmethod
    def setup(cls, log_dir: str = "logs", console_level: int = logging.INFO, file_level: int = logging.DEBUG) -> None:
        if cls._initialized:
            return

        os.makedirs(log_dir, exist_ok=True)

        console_fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-10s | %(message)s",
            datefmt="%H:%M:%S",
        )
        file_fmt = logging.Formatter(
            "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-10s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(console_fmt)

        def _file_handler(filename: str, lvl: int) -> RotatingFileHandler:
            path = os.path.join(log_dir, filename)
            h = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
            h.setLevel(lvl)
            h.setFormatter(file_fmt)
            return h

        trade_file = _file_handler("trades.log", logging.INFO)
        error_file = _file_handler("errors.log", logging.ERROR)
        system_file = _file_handler("system.log", logging.DEBUG)

        configs = {
            "trade": [console_handler, trade_file],
            "error": [console_handler, error_file],
            "system": [console_handler, system_file],
            "execution": [console_handler, system_file, trade_file],
            "risk": [console_handler, system_file, error_file],
            "tick": [system_file],
            "signal": [console_handler, system_file],
            "position": [console_handler, system_file, trade_file],
        }

        for name, handlers in configs.items():
            logger = logging.getLogger(name)
            logger.setLevel(file_level)
            logger.propagate = False
            for h in handlers:
                logger.addHandler(h)
            cls._loggers[name] = logger

        cls._initialized = True

    @classmethod
    def get(cls, name: str) -> logging.Logger:
        if not cls._initialized:
            cls.setup()
        if name not in cls._loggers:
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            cls._loggers[name] = logger
        return cls._loggers[name]

    @classmethod
    def shutdown(cls) -> None:
        for logger in cls._loggers.values():
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
        cls._loggers.clear()
        cls._initialized = False
