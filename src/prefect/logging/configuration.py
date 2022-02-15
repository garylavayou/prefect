import logging
import logging.config
import os
import re
import string
import warnings
from functools import partial
from pathlib import Path

import yaml

from prefect.settings import (
    PREFECT_LOGGING_EXTRA_LOGGERS,
    PREFECT_LOGGING_SETTINGS_PATH,
    SETTINGS,
    Settings,
)
from prefect.utilities.collections import dict_to_flatdict, flatdict_to_dict

# This path will be used if `PREFECT_LOGGING_SETTINGS_PATH` is null
DEFAULT_LOGGING_SETTINGS_PATH = Path(__file__).parent / "logging.yml"

# Stores the configuration used to setup logging in this Python process
PROCESS_LOGGING_CONFIG: dict = None


# Regex call to replace non-alphanumeric characters to '_' to create a valid env var
to_envvar = partial(re.sub, re.compile(r"[^0-9a-zA-Z]+"), "_")
# Regex for detecting interpolated global settings
interpolated_settings = re.compile(r"^{{([\w\d_]+)}}$")


def load_logging_config(path: Path, settings: Settings) -> dict:
    """
    Loads logging configuration from a path allowing override from the environment
    """
    template = string.Template(path.read_text())
    config = yaml.safe_load(
        template.substitute(
            {
                setting.name: str(setting.value_from(settings))
                for setting in SETTINGS.values()
            }
        )
    )

    # Load overrides from the environment
    flat_config = dict_to_flatdict(config)

    for key_tup, val in flat_config.items():

        env_val = os.environ.get(
            # Generate a valid environment variable with nesting indicated with '_'
            to_envvar("PREFECT_LOGGING_" + "_".join(key_tup)).upper()
        )
        if env_val:
            val = env_val

        # reassign the updated value
        flat_config[key_tup] = val

    return flatdict_to_dict(flat_config)


def setup_logging(settings: Settings) -> None:
    global PROCESS_LOGGING_CONFIG

    # If the user has specified a logging path and it exists we will ignore the
    # default entirely rather than dealing with complex merging
    config = load_logging_config(
        (
            PREFECT_LOGGING_SETTINGS_PATH.value_from(settings)
            if PREFECT_LOGGING_SETTINGS_PATH.value_from(settings).exists()
            else DEFAULT_LOGGING_SETTINGS_PATH
        ),
        settings,
    )

    if PROCESS_LOGGING_CONFIG:
        # Do not allow repeated configuration calls, only warn if the config differs
        config_diff = {
            key: value
            for key, value in config.items()
            if PROCESS_LOGGING_CONFIG[key] != value
        }
        if config_diff:
            warnings.warn(
                "Logging can only be setup once per process, the new logging config "
                f"will be ignored. The attempted changes were: {config_diff}",
                stacklevel=2,
            )
        return

    logging.config.dictConfig(config)

    # Copy configuration of the 'prefect.extra' logger to the extra loggers
    extra_config = logging.getLogger("prefect.extra")

    for logger_name in PREFECT_LOGGING_EXTRA_LOGGERS.value_from(settings):
        logger = logging.getLogger(logger_name)
        for handler in extra_config.handlers:
            logger.addHandler(handler)
            if logger.level == logging.NOTSET:
                logger.setLevel(extra_config.level)
            logger.propagate = extra_config.propagate

    PROCESS_LOGGING_CONFIG = config
