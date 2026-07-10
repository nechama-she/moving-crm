import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def migrate() -> None:
    logger.info("No migration actions to run.")


if __name__ == "__main__":
    migrate()
