import json
import os

try:
    import keyring  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"keyring is required: {exc}")


PREFIX = "toolreadjson"


def _service(env: str):
    return f"{PREFIX}:{env.upper()}"


def main(config_file="config.json"):
    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    envs = ("TEST", "STG")
    for env in envs:
        srv = _service(env)
        bearer = cfg.get("bearertoken", {}) or {}
        headers = cfg.get("headers", {}) or {}
        pairs = {
            "BEARER_USERNAME": bearer.get("username", ""),
            "BEARER_PASSWORD": bearer.get("password", ""),
            "BEARER_APIKEY": bearer.get("apikey", ""),
            "API_USERNAME": headers.get("username", ""),
            "API_PASSWORD": headers.get("password", ""),
            "API_APIKEY": headers.get("apikey", ""),
        }
        for key, value in pairs.items():
            if value:
                keyring.set_password(srv, key, str(value))
                print(f"Stored {srv}/{key}")

    print("Done. You can now rotate/remove secrets in config.json.")
    print("Env var override format:")
    print("  TOOLREADJSON_TEST_BEARER_USERNAME=...")
    print("  TOOLREADJSON_TEST_BEARER_PASSWORD=...")
    print("  TOOLREADJSON_TEST_API_USERNAME=...")
    print("  TOOLREADJSON_TEST_API_PASSWORD=...")


if __name__ == "__main__":
    cfg = os.getenv("TOOLREADJSON_CONFIG", "config.json")
    main(cfg)
