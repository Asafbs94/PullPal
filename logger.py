import logging
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def setup_logger():
    """
    configure the logger format and handlers
    required env variables:
        - LOG_PATH
        - LOG_LEVEL (DEBUG, INFO, WARNING, ERROR)
        - PRINT_TO_CONSOLE (TRUE, FALSE)md
    """
    log_path = os.getenv("LOG_PATH", "logs")
    os.makedirs(log_path, exist_ok=True)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = validate_log_level(log_level)

    log_file = f"{log_path}/{datetime.today().strftime('%d-%m-%Y')}.log"
    log_format = "%(asctime)s - %(levelname)s - %(message)s - (%(filename)s:%(lineno)s)"

    handlers = [logging.FileHandler(log_file, mode="a")]

    if os.getenv("PRINT_TO_CONSOLE", "true").lower() == "true":
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(ColorFormatter(log_format))
        handlers.append(console_handler)

    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        handlers=handlers
    )

    logging.debug(f"Logger initialized successfully with level: <{log_level}>")
    return logging.getLogger()


class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[94m",  # blue
        "INFO": "\033[92m",   # green
        "WARNING": "\033[93m",  # yellow
        "ERROR": "\033[91m",   # red
        "CRITICAL": "\033[95m",  # purple
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        formatted = super().format(record)
        return f"{color}{formatted}{self.RESET}"


def validate_log_level(log_level):
    if log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        raise ValueError(f"Invalid log level: {log_level}.")

    return getattr(logging, log_level, logging.INFO)
