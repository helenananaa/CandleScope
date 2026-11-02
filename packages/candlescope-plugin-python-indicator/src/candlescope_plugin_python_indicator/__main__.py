from candlescope_plugin_sdk import serve_runtime
from .runtime import PythonIndicatorRuntime


def main():
    return serve_runtime(PythonIndicatorRuntime())


if __name__ == "__main__":
    raise SystemExit(main())
