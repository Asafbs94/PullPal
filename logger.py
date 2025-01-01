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
        - PRINT_TO_CONSOLE (TRUE, FALSE)
    """
    log_path = os.getenv("LOG_PATH", f"logs")
    if not os.path.exists(log_path):
        os.mkdir(log_path)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    log_file = f"{log_path}/{datetime.today().strftime('%d-%m-%Y')}.log"
    log_format = "%(asctime)s - %(levelname)s - %(message)s - (%(filename)s:%(lineno)s)"

    handlers = [logging.FileHandler(log_file, mode="a")]

    if os.getenv("PRINT_TO_CONSOLE", "true").lower() == "true":
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        handlers=handlers
    )

    return logging.getLogger()