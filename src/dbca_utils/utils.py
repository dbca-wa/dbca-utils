import os
from ast import literal_eval


def env(key, default=None, required=False, value_type=None):
    """
    Retrieves environment variables and returns Python natives. The (optional)
    `default` value will be returned if the environment variable does not exist.
    Setting `required` will cause an Exception to be thrown if the variable does
    not exist.
    Setting `value_type` will try to ensure that the returned value is of the
    nominated type (within reason).
    Supported Python object types: str, list, tuple, bool, int, float.
    """
    value = None

    try:
        value = os.environ[key]
        # Evaluate the environment variable value as a Python object.
        value = literal_eval(value)
    except (SyntaxError, ValueError):
        pass
    except KeyError:
        if default is not None or not required:
            return default
        raise Exception(f"Missing required environment variable {key}")

    if value_type is None and default is not None:
        # If we've passed a default return value but not set a value_type, use the
        # default's type.
        value_type = default.__class__

    if value_type is None:
        return value
    elif isinstance(value, value_type):
        return value
    elif issubclass(value_type, str):
        return str(value)
    elif issubclass(value_type, list):
        if isinstance(value, tuple):
            return list(value)
        else:
            value = str(value).strip()
            if not value:
                return []
            else:
                return [s.strip() for s in value.split(",") if s.strip()]
    elif issubclass(value_type, tuple):
        if isinstance(value, list):
            return tuple(value)
        else:
            value = str(value).strip()
            if not value:
                return tuple()
            else:
                return tuple([s.strip() for s in value.split(",") if s.strip()])
    elif issubclass(value_type, bool):
        value = str(value).strip()
        if not value:
            return False
        elif value.lower() == "true":
            return True
        elif value.lower() == "false":
            return False
        else:
            raise Exception(
                f"{key} is a boolean environment variable and only accepts 'true', 'false' or '' (case-insensitive), but the configured value is '{value}'"
            )
    elif issubclass(value_type, int):
        return int(value)
    elif issubclass(value_type, float):
        return float(value)
    else:
        raise Exception(
            f"{key} is a {value_type} environment variable, but {value_type} is not supported"
        )
